"""流式请求的首字时间（ttft）：第一个真正的内容帧（正文或思考）发出的时刻。

log_capture_middleware 对流式响应要等**整条流发完**才写日志（见 app/main.py），这时除了总耗时
还要知道「首字等了多久」—— 东京实测慢全在首字前（谷歌把思考在快出正文时才一次性下发）。

为什么不在中间件里看帧：中间件只拿到字节，四种协议的「非内容帧」各不相同（OpenAI 的 role 首帧、
Claude 的 message_start / ping、Responses 的 created / in_progress、Gemini NDJSON 的空行保活），
在那里按协议拆 SSE 既要猜协议又容易认错。所以由**产出这条流的那一侧**判定：各协议的流式响应体
在构造 StreamingResponse 时套一层 track_first_content(agen, <本协议的判定函数>)，第一个内容帧
发出时调 mark_first_token()（幂等）；中间件在流结束时只读这个点。

只套在「原样发给客户端」的那一层：中间还要再转一道的流（第三方 key 的上游 chat 流被
/v1/responses 转成 Responses 事件，思考不转发、工具调用攒到流尾）不能在里层打点，否则里层先
触发，记成了上游开始思考的时刻。所以 api_forwarder 返回的流不套，由 openai / responses 两个
分发入口各自套。

为什么用 ContextVar 装一个可变计时对象，而不是 request.state：产出流的生成器很多拿不到
Request。中间件在 call_next 之前 set；BaseHTTPMiddleware 起的 app 任务、StreamingResponse
的迭代都在建任务时复制上下文 —— 复制的是引用，拿到的是同一个计时对象，打点中间件看得见。
（与 app/core/access_context.py 同一座桥。）每个请求在自己的任务里 set 一个新对象，互不串。

判定函数只在首字之前逐帧看，打过点之后整条流原样直通、不再解析。
"""

import json
import time
from contextvars import ContextVar
from typing import Any, AsyncIterator, Callable, Iterator, Optional


class RequestTiming:
    """一次请求的计时：start 与中间件的 latency 起点是同一个 perf_counter 读数。"""

    __slots__ = ("start", "first_token_at")

    def __init__(self, start: Optional[float] = None) -> None:
        self.start = time.perf_counter() if start is None else start
        self.first_token_at: Optional[float] = None

    def mark(self, now: Optional[float] = None) -> None:
        """记首字时刻；只认第一次（幂等）。"""
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter() if now is None else now

    def ttft_ms(self) -> Optional[float]:
        if self.first_token_at is None:
            return None
        return max(0.0, (self.first_token_at - self.start) * 1000)


_current: ContextVar[Optional[RequestTiming]] = ContextVar("request_timing", default=None)


def begin_request_timing(start: Optional[float] = None) -> RequestTiming:
    """中间件在 call_next 之前调用：给本次请求装一个新的计时对象。"""
    timing = RequestTiming(start)
    _current.set(timing)
    return timing


def mark_first_token() -> None:
    """第一个内容帧（正文或思考）发出时调用。幂等；没有计时上下文时什么都不做。"""
    timing = _current.get()
    if timing is not None:
        timing.mark()


# ---------------------------------------------------------------------------
# 各协议的「内容帧」判定：只认非空的正文 / 思考 / 工具调用增量
# ---------------------------------------------------------------------------

def _as_text(chunk: Any) -> str:
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return bytes(chunk).decode("utf-8", "replace")
    return chunk if isinstance(chunk, str) else ""


def _json_payloads(chunk: Any) -> Iterator[Any]:
    """一个分片里的每个 JSON 负载：SSE 的 data: 行，或 NDJSON 的整行。

    `:` 开头的注释（保活帧）、event: 行、空行、[DONE] 和解析不了的行一律跳过。"""
    for line in _as_text(chunk).splitlines():
        line = line.strip()
        if not line or line.startswith((":", "event:", "id:", "retry:")):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line[0] not in "{[":
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def openai_chat_has_content(chunk: Any) -> bool:
    """OpenAI chat.completion.chunk：delta 里有非空 content / 思考 / 工具调用。

    role 首帧（content 为 None 或 ""）、finish_reason 收尾帧、error 帧都不算。
    reasoning 是部分第三方中转（OpenRouter 等）的思考字段名。"""
    for obj in _json_payloads(chunk):
        if not isinstance(obj, dict):
            continue
        for choice in obj.get("choices") or ():
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict) and (
                delta.get("content") or delta.get("reasoning_content")
                or delta.get("reasoning") or delta.get("tool_calls")
                or delta.get("function_call")
            ):
                return True
    return False


def claude_has_content(chunk: Any) -> bool:
    """Claude messages：content_block_delta 里有非空 text / thinking / partial_json。

    message_start、content_block_start、ping、message_delta 都不算。"""
    for obj in _json_payloads(chunk):
        if not isinstance(obj, dict) or obj.get("type") != "content_block_delta":
            continue
        delta = obj.get("delta")
        if isinstance(delta, dict) and (
            delta.get("text") or delta.get("thinking") or delta.get("partial_json")
        ):
            return True
    return False


def responses_has_content(chunk: Any) -> bool:
    """OpenAI Responses：任何 *.delta 事件（正文 / 思考摘要 / 工具参数）带非空 delta。

    created、in_progress、output_item.added、content_part.added 都不算。"""
    for obj in _json_payloads(chunk):
        if (isinstance(obj, dict) and str(obj.get("type") or "").endswith(".delta")
                and obj.get("delta")):
            return True
    return False


def gemini_has_content(chunk: Any) -> bool:
    """Gemini 原生流（NDJSON / SSE 皆可）：candidates[].content.parts[] 有非空 text
    （含 thought: true 的思考段）或 functionCall。空行保活、收尾的空 text、error 行都不算。"""
    for obj in _json_payloads(chunk):
        if not isinstance(obj, dict):
            continue
        for cand in obj.get("candidates") or ():
            content = cand.get("content") if isinstance(cand, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            for part in parts or ():
                if isinstance(part, dict) and (
                    part.get("text") or part.get("functionCall") or part.get("function_call")
                ):
                    return True
    return False


async def track_first_content(agen: AsyncIterator[Any],
                              has_content: Callable[[Any], bool]) -> AsyncIterator[Any]:
    """原样转发 agen 的每个分片；第一个内容帧发出时打首字点，之后不再检查。

    没有计时上下文（不经中间件的直接调用 / 单元测试）时纯直通。判定函数出任何异常都只当
    「不是内容」，绝不影响这条流本身。"""
    timing = _current.get()
    async for chunk in agen:
        if timing is not None and timing.first_token_at is None:
            try:
                hit = has_content(chunk)
            except Exception:      # noqa: BLE001 计时是辅助功能，绝不打断流
                hit = False
            if hit:
                timing.mark()
        yield chunk

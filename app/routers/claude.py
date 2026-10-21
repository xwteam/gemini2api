import time
import uuid
import json
import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.core.account_pool import account_pool as gemini_client
from app.core.access_context import (
    ensure_model_allowed, filter_models_for_access_key, record_token_usage,
    with_retired_models_for_access_key,
)
from app.core.gemini_client import (HTTPStatusError, classify_error,
                                    generate_with_thinking_fallback, parse_anthropic_thinking,
                                    resolve_thinking, should_retry_without_thinking)
from app.core.thinking_stream import HiddenThoughts, drop_thought_events
from app.core.stream import split_into_chunks, iter_with_keepalive, SSE_KEEPALIVE_FRAME, sse_keepalive_during
from app.models.claude import (
    ClaudeRequest, ClaudeResponse, ContentBlock, ClaudeUsage,
    ClaudeModelInfo, ClaudeModelList,
)
from app.routers.openai import _images_to_markdown
from app.utils.tools import build_tool_prompt, parse_tool_response_with_retry, estimate_tokens, is_image_generation_intent
from app.utils.prompt import build_prompt_from_messages, extract_attachments, last_user_text
from app.core.limiter import limiter, dynamic_rate_limit, rate_limit_exempt

logger = logging.getLogger(__name__)


def _claude_sse(data: dict) -> str:
    """Anthropic 流式是 event+data 两行制（官方 SDK 按 event 字段分发），与 OpenAI 的纯 data 帧不同。"""
    return f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"


def _text_block_start(index: int) -> str:
    return _claude_sse({
        "type": "content_block_start",
        "index": index,
        "content_block": {"type": "text", "text": "", "citations": None},
    })


def _record_usage(model: str, prompt: str, text: str, result: dict | None = None) -> None:
    """按-key 用量落账（只统计、不限额）。思考链计进 output：官方 API 对 thinking
    token 按 output 计费，口径跟着官方走。详见 app/core/token_pricing.py。

    幂等（首次调用生效）由 record_token_usage 自己保证，所以每条分支的终点都可以直接调。
    """
    thoughts = (result or {}).get("thoughts") or ""
    record_token_usage(model, estimate_tokens(prompt),
                       estimate_tokens(text or "") + estimate_tokens(thoughts))


def _thinking_block_frames(blocks: list[ContentBlock]) -> list[str]:
    """把 thinking 块切成一组 SSE 帧（start → thinking_delta* → stop），恒占 index 0。

    blocks 为空（= 客户端没传 thinking，或这一轮没有思考内容）时返回空列表，
    于是后续块的 index 从 0 起、帧序列与改动前逐字节一致。
    """
    frames: list[str] = []
    for block in blocks:
        if block.type != "thinking":
            continue
        frames.append(_claude_sse({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        }))
        frames.append(_claude_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": block.thinking or ""},
        }))
        frames.append(_claude_sse({"type": "content_block_stop", "index": 0}))
    return frames


def _thoughts_tokens(blocks: list[ContentBlock]) -> int:
    """thinking 块里的思考 token。没有 thinking 块时恒为 0 —— 不传 thinking 的请求的
    usage 数字因此逐字节不变。"""
    return sum(estimate_tokens(b.thinking or "") for b in blocks if b.type == "thinking")


def _thinking_blocks(result: dict, show_thinking) -> list[ContentBlock]:
    """思考内容 → Anthropic thinking 内容块（规范要求它排在 text / tool_use 之前）。

    开关只看 show_thinking（= 客户端有没有明确要思考），**不看**发给上游的档位：
    不传 thinking 时上游照样会按"默认思考档位"思考，但官方 API 只有请求了才返回
    thinking 块，严格的客户端（含部分 Claude Code 版本）遇到未请求的 thinking 块会出错。
    signature 不发：真实 API 的 thinking 块恒带签名，我们造不出合法的，发空串/自造串
    更坏（客户端把它回传给真 API 会 400）。
    """
    if not show_thinking:
        return []
    thoughts = result.get("thoughts") or ""
    if not thoughts.strip():
        return []
    return [ContentBlock(type="thinking", thinking=thoughts)]


def _apply_model_whitelist(models: list[str]) -> list[str]:
    """按 MODEL_WHITELIST（逗号分隔）过滤模型列表；为空表示不过滤（放行全部）。
    让文档化的 MODEL_WHITELIST 真正生效——只暴露白名单内的模型。"""
    raw = (settings.model_whitelist or "").strip()
    if not raw:
        return models
    allowed = {m.strip() for m in raw.split(",") if m.strip()}
    if not allowed:
        return models
    return [m for m in models if m in allowed]


# router：对话主入口（messages），同时挂在 /claude/v1 和裸 /v1（开箱即用）
router = APIRouter(tags=["Claude"])
# models_router：模型列表/详情，仅挂在 /claude/v1，避免裸 /v1/models 与 OpenAI 撞车
models_router = APIRouter(tags=["Claude"])


@models_router.get("/models")
async def list_models():
    models = filter_models_for_access_key(_apply_model_whitelist(
        with_retired_models_for_access_key(gemini_client.models)))
    data = [
        ClaudeModelInfo(
            id=m,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            display_name=m,
        )
        for m in models
    ]
    return ClaudeModelList(data=data)


@models_router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    # 与 /models 列表保持一致：被白名单挡掉的模型也视为 not found
    if model_id not in filter_models_for_access_key(_apply_model_whitelist(
        with_retired_models_for_access_key(gemini_client.models))):
        return JSONResponse(
            status_code=404,
            content={"type": "error", "error": {"type": "not_found", "message": f"Model {model_id} not found"}},
        )
    return ClaudeModelInfo(
        id=model_id,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        display_name=model_id,
    )


@router.post("/messages")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def create_message(req: ClaudeRequest, request: Request):
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)
    attachments = extract_attachments(messages_raw)

    # gem 模型解析：命中则取出 gem_id/account_id，并把对话模型换成 base_model
    resolved_model = req.model
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    gem_id = None
    gem_account_id = None
    if gem_mapping:
        gem_info = gem_mapping.resolve(resolved_model)
        if gem_info:
            gem_id = gem_info.get("gem_id")
            gem_account_id = gem_info.get("account_id") or None
            resolved_model = gem_info.get("base_model") or "gemini-pro"

    ensure_model_allowed(req.model, resolved_model)

    # thinking（+ output_config.effort）→ 思考档位（与 /v1/chat/completions 的 reasoning_effort
    # 同一套决策，见 gemini_client.resolve_thinking）；**不传 → "默认思考档位"设置**（出厂 low），
    # adaptive 且 effort 是 high / 没给（Claude Code 的出厂请求）同样跟随默认档。拆成两个量：
    #   extended_thinking —— 发给上游的档位（False = 不思考旧路径；1/2/4 = 档位）
    #   show_thinking     —— 出不出 thinking 块。**只看客户端是否明确要了思考**：按默认档
    #                        替它开的思考绝不出 thinking 块，帧序列与不思考时逐字节一致。
    # thinking.display 刻意不看：Claude Code 不论设置如何都发 "omitted"（2.1.296 抓包，
    # 打开 showThinkingSummaries 也一样），照官方语义压掉思考文本的话 Claude Code 用户就
    # 永远看不到思考。客户端要了思考，多给思考文本不违反协议。
    _plan = resolve_thinking(parse_anthropic_thinking(req.thinking, req.output_config))
    extended_thinking = _plan.upstream
    show_thinking = _plan.show

    has_tools = bool(req.tools)
    # 生图意图优先：带 tools 但明确生图意图时跳过工具模拟，直接生图（否则生图被压制）。
    # 只看最后一轮用户消息：整段 prompt 含 system 提示词与 tool_result 正文，
    # 拿它判断会把引用到的图片字样当成用户要图，从而静默丢掉客户端 tools 并改走真流式。
    if has_tools and is_image_generation_intent(last_user_text(messages_raw)):
        has_tools = False
        logger.info("检测到生图意图，跳过工具调用模拟，直接生图")
    if has_tools:
        tools_raw = [
            {"name": t.name, "description": t.description, "parameters": t.input_schema}
            for t in req.tools
        ]
        choice = None
        if req.tool_choice:
            tc_type = req.tool_choice.get("type", "auto")
            if tc_type == "any":
                choice = "required"
            elif tc_type == "tool":
                choice = {"function": {"name": req.tool_choice.get("name", "")}}
            else:
                choice = tc_type
        prompt = build_tool_prompt(prompt, tools_raw, choice)

    if req.stream:
        return StreamingResponse(
            _stream_claude(prompt, resolved_model, has_tools, attachments, req.model, gem_id, gem_account_id,
                          request=request, extended_thinking=extended_thinking,
                          show_thinking=show_thinking),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = None
    try:
        result = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                              gem_id=gem_id, account_id=gem_account_id,
                                              extended_thinking=extended_thinking)
    except (RuntimeError, ValueError, HTTPStatusError) as e:
        err = e
        # 开思考 = 走另一套 payload + header（见 gemini_client._send_request），失败率与
        # 普通路径不同。先原样退回非思考重试一次再报错，别让"勾了思考"把整条请求搞挂
        # （镜像 openai.py 既有做法）。退回成功时也把 show_thinking 关掉：
        # 这一轮确实没有思考，不该再去吐 thinking 块。
        if extended_thinking:
            logger.warning(f"extended-thinking request failed, retrying normal: {e}")
            extended_thinking = False
            show_thinking = False
            try:
                result = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                                      gem_id=gem_id, account_id=gem_account_id)
            except (RuntimeError, ValueError, HTTPStatusError) as e2:
                err = e2
        if result is None:
            status, err_type, retry_after = classify_error(err)
            headers = {"Retry-After": str(retry_after)} if retry_after else None
            return JSONResponse(
                status_code=status,
                content={"type": "error", "error": {"type": err_type, "message": str(err)}},
                headers=headers,
            )

    text = result.get("text", "")
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    if has_tools:
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                             gem_id=gem_id, account_id=gem_account_id)
            return r.get("text", "")

        parsed = await parse_tool_response_with_retry(text, _regenerate_for_tools)
        if parsed["type"] == "tool_calls":
            blocks = _thinking_blocks(result, show_thinking)
            _record_usage(resolved_model, prompt, text, result)
            for tc in parsed["tool_calls"]:
                blocks.append(ContentBlock(
                    type="tool_use",
                    id=f"toolu_{uuid.uuid4().hex[:8]}",
                    name=tc["name"],
                    input=tc.get("arguments", {}),
                ))
            return ClaudeResponse(
                id=msg_id,
                model=req.model,
                content=blocks,
                stop_reason="tool_use",
                usage=ClaudeUsage(
                    input_tokens=estimate_tokens(prompt),
                    output_tokens=estimate_tokens(text) + _thoughts_tokens(blocks),
                ),
            )
        text = parsed.get("content", text)

    # AI 生成图片：Anthropic assistant 侧 content-block union 没有 image 成员——真实 SDK
    # 严格校验会直接报 35 个错误，宽松路径会把它默默转成 text=None 的 TextBlock，
    # isinstance(block, TextBlock) 的客户端直接崩，按 type 过滤的客户端整块丢弃，两种情况
    # 下图片都到不了用户手里（defect ⑥）。改用 openai.py 既有做法：图片渲染成 markdown
    # 嵌进文字块（图在前，文字在后），不单开 image 块。
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_to_markdown(gen_images, request)
        text = (md + "\n" + text.strip()) if text.strip() else md
    # 上游回答是空字符串且无图时，不能发一个 text:"" 的空文本块，也不能让 content
    # 整体变成 []（defect ⑩）——两者都有客户端会踩坑（遍历 content 假设至少一块非空）。
    # 用单空格占位，恰好一块，不改变非空/纯空白文本的既有行为。
    blocks = _thinking_blocks(result, show_thinking) + [
        ContentBlock(type="text", text=text if text else " ")
    ]
    _record_usage(resolved_model, prompt, text, result)

    return ClaudeResponse(
        id=msg_id,
        model=req.model,
        content=blocks,
        stop_reason="end_turn",
        usage=ClaudeUsage(
            input_tokens=estimate_tokens(prompt),
            # 真实 API 把思考 token 计进 output，这里跟随同一口径（仍是估算，见文档）
            output_tokens=estimate_tokens(text) + _thoughts_tokens(blocks),
        ),
    )


@router.post("/messages/count_tokens")
async def count_tokens(req: ClaudeRequest):
    ensure_model_allowed(req.model)
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)
    count = estimate_tokens(prompt)
    return {"input_tokens": count}


async def _stream_claude(prompt: str, model: str, has_tools: bool, attachments=None, display_model: str = "", gem_id=None, account_id=None, request=None, extended_thinking=False, show_thinking=False) -> AsyncGenerator[str, None]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    model_name = display_model or model

    # 只有「工具调用」才强制走 buffered：tool_calls 必须拿到完整 JSON 才能解析。
    # 附件不再挡在这里 —— 附件在 generate_stream 里照样会先上传完再开始对话（底层支持，
    # 下面的真流式路径本来就把 attachments 原样传了下去），把它挡进 buffered 只是让所有
    # 带图/带文件的请求都"等全文生成完才吐第一个字"。与 /v1/chat/completions 同口径。
    if has_tools:
        async for sse in _stream_claude_buffered(prompt, model, has_tools, attachments, msg_id, model_name, gem_id, account_id,
                                                 request=request, extended_thinking=extended_thinking,
                                                 show_thinking=show_thinking):
            yield sse
        return

    # === 真流式路径（纯文本）===
    yield _claude_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model_name,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": estimate_tokens(prompt), "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                "service_tier": "standard",
            },
        },
    })
    # 块索引与开块时机（只看 show_thinking，不看发给上游的档位）：
    # - 不回传思考（客户端没要求，含"按默认档替它开了思考"）时，照旧在循环前就开
    #   index 0 的文本块，SSE 帧序列与改动前逐字节一致。
    # - 传了 thinking 时改成惰性开块：先等思考增量（开 index 0 的 thinking 块），首个
    #   正文增量到达时才关掉它、开 index 1 的文本块。Anthropic 规定 thinking 块必须排在
    #   text 之前，所以文本块一开就回不去了。
    thinking_open = False
    text_open = False
    text_index = 0
    emitted_thoughts = ""
    # 不回传时思考只进内部记账（官方口径：思考 token 按 output 计费），一个字都不进 SSE。
    # 过滤放在 iter_with_keepalive 之前，思考期间照发保活帧（见 app/core/thinking_stream.py）。
    hidden = HiddenThoughts()
    # 正文块开了之后才到的思考增量只能丢（见下面那条 WARNING）。记下丢了多少，
    # 收尾时一次说清，别让 reasoning 通道静默少内容。
    dropped_thoughts = 0
    late_thinking_warned = False

    def _ensure_text_open() -> list[str]:
        """返回「把文本块开好」所需的帧（已开则为空）。"""
        nonlocal thinking_open, text_open, text_index
        if text_open:
            return []
        frames = []
        if thinking_open:
            frames.append(_claude_sse({"type": "content_block_stop", "index": 0}))
            thinking_open = False
            text_index = 1
        text_open = True
        frames.append(_text_block_start(text_index))
        return frames

    if not show_thinking:
        text_open = True
        yield _text_block_start(0)

    full_text = ""
    final_images = []
    streamed_text = False   # 是否已经发出过正文增量（决定失败时还能不能退回重试）
    upstream = gemini_client.generate_stream(prompt, model, "", attachments,
                                             gem_id=gem_id, account_id=account_id,
                                             extended_thinking=extended_thinking)
    if not show_thinking:
        upstream = drop_thought_events(upstream, hidden)
    try:
        async for _kind, evt in iter_with_keepalive(upstream):
            if _kind == "ping":
                yield SSE_KEEPALIVE_FRAME
                continue
            if evt.get("type") == "thoughts":
                # 这一支过去根本不存在：{"type":"thoughts"} 事件被 if/elif 整个漏掉，
                # 于是 Anthropic 协议用户永远拿不到思考链。
                # 只有 show_thinking 时才会到这里（不回传的已在上游一侧被滤掉）。
                t_delta = evt.get("text", "")
                if not t_delta:
                    continue
                if text_open:
                    # 文本块已经开了，按规范回不去 thinking 块前面，也不能在 text 之后插
                    # 一个顺序违规的 thinking 块（SDK 会按块顺序校验）。只能丢。
                    # 但这是 reasoning 通道的**静默丢内容**：同一次生成在 OpenAI 协议侧
                    # （openai.py 没有块顺序约束）是完整的。所以每条流最多打一次 WARNING
                    # 把丢掉的字数说清楚，而不是一行看不见的 debug。
                    dropped_thoughts += len(t_delta)
                    if not late_thinking_warned:
                        late_thinking_warned = True
                        logger.warning(
                            "Dropping late thinking delta(s) after the text block opened: "
                            "the Anthropic content-block order forbids a thinking block "
                            "after text (same generation is complete on the OpenAI protocol)"
                        )
                    continue
                if not thinking_open:
                    thinking_open = True
                    yield _claude_sse({
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "thinking", "thinking": ""},
                    })
                emitted_thoughts += t_delta
                yield _claude_sse({
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": t_delta},
                })
            elif evt.get("type") == "delta":
                # generate_stream 现在是严格 append-only（不再发 _replace），delta 总是新增尾部
                delta = evt.get("text", "")
                full_text += delta
                if delta:
                    for frame in _ensure_text_open():
                        yield frame
                    streamed_text = True
                    yield _claude_sse({
                        "type": "content_block_delta",
                        "index": text_index,
                        "delta": {"type": "text_delta", "text": delta},
                    })
            elif evt.get("type") == "final":
                # final.text 是过滤完占位串的完整文本，可能比已流出的 full_text 多出
                # （流式时被 hold 住的尾部）。补发缺失尾部，保证客户端拿到完整内容。
                # 收尾的完整思考链：按「已发前缀 diff」补发差量（同 openai.py 的口径，
                # startswith 不成立时不重发整段、避免重复）。只有文本块还没开时才可能补 ——
                # 开了就回不去 thinking 块前面了。
                if not show_thinking:
                    hidden.text = (evt.get("thoughts", "") or "") or hidden.text
                if show_thinking and text_open:
                    final_thoughts = evt.get("thoughts", "") or ""
                    missing = len(final_thoughts) - len(emitted_thoughts)
                    if missing > 0 or dropped_thoughts:
                        logger.warning(
                            "Anthropic thinking chain is short by %d char(s) "
                            "(%d dropped as late deltas): the text block was already open, "
                            "so the thinking block could no longer be extended",
                            max(missing, dropped_thoughts), dropped_thoughts,
                        )
                if show_thinking and not text_open:
                    final_thoughts = evt.get("thoughts", "") or ""
                    if final_thoughts != emitted_thoughts \
                            and final_thoughts.startswith(emitted_thoughts):
                        t_tail = final_thoughts[len(emitted_thoughts):]
                        if t_tail:
                            if not thinking_open:
                                thinking_open = True
                                yield _claude_sse({
                                    "type": "content_block_start",
                                    "index": 0,
                                    "content_block": {"type": "thinking", "thinking": ""},
                                })
                            emitted_thoughts = final_thoughts
                            yield _claude_sse({
                                "type": "content_block_delta",
                                "index": 0,
                                "delta": {"type": "thinking_delta", "thinking": t_tail},
                            })
                final_text = evt.get("text", full_text)
                if final_text.startswith(full_text) and len(final_text) > len(full_text):
                    tail = final_text[len(full_text):]
                    full_text = final_text
                    if tail:
                        for frame in _ensure_text_open():
                            yield frame
                        streamed_text = True
                        yield _claude_sse({
                            "type": "content_block_delta",
                            "index": text_index,
                            "delta": {"type": "text_delta", "text": tail},
                        })
                else:
                    full_text = final_text
                final_images = evt.get("images") or []
    except Exception as e:
        failure = e
    else:
        failure = None

    if failure is not None and not streamed_text \
            and should_retry_without_thinking(failure, extended_thinking):
        # 思考路径失败、还没发出任何正文：原样退回不思考、非流式重试一次（与非流式 /
        # buffered 的 generate_with_thinking_fallback、Responses 真流式同口径）。默认档上线后
        # 几乎每个请求都走思考路径，没有这一退回，上游拒收思考 payload 时 v1.6.42 能答的
        # 不传参流式请求会变成硬失败。重试期间用 task + keepalive 续心跳。
        logger.warning(f"extended-thinking stream failed, retrying normal: {failure}")
        retry_task = asyncio.create_task(gemini_client.generate(
            prompt, model, "", attachments,
            gem_id=gem_id, account_id=account_id, extended_thinking=False))
        try:
            async for ping in sse_keepalive_during(retry_task):
                yield ping
        except BaseException:          # GeneratorExit / CancelledError on client disconnect
            retry_task.cancel()
            if retry_task.done() and not retry_task.cancelled():
                retry_task.exception()
            raise
        try:
            result = retry_task.result()
        except Exception as e2:
            failure = e2
        else:
            failure = None
            full_text = result.get("text", "") or ""
            final_images = result.get("images") or []
            if full_text:
                for frame in _ensure_text_open():
                    yield frame
                yield _claude_sse({
                    "type": "content_block_delta",
                    "index": text_index,
                    "delta": {"type": "text_delta", "text": full_text},
                })

    if failure is not None:
        e = failure
        # 真实上游失败绝不能伪装成正常回答：不能落回下面的
        # content_block_stop/message_delta(stop_reason=end_turn)/message_stop 正常收尾——
        # 否则官方 SDK 会看到 stop_reason='end_turn' 且没有异常，client 的重试/故障转移/退避
        # 永远不会触发，错误文本还会被当成模型说的话存进对话历史。改发标准 Anthropic error
        # 事件并直接结束流，与下面 _stream_claude_buffered 的既有正确写法（第 289-293 行左右）对齐。
        _, err_type, _retry_after = classify_error(e)
        # 关掉当前真正开着的那个块。不传 thinking 时文本块恒在 index 0 开着，
        # 这一行与改动前逐字节相同；传了 thinking 而一个块都还没开时就不发 stop
        # （发了会指向一个不存在的块）。
        if text_open:
            yield _claude_sse({"type": "content_block_stop", "index": text_index})
        elif thinking_open:
            yield _claude_sse({"type": "content_block_stop", "index": 0})
        yield _claude_sse({"type": "error", "error": {"type": err_type, "message": str(e)}})
        return

    if final_images:
        # 生成图片只在 final 事件才知道，此时文字已经流出去了，只能追加一条 delta
        # 补进同一个文本块（index 0）——绝不能单开 image 块把文字块挤出 index 0，
        # 否则 SDK 客户端会拿到未知 discriminator（defect ⑥）。
        md = _images_to_markdown(final_images, request)
        if full_text.strip():
            appended = "\n" + md
            full_text = full_text + appended
        else:
            appended = md
            full_text = md
        for frame in _ensure_text_open():
            yield frame
        yield _claude_sse({
            "type": "content_block_delta",
            "index": text_index,
            "delta": {"type": "text_delta", "text": appended},
        })
    elif not full_text:
        # 上游回答真的是空字符串、也没有生图时，此前不发一个 delta——content_block_start
        # (text:"") 之后直接 content_block_stop，零个 delta。buffered 路径（同一个
        # defect ⑩）已经用单空格占位补上了这个缺口；这里是真流式侧的对称缺口，客户端遍历
        # delta 流、假设至少收到一块非空内容的假设一样会被打破。补发一个单空格 delta，
        # 不改变非空回答/有生图场景（上面 if 分支已经保证非空）的既有行为。
        full_text = " "
        for frame in _ensure_text_open():
            yield frame
        yield _claude_sse({
            "type": "content_block_delta",
            "index": text_index,
            "delta": {"type": "text_delta", "text": full_text},
        })

    _record_usage(model, prompt, full_text,
                  {"thoughts": emitted_thoughts if show_thinking else hidden.text})

    yield _claude_sse({"type": "content_block_stop", "index": text_index})
    yield _claude_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {
            # 真实 API 把思考 token 计进 output。没发过 thinking 块时 emitted_thoughts
            # 恒为空串，estimate_tokens("") == 0，这个数字逐字节不变。
            "output_tokens": estimate_tokens(full_text) + estimate_tokens(emitted_thoughts),
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "service_tier": "standard",
        },
    })
    yield _claude_sse({"type": "message_stop"})


async def _stream_claude_buffered(prompt: str, model: str, has_tools: bool, attachments, msg_id: str, display_model: str = "", gem_id=None, account_id=None, request=None, extended_thinking=False, show_thinking=False) -> AsyncGenerator[str, None]:
    """非流式收集 + 切片：用于有工具调用/附件的场景。"""
    model_name = display_model or model
    # 思考路径失败时在同一个 task 里退回不思考重试一次（keepalive 照常覆盖）。退回后
    # 结果里没有思考，_thinking_blocks 自然为空。
    gen_task = asyncio.create_task(generate_with_thinking_fallback(
        gemini_client, prompt, model, "", attachments,
        gem_id=gem_id, account_id=account_id, extended_thinking=extended_thinking))
    try:
        async for ping in sse_keepalive_during(gen_task):
            yield ping
    except BaseException:          # GeneratorExit / CancelledError on client disconnect
        gen_task.cancel()
        if gen_task.done() and not gen_task.cancelled():
            gen_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
        raise
    try:
        result = gen_task.result()
    except Exception as e:
        # 硬编码 "api_error" 会绕开 classify_error 的统一映射（929a049），buffered 流式路径
        # （Claude Code 走的这条）跟非流式/真流式给出不一致的 error type——同一个 pool-busy
        # 失败，非流式吐 overloaded_error，这里却吐 api_error，客户端的重试/故障转移策略
        # 因 type 不同而表现不一致。
        _, err_type, _retry_after = classify_error(e)
        yield _claude_sse({"type": "error", "error": {"type": err_type, "message": str(e)}})
        return

    text = result.get("text", "")
    # thinking 块（若有）恒占 index 0，后面所有块的索引整体 +1。
    # 不回传思考时 thinking_blocks 为空、base 为 0，帧序列与改动前逐字节一致。
    thinking_blocks = _thinking_blocks(result, show_thinking)
    base = 1 if thinking_blocks else 0

    yield _claude_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model_name,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": estimate_tokens(prompt), "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                "service_tier": "standard",
            },
        },
    })

    if has_tools:
        # message_start 已发出，但还没发任何 content 块，此处重试是安全的。
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, model, "", attachments,
                                             gem_id=gem_id, account_id=account_id)
            return r.get("text", "")

        # 畸形工具 JSON 的重试要再跑一整轮上游 generate()——message_start 已经发出、
        # 这条流早就开了，裸 await 会在已开的连接上制造一次远超单个 keepalive 间隔的
        # 死寂（issue #10 followup F2）。用与上面 gen_task 相同的 task + keepalive 套路续心跳。
        parse_task = asyncio.create_task(parse_tool_response_with_retry(text, _regenerate_for_tools))
        try:
            async for ping in sse_keepalive_during(parse_task):
                yield ping
        except BaseException:          # GeneratorExit / CancelledError on client disconnect
            parse_task.cancel()
            if parse_task.done() and not parse_task.cancelled():
                parse_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
            raise
        parsed = parse_task.result()
        if parsed["type"] == "tool_calls":
            for frame in _thinking_block_frames(thinking_blocks):
                yield frame
            for i, tc in enumerate(parsed["tool_calls"]):
                block_id = f"toolu_{uuid.uuid4().hex[:8]}"
                yield _claude_sse({
                    "type": "content_block_start",
                    "index": base + i,
                    "content_block": {"type": "tool_use", "id": block_id, "name": tc["name"], "input": {}},
                })
                args_str = json.dumps(tc.get("arguments", {}))
                yield _claude_sse({
                    "type": "content_block_delta",
                    "index": base + i,
                    "delta": {"type": "input_json_delta", "partial_json": args_str},
                })
                yield _claude_sse({"type": "content_block_stop", "index": base + i})

            _record_usage(model, prompt, text, result)
            yield _claude_sse({
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {
                    "output_tokens": estimate_tokens(text) + _thoughts_tokens(thinking_blocks),
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                    "service_tier": "standard",
                },
            })
            yield _claude_sse({"type": "message_stop"})
            return
        text = parsed.get("content", text)

    # AI 生成图片：同非流式路径，折进文字块的 markdown，不单开 image 块（defect ⑥）。
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_to_markdown(gen_images, request)
        text = (md + "\n" + text.strip()) if text.strip() else md

    # 上游回答真的是空字符串时，非流式路径（6cf8ca0）已经改发单空格占位文本块，不再吐
    # text:"" 的空块；这里是同一个 defect 在流式侧留下的对称缺口——不补的话客户端会拿到
    # content_block_start(text:"") -> content_block_stop 之间零个 delta，同样违反"遍历
    # content/delta 假设至少一块非空"的客户端假设。用单空格占位，不改变非空文本的既有行为。
    if not text:
        text = " "

    _record_usage(model, prompt, text, result)

    for frame in _thinking_block_frames(thinking_blocks):
        yield frame

    yield _text_block_start(base)

    async for word in split_into_chunks(text):
        # split_into_chunks("") 因 "".split(" ") == [""] 会吐出一个空字符串块；
        # 没有这道防线就会发出零长度的 content_block_delta（defect ⑩）。
        if word:
            yield _claude_sse({
                "type": "content_block_delta",
                "index": base,
                "delta": {"type": "text_delta", "text": word},
            })

    yield _claude_sse({"type": "content_block_stop", "index": base})

    yield _claude_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {
            "output_tokens": estimate_tokens(text) + _thoughts_tokens(thinking_blocks),
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "service_tier": "standard",
        },
    })

    yield _claude_sse({"type": "message_stop"})


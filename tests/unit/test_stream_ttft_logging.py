"""v1.6.56 B1/B3：流式请求的日志记真实耗时 + 首字时间（ttft_ms）。

东京实测：模型测试页用 gemini-4-neon 体感 ≥40 秒，「日志」页却显示 2ms —— 中间件在
call_next 返回时就记了 latency_ms，而流式请求那一刻只是拿到了 StreamingResponse，后面几十秒
的生成一点没算进去。这里钉死：

1. 四种协议（OpenAI chat / Responses / Claude messages / Gemini 原生流）的流式请求，日志在
   **流结束时**才写：latency_ms ≥ 注入的上游总延迟；ttft_ms ≥ 首个内容前的注入延迟、
   且不超过 latency_ms。role 首帧、`:` 保活注释帧、NDJSON 空行保活都不算「内容」。
2. 只有 role 帧 + 保活帧客户端就断开：照样有一条记录，ttft_ms 为 None。
3. 非流式请求行为不变：latency_ms 照旧，ttft_ms 为 None。
4. 旧记录（没有 ttft_ms 字段）照常读、照常返回。
5. 第三方 key 的流：/v1/responses 上游先思考 / 只有工具调用时，首字按客户端真正收到的第一个
   内容帧算（不按上游原始帧）；/v1/chat/completions 原样透传，思考帧就算首字。
6. 流中途出错：正好一条记录，ttft_ms / latency_ms 按实际。
7. Claude（thinking 开）与 Gemini 原生（includeThoughts）的思考帧端到端算首字。
"""

import asyncio
import json

import pytest

from app.config import settings
from app.core import request_timing as rt
from app.core import stream as stream_mod

_AUTH = {"Authorization": "Bearer sk-test-key"}

D_FIRST = 0.25   # 首个内容前的注入延迟（秒）
D_TAIL = 0.15    # 首个内容之后、流结束前的注入延迟（秒）
PING = 0.03      # 测试里把保活间隔调小，确保首字前一定发过保活帧

_CHAT = {"model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True}
_CLAUDE = {"model": "gemini-flash", "max_tokens": 64, "stream": True,
           "messages": [{"role": "user", "content": "hi"}]}
_RESP = {"model": "gemini-flash", "input": "hi", "stream": True}
_NATIVE = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}

STREAMS = {
    "openai": ("/v1/chat/completions", _CHAT),
    "anthropic": ("/v1/messages", _CLAUDE),
    "gemini": ("/v1beta/models/gemini-flash:streamGenerateContent", _NATIVE),
    "responses": ("/v1/responses", _RESP),
}


class _CapturingLogStore:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def flush(self, *a, **k):
        return None


@pytest.fixture
def log_app(app_main, tmp_path, monkeypatch):
    from app.core.gem_mapping import GemMapping
    from app.core.model_mapping import ModelMapping

    store = _CapturingLogStore()
    app_main.app.state.log_store = store
    app_main.app.state.model_mapping = ModelMapping(path=str(tmp_path / "mm.json"))
    app_main.app.state.gem_mapping = GemMapping(path=str(tmp_path / "gm.json"))
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", PING)
    # 默认档不回传思考；这里关掉总闸，让四条路径都走最朴素的真流式
    monkeypatch.setattr(settings, "extended_thinking_enabled", False)
    return app_main.app, store


def _routers():
    import app.routers.claude as cl
    import app.routers.gemini as ge
    import app.routers.openai as oai
    import app.routers.responses as rp
    return oai, rp, cl, ge


def _install_stream(monkeypatch, agen_factory):
    for mod in _routers():
        monkeypatch.setattr(mod.gemini_client, "generate_stream", agen_factory)


async def _slow_answer(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       account_id=None, extended_thinking=False):
    await asyncio.sleep(D_FIRST)
    yield {"type": "delta", "text": "HELLO"}
    await asyncio.sleep(D_TAIL)
    yield {"type": "delta", "text": "WORLD"}
    yield {"type": "final", "text": "HELLOWORLD", "conversation_id": "", "images": [], "thoughts": ""}


async def _never_answers(prompt, model, conversation_id="", attachments=None, gem_id=None,
                         account_id=None, extended_thinking=False):
    await asyncio.sleep(30)
    yield {"type": "delta", "text": "太晚了"}


def _api_records(store):
    return [r for r in store.records if not r.path.startswith("/admin/")]


# ---------------------------------------------------------------------------
# 1. 四种协议：latency_ms 记到流结束，ttft_ms 记到第一个内容帧
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(STREAMS))
def test_stream_log_records_total_latency_and_ttft(log_app, monkeypatch, case):
    from fastapi.testclient import TestClient

    app, store = log_app
    _install_stream(monkeypatch, _slow_answer)
    path, body = STREAMS[case]

    with TestClient(app).stream("POST", path, json=body, headers=_AUTH) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "HELLO" in text and "WORLD" in text      # 流本身完好

    recs = _api_records(store)
    assert len(recs) == 1, "一次流式请求必须正好一条记录"
    rec = recs[0]
    assert rec.stream is True or case == "gemini"
    assert rec.latency_ms >= (D_FIRST + D_TAIL) * 1000, rec.latency_ms
    assert rec.ttft_ms is not None
    assert rec.ttft_ms >= D_FIRST * 1000, rec.ttft_ms
    assert 0 < rec.ttft_ms <= rec.latency_ms
    # 首字之后还有 D_TAIL 的生成，总耗时与首字必须拉得开
    assert rec.latency_ms - rec.ttft_ms >= D_TAIL * 1000 * 0.8


def test_stream_ttft_counts_thinking_frames(log_app, monkeypatch):
    """思考也算「首字」：客户端要了思考时，第一个思考帧发出就打点。"""
    from fastapi.testclient import TestClient

    app, store = log_app
    monkeypatch.setattr(settings, "extended_thinking_enabled", True)

    async def thinks_then_answers(prompt, model, conversation_id="", attachments=None, gem_id=None,
                                  account_id=None, extended_thinking=False):
        await asyncio.sleep(D_FIRST)
        yield {"type": "thoughts", "text": "THINKING"}
        await asyncio.sleep(D_TAIL * 2)
        yield {"type": "delta", "text": "ANSWER"}
        yield {"type": "final", "text": "ANSWER", "conversation_id": "", "images": [],
               "thoughts": "THINKING"}

    _install_stream(monkeypatch, thinks_then_answers)
    with TestClient(app).stream("POST", "/v1/chat/completions",
                                json={**_CHAT, "reasoning_effort": "low"}, headers=_AUTH) as r:
        text = "".join(r.iter_text())
    assert "THINKING" in text and "ANSWER" in text

    rec = _api_records(store)[0]
    assert D_FIRST * 1000 <= rec.ttft_ms < (D_FIRST + D_TAIL * 2) * 1000, rec.ttft_ms
    assert rec.latency_ms >= (D_FIRST + D_TAIL * 2) * 1000


# ---------------------------------------------------------------------------
# 2. 只有 role 帧 + 保活帧就断开：有记录，ttft_ms = None
# ---------------------------------------------------------------------------

def _scope(path: str, body: bytes) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},   # 与 uvicorn 0.34 一致
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"authorization", b"Bearer sk-test-key"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


async def _drive_until_disconnect(app, path: str, payload: dict, *, pings: int, mode: str):
    """直接按 ASGI 驱动：收到 pings 个保活帧（`:` 注释帧或 NDJSON 空行）后客户端断开。

    mode="receive"：uvicorn 的行为 —— receive() 报 http.disconnect（send 之后静默丢弃）；
    mode="send"：   send() 抛 OSError（ASGI 2.4 服务器的行为）。"""
    body = json.dumps(payload).encode()
    gone = asyncio.Event()
    state = {"body_sent": False, "chunks": 0, "pings": 0}

    async def receive():
        if not state["body_sent"]:
            state["body_sent"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] != "http.response.body" or not message.get("body"):
            return
        if gone.is_set():
            if mode == "send":
                raise OSError("client went away")
            return
        state["chunks"] += 1
        chunk = bytes(message["body"])
        if not chunk.strip() or chunk.lstrip().startswith(b":"):
            state["pings"] += 1
        if state["pings"] >= pings:
            gone.set()

    try:
        await asyncio.wait_for(app(_scope(path, body), receive, send), timeout=10)
    except OSError:
        assert mode == "send"
    return state


@pytest.mark.parametrize("mode", ["receive", "send"])
@pytest.mark.parametrize("case", sorted(STREAMS))
def test_disconnect_before_any_content_still_logs_without_ttft(log_app, monkeypatch, case, mode):
    app, store = log_app
    _install_stream(monkeypatch, _never_answers)
    path, body = STREAMS[case]

    state = asyncio.run(_drive_until_disconnect(app, path, body, pings=2, mode=mode))
    assert state["pings"] >= 2

    recs = _api_records(store)
    assert len(recs) == 1, "断开也必须写一条记录"
    rec = recs[0]
    assert rec.ttft_ms is None
    assert rec.status == 200
    # 发过两个保活帧才断开：总耗时不能再是「拿到 StreamingResponse 那一刻」的几毫秒
    assert rec.latency_ms >= PING * 1000 * 1.5


# ---------------------------------------------------------------------------
# 3. 非流式请求不变
# ---------------------------------------------------------------------------

def test_non_stream_latency_unchanged_and_ttft_is_none(log_app, monkeypatch):
    from fastapi.testclient import TestClient
    import app.routers.openai as oai

    app, store = log_app

    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                  account_id=None, extended_thinking=False):
        await asyncio.sleep(0.1)
        return {"text": "hello", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate", gen)
    r = TestClient(app).post("/v1/chat/completions",
                             json={**_CHAT, "stream": False}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello"

    rec = _api_records(store)[0]
    assert rec.ttft_ms is None
    assert rec.latency_ms >= 100
    assert rec.stream is False


def test_admin_request_still_logged_immediately(log_app):
    from fastapi.testclient import TestClient

    app, store = log_app
    r = TestClient(app).get("/admin/status", headers=_AUTH)
    assert r.status_code == 200
    assert store.records[-1].path == "/admin/status"
    assert store.records[-1].ttft_ms is None


# ---------------------------------------------------------------------------
# 4. LogStore / create_log_record：新字段 + 旧记录兼容
# ---------------------------------------------------------------------------

def test_create_log_record_rounds_ttft():
    from app.core.log_store import create_log_record

    rec = create_log_record(method="POST", path="/v1/chat/completions", latency_ms=16600.04,
                            ttft_ms=15234.567, stream=True)
    assert rec.ttft_ms == 15234.6
    assert rec.to_dict()["ttft_ms"] == 15234.6
    assert create_log_record(method="GET", path="/x").ttft_ms is None


def test_old_records_without_ttft_load_and_query(tmp_path):
    from app.core.log_store import LogStore

    old = {
        "id": "abc123def456", "request_id": "r1", "direction": "ingress",
        "ts": "2026-11-24T00:00:00+00:00", "method": "POST", "path": "/v1/chat/completions",
        "model": "gemini-flash", "provider": "gemini", "status": 200, "latency_ms": 2.1,
        "stream": True, "error": None, "tags": [], "request": None, "response": None,
    }
    newer = {**old, "id": "fff000fff000", "ttft_ms": 1500.0, "some_future_field": 1}
    p = tmp_path / "logs.json"
    p.write_text(json.dumps([old, newer]), encoding="utf-8")

    store = LogStore(capacity=10, persist_path=str(p))
    out = store.query(limit=10)
    assert out["total"] == 2
    by_id = {r["id"]: r for r in out["records"]}
    assert by_id["abc123def456"]["ttft_ms"] is None
    assert by_id["abc123def456"]["latency_ms"] == 2.1
    assert by_id["fff000fff000"]["ttft_ms"] == 1500.0
    assert store.get("abc123def456")["ttft_ms"] is None


# ---------------------------------------------------------------------------
# 5. 各协议「内容帧」的判定（不含 role 首帧 / 保活帧 / 空增量）
# ---------------------------------------------------------------------------

def _sse(obj, event=None) -> str:
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {json.dumps(obj)}\n\n"


def test_openai_chat_frames():
    f = rt.openai_chat_has_content
    assert not f(": ping\n\n")
    assert not f(_sse({"choices": [{"delta": {"role": "assistant", "content": None}}]}))
    assert not f(_sse({"choices": [{"delta": {"role": "assistant", "content": ""}}]}))
    assert not f("data: [DONE]\n\n")
    assert not f(_sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
    assert not f(_sse({"error": {"message": "boom"}}))
    assert f(_sse({"choices": [{"delta": {"content": "你"}}]}))
    assert f(_sse({"choices": [{"delta": {"reasoning_content": "想"}}]}).encode())
    assert f(_sse({"choices": [{"delta": {"reasoning": "想"}}]}))
    assert f(_sse({"choices": [{"delta": {"tool_calls": [{"index": 0}]}}]}))


def test_claude_frames():
    f = rt.claude_has_content
    assert not f(_sse({"type": "message_start", "message": {}}, "message_start"))
    assert not f(_sse({"type": "content_block_start", "index": 0,
                       "content_block": {"type": "text", "text": ""}}, "content_block_start"))
    assert not f(_sse({"type": "ping"}, "ping"))
    assert not f(": ping\n\n")
    assert not f(_sse({"type": "content_block_delta", "index": 0,
                       "delta": {"type": "text_delta", "text": ""}}, "content_block_delta"))
    assert f(_sse({"type": "content_block_delta", "index": 0,
                   "delta": {"type": "thinking_delta", "thinking": "想"}}, "content_block_delta"))
    assert f(_sse({"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": "你"}}, "content_block_delta"))
    assert f(_sse({"type": "content_block_delta", "index": 1,
                   "delta": {"type": "input_json_delta", "partial_json": "{}"}},
                  "content_block_delta"))


def test_responses_frames():
    f = rt.responses_has_content
    assert not f(_sse({"type": "response.created", "response": {}}, "response.created"))
    assert not f(_sse({"type": "response.in_progress", "response": {}}, "response.in_progress"))
    assert not f(_sse({"type": "response.output_item.added", "item": {}},
                      "response.output_item.added"))
    assert not f(_sse({"type": "response.output_text.delta", "delta": ""},
                      "response.output_text.delta"))
    assert not f(": ping\n\n")
    assert f(_sse({"type": "response.output_text.delta", "delta": "你"},
                  "response.output_text.delta"))
    assert f(_sse({"type": "response.reasoning_summary_text.delta", "delta": "想"},
                  "response.reasoning_summary_text.delta"))
    assert f(_sse({"type": "response.function_call_arguments.delta", "delta": "{}"},
                  "response.function_call_arguments.delta"))


def test_gemini_native_frames():
    f = rt.gemini_has_content
    assert not f("\n")
    assert not f(json.dumps({"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"},
                                             "finishReason": "STOP"}]}) + "\n")
    assert not f(json.dumps({"error": {"code": 500, "message": "boom"}}) + "\n")
    assert f(json.dumps({"candidates": [{"content": {"parts": [{"text": "你"}]}}]}) + "\n")
    assert f(json.dumps({"candidates": [{"content": {"parts": [
        {"text": "想", "thought": True}]}}]}) + "\n")
    assert f("data: " + json.dumps({"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "x", "args": {}}}]}}]}) + "\n\n")


def test_mark_first_token_is_idempotent_and_noop_without_context():
    rt.mark_first_token()          # 没有计时上下文：什么都不做、不报错
    timing = rt.RequestTiming(start=0.0)
    timing.mark(now=1.5)
    timing.mark(now=9.0)
    assert timing.ttft_ms() == 1500.0
    assert rt.RequestTiming(start=0.0).ttft_ms() is None


# ---------------------------------------------------------------------------
# 6. B2 核对：用量统计（usage_metrics）对流式请求本来就记整段生成时长
# ---------------------------------------------------------------------------

def test_usage_metrics_stream_latency_covers_whole_generation(monkeypatch):
    """account_pool.generate_stream 在整条上游流迭代完之后才 live_metrics.record_request，
    计时起点是拿到账号、开始调上游之前 —— 记的是整段生成时长，不是「开始」那一刻。"""
    from app.core import account_pool as ap
    from app.core.account_pool import Account, AccountPool, AccountStatus
    from app.core.usage_metrics import LiveMetricsCollector

    class _Client:
        is_healthy = True

        def __init__(self):
            self._heal_lock = asyncio.Lock()

        async def generate_stream(self, prompt, model, conversation_id="", attachments=None,
                                  gem_id=None, extended_thinking=False):
            await asyncio.sleep(D_FIRST)
            yield {"type": "delta", "text": "HELLO"}
            await asyncio.sleep(D_TAIL)
            yield {"type": "final", "text": "HELLO", "images": [], "conversation_id": ""}

    metrics = LiveMetricsCollector()
    monkeypatch.setattr(ap, "live_metrics", metrics)
    pool = AccountPool()
    pool._accounts = [Account(id="account-0", psid="p", psidts="", label="a",
                              status=AccountStatus.ACTIVE, client=_Client())]
    pool._max_concurrent = 8
    pool._acquire_timeout = 2.0

    async def drain():
        return [evt async for evt in pool.generate_stream("hi", "gemini-flash")]

    asyncio.run(drain())
    m = metrics.peek()
    assert m["latency_count"] == 1
    assert m["latency_sum_ms"] >= (D_FIRST + D_TAIL) * 1000


# ---------------------------------------------------------------------------
# 6. 第三方 key 的流：首字按「客户端收到的第一个内容帧」算，不按上游原始帧算
# ---------------------------------------------------------------------------
# /v1/responses 走第三方时，_dispatch_stream 自己读上游 chat 流、再转成 Responses 事件：上游的
# reasoning_content 不转发、tool_calls 攒到流尾才发。过去 api_forwarder 在上游流上也套了一层
# 首字计时，这层先触发 —— 上游刚开始思考 / 刚开始吐工具调用就记成了首字，客户端其实还什么都
# 没看到。

_TP_MODEL = "deepseek-r1"   # 不是 Gemini 模型名，必走第三方分发


def _install_thirdparty(monkeypatch, app, tmp_path, frames):
    """给 app 装一个只有一条 openai 兼容 key 的池，上游用 MockTransport 按 frames 慢慢吐。

    frames：[(先等多少秒, 这一帧的 chunk dict 或 "[DONE]"), ...]"""
    import httpx

    import app.core.api_forwarder as fwd
    from app.core.api_key_store import ApiKeyPool

    pool = ApiKeyPool(file_path=str(tmp_path / "api-keys.json"))
    pool.add(provider="openai", model=_TP_MODEL, api_key="sk-x", base_url="https://up.example/v1")
    monkeypatch.setattr(app.state, "api_key_pool", pool, raising=False)

    class _Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for delay, chunk in frames:
                if delay:
                    await asyncio.sleep(delay)
                payload = chunk if isinstance(chunk, str) else json.dumps(chunk)
                yield f"data: {payload}\n\n".encode()

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_Body())

    monkeypatch.setattr(fwd, "_make_async_client",
                        lambda timeout=300.0: httpx.AsyncClient(
                            transport=httpx.MockTransport(handler), timeout=timeout))
    monkeypatch.setattr(fwd, "_build_safe_target_url",
                        lambda entry, suffix: f"{entry.base_url.rstrip('/')}{suffix}")


def _role_frame():
    return {"choices": [{"delta": {"role": "assistant", "content": ""}}]}


_REASONING_THEN_TEXT = [
    (0, _role_frame()),
    (0.05, {"choices": [{"delta": {"reasoning_content": "thinking..."}}]}),
    (D_FIRST, {"choices": [{"delta": {"content": "HELLO"}}]}),
    (D_TAIL, {"choices": [{"delta": {"content": "WORLD"}}]}),
    (0, {"choices": [{"delta": {}, "finish_reason": "stop"}]}),
    (0, "[DONE]"),
]


def test_thirdparty_responses_stream_ttft_skips_unforwarded_reasoning(log_app, monkeypatch, tmp_path):
    """上游先思考 50ms 再出正文：Responses 客户端看不到思考，首字必须落在正文那一刻。"""
    from fastapi.testclient import TestClient

    app, store = log_app
    _install_thirdparty(monkeypatch, app, tmp_path, _REASONING_THEN_TEXT)

    with TestClient(app).stream("POST", "/v1/responses",
                                json={"model": _TP_MODEL, "input": "hi", "stream": True},
                                headers=_AUTH) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "response.output_text.delta" in text and "HELLO" in text and "WORLD" in text
    assert "thinking..." not in text            # 思考确实没转给客户端

    recs = _api_records(store)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.ttft_ms is not None
    assert rec.ttft_ms >= (0.05 + D_FIRST) * 1000, rec.ttft_ms
    assert rec.latency_ms >= (0.05 + D_FIRST + D_TAIL) * 1000, rec.latency_ms
    assert rec.latency_ms - rec.ttft_ms >= D_TAIL * 1000 * 0.8


def test_thirdparty_responses_stream_ttft_waits_for_held_tool_calls(log_app, monkeypatch, tmp_path):
    """只有工具调用的上游：工具调用攒到流尾才发给客户端，首字应贴着总耗时。"""
    from fastapi.testclient import TestClient

    app, store = log_app
    frames = [
        (0, _role_frame()),
        (0.05, {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "shell", "arguments": ""}}]}}]}),
        (D_FIRST, {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "{\"cmd\": \"ls\"}"}}]}}]}),
        (0, {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        (0, "[DONE]"),
    ]
    _install_thirdparty(monkeypatch, app, tmp_path, frames)
    body = {"model": _TP_MODEL, "input": "list files", "stream": True,
            "tools": [{"type": "function", "name": "shell",
                       "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}]}

    with TestClient(app).stream("POST", "/v1/responses", json=body, headers=_AUTH) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "function_call" in text and "call_1" in text

    rec = _api_records(store)[0]
    assert rec.ttft_ms is not None
    assert rec.ttft_ms >= (0.05 + D_FIRST) * 1000, rec.ttft_ms
    assert rec.latency_ms - rec.ttft_ms < 100, (rec.latency_ms, rec.ttft_ms)


def test_thirdparty_chat_stream_ttft_counts_forwarded_reasoning(log_app, monkeypatch, tmp_path):
    """/v1/chat/completions 走第三方是原样透传：思考帧客户端看得到，首字就落在思考那一刻。"""
    from fastapi.testclient import TestClient

    app, store = log_app
    _install_thirdparty(monkeypatch, app, tmp_path, _REASONING_THEN_TEXT)

    with TestClient(app).stream("POST", "/v1/chat/completions",
                                json={**_CHAT, "model": _TP_MODEL}, headers=_AUTH) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "thinking..." in text and "HELLO" in text

    recs = _api_records(store)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.ttft_ms is not None
    assert 50 <= rec.ttft_ms < (0.05 + D_FIRST) * 1000, rec.ttft_ms
    assert rec.latency_ms >= (0.05 + D_FIRST + D_TAIL) * 1000, rec.latency_ms


# ---------------------------------------------------------------------------
# 7. 流中途出错：照样正好一条记录，首字 / 总耗时都按实际
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(STREAMS))
def test_stream_error_after_content_logs_once_with_ttft(log_app, monkeypatch, case):
    from fastapi.testclient import TestClient

    app, store = log_app

    async def answers_then_breaks(prompt, model, conversation_id="", attachments=None, gem_id=None,
                                  account_id=None, extended_thinking=False):
        await asyncio.sleep(D_FIRST)
        yield {"type": "delta", "text": "HELLO"}
        await asyncio.sleep(D_TAIL)
        raise RuntimeError("upstream broke mid-stream")

    _install_stream(monkeypatch, answers_then_breaks)
    path, body = STREAMS[case]

    # 有的协议把异常转成错误帧收尾，有的让它冒出去（服务器断流）；两种都要只记一条
    try:
        with TestClient(app, raise_server_exceptions=False).stream(
                "POST", path, json=body, headers=_AUTH) as r:
            assert r.status_code == 200
            "".join(r.iter_text())
    except Exception:   # noqa: BLE001 断流在客户端这边表现为读出错，不是本测试关心的
        pass

    recs = _api_records(store)
    assert len(recs) == 1, [r.path for r in recs]
    rec = recs[0]
    assert rec.ttft_ms is not None
    assert rec.ttft_ms >= D_FIRST * 1000, rec.ttft_ms
    assert rec.latency_ms >= (D_FIRST + D_TAIL) * 1000, rec.latency_ms
    assert rec.ttft_ms <= rec.latency_ms


# ---------------------------------------------------------------------------
# 8. 思考帧算首字：Claude messages（thinking 开）与 Gemini 原生（includeThoughts）端到端
# ---------------------------------------------------------------------------

async def _thinks_then_answers(prompt, model, conversation_id="", attachments=None, gem_id=None,
                               account_id=None, extended_thinking=False):
    await asyncio.sleep(D_FIRST)
    yield {"type": "thoughts", "text": "THINKING"}
    await asyncio.sleep(D_TAIL * 2)
    yield {"type": "delta", "text": "ANSWER"}
    yield {"type": "final", "text": "ANSWER", "conversation_id": "", "images": [],
           "thoughts": "THINKING"}


@pytest.mark.parametrize("case", ["anthropic", "gemini"])
def test_stream_ttft_counts_thinking_frames_claude_and_gemini(log_app, monkeypatch, case):
    from fastapi.testclient import TestClient

    app, store = log_app
    monkeypatch.setattr(settings, "extended_thinking_enabled", True)
    _install_stream(monkeypatch, _thinks_then_answers)
    path, body = STREAMS[case]
    if case == "anthropic":
        body = {**body, "max_tokens": 4096,
                "thinking": {"type": "enabled", "budget_tokens": 2048}}
    else:
        body = {**body, "generationConfig": {
            "thinkingConfig": {"includeThoughts": True, "thinkingBudget": 2048}}}

    with TestClient(app).stream("POST", path, json=body, headers=_AUTH) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "THINKING" in text and "ANSWER" in text

    rec = _api_records(store)[0]
    assert rec.ttft_ms is not None
    assert D_FIRST * 1000 <= rec.ttft_ms < (D_FIRST + D_TAIL * 2) * 1000, rec.ttft_ms
    assert rec.latency_ms >= (D_FIRST + D_TAIL * 2) * 1000

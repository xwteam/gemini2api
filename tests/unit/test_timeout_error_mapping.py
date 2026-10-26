"""生成超时不能再变成纯文本 500（v1.6.45 规格 A）。

线上（新加坡中转站 v1.6.44，北京 2026-10-26 14:18～14:4x）：谷歌那边 3.8 Flash 卡住，非流式生成
按预算 120 秒掐断、抛 GenerationTimedOut（TimeoutError 的子类）。四个协议路由的非流式 / buffered
路径只接 (RuntimeError, ValueError, HTTPStatusError)，超时一路冒到 ASGI 层，客户端拿到纯文本的
「500 Internal Server Error」：OpenAI / Anthropic SDK 都解析不了、不会按超时重试，开了
FALLBACK_ENABLED 也没去兜底。

本文件钉住：
  - classify_error：生成期超时 → (504, "timeout_error", None)；
  - 四个协议的非流式与 buffered（带工具的伪流式）路径：504 + 该协议的 JSON 错误信封（流式路径是
    协议内错误事件），开兜底时先兜底；
  - 超时不触发「退回不思考再试一次」，也不触发「会话过期、用完整 prompt 重试」（预算已经花完）；
  - 真流式路径的错误事件类型是 timeout_error，不是 api_error / 500。
"""

import asyncio
import json

import pytest
from curl_cffi.requests import RequestsError

from app.core.gemini_client import GenerationTimedOut, HTTPStatusError, classify_error

_AUTH = {"Authorization": "Bearer sk-test-key"}

_TOOLS_OPENAI = [{"type": "function", "function": {
    "name": "get_weather", "description": "w",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
}}]
_TOOLS_ANTHROPIC = [{"name": "get_weather", "description": "w",
                     "input_schema": {"type": "object", "properties": {}}}]
_TOOLS_GEMINI = [{"functionDeclarations": [{"name": "get_weather", "description": "w",
                                             "parameters": {"type": "object", "properties": {}}}]}]
_TOOLS_RESPONSES = [{"type": "function", "name": "get_weather", "description": "w",
                     "parameters": {"type": "object", "properties": {}}}]


def _timed_out() -> GenerationTimedOut:
    return GenerationTimedOut(120, 120.4, RequestsError("Operation timed out", code=28))


class _Calls:
    """记录 generate / generate_stream 被调了几次、带的什么参数。"""

    def __init__(self):
        self.generate = []
        self.stream = []


def _patch_timeouts(monkeypatch, router_module) -> _Calls:
    """把路由用的 gemini_client（账号池）换成「每次都超时」的替身。"""
    calls = _Calls()

    async def generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       account_id=None, extended_thinking=False):
        calls.generate.append({"prompt": prompt, "conv": conversation_id,
                               "thinking": extended_thinking, "account_id": account_id})
        raise _timed_out()

    async def generate_stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                              account_id=None, extended_thinking=False):
        calls.stream.append({"prompt": prompt, "conv": conversation_id,
                             "thinking": extended_thinking, "account_id": account_id})
        raise _timed_out()
        yield  # pragma: no cover - 保留 async generator 形状

    monkeypatch.setattr(router_module.gemini_client, "generate", generate)
    monkeypatch.setattr(router_module.gemini_client, "generate_stream", generate_stream)
    return calls


def _sse_events(body: str):
    """SSE 文本 → [(event, data)]；忽略注释行（: ping）与 [DONE]。"""
    out = []
    for block in body.split("\n\n"):
        ev, data = None, None
        for line in block.split("\n"):
            if not line.strip() or line.startswith(":"):
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                if raw == "[DONE]":
                    continue
                data = json.loads(raw)
        if ev or data is not None:
            out.append((ev, data))
    return out


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    _timed_out(),
    TimeoutError("read timed out"),
    asyncio.TimeoutError(),
    RequestsError("Operation timed out after 180000 milliseconds", code=28),
], ids=["GenerationTimedOut", "TimeoutError", "asyncio.TimeoutError", "curl-code-28"])
def test_generation_timeouts_classify_as_504_timeout_error(exc):
    assert classify_error(exc) == (504, "timeout_error", None)


def test_other_curl_errors_keep_their_old_mapping():
    """只有超时（code 28）改成 504；别的 curl 错误照旧（落到兜底的 500 api_error）。"""
    assert classify_error(RequestsError("Could not resolve host", code=6)) == (500, "api_error", None)


@pytest.mark.parametrize("exc,expected", [
    (HTTPStatusError(429, "x"), (429, "rate_limit_error", None)),
    (HTTPStatusError(503, "x"), (503, "api_error", None)),
    (RuntimeError("No available accounts"), (529, "overloaded_error", 30)),
    (RuntimeError("Client not ready"), (500, "api_error", None)),
    (ValueError("bad model"), (400, "invalid_request_error", None)),
])
def test_non_timeout_mappings_are_unchanged(exc, expected):
    assert classify_error(exc) == expected


# ---------------------------------------------------------------------------
# OpenAI chat completions
# ---------------------------------------------------------------------------

def _assert_json_504(r, envelope_type_path=("error", "type")):
    assert r.status_code == 504, r.text
    assert r.headers["content-type"].startswith("application/json"), r.headers
    body = r.json()
    node = body
    for key in envelope_type_path:
        node = node[key]
    assert node == "timeout_error", body
    return body


def test_openai_nonstream_timeout_is_a_504_json_error_and_is_not_retried(gem_client, monkeypatch):
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)

    body = _assert_json_504(r)
    assert "timed out" in body["error"]["message"]
    # 默认思考档（出厂 low）开着：超时不能触发「退回不思考再试一次」
    assert len(calls.generate) == 1, calls.generate
    assert calls.generate[0]["thinking"], "前提不成立：这条请求本该走思考路径"


def test_openai_nonstream_timeout_tries_the_third_party_fallback_first(gem_client, monkeypatch):
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    seen = {}

    async def fake_fallback(request, req, messages_raw, exclude_model=""):
        seen["hit"] = True
        return {"id": "chatcmpl-fb", "object": "chat.completion", "created": 0, "model": "tp",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "from fallback"}}]}

    monkeypatch.setattr(oai, "_fallback_result", fake_fallback)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)

    assert seen.get("hit") is True
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "from fallback"
    assert len(calls.generate) == 1


class _ConvStore:
    """内存版 conversation_store，预置一条可续接的会话。"""

    def __init__(self, records=None):
        self.records = dict(records or {})

    async def get(self, conv_id):
        return self.records.get(conv_id)

    async def create(self, conv_id, model):
        from types import SimpleNamespace
        conv = SimpleNamespace(id=conv_id, gemini_conv_id="", account_id="", model=model,
                               messages=[], add_message=lambda role, content: None)
        self.records[conv_id] = conv
        return conv

    async def update(self, conv):
        self.records[conv.id] = conv


def _resumable_conversation(conv_id="thread-1"):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=conv_id, gemini_conv_id=json.dumps(["c_abc", "r_def", "rc_ghi"]),
        account_id="account-0", model="gemini-pro", messages=[],
        add_message=lambda role, content: None,
    )


def test_openai_nonstream_timeout_in_a_resumed_conversation_is_not_retried_with_full_prompt(
        gem_client, monkeypatch):
    """「会话过期 → 用完整 prompt 重试」不能被超时触发：预算已经花完，再试让客户端再等一整轮。"""
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    monkeypatch.setattr(oai, "conversation_store", _ConvStore({"thread-1": _resumable_conversation()}))
    monkeypatch.setattr(oai.gemini_client, "account_pinnable", lambda account_id: True, raising=False)

    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False, "conversation_id": "thread-1",
        "messages": [{"role": "user", "content": "first"},
                     {"role": "assistant", "content": "answer"},
                     {"role": "user", "content": "second"}],
    }, headers=_AUTH)

    _assert_json_504(r)
    assert len(calls.generate) == 1, calls.generate
    assert calls.generate[0]["conv"], "前提不成立：第一次本该走续接分支"


def test_openai_buffered_tool_stream_timeout_emits_a_timeout_error_frame(gem_client, monkeypatch):
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-pro", "stream": True, "tools": _TOOLS_OPENAI,
        "messages": [{"role": "user", "content": "weather?"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    errors = [d["error"] for _, d in _sse_events(body) if isinstance(d, dict) and "error" in d]
    assert len(errors) == 1, body
    assert errors[0]["type"] == "timeout_error"
    assert errors[0]["code"] == 504
    assert len(calls.generate) == 1, calls.generate


def test_openai_buffered_tool_stream_timeout_tries_the_fallback_first(gem_client, monkeypatch):
    import app.routers.openai as oai

    _patch_timeouts(monkeypatch, oai)

    async def fake_fallback_stream(request, req, messages_raw, exclude_model, completion_id, model_name):
        yield 'data: {"fallback": true}\n\n'

    monkeypatch.setattr(oai, "_maybe_fallback_stream", fake_fallback_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-pro", "stream": True, "tools": _TOOLS_OPENAI,
        "messages": [{"role": "user", "content": "weather?"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert '"fallback": true' in body
    assert "timeout_error" not in body


def _drive(agen):
    async def run():
        return "".join([chunk async for chunk in agen])

    return asyncio.run(run())


def test_openai_buffered_timeout_with_a_conversation_is_not_retried_with_full_prompt(monkeypatch):
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    body = _drive(oai._stream_response_buffered(
        "prompt", "gemini-pro", False, json.dumps(["c_abc", "r_def", "rc_ghi"]), None,
        [{"role": "user", "content": "hi"}],
        "gemini-pro", "chatcmpl-test", None, "", None, None, None, None,
    ))

    assert len(calls.generate) == 1, calls.generate
    errors = [d["error"] for _, d in _sse_events(body) if isinstance(d, dict) and "error" in d]
    assert [e["type"] for e in errors] == ["timeout_error"], body


def test_openai_real_stream_timeout_emits_a_timeout_error_frame_without_retrying(gem_client, monkeypatch):
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-pro", "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    errors = [d["error"] for _, d in _sse_events(body) if isinstance(d, dict) and "error" in d]
    assert len(errors) == 1, body
    assert (errors[0]["type"], errors[0]["code"]) == ("timeout_error", 504)
    assert len(calls.stream) == 1
    assert calls.generate == [], "超时不该触发非流式的不思考重试"


def test_openai_real_stream_timeout_with_a_conversation_is_not_retried_with_full_prompt(monkeypatch):
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)
    body = _drive(oai._stream_response(
        "prompt", "gemini-pro", False, json.dumps(["c_abc", "r_def", "rc_ghi"]), None,
        [{"role": "user", "content": "hi"}], "gemini-pro",
    ))

    assert calls.generate == [], calls.generate
    errors = [d["error"] for _, d in _sse_events(body) if isinstance(d, dict) and "error" in d]
    assert [e["type"] for e in errors] == ["timeout_error"], body


def test_openai_real_stream_timeout_after_partial_output_keeps_the_text_and_reports_timeout(
        gem_client, monkeypatch):
    """已经流出正文后再超时：既有行为不变（不兜底、不重试、已发的正文不收回），只是错误帧的
    type 变成 timeout_error。"""
    import app.routers.openai as oai

    calls = _patch_timeouts(monkeypatch, oai)

    async def partial_then_timeout(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        yield {"type": "delta", "text": "partial answer"}
        raise TimeoutError()

    monkeypatch.setattr(oai.gemini_client, "generate_stream", partial_then_timeout)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-pro", "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert "partial answer" in body
    errors = [d["error"] for _, d in _sse_events(body) if isinstance(d, dict) and "error" in d]
    assert [e["type"] for e in errors] == ["timeout_error"], body
    assert calls.generate == []


# ---------------------------------------------------------------------------
# Anthropic messages
# ---------------------------------------------------------------------------

def test_claude_nonstream_timeout_is_a_504_anthropic_error_and_is_not_retried(gem_client, monkeypatch):
    import app.routers.claude as cl

    calls = _patch_timeouts(monkeypatch, cl)
    r = gem_client.post("/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)

    body = _assert_json_504(r)
    assert body["type"] == "error"
    assert len(calls.generate) == 1, calls.generate
    assert calls.generate[0]["thinking"], "前提不成立：这条请求本该走思考路径"


def test_claude_buffered_tool_stream_timeout_emits_timeout_error_event(gem_client, monkeypatch):
    import app.routers.claude as cl

    calls = _patch_timeouts(monkeypatch, cl)
    with gem_client.stream("POST", "/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": True, "tools": _TOOLS_ANTHROPIC,
        "messages": [{"role": "user", "content": "weather?"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    errors = [d["error"] for ev, d in _sse_events(body) if ev == "error"]
    assert [e["type"] for e in errors] == ["timeout_error"], body
    assert len(calls.generate) == 1, calls.generate


def test_claude_real_stream_timeout_emits_timeout_error_event_without_retrying(gem_client, monkeypatch):
    import app.routers.claude as cl

    calls = _patch_timeouts(monkeypatch, cl)
    with gem_client.stream("POST", "/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    errors = [d["error"] for ev, d in _sse_events(body) if ev == "error"]
    assert [e["type"] for e in errors] == ["timeout_error"], body
    assert calls.generate == []
    assert "end_turn" not in body


# ---------------------------------------------------------------------------
# Gemini 原生
# ---------------------------------------------------------------------------

def _ndjson_errors(body: str):
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "error" in obj:
            out.append(obj["error"])
    return out


def test_gemini_nonstream_timeout_is_a_504_json_error_and_is_not_retried(gem_client, monkeypatch):
    import app.routers.gemini as ge

    calls = _patch_timeouts(monkeypatch, ge)
    r = gem_client.post("/v1beta/models/gemini-pro:generateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    }, headers=_AUTH)

    body = _assert_json_504(r)
    assert "timed out" in body["error"]["message"]
    assert len(calls.generate) == 1, calls.generate


def test_gemini_buffered_tool_stream_timeout_emits_timeout_error_line(gem_client, monkeypatch):
    import app.routers.gemini as ge

    calls = _patch_timeouts(monkeypatch, ge)
    with gem_client.stream("POST", "/v1beta/models/gemini-pro:streamGenerateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "weather?"}]}],
        "tools": _TOOLS_GEMINI,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert [e["type"] for e in _ndjson_errors(body)] == ["timeout_error"], body
    assert len(calls.generate) == 1, calls.generate


def test_gemini_real_stream_timeout_emits_timeout_error_line_without_retrying(gem_client, monkeypatch):
    import app.routers.gemini as ge

    calls = _patch_timeouts(monkeypatch, ge)
    with gem_client.stream("POST", "/v1beta/models/gemini-pro:streamGenerateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert [e["type"] for e in _ndjson_errors(body)] == ["timeout_error"], body
    assert calls.generate == []


def test_gemini_stream_non_timeout_errors_keep_their_old_type(gem_client, monkeypatch):
    """零回归：NDJSON 流里别的失败照旧是 api_error（只有超时换成 timeout_error）。"""
    import app.routers.gemini as ge

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise RuntimeError("upstream exploded")
        yield  # pragma: no cover

    async def boom_generate(*a, **k):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(ge.gemini_client, "generate_stream", boom)
    monkeypatch.setattr(ge.gemini_client, "generate", boom_generate)
    with gem_client.stream("POST", "/v1beta/models/gemini-pro:streamGenerateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert [e["type"] for e in _ndjson_errors(body)] == ["api_error"], body


# ---------------------------------------------------------------------------
# OpenAI Responses
# ---------------------------------------------------------------------------

def _failed_events(body: str):
    return [d["response"] for ev, d in _sse_events(body) if ev == "response.failed"]


def test_responses_nonstream_timeout_is_a_504_json_error_and_is_not_retried(gem_client, monkeypatch):
    import app.routers.responses as rr

    calls = _patch_timeouts(monkeypatch, rr)
    r = gem_client.post("/v1/responses", json={"model": "gemini-pro", "input": "hi"}, headers=_AUTH)

    body = _assert_json_504(r)
    assert "timed out" in body["error"]["message"]
    assert len(calls.generate) == 1, calls.generate
    assert calls.generate[0]["thinking"], "前提不成立：这条请求本该走思考路径"


def test_responses_nonstream_other_failures_keep_their_old_status(gem_client, monkeypatch):
    """零回归：Responses 非流式别的失败照旧 502 api_error。"""
    import app.routers.responses as rr

    async def boom(*a, **k):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(rr.gemini_client, "generate", boom)
    r = gem_client.post("/v1/responses", json={"model": "gemini-pro", "input": "hi"}, headers=_AUTH)
    assert r.status_code == 502, r.text
    assert r.json()["error"]["type"] == "api_error"


def test_responses_buffered_tool_stream_timeout_fails_with_timeout_code(gem_client, monkeypatch):
    import app.routers.responses as rr

    calls = _patch_timeouts(monkeypatch, rr)
    with gem_client.stream("POST", "/v1/responses", json={
        "model": "gemini-pro", "input": "weather?", "stream": True, "tools": _TOOLS_RESPONSES,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    failed = _failed_events(body)
    assert len(failed) == 1, body
    assert failed[0]["error"]["code"] == "timeout_error"
    assert len(calls.generate) == 1, calls.generate


def test_responses_real_stream_timeout_fails_with_timeout_code_without_retrying(gem_client, monkeypatch):
    import app.routers.responses as rr

    calls = _patch_timeouts(monkeypatch, rr)
    with gem_client.stream("POST", "/v1/responses", json={
        "model": "gemini-pro", "input": "hi", "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    failed = _failed_events(body)
    assert len(failed) == 1, body
    assert failed[0]["error"]["code"] == "timeout_error"
    assert calls.generate == [], calls.generate


def test_responses_stream_other_failures_keep_internal_error_code(gem_client, monkeypatch):
    import app.routers.responses as rr

    async def boom_stream(*a, **k):
        raise RuntimeError("upstream exploded")
        yield  # pragma: no cover

    async def boom(*a, **k):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(rr.gemini_client, "generate_stream", boom_stream)
    monkeypatch.setattr(rr.gemini_client, "generate", boom)
    with gem_client.stream("POST", "/v1/responses", json={
        "model": "gemini-pro", "input": "hi", "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    failed = _failed_events(body)
    assert [f["error"]["code"] for f in failed] == ["internal_error"], body

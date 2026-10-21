"""Defect ②③ 回归测试（+ R2 残余修复）：

② Claude 真流式失败此前会伪装成 stop_reason=end_turn 的正常回答（content_block_delta 里塞
   "Error: ..." 文本，然后照常走 content_block_stop/message_delta/message_stop 收尾）——官方 SDK
   看不到异常，client 的重试/故障转移/退避永远不会触发，错误文本还会被当成模型说的话存进历史。
   修复后必须发标准 Anthropic error 事件并直接结束流。

③ app/core/gemini_client.HTTPStatusError 不是 RuntimeError/ValueError 的子类，三个协议路由的
   非流式入口此前只捕获 (RuntimeError, ValueError)，导致每个 Google 4xx（含 429）都逃逸成裸 500
   （openai.py 还因此绕过了第三方兜底）。且旧的 "retry" in str(e).lower() 状态码映射是死代码：
   account_pool 里三条真实的池耗尽/打满消息都不含 "retry"，池打满因此被误判成不可重试的 400。
   三个路由现在统一复用 app.core.gemini_client.classify_error，且与 ② 的流式错误分类共用同一份。

R2：classify_error 对上游 4xx 的 type 错配——HTTPStatusError(400) 此前返回 "api_error"，
   语义上 400 应是 "invalid_request_error"（请求侧问题，不该跟 5xx 的 "api_error" 混用）。
   细化为：429 → rate_limit_error；其余 4xx（含 400/401/403/404）→ invalid_request_error；
   5xx → api_error。上游状态码透传保持不变，只细化 type。
"""
import json

import pytest

from app.core.gemini_client import HTTPStatusError, classify_error

_AUTH = {"Authorization": "Bearer sk-test-key"}


# ---------------------------------------------------------------------------
# 纯函数：classify_error 映射表
# ---------------------------------------------------------------------------

def test_classify_http_status_error_429_is_rate_limit():
    status, err_type, retry_after = classify_error(HTTPStatusError(429, "rate limited"))
    assert (status, err_type) == (429, "rate_limit_error")
    assert retry_after is None


def test_classify_http_status_error_other_status_is_api_error():
    status, err_type, retry_after = classify_error(HTTPStatusError(503, "boom"))
    assert (status, err_type) == (503, "api_error")
    assert retry_after is None


@pytest.mark.parametrize("status,expected_type", [
    (400, "invalid_request_error"),
    (401, "invalid_request_error"),
    (403, "invalid_request_error"),
    (404, "invalid_request_error"),
    (429, "rate_limit_error"),
    (500, "api_error"),
    (503, "api_error"),
])
def test_classify_http_status_error_type_by_status_r2(status, expected_type):
    """R2：4xx（含 400）细分成 invalid_request_error，5xx 仍是 api_error；状态码本身透传不变。"""
    result_status, err_type, _retry_after = classify_error(HTTPStatusError(status, "boom"))
    assert (result_status, err_type) == (status, expected_type)


def test_classify_pool_exhausted_runtime_errors_are_529_with_retry_after():
    # 与 app/core/account_pool.py::acquire 实际抛出的三条消息逐字对齐（均不含 "retry"，
    # 曾经的死代码判断会把它们全部误判成 400）。
    for msg in (
        "No more accounts to failover to",
        "No available accounts",
        "All accounts busy (max_concurrent=8), waited 60.0s",
    ):
        status, err_type, retry_after = classify_error(RuntimeError(msg))
        assert (status, err_type) == (529, "overloaded_error"), msg
        assert retry_after and retry_after > 0


def test_classify_other_runtime_error_is_500():
    status, err_type, retry_after = classify_error(RuntimeError("Client not ready"))
    assert (status, err_type) == (500, "api_error")
    assert retry_after is None


def test_classify_value_error_is_400():
    status, err_type, retry_after = classify_error(ValueError("Model 'bogus' unavailable"))
    assert (status, err_type) == (400, "invalid_request_error")
    assert retry_after is None


# ---------------------------------------------------------------------------
# ② Claude 真流式：上游失败必须是错误事件，不能是伪装的成功收尾
# ---------------------------------------------------------------------------

def _parse_sse(body: str):
    """把 SSE 文本解析成 [(event, data_json)]，忽略注释行(: ping)。"""
    out = []
    for chunk in body.split("\n\n"):
        ev, data = None, None
        for line in chunk.split("\n"):
            if line.startswith(":") or not line.strip():
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if ev or data:
            out.append((ev, data))
    return out


def test_claude_real_stream_error_emits_error_event_not_fake_success(gem_client, monkeypatch):
    import app.routers.claude as cl

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        yield {"type": "delta", "text": "partial "}
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(cl.gemini_client, "generate_stream", fake_generate_stream)
    with gem_client.stream("POST", "/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    frames = _parse_sse(body)
    assert frames, "no SSE frames parsed"

    error_frames = [d for ev, d in frames if ev == "error"]
    assert len(error_frames) == 1, body
    assert error_frames[0]["error"]["message"] == "upstream exploded"
    assert error_frames[0]["error"]["type"] == "api_error"

    # 不能有伪装成功的收尾：没有 message_delta（更别提 stop_reason=end_turn），没有 message_stop。
    assert not any(ev == "message_delta" for ev, _ in frames)
    assert not any(ev == "message_stop" for ev, _ in frames)
    assert "end_turn" not in body

    # 失败文本绝不能混进 content_block_delta（旧行为：content_block_delta 里塞 "Error: ..."）。
    delta_texts = [
        d.get("delta", {}).get("text", "")
        for ev, d in frames
        if ev == "content_block_delta"
    ]
    assert all("upstream exploded" not in t and "Error:" not in t for t in delta_texts)


def test_claude_real_stream_http_status_error_matches_nonstream_type(gem_client, monkeypatch):
    """流式（②）与非流式（③）复用同一个 classify_error：HTTPStatusError(429) 两条路径
    必须给出同一个 error.type，不能各说各话。"""
    import app.routers.claude as cl

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        raise HTTPStatusError(429, "rate limited")
        yield  # pragma: no cover - 只为让本函数保留 async generator 形状

    monkeypatch.setattr(cl.gemini_client, "generate_stream", fake_generate_stream)
    # 默认思考档（出厂 low）开着时，真流式失败会先退回不思考的非流式重试一次；
    # 上游整体故障时那一次也同样失败，这里让 generate 抛同一个错误。
    async def _same_failure(*a, **k):
        raise HTTPStatusError(429, "rate limited")

    monkeypatch.setattr(cl.gemini_client, "generate", _same_failure)
    with gem_client.stream("POST", "/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    error_frames = [d for ev, d in _parse_sse(body) if ev == "error"]
    assert len(error_frames) == 1, body
    assert error_frames[0]["error"]["type"] == "rate_limit_error"


# ---------------------------------------------------------------------------
# ③ 非流式：三个协议路由都要正确捕获 HTTPStatusError，并用 classify_error 给出真实映射
# ---------------------------------------------------------------------------

def test_claude_nonstream_http_status_error_maps_to_upstream_status(gem_client, monkeypatch):
    import app.routers.claude as cl

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise HTTPStatusError(429, "rate limited")

    monkeypatch.setattr(cl.gemini_client, "generate", boom)
    r = gem_client.post("/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["type"] == "rate_limit_error"


def test_claude_nonstream_pool_busy_maps_to_529_with_retry_after(gem_client, monkeypatch):
    import app.routers.claude as cl

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise RuntimeError("All accounts busy (max_concurrent=8), waited 60.0s")

    monkeypatch.setattr(cl.gemini_client, "generate", boom)
    r = gem_client.post("/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 529, r.text
    assert r.headers.get("retry-after") == "30"
    assert r.json()["error"]["type"] == "overloaded_error"


def test_claude_nonstream_value_error_maps_to_400(gem_client, monkeypatch):
    import app.routers.claude as cl

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise ValueError("Model 'bogus' unavailable")

    monkeypatch.setattr(cl.gemini_client, "generate", boom)
    r = gem_client.post("/v1/messages", json={
        "model": "gemini-pro", "max_tokens": 100, "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_openai_nonstream_http_status_error_maps_to_upstream_status(gem_client, monkeypatch):
    import app.routers.openai as oai

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise HTTPStatusError(429, "rate limited")

    monkeypatch.setattr(oai.gemini_client, "generate", boom)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["type"] == "rate_limit_error"


def test_openai_nonstream_pool_busy_maps_to_529_with_retry_after(gem_client, monkeypatch):
    import app.routers.openai as oai

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise RuntimeError("No available accounts")

    monkeypatch.setattr(oai.gemini_client, "generate", boom)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 529, r.text
    assert r.headers.get("retry-after") == "30"
    assert r.json()["error"]["type"] == "overloaded_error"


def test_openai_nonstream_value_error_maps_to_400(gem_client, monkeypatch):
    import app.routers.openai as oai

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise ValueError("Model 'bogus' unavailable")

    monkeypatch.setattr(oai.gemini_client, "generate", boom)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_openai_nonstream_http_status_error_still_tries_fallback(gem_client, monkeypatch):
    """曾经的 bug：HTTPStatusError 不在捕获元组里 -> 未处理异常直接 500，_fallback_result
    根本没机会跑。修复后即使上游是 HTTPStatusError，也必须先过一遍既有的第三方兜底逻辑。"""
    import app.routers.openai as oai

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise HTTPStatusError(500, "upstream 500")

    monkeypatch.setattr(oai.gemini_client, "generate", boom)

    called = {}

    async def fake_fallback(request, req, messages_raw, exclude_model=""):
        called["hit"] = True
        return {
            "id": "chatcmpl-fb", "object": "chat.completion", "created": 0,
            "model": "third-party",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "fallback answer"},
                "finish_reason": "stop",
            }],
        }

    monkeypatch.setattr(oai, "_fallback_result", fake_fallback)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert called.get("hit") is True
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "fallback answer"


def test_gemini_nonstream_http_status_error_maps_to_upstream_status(gem_client, monkeypatch):
    import app.routers.gemini as ge

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        raise HTTPStatusError(429, "rate limited")

    monkeypatch.setattr(ge.gemini_client, "generate", boom)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
        headers=_AUTH,
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["type"] == "rate_limit_error"


def test_gemini_nonstream_pool_busy_maps_to_529_with_retry_after(gem_client, monkeypatch):
    import app.routers.gemini as ge

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        raise RuntimeError("No more accounts to failover to")

    monkeypatch.setattr(ge.gemini_client, "generate", boom)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
        headers=_AUTH,
    )
    assert r.status_code == 529, r.text
    assert r.headers.get("retry-after") == "30"
    assert r.json()["error"]["type"] == "overloaded_error"


def test_gemini_nonstream_value_error_maps_to_400(gem_client, monkeypatch):
    import app.routers.gemini as ge

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        raise ValueError("Model 'bogus' unavailable")

    monkeypatch.setattr(ge.gemini_client, "generate", boom)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
        headers=_AUTH,
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"

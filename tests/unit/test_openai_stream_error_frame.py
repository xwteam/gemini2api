"""R1：OpenAI 真流式的上游错误此前被伪装成一次"成功完成的回答"——_err_chunk 发出
content:"Error: ..." + finish_reason="stop"，官方 openai SDK 看不到异常（它检测的是
data 帧里的顶层 "error" 键，见 openai/_streaming.py），client 的重试/故障转移/退避
永远不会触发，错误文本还会被当成模型说的话存进对话历史。与 v1.6.35 在 Claude 侧修的
defect ② 属同一缺陷类，这里补 OpenAI 协议的残留。

必须保留的既有行为（不能回归）：
- 第三方兜底（_maybe_fallback_stream）仍先于错误帧被尝试。
- 已经流出内容后才失败的场景，不能把已发内容回退掉。
- 仍以 `data: [DONE]` 收尾（SSE 收尾约定）。
"""
import json

from app.core.gemini_client import HTTPStatusError

_AUTH = {"Authorization": "Bearer sk-test-key"}


def _parse_sse(body: str):
    """把 SSE body 解析成 [("data", dict), ...]，"[DONE]" 单独标记，忽略 ping 注释行。"""
    out = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                out.append(("[DONE]", None))
            else:
                out.append(("data", json.loads(raw)))
    return out


def _error_frames(body: str):
    return [d for tag, d in _parse_sse(body) if tag == "data" and isinstance(d, dict) and "error" in d]


def test_realstream_error_before_any_delta_emits_error_frame_not_fake_success(gem_client, monkeypatch):
    import app.routers.openai as oai

    async def boom_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        raise RuntimeError("boom")
        yield  # pragma: no cover — 让函数保持 async generator 形态

    monkeypatch.setattr(oai.gemini_client, "generate_stream", boom_generate_stream)
    # 默认思考档（出厂 low）开着时，真流式失败会先退回不思考的非流式重试一次；
    # 上游整体故障时那一次也同样失败，这里让 generate 抛同一个错误。
    async def _same_failure(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(oai.gemini_client, "generate", _same_failure)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }, headers=_AUTH) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())

    error_frames = _error_frames(body)
    assert len(error_frames) == 1, body
    assert error_frames[0]["error"]["message"] == "boom"
    assert error_frames[0]["error"]["type"] == "api_error"
    assert error_frames[0]["error"]["code"] == 500

    # 不能伪装成功：没有 content:"Error: ..." 的增量，没有 finish_reason="stop"。
    assert "Error: boom" not in body
    data_frames = [d for tag, d in _parse_sse(body) if tag == "data"]
    assert not any(
        (d.get("choices") or [{}])[0].get("finish_reason") == "stop"
        for d in data_frames if "choices" in d
    )
    assert any(tag == "[DONE]" for tag, _ in _parse_sse(body))   # 仍以 [DONE] 收尾


def test_realstream_error_after_partial_content_keeps_streamed_content(gem_client, monkeypatch):
    """已经流出内容后才失败：内容不能被回退，但仍要用 error 帧收尾（不能伪装成功）。"""
    import app.routers.openai as oai

    async def boom_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        yield {"type": "delta", "text": "partial answer "}
        raise RuntimeError("mid-stream boom")

    monkeypatch.setattr(oai.gemini_client, "generate_stream", boom_generate_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert "partial answer" in body    # 已流出内容不能被回退

    error_frames = _error_frames(body)
    assert len(error_frames) == 1, body
    assert error_frames[0]["error"]["message"] == "mid-stream boom"
    assert "Error: mid-stream boom" not in body


def test_realstream_pool_exhausted_maps_to_overloaded_error_type(gem_client, monkeypatch):
    import app.routers.openai as oai

    async def boom_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        raise RuntimeError("No available accounts")
        yield  # pragma: no cover

    monkeypatch.setattr(oai.gemini_client, "generate_stream", boom_generate_stream)
    # 默认思考档（出厂 low）开着时，真流式失败会先退回不思考的非流式重试一次；
    # 上游整体故障时那一次也同样失败，这里让 generate 抛同一个错误。
    async def _same_failure(*a, **k):
        raise RuntimeError("No available accounts")

    monkeypatch.setattr(oai.gemini_client, "generate", _same_failure)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    error_frames = _error_frames(body)
    assert len(error_frames) == 1, body
    assert error_frames[0]["error"]["type"] == "overloaded_error"
    assert error_frames[0]["error"]["code"] == 529


def test_realstream_http_status_error_matches_nonstream_type(gem_client, monkeypatch):
    """流式（R1）与非流式复用同一个 classify_error：HTTPStatusError(429) 两条路径必须
    给出同一个 error.type，不能各说各话（与 Claude 侧同款回归对齐）。"""
    import app.routers.openai as oai

    async def boom_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        raise HTTPStatusError(429, "rate limited")
        yield  # pragma: no cover

    monkeypatch.setattr(oai.gemini_client, "generate_stream", boom_generate_stream)
    # 默认思考档（出厂 low）开着时，真流式失败会先退回不思考的非流式重试一次；
    # 上游整体故障时那一次也同样失败，这里让 generate 抛同一个错误。
    async def _same_failure(*a, **k):
        raise HTTPStatusError(429, "rate limited")

    monkeypatch.setattr(oai.gemini_client, "generate", _same_failure)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    error_frames = _error_frames(body)
    assert len(error_frames) == 1, body
    assert error_frames[0]["error"]["type"] == "rate_limit_error"
    assert error_frames[0]["error"]["code"] == 429


def test_realstream_error_still_tries_fallback_before_error_frame(gem_client, monkeypatch):
    """兜底必须先于错误帧被尝试：fallback 命中时压根不该看到 error 帧（不能回归）。"""
    import app.routers.openai as oai
    from app.core.stream import format_sse
    from app.models.openai import StreamChunk, StreamChoice, StreamDelta

    async def boom_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    async def fake_fallback_stream(request, req, messages_raw, exclude_model, completion_id, model_name):
        chunk = StreamChunk(id=completion_id, model=model_name,
                            choices=[StreamChoice(delta=StreamDelta(content="fallback content"))])
        yield format_sse(chunk.model_dump())
        done = StreamChunk(id=completion_id, model=model_name,
                           choices=[StreamChoice(delta=StreamDelta(), finish_reason="stop")])
        yield format_sse(done.model_dump())
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(oai.gemini_client, "generate_stream", boom_generate_stream)
    monkeypatch.setattr(oai, "_maybe_fallback_stream", fake_fallback_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert "fallback content" in body
    assert not _error_frames(body)   # 兜底命中就不该再落到错误帧

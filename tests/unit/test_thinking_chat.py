# reasoning_effort 不再被布尔化：high → THINKING_LEVEL_HIGH 这个具体档位，
# 下游用它决定 payload 的第 80 格与 model header 的第 15 位（见 gemini_client.parse_effort_request）。
from app.core.gemini_client import THINKING_LEVEL_DEFAULT, THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW

_AUTH = {"Authorization": "Bearer sk-test-key"}


def test_reasoning_effort_enables_thinking_and_returns_reasoning_content(gem_client, monkeypatch):
    import app.routers.openai as oai
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": "my thoughts"}
    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "high",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] == THINKING_LEVEL_HIGH
    assert r.json()["choices"][0]["message"]["reasoning_content"] == "my thoughts"


def test_no_reasoning_effort_uses_default_level_but_returns_no_reasoning(gem_client, monkeypatch):
    """不传 reasoning_effort：上游按"默认思考档位"（出厂 low）思考，但客户端没要求，
    **绝不回传 reasoning_content**。上游给了非空思考，才验得到这道拦截。"""
    import app.routers.openai as oai
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": "hidden thoughts"}
    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert captured["ext"] == THINKING_LEVEL_LOW
    assert r.json()["choices"][0]["message"].get("reasoning_content") is None
    assert "hidden thoughts" not in r.text


def test_blank_reasoning_effort_counts_as_not_passed(gem_client, monkeypatch):
    """纯空白 reasoning_effort（如 "   "）strip 后为空，视同未设置：默认档、不回传。"""
    import app.routers.openai as oai
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": "hidden thoughts"}
    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "   ",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] == THINKING_LEVEL_LOW
    assert r.json()["choices"][0]["message"].get("reasoning_content") is None


def test_extended_thinking_disabled_by_settings_toggle(gem_client, monkeypatch):
    """全局开关 extended_thinking_enabled=False 时，即使传了 reasoning_effort 也不应启用思维链。"""
    import app.routers.openai as oai
    monkeypatch.setattr(oai.settings, "extended_thinking_enabled", False)
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}
    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "high",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] is False


def test_thinking_failure_falls_back_to_normal_generate(gem_client, monkeypatch):
    """thinking 路径失败（RuntimeError/ValueError）应自动降级重试一次非思维链请求，而不是直接报错。"""
    import app.routers.openai as oai
    calls = []
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        calls.append(extended_thinking)
        if extended_thinking:
            raise RuntimeError("thinking path exploded")
        return {"text": "recovered", "images": [], "conversation_id": "c", "thoughts": ""}
    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "high",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert calls == [THINKING_LEVEL_HIGH, False]
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "recovered"
    assert body["choices"][0]["message"].get("reasoning_content") is None


def test_thinking_failure_then_normal_also_fails_returns_error(gem_client, monkeypatch):
    """thinking 重试后仍失败：应落回既有错误处理（此处无 conversation_id，直接走 400/500 错误分支）。"""
    import app.routers.openai as oai

    async def fake_fallback(*a, **k):
        return None
    monkeypatch.setattr(oai, "_fallback_result", fake_fallback)

    calls = []
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        calls.append(extended_thinking)
        raise ValueError("still broken")
    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "high",
    }, headers=_AUTH)
    assert calls == [THINKING_LEVEL_HIGH, False]
    assert r.status_code == 400
    assert "still broken" in r.json()["error"]["message"]


def test_streaming_emits_reasoning_content_before_done(gem_client, monkeypatch):
    """真流式路径：thoughts 只在 final 帧一次性拿到，应在收尾文本补发前，以 reasoning_content
    delta 的形式先发出，且要早于 [DONE]。"""
    import app.routers.openai as oai
    captured = {}

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        yield {"type": "delta", "text": "Hel"}
        yield {"type": "delta", "text": "lo"}
        yield {"type": "final", "text": "Hello", "conversation_id": "", "images": [], "thoughts": "let me think"}

    monkeypatch.setattr(oai.gemini_client, "generate_stream", fake_generate_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "high", "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert captured["ext"] == THINKING_LEVEL_HIGH
    assert "let me think" in body
    reasoning_idx = body.index("let me think")
    done_idx = body.index("[DONE]")
    assert reasoning_idx < done_idx


def test_streaming_no_reasoning_effort_no_reasoning_content(gem_client, monkeypatch):
    """未设置 reasoning_effort：上游按默认档（出厂 low）思考，但真流式路径每帧的
    reasoning_content 都应是 null —— 客户端没要求思考，增量与收尾帧里的思考都不许发出
    （StreamDelta 未设置字段本就序列化为 null，与既有 content/tool_calls 字段的约定一致）。
    上游的思考增量与 final 帧都带非空思考，才验得到这两处拦截。"""
    import json as _json
    import app.routers.openai as oai
    captured = {}

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        yield {"type": "thoughts", "text": "hidden "}
        yield {"type": "delta", "text": "Hi"}
        yield {"type": "final", "text": "Hi", "conversation_id": "", "images": [],
               "thoughts": "hidden thoughts"}

    monkeypatch.setattr(oai.gemini_client, "generate_stream", fake_generate_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert captured["ext"] == THINKING_LEVEL_LOW
    assert "hidden" not in body
    for line in body.splitlines():
        if not line.startswith("data: ") or line.strip() == "data: [DONE]":
            continue
        chunk = _json.loads(line[len("data: "):])
        for choice in chunk.get("choices", []):
            assert not choice.get("delta", {}).get("reasoning_content")

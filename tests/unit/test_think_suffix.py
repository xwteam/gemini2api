"""模型名后缀 @think=档位（v1.6.52）：只能填模型名的客户端也能选思考档位，后缀优先于请求体参数。"""
import pytest

from app.core import gemini_client as gc

_AUTH = {"Authorization": "Bearer sk-test-key"}


@pytest.mark.parametrize("model,base,requested", [
    ("gemini-pro@think=high", "gemini-pro", gc.THINKING_LEVEL_HIGH),
    ("gemini-pro@think=medium", "gemini-pro", gc.THINKING_LEVEL_MEDIUM),
    ("gemini-flash@think=LOW", "gemini-flash", gc.THINKING_LEVEL_LOW),
    ("gemini-pro@think=none", "gemini-pro", False),
    ("gemini-pro@think=xhigh", "gemini-pro", gc.THINKING_LEVEL_HIGH),
    ("gemini-pro@think=", "gemini-pro", None),
    ("gemini-pro", "gemini-pro", None),
])
def test_split_think_suffix(model, base, requested):
    assert gc.split_think_suffix(model) == (base, requested)


def _capture(monkeypatch, router_module):
    seen = {}

    async def generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       account_id=None, extended_thinking=False):
        seen.update(model=model, thinking=extended_thinking)
        return {"text": "ok", "images": [], "conversation_id": "", "thoughts": ""}

    monkeypatch.setattr(router_module.gemini_client, "generate", generate)
    return seen


def test_openai_chat_suffix_picks_the_level_and_beats_the_body(gem_client, monkeypatch):
    import app.routers.openai as oai

    seen = _capture(monkeypatch, oai)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro@think=high", "reasoning_effort": "none",
        "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert seen["thinking"] == gc.THINKING_LEVEL_HIGH
    assert "@think" not in seen["model"] and r.json()["model"] == "gemini-pro"


def test_openai_chat_suffix_none_turns_thinking_off(gem_client, monkeypatch):
    import app.routers.openai as oai

    seen = _capture(monkeypatch, oai)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro@think=none", "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert seen["thinking"] is False


def test_claude_suffix(gem_client, monkeypatch):
    import app.routers.claude as cl

    seen = _capture(monkeypatch, cl)
    r = gem_client.post("/v1/messages", json={
        "model": "gemini-pro@think=medium", "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert seen["thinking"] == gc.THINKING_LEVEL_MEDIUM and "@think" not in seen["model"]


def test_responses_suffix(gem_client, monkeypatch):
    import app.routers.responses as rs

    seen = _capture(monkeypatch, rs)
    r = gem_client.post("/v1/responses", json={"model": "gemini-pro@think=low", "input": "hi"}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert seen["thinking"] == gc.THINKING_LEVEL_LOW and "@think" not in seen["model"]

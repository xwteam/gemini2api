"""OpenAI 兼容路径按 entry.reasoning_effort 注入(monkeypatch SSRF,纯函数)。"""

import app.core.api_forwarder as fwd


class _Entry:
    def __init__(self, effort=None):
        self.id = "e"; self.provider = "openai"; self.model = "m"
        self.api_key = "sk"; self.base_url = "https://up.example/v1"
        self.reasoning_effort = effort


class _Req:
    stream = False; temperature = None; max_tokens = None; tools = None; tool_choice = None


def _no_ssrf(monkeypatch):
    monkeypatch.setattr(fwd, "_build_safe_target_url", lambda entry, suffix: entry.base_url.rstrip("/") + suffix)


def test_inject_when_set(monkeypatch):
    _no_ssrf(monkeypatch)
    _, _, payload = fwd._build_openai_request(_Entry("medium"), [{"role": "user", "content": "x"}], _Req())
    assert payload["reasoning_effort"] == "medium"


def test_inject_custom_value(monkeypatch):
    _no_ssrf(monkeypatch)
    _, _, payload = fwd._build_openai_request(_Entry("minimal"), [{"role": "user", "content": "x"}], _Req())
    assert payload["reasoning_effort"] == "minimal"


def test_no_inject_when_unset(monkeypatch):
    _no_ssrf(monkeypatch)
    _, _, payload = fwd._build_openai_request(_Entry(None), [{"role": "user", "content": "x"}], _Req())
    assert "reasoning_effort" not in payload

import json

# reasoning_effort 不再被布尔化：high → THINKING_LEVEL_HIGH 这个具体档位，
# 下游用它决定 payload 的第 80 格与 model header 的第 15 位（见 gemini_client.parse_effort_request）。
from app.core.gemini_client import THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW

_AUTH = {"Authorization": "Bearer sk-test-key"}


def test_responses_reasoning_effort_enables_thinking(gem_client, monkeypatch):
    import app.routers.responses as rp
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": "resp thoughts"}
    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi", "reasoning": {"effort": "high"},
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] == THINKING_LEVEL_HIGH
    types = [it.get("type") for it in r.json()["output"]]
    assert "reasoning" in types


def test_responses_no_reasoning_uses_default_level_without_reasoning_item(gem_client, monkeypatch):
    """不传 reasoning：上游按"默认思考档位"（出厂 low）思考，但**不出 reasoning 输出项**
    （客户端没要求）。上游返回了非空思考，才验得到这道拦截。"""
    import app.routers.responses as rp
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": "hidden thoughts"}
    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] == THINKING_LEVEL_LOW
    types = [it.get("type") for it in r.json()["output"]]
    assert "reasoning" not in types
    assert "hidden thoughts" not in r.text


def test_responses_top_level_reasoning_effort_enables_thinking(gem_client, monkeypatch):
    """顶层 reasoning_effort（无嵌套 reasoning.effort 时）也应启用思维链。"""
    import app.routers.responses as rp
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}
    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi", "reasoning_effort": "high",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] == THINKING_LEVEL_HIGH


def test_responses_extended_thinking_disabled_by_settings_toggle(gem_client, monkeypatch):
    import app.routers.responses as rp
    monkeypatch.setattr(rp.settings, "extended_thinking_enabled", False)
    captured = {}
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}
    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi", "reasoning": {"effort": "high"},
    }, headers=_AUTH)
    assert r.status_code == 200
    assert captured["ext"] is False


def test_responses_thinking_failure_falls_back_to_normal(gem_client, monkeypatch):
    """thinking 路径失败应自动降级重试一次非思维链请求。"""
    import app.routers.responses as rp
    calls = []
    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        calls.append(extended_thinking)
        if extended_thinking:
            raise RuntimeError("thinking path exploded")
        return {"text": "recovered", "images": [], "conversation_id": "c", "thoughts": ""}
    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi", "reasoning": {"effort": "high"},
    }, headers=_AUTH)
    assert r.status_code == 200
    assert calls == [THINKING_LEVEL_HIGH, False]
    body = r.json()
    types = [it.get("type") for it in body["output"]]
    assert "reasoning" not in types
    assert any(it.get("type") == "message" for it in body["output"])


def test_responses_stream_emits_reasoning_item_in_completed_output(gem_client, monkeypatch):
    """真流式路径：final 事件带 thoughts 时，response.completed 的 output 里要含 reasoning item。"""
    import app.routers.responses as rp

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        assert extended_thinking == THINKING_LEVEL_HIGH
        yield {"type": "delta", "text": "Hel"}
        yield {"type": "delta", "text": "lo"}
        yield {"type": "final", "text": "Hello", "conversation_id": "", "images": [],
              "thoughts": "stream thoughts"}

    monkeypatch.setattr(rp.gemini_client, "generate_stream", fake_generate_stream)
    with gem_client.stream("POST", "/v1/responses", json={
        "model": "gemini-pro", "input": "hi", "stream": True, "reasoning": {"effort": "high"},
    }, headers=_AUTH) as r:
        events = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    completed = [e for e in events if e.get("type") == "response.completed"]
    assert completed, "no response.completed event found"
    output = completed[0]["response"]["output"]
    types = [it.get("type") for it in output]
    assert "reasoning" in types
    reasoning_item = next(it for it in output if it["type"] == "reasoning")
    assert reasoning_item["summary"][0]["text"] == "stream thoughts"
    assert any(it.get("type") == "message" for it in output)


def test_responses_non_string_effort_enables_thinking_without_500(gem_client, monkeypatch):
    """reasoning.effort 是非字符串（如 int）时不能 500，且非空真值仍应启用思维链。"""
    import app.routers.responses as rp
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}

    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi", "reasoning": {"effort": 5},
    }, headers=_AUTH)
    assert r.status_code == 200
    # 认不出的档位值跟随默认思考档位（出厂 low；绝不 500、也不关掉思维链）
    assert captured["ext"] == THINKING_LEVEL_LOW

"""v1.6.43 思考档位：low / medium / high 三档，客户端没指定时用"默认思考档位"（出厂 low）。

钉四件事：
  1. 设置本身：出厂 low、off 回到不思考旧路径（发给上游的请求与改动前不传参时逐字节一致）、
     面板改了即时生效、非法值被拒；
  2. 四个协议的参数 → 档位映射，不传 → 默认档；
  3. **协议合规红线**：客户端没要求思考、是我们按默认档替它开的，思考只给上游用，绝不回传。
     判据是"默认档 low 的响应 == 默认档 off 的响应"（逐字段，只把随机 id / 时间戳归一），
     上游的假回答**带非空思考**，才验得到那道拦截；流式与非流式都测；
  4. 客户端明确要了思考 → 照常回传。
"""

import json
import re
from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.core import gemini_client as gc
from app.core.gemini_client import (
    THINKING_LEVEL_DEFAULT, THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW, THINKING_LEVEL_MEDIUM,
    default_thinking_level, parse_effort_request, parse_gemini_thinking_config,
    resolve_thinking,
)
from app.core import settings_overrides as so

_AUTH = {"Authorization": "Bearer sk-test-key"}
THOUGHTS = "SECRET-CHAIN-OF-THOUGHT"
_TOOLS_OAI = [{"type": "function", "function": {
    "name": "get_weather", "description": "w",
    "parameters": {"type": "object", "properties": {}}}}]
_TOOL_TEXT = '{"tool_calls":[{"name":"get_weather","arguments":{}}]}'


# ---------------------------------------------------------------------------
# 0. 假上游：记录收到的档位，回答里永远带非空思考
# ---------------------------------------------------------------------------

def _install(monkeypatch, *modules, text="答案", thoughts=THOUGHTS):
    captured = []

    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                  account_id=None, extended_thinking=False):
        captured.append(extended_thinking)
        return {"text": text, "images": [], "conversation_id": "", "thoughts": thoughts}

    async def stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                     account_id=None, extended_thinking=False):
        captured.append(extended_thinking)
        yield {"type": "thoughts", "text": thoughts[:6]}
        yield {"type": "delta", "text": text}
        yield {"type": "final", "text": text, "conversation_id": "", "images": [],
               "thoughts": thoughts}

    for mod in modules:
        monkeypatch.setattr(mod.gemini_client, "generate", gen)
        monkeypatch.setattr(mod.gemini_client, "generate_stream", stream)
    return captured


_ID_RE = re.compile(r"\b(chatcmpl|msg|resp|rs|fc|call|toolu)[-_][A-Za-z0-9]+")
_TS_RE = re.compile(r'"(created|created_at)":\s*\d+')


def _norm(text: str) -> str:
    return _TS_RE.sub(r'"\1": 0', _ID_RE.sub(r"\1_X", text))


def _post(client, path, body, stream=False):
    if stream:
        with client.stream("POST", path, json=body, headers=_AUTH) as r:
            assert r.status_code == 200
            return "".join(r.iter_text())
    r = client.post(path, json=body, headers=_AUTH)
    assert r.status_code == 200, r.text
    return r.text


# 每个协议 × 流式/非流式 × 有无工具，都是"客户端没提思考"的请求
_CHAT = {"model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}]}
_CLAUDE = {"model": "gemini-flash", "max_tokens": 64,
           "messages": [{"role": "user", "content": "hi"}]}
_RESP = {"model": "gemini-flash", "input": "hi"}
_NATIVE = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
_NATIVE_TOOLS = [{"functionDeclarations": [{"name": "get_weather", "description": "w",
                                            "parameters": {"type": "object"}}]}]

CASES = {
    "openai": ("/v1/chat/completions", _CHAT, False),
    "openai-stream": ("/v1/chat/completions", {**_CHAT, "stream": True}, True),
    "openai-stream-tools": ("/v1/chat/completions",
                            {**_CHAT, "stream": True, "tools": _TOOLS_OAI}, True),
    "responses": ("/v1/responses", _RESP, False),
    "responses-stream": ("/v1/responses", {**_RESP, "stream": True}, True),
    "responses-stream-tools": ("/v1/responses", {**_RESP, "stream": True, "tools": [
        {"type": "function", "name": "get_weather", "parameters": {"type": "object"}}]}, True),
    "anthropic": ("/v1/messages", _CLAUDE, False),
    "anthropic-stream": ("/v1/messages", {**_CLAUDE, "stream": True}, True),
    "anthropic-stream-tools": ("/v1/messages", {**_CLAUDE, "stream": True, "tools": [
        {"name": "get_weather", "description": "w",
         "input_schema": {"type": "object"}}]}, True),
    "gemini": ("/v1beta/models/gemini-flash:generateContent", _NATIVE, False),
    "gemini-stream": ("/v1beta/models/gemini-flash:streamGenerateContent", _NATIVE, True),
    "gemini-stream-tools": ("/v1beta/models/gemini-flash:streamGenerateContent",
                            {**_NATIVE, "tools": _NATIVE_TOOLS}, True),
}


def _routers():
    import app.routers.claude as cl
    import app.routers.gemini as ge
    import app.routers.openai as oai
    import app.routers.responses as rp
    return oai, rp, cl, ge


# ---------------------------------------------------------------------------
# 1. 合规红线：没要求思考 → 响应与"不思考"逐字段一致，思考一个字都不出去
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_unrequested_thinking_never_reaches_the_client(gem_client, monkeypatch, case):
    path, body, stream = CASES[case]
    captured = _install(monkeypatch, *_routers())

    monkeypatch.setattr(settings, "default_thinking_level", "low")
    with_low = _post(gem_client, path, body, stream)
    monkeypatch.setattr(settings, "default_thinking_level", "off")
    with_off = _post(gem_client, path, body, stream)

    # 上游确实一次按 low 思考、一次走不思考旧路径
    assert captured == [THINKING_LEVEL_LOW, False], captured
    # 思考没出去：没有思考文本、没有任何思考字段/块
    assert THOUGHTS[:6] not in with_low
    for marker in ('"reasoning_content": "', '"type": "thinking"', '"type":"thinking"',
                   '"thinking_delta"', '"type": "reasoning"', '"thought": true'):
        assert marker not in with_low, marker
    # 逐字段一致：只多想了一下，响应结构与不思考时完全一样
    assert _norm(with_low) == _norm(with_off)


def test_explicit_requests_still_get_their_thinking_back(gem_client, monkeypatch):
    """客户端明确要了 → 照常回传（与 v1.6.42 一致），四个协议各一条。"""
    _install(monkeypatch, *_routers())

    chat = _post(gem_client, "/v1/chat/completions", {**_CHAT, "reasoning_effort": "low"})
    assert json.loads(chat)["choices"][0]["message"]["reasoning_content"] == THOUGHTS

    resp = json.loads(_post(gem_client, "/v1/responses", {**_RESP, "reasoning": {"effort": "low"}}))
    assert resp["output"][0]["type"] == "reasoning"

    msg = json.loads(_post(gem_client, "/v1/messages", {
        **_CLAUDE, "thinking": {"type": "enabled", "budget_tokens": 1024}}))
    assert msg["content"][0] == {"type": "thinking", "thinking": THOUGHTS}

    native = json.loads(_post(gem_client, "/v1beta/models/gemini-flash:generateContent", {
        **_NATIVE, "generationConfig": {"thinkingConfig": {"includeThoughts": True}}}))
    parts = native["candidates"][0]["content"]["parts"]
    assert parts[0] == {"text": THOUGHTS, "thought": True}
    assert parts[1] == {"text": "答案"}


def test_gemini_stream_returns_thought_parts_only_when_included(gem_client, monkeypatch):
    _install(monkeypatch, *_routers())
    path = "/v1beta/models/gemini-flash:streamGenerateContent"

    shown = _post(gem_client, path, {**_NATIVE, "generationConfig": {
        "thinkingConfig": {"thinkingLevel": "HIGH", "includeThoughts": True}}}, stream=True)
    hidden = _post(gem_client, path, {**_NATIVE, "generationConfig": {
        "thinkingConfig": {"thinkingLevel": "HIGH"}}}, stream=True)

    thought_text = "".join(
        p["text"]
        for line in shown.splitlines() if line.strip()
        for p in json.loads(line)["candidates"][0]["content"]["parts"] if p.get("thought"))
    assert thought_text == THOUGHTS, "增量 + 收尾差量拼起来必须恰好是完整思考、不重复"
    assert '"thought": true' not in hidden and THOUGHTS[:6] not in hidden


def test_anthropic_explicit_thinking_still_streams_a_thinking_block(gem_client, monkeypatch):
    _install(monkeypatch, *_routers())
    body = _post(gem_client, "/v1/messages", {
        **_CLAUDE, "stream": True, "thinking": {"type": "enabled", "budget_tokens": 4096}},
        stream=True)
    assert '"thinking_delta"' in body


# ---------------------------------------------------------------------------
# 2. 参数 → 档位；不传 → 默认档
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("effort,expected", [
    (None, THINKING_LEVEL_LOW), ("", THINKING_LEVEL_LOW), ("  ", THINKING_LEVEL_LOW),
    ("low", 1), ("medium", 4), ("high", 2), ("HIGH", 2),
    ("none", 1), ("minimal", 1), ("xhigh", 2),
    ("bogus", THINKING_LEVEL_DEFAULT),
])
def test_openai_effort_maps_to_a_level(gem_client, monkeypatch, effort, expected):
    import app.routers.openai as oai
    captured = _install(monkeypatch, oai)
    body = dict(_CHAT)
    if effort is not None:
        body["reasoning_effort"] = effort
    _post(gem_client, "/v1/chat/completions", body)
    assert captured == [expected]


@pytest.mark.parametrize("reasoning,expected", [
    (None, THINKING_LEVEL_LOW),
    ({"effort": "low"}, 1), ({"effort": "medium"}, 4), ({"effort": "high"}, 2),
    ({"effort": "minimal"}, 1), ({"effort": "xhigh"}, 2),
    ({"effort": 7}, THINKING_LEVEL_DEFAULT),       # 非字符串也不 500
    ({}, THINKING_LEVEL_LOW),
])
def test_responses_effort_maps_to_a_level(gem_client, monkeypatch, reasoning, expected):
    import app.routers.responses as rp
    captured = _install(monkeypatch, rp)
    body = dict(_RESP)
    if reasoning is not None:
        body["reasoning"] = reasoning
    _post(gem_client, "/v1/responses", body)
    assert captured == [expected]


@pytest.mark.parametrize("thinking,expected", [
    (None, THINKING_LEVEL_LOW),
    ({"type": "enabled", "budget_tokens": 1024}, 1),
    ({"type": "enabled", "budget_tokens": 2048}, 4),
    ({"type": "enabled", "budget_tokens": 8192}, 2),
    ({"type": "adaptive"}, THINKING_LEVEL_DEFAULT),
    ({"type": "disabled"}, False),
    ({"type": "something-new"}, THINKING_LEVEL_LOW),   # 认不出 = 没传
])
def test_anthropic_thinking_maps_to_a_level(gem_client, monkeypatch, thinking, expected):
    import app.routers.claude as cl
    captured = _install(monkeypatch, cl)
    body = dict(_CLAUDE)
    if thinking is not None:
        body["thinking"] = thinking
    _post(gem_client, "/v1/messages", body)
    assert captured == [expected]
    if expected is False:
        assert captured[0] is False


@pytest.mark.parametrize("config,expected", [
    (None, THINKING_LEVEL_LOW),
    ({}, THINKING_LEVEL_LOW),
    ("nonsense", THINKING_LEVEL_LOW),                       # 非对象：宽容，视同没传
    ({"thinkingLevel": "low"}, 1),
    ({"thinkingLevel": "MEDIUM"}, 4),
    ({"thinkingLevel": "HIGH"}, 2),
    ({"thinkingLevel": "MINIMAL"}, 1),
    ({"thinkingLevel": "THINKING_LEVEL_UNSPECIFIED"}, THINKING_LEVEL_DEFAULT),
    ({"thinkingBudget": 0}, False),
    ({"thinkingBudget": -1}, THINKING_LEVEL_DEFAULT),
    ({"thinkingBudget": 1024}, 1),
    ({"thinkingBudget": 2048}, 4),
    ({"thinkingBudget": 24576}, 2),
    ({"thinking_budget": 4096}, 2),                         # snake_case 也认
    ({"thinkingLevel": "low", "thinkingBudget": 24576}, 1),  # 两个都给：level 优先
    ({"includeThoughts": True}, THINKING_LEVEL_DEFAULT),
])
@pytest.mark.parametrize("method", ["generateContent", "streamGenerateContent"])
def test_gemini_thinking_config_maps_to_a_level(gem_client, monkeypatch, config, expected,
                                                method):
    import app.routers.gemini as ge
    captured = _install(monkeypatch, ge)
    body = dict(_NATIVE)
    if config is not None:
        body["generationConfig"] = {"thinkingConfig": config}
    _post(gem_client, f"/v1beta/models/gemini-flash:{method}", body,
          stream=method.startswith("stream"))
    assert captured == [expected]
    if expected is False:
        assert captured[0] is False


@pytest.mark.parametrize("config,show", [
    ({"includeThoughts": True}, True),
    ({"includeThoughts": False, "thinkingLevel": "high"}, False),
    ({"thinkingLevel": "high"}, False),
    ({"thinkingBudget": 0, "includeThoughts": True}, False),
    (None, False),
])
def test_gemini_include_thoughts_decides_whether_thoughts_are_returned(config, show):
    requested, show_flag = parse_gemini_thinking_config(config)
    assert resolve_thinking(requested, show=show_flag).show is show


# ---------------------------------------------------------------------------
# 3. 设置项
# ---------------------------------------------------------------------------

def test_factory_default_is_low():
    assert Settings.model_fields["default_thinking_level"].default == "low"
    assert settings.default_thinking_level == "low"
    assert default_thinking_level() == THINKING_LEVEL_LOW


@pytest.mark.parametrize("raw,expected", [
    ("off", "off"), ("low", "low"), ("medium", "medium"), ("high", "high"),
    (" HIGH ", "high"), ("Medium", "medium"),
    ("xhigh", "low"), ("", "low"), ("garbage", "low"),   # 写错不许把服务搞起不来
])
def test_env_value_is_normalised_and_never_bricks_startup(raw, expected):
    assert Settings(default_thinking_level=raw).default_thinking_level == expected


@pytest.mark.parametrize("value,level", [
    ("off", None), ("low", 1), ("medium", 4), ("high", 2)])
def test_each_setting_value_maps_to_a_level(monkeypatch, value, level):
    monkeypatch.setattr(settings, "default_thinking_level", value)
    assert default_thinking_level() == level
    plan = resolve_thinking(None)
    assert plan.upstream == (level or False) and plan.show is False


def test_the_allowed_values_agree_between_the_setting_and_the_resolver():
    assert so.THINKING_DEFAULT_LEVELS == set(gc._DEFAULT_THINKING_CHOICES)
    assert "default_thinking_level" in so.EDITABLE_FIELDS
    assert so.FIELD_TYPES["default_thinking_level"] is str


def test_the_master_switch_still_wins_over_everything(monkeypatch):
    monkeypatch.setattr(settings, "extended_thinking_enabled", False)
    monkeypatch.setattr(settings, "default_thinking_level", "high")
    assert resolve_thinking(None) == gc.THINKING_OFF
    assert resolve_thinking(THINKING_LEVEL_HIGH) == gc.THINKING_OFF
    assert parse_effort_request("high") == THINKING_LEVEL_HIGH   # 解析照旧，决策时被总闸拦下


@pytest.fixture
def isolated_persistence(monkeypatch, tmp_path):
    import app.routers.settings as sr
    monkeypatch.setattr(so, "OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(sr, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(settings, "default_thinking_level", settings.default_thinking_level)
    return tmp_path


def test_panel_switch_takes_effect_on_the_next_request(gem_client, monkeypatch,
                                                       isolated_persistence):
    """面板改了即时生效、无需重启：同一个进程里下一个请求就用新档位。"""
    import app.routers.openai as oai
    captured = _install(monkeypatch, oai)

    for value, level in (("high", THINKING_LEVEL_HIGH), ("medium", THINKING_LEVEL_MEDIUM),
                         ("off", False)):
        r = gem_client.post("/admin/settings", json={"settings": {"default_thinking_level": value}},
                            headers=_AUTH)
        assert r.status_code == 200, r.text
        assert r.json()["thinking"]["default_thinking_level"] == value
        _post(gem_client, "/v1/chat/completions", _CHAT)
        assert captured[-1] == level
    assert captured[-1] is False
    persisted = json.loads((isolated_persistence / "overrides.json").read_text())
    assert persisted["default_thinking_level"] == "off"
    assert "DEFAULT_THINKING_LEVEL=off" in (isolated_persistence / ".env").read_text()


@pytest.mark.parametrize("bad", ["garbage", "LOW", "xhigh", "", 1, True, None])
def test_panel_rejects_invalid_values_without_persisting(gem_client, isolated_persistence, bad):
    before = settings.default_thinking_level
    r = gem_client.post("/admin/settings", json={"settings": {"default_thinking_level": bad}},
                        headers=_AUTH)
    assert r.status_code == 400, r.text
    assert settings.default_thinking_level == before
    assert not (isolated_persistence / "overrides.json").exists()


def test_a_hand_broken_overrides_file_is_ignored_on_replay(tmp_path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"default_thinking_level": "xhigh"}))
    target = SimpleNamespace(default_thinking_level="low")
    assert so.apply_overrides(target, path) == {}
    assert target.default_thinking_level == "low"
    path.write_text(json.dumps({"default_thinking_level": "medium"}))
    assert so.apply_overrides(target, path) == {"default_thinking_level": "medium"}


def test_settings_page_shows_one_thinking_control_unless_the_master_switch_is_off(
        gem_client, monkeypatch):
    """平时只露"默认思考档位"一个控件；总闸被关掉时才露出来（否则关过它的人改不回来，
    而默认档位怎么切都不生效）。"""
    group = gem_client.get("/admin/settings", headers=_AUTH).json()["thinking"]
    assert group == {"default_thinking_level": "low"}
    monkeypatch.setattr(settings, "extended_thinking_enabled", False)
    group = gem_client.get("/admin/settings", headers=_AUTH).json()["thinking"]
    assert group == {"default_thinking_level": "low", "extended_thinking_enabled": False}
    chat_cleanup = gem_client.get("/admin/settings", headers=_AUTH).json()["chat_cleanup"]
    assert "extended_thinking_enabled" not in chat_cleanup


# ---------------------------------------------------------------------------
# 4. off = 不思考旧路径：真正发给 Google 的请求与改动前不传参时逐字节一致
# ---------------------------------------------------------------------------

def _wire_client(monkeypatch):
    """一个真 GeminiWebClient，只把网络与会话维护换成假的，记录真正要发出去的 POST。"""
    sent = []

    class _Resp:
        status_code = 200
        text = ""

    class _Http:
        async def post(self, url, data=None, cookies=None, headers=None, timeout=None):
            sent.append({"data": dict(data), "headers": dict(headers)})
            return _Resp()

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(gc, "apply_jitter", _noop)
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    c._family_model, c._discovered_models, c._available_models = {}, {}, []
    c._session_token, c._session_uuid = "AT", "S"
    c._http = _Http()
    c._cookie_jar = SimpleNamespace(update_from_response=lambda r: None)
    c._ensure_session_current = _noop
    c._clear_session_cookies = lambda: None
    c._get_cookies = lambda: {}
    c._get_headers = lambda *a, **k: {"x-base": "1"}
    c._parse_output = lambda text: {"text": "ok", "images": [], "thoughts": ""}
    return c, sent


def test_default_off_sends_exactly_what_v1_6_42_sent_without_parameters(monkeypatch):
    import asyncio
    c, sent = _wire_client(monkeypatch)

    # v1.6.42：不传思考参数的请求在路由层恒为 extended_thinking=False
    asyncio.run(c._send_request("hi", "gemini-flash", extended_thinking=False))
    # 现在：默认档 off + 不传参数，经同一套决策得到的上游参数
    monkeypatch.setattr(settings, "default_thinking_level", "off")
    plan = resolve_thinking(parse_effort_request(None))
    assert plan.upstream is False
    asyncio.run(c._send_request("hi", "gemini-flash", extended_thinking=plan.upstream))

    assert sent[0] == sent[1]
    assert "x-goog-ext-525005358-jspb" not in sent[1]["headers"]


def test_default_low_really_switches_the_wire_request_to_thinking(monkeypatch):
    import asyncio
    c, sent = _wire_client(monkeypatch)
    monkeypatch.setattr(settings, "default_thinking_level", "low")
    plan = resolve_thinking(parse_effort_request(None))
    asyncio.run(c._send_request("hi", "gemini-flash", extended_thinking=plan.upstream))

    hdrs = sent[0]["headers"]
    assert "x-goog-ext-525005358-jspb" in hdrs
    assert json.loads(hdrs[gc.MODEL_HEADER_KEY])[15] == THINKING_LEVEL_LOW
    inner = json.loads(json.loads(sent[0]["data"]["f.req"])[1])
    assert inner[80] == THINKING_LEVEL_LOW


# ---------------------------------------------------------------------------
# 5. 默认档开着时，思考路径失败要退回不思考重试（否则默认 low 多出一类硬失败）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["openai-stream-tools", "gemini", "gemini-stream-tools",
                                  "anthropic-stream-tools"])
def test_default_level_failures_fall_back_to_no_thinking(gem_client, monkeypatch, case):
    path, body, stream = CASES[case]
    calls = []

    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                  account_id=None, extended_thinking=False):
        calls.append(extended_thinking)
        if extended_thinking:
            raise RuntimeError("thinking path exploded")
        return {"text": "退回后的答案", "images": [], "conversation_id": "", "thoughts": ""}

    for mod in _routers():
        monkeypatch.setattr(mod.gemini_client, "generate", gen)
    out = _post(gem_client, path, body, stream)
    assert calls[:2] == [THINKING_LEVEL_LOW, False]
    assert "退回后的答案" in out or "\\u9000" in out
    assert "exploded" not in out


# ---------------------------------------------------------------------------
# 6. Anthropic 真流式的两处细节：开块时机、迟到思考的告警
# ---------------------------------------------------------------------------

def test_anthropic_realstream_error_frames_match_the_no_thinking_path(gem_client, monkeypatch):
    """开块时机只能看"回不回传"，不能看发给上游的档位：否则默认档开着时文本块改成惰性开，
    上游在第一个字之前就失败的那条流会少一个 content_block_stop，帧序列与不思考时不一致。"""
    import app.routers.claude as cl

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        raise RuntimeError("upstream died before the first token")
        yield  # pragma: no cover

    monkeypatch.setattr(cl.gemini_client, "generate_stream", boom)
    body = {**_CLAUDE, "stream": True}
    monkeypatch.setattr(settings, "default_thinking_level", "low")
    with_low = _post(gem_client, "/v1/messages", body, stream=True)
    monkeypatch.setattr(settings, "default_thinking_level", "off")
    with_off = _post(gem_client, "/v1/messages", body, stream=True)

    assert '"content_block_stop"' in with_off
    assert _norm(with_low) == _norm(with_off)


def test_unrequested_thinking_does_not_raise_the_late_thinking_warning(gem_client, monkeypatch,
                                                                       caplog):
    """默认档替客户端开的思考本来就不回传，不该被当成"正文开块后迟到、被迫丢弃"的思考
    去打 WARNING —— 那条告警是给"客户端要了思考却少了一截"准备的，误报会把排查带偏。"""
    import logging
    _install(monkeypatch, *_routers())
    caplog.set_level(logging.WARNING)
    _post(gem_client, "/v1/messages", {**_CLAUDE, "stream": True}, stream=True)
    assert not [r for r in caplog.records if "late thinking" in r.getMessage()
                or "thinking chain is short" in r.getMessage()]

"""熔断期间 /v1/chat/completions 带兜底的请求直接走兜底（v1.6.46 规格 C.6，按 I.5 / I.8 / I.10 / I.11）。

  - 绕开条件 = fallback_enabled() 且 get_fallback_entries(...) 非空 且 该族 should_bypass 为真；
  - 非流式在调谷歌之前用 _fallback()；真流式与 buffered（带工具）两条流式路径在各自的 SSE 生成器里
    判断（role 首帧之后、调谷歌之前），兜底包成 task 放在 _sse_keepalive_during 下跑（保活）；
  - 兜底答了才打 [breaker] INFO 日志；兜底没答出来 → 照常调谷歌，且之后谷歌失败 / 回空的分支不再
    重复兜底；
  - 探测请求的探测位在谷歌调用一结束、兜底开始之前就释放；
  - 没开兜底、或其它协议（Claude / Gemini 原生 / Responses）照常调谷歌。
"""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.core import gemini_client as gc
from app.core.model_breaker import model_breaker

_AUTH = {"Authorization": "Bearer sk-test-key"}
PHRASE = "I seem to be encountering an error. Can I try something else for you?"

_FB_DATA = {"id": "chatcmpl-fb", "object": "chat.completion", "created": 0, "model": "tp-model",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "answered by fallback"}}]}

_TOOLS = [{"type": "function", "function": {
    "name": "get_weather", "description": "w",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
}}]


class _KeyPool:
    def __init__(self, entries):
        self.entries = {e.id: e for e in entries}

    def get_entries_for_model(self, model):
        return [e for e in self.entries.values() if e.model == model]

    def update_last_used(self, entry_id):
        return True


class _World:
    def __init__(self):
        self.generate = []
        self.stream = []
        self.fallback = []
        self.gemini_answer = {"text": "answered by gemini", "images": [], "conversation_id": ""}
        self.gemini_error = None
        self.fallback_result = _FB_DATA
        self.fallback_delay = 0.0
        self.during_fallback = []


@pytest.fixture
def world(gem_client, monkeypatch):
    import app.routers.openai as oai
    from app.config import settings

    w = _World()
    w.http = gem_client
    monkeypatch.setattr(settings, "fallback_enabled", True)
    monkeypatch.setattr(gem_client.app.state, "api_key_pool",
                        _KeyPool([SimpleNamespace(id="k1", model="tp-model", status="active")]),
                        raising=False)

    async def generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       account_id=None, extended_thinking=False):
        w.generate.append({"model": model, "thinking": extended_thinking})
        if w.gemini_error is not None:
            raise w.gemini_error
        return dict(w.gemini_answer)

    async def generate_stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                              account_id=None, extended_thinking=False):
        w.stream.append({"model": model})
        if w.gemini_error is not None:
            raise w.gemini_error
        yield {"type": "delta", "text": w.gemini_answer["text"]}
        yield {"type": "final", **w.gemini_answer}

    async def fallback(request, req, messages_raw, exclude_model=""):
        w.fallback.append(exclude_model)
        w.during_fallback.append(model_breaker.snapshot())
        if w.fallback_delay:
            await asyncio.sleep(w.fallback_delay)
        return w.fallback_result

    monkeypatch.setattr(oai.gemini_client, "generate", generate)
    monkeypatch.setattr(oai.gemini_client, "generate_stream", generate_stream)
    monkeypatch.setattr(oai, "_fallback_result", fallback)
    return w


def _open(family="flash"):
    model_breaker.record_failure(family, started_at=model_breaker.now(), fingerprint="a", reason="x")
    model_breaker.record_failure(family, started_at=model_breaker.now(), fingerprint="b", reason="x")
    assert model_breaker.snapshot()[family]["state"] == "open"


def _half_open(monkeypatch, family="flash"):
    _open(family)
    st = model_breaker._families[family]
    st.open_until = model_breaker.now() - 0.001        # 开放期已到，下一次调用惰性转 half_open


def _chat(w, *, stream=False, tools=None, model="gemini-flash"):
    body = {"model": model, "stream": stream, "messages": [{"role": "user", "content": "hi"}]}
    if tools:
        body["tools"] = tools
    if stream:
        with w.http.stream("POST", "/v1/chat/completions", json=body, headers=_AUTH) as r:
            return r.status_code, "".join(r.iter_text())
    r = w.http.post("/v1/chat/completions", json=body, headers=_AUTH)
    return r.status_code, r.json()


def _content(sse_body: str) -> str:
    out = []
    for block in sse_body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                data = json.loads(line[5:].strip())
                for ch in data.get("choices") or []:
                    out.append((ch.get("delta") or {}).get("content") or "")
    return "".join(out)


def _errors(sse_body: str):
    out = []
    for block in sse_body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                data = json.loads(line[5:].strip())
                if "error" in data:
                    out.append(data["error"])
    return out


# ---------------------------------------------------------------------------
# 三条 Gemini 路径：open + 有兜底 → 不调谷歌
# ---------------------------------------------------------------------------

def test_nonstream_goes_straight_to_the_fallback_while_open(world, caplog):
    _open()
    with caplog.at_level(logging.INFO, logger="app.routers.openai"):
        status, body = _chat(world)
    assert status == 200, body
    assert body["choices"][0]["message"]["content"] == "answered by fallback"
    assert world.generate == [], "熔断打开、有兜底时不能再先白等谷歌"
    assert world.fallback == ["gemini-flash"]
    assert any("[breaker]" in r.getMessage() and "gemini-flash" in r.getMessage()
               and "直接走兜底" in r.getMessage() for r in caplog.records)


def test_real_stream_goes_straight_to_the_fallback_while_open(world):
    _open()
    status, body = _chat(world, stream=True)
    assert status == 200
    assert _content(body) == "answered by fallback"
    assert world.stream == [] and world.generate == []
    assert body.count('"role": "assistant"') == 1, "role 首帧只发一次（判断在首帧之后）"


def test_buffered_tool_stream_goes_straight_to_the_fallback_while_open(world):
    _open()
    status, body = _chat(world, stream=True, tools=_TOOLS)
    assert status == 200
    assert _content(body) == "answered by fallback"
    assert world.generate == [] and world.stream == []


def test_the_family_is_resolved_from_the_model_actually_sent_to_gemini(world):
    _open()
    status, body = _chat(world, model="gemini-2.5-flash")            # 别名 → flash
    assert status == 200 and world.generate == []
    status, body = _chat(world, model="gemini-flash-lite")           # 别的族不受牵连
    assert status == 200 and len(world.generate) == 1
    assert body["choices"][0]["message"]["content"] == "answered by gemini"


def test_the_bypass_keeps_the_stream_alive_while_the_fallback_runs(world, monkeypatch):
    """I.11：绕开期间流式主路径是「role 首帧 → 静默到第三方答完」，要保活。"""
    import app.core.stream as stream_mod

    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.02)
    world.fallback_delay = 0.2
    _open()
    status, body = _chat(world, stream=True)
    assert ": ping" in body
    assert _content(body) == "answered by fallback"


# ---------------------------------------------------------------------------
# 兜底没答出来：照常调谷歌，且不重复兜底（I.10）
# ---------------------------------------------------------------------------

def test_nonstream_falls_through_to_gemini_when_the_fallback_cannot_answer(world):
    _open()
    world.fallback_result = None
    status, body = _chat(world)
    assert status == 200
    assert body["choices"][0]["message"]["content"] == "answered by gemini"
    assert len(world.fallback) == 1 and len(world.generate) == 1


def test_nonstream_does_not_retry_the_fallback_after_gemini_fails_too(world):
    _open()
    world.fallback_result = None
    world.gemini_error = gc.GeminiFailureReply(PHRASE)
    status, body = _chat(world)
    assert status == 502, body
    assert body["error"]["type"] == "api_error"
    assert len(world.fallback) == 1, "绕开阶段已经遍历过一轮兜底，谷歌失败的分支不再重复兜底"


def test_nonstream_does_not_retry_the_fallback_after_an_empty_gemini_answer(world):
    _open()
    world.fallback_result = None
    world.gemini_answer = {"text": "", "images": [], "conversation_id": ""}
    status, body = _chat(world)
    assert status == 200
    assert len(world.fallback) == 1


def test_real_stream_falls_through_once(world):
    _open()
    world.fallback_result = None
    world.gemini_error = gc.GeminiFailureReply(PHRASE)
    status, body = _chat(world, stream=True)
    assert [e["type"] for e in _errors(body)] == ["api_error"]
    assert len(world.stream) == 1
    assert len(world.fallback) == 1


def test_buffered_stream_falls_through_once(world):
    _open()
    world.fallback_result = None
    world.gemini_error = gc.GeminiFailureReply(PHRASE)
    status, body = _chat(world, stream=True, tools=_TOOLS)
    assert [e["type"] for e in _errors(body)] == ["api_error"]
    assert len(world.fallback) == 1


# ---------------------------------------------------------------------------
# 不绕开的情况
# ---------------------------------------------------------------------------

def test_without_fallback_enabled_gemini_is_always_called(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fallback_enabled", False)
    _open()
    status, body = _chat(world)
    assert status == 200 and len(world.generate) == 1
    status, body = _chat(world, stream=True)
    assert len(world.stream) == 1
    assert world.fallback == []


def test_without_fallback_candidates_gemini_is_always_called(world, monkeypatch):
    monkeypatch.setattr(world.http.app.state, "api_key_pool", _KeyPool([]), raising=False)
    _open()
    status, body = _chat(world)
    assert status == 200 and len(world.generate) == 1


def test_closed_breaker_changes_nothing(world):
    status, body = _chat(world)
    assert status == 200 and len(world.generate) == 1 and world.fallback == []


def test_a_disabled_breaker_never_bypasses(world, monkeypatch):
    from app.config import settings

    _open()
    monkeypatch.setattr(settings, "model_breaker_enabled", False)
    status, body = _chat(world)
    assert status == 200 and len(world.generate) == 1 and world.fallback == []


@pytest.mark.parametrize("path,body", [
    ("/v1/messages", {"model": "gemini-flash", "max_tokens": 32,
                      "messages": [{"role": "user", "content": "hi"}]}),
    ("/v1beta/models/gemini-flash:generateContent",
     {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}),
    ("/v1/responses", {"model": "gemini-flash", "input": "hi"}),
], ids=["claude", "gemini-native", "responses"])
def test_other_protocols_never_bypass(world, path, body):
    """它们没有第三方兜底：熔断打开时照常调谷歌（四个路由共用同一个账号池，world 已经替换了它）。"""
    _open()
    r = world.http.post(path, json=body, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert len(world.generate) == 1
    assert world.fallback == []


# ---------------------------------------------------------------------------
# 探测（I.5）
# ---------------------------------------------------------------------------

def test_half_open_lets_one_request_probe_gemini(world, monkeypatch):
    _half_open(monkeypatch)
    status, body = _chat(world)
    assert status == 200
    assert body["choices"][0]["message"]["content"] == "answered by gemini"
    assert len(world.generate) == 1 and world.fallback == []


def test_the_probe_slot_is_released_before_the_fallback_starts(world, monkeypatch):
    """探测请求的谷歌调用以「不计入」的结果结束（这里是 400）：兜底开始之前探测位就得放掉，否则兜底
    （第三方 httpx 超时 300 秒）期间所有请求都只能绕开、没人能探测。"""
    _half_open(monkeypatch)
    world.gemini_error = gc.HTTPStatusError(400, "bad request")
    status, body = _chat(world)
    assert status == 200 and body["choices"][0]["message"]["content"] == "answered by fallback"
    assert [g["thinking"] for g in world.generate] == [1, False], \
        "探测请求照常调了谷歌（思考路径 + 既有的退回不思考一次），都在兜底之前"
    assert world.during_fallback[0]["flash"]["state"] == "half_open"
    assert world.during_fallback[0]["flash"]["probe_in_flight"] is False
    assert model_breaker.should_bypass("flash", probe_timeout=10).is_probe, "下一个请求接着探测"


@pytest.mark.parametrize("stream,tools", [(True, None), (True, _TOOLS)], ids=["real-stream", "buffered"])
def test_stream_probe_slot_is_released_before_the_fallback(world, monkeypatch, stream, tools):
    _half_open(monkeypatch)
    world.gemini_error = gc.HTTPStatusError(400, "bad request")
    status, body = _chat(world, stream=stream, tools=tools)
    assert _content(body) == "answered by fallback"
    assert world.during_fallback[0]["flash"]["probe_in_flight"] is False


def test_the_probe_slot_is_released_when_the_request_finishes(world, monkeypatch):
    _half_open(monkeypatch)
    world.gemini_answer = {"text": "", "images": [], "conversation_id": ""}     # 空响应：不计入
    world.fallback_result = None
    status, body = _chat(world, stream=True)
    assert model_breaker.snapshot()["flash"]["probe_in_flight"] is False


def test_while_the_probe_is_out_other_requests_still_bypass(world, monkeypatch):
    """真并发：探测请求卡在谷歌那边时，第二个请求照样直接走兜底（只有一个探测）。"""
    import app.routers.openai as oai

    _half_open(monkeypatch)
    msgs = [{"role": "user", "content": "hi"}]

    async def run():
        release = asyncio.Event()

        async def blocking_stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                                  account_id=None, extended_thinking=False):
            world.stream.append({"model": model})
            await release.wait()
            yield {"type": "delta", "text": "probe answer"}
            yield {"type": "final", "text": "probe answer", "images": [], "conversation_id": ""}

        monkeypatch.setattr(oai.gemini_client, "generate_stream", blocking_stream)
        request = SimpleNamespace(app=world.http.app)
        req = oai.ChatRequest(model="gemini-flash", stream=True, messages=msgs)

        async def drain(gate):
            gen = oai._stream_response("hi", "gemini-flash", False, "", None, msgs, "gemini-flash",
                                       None, "", request, req, breaker=gate)
            return "".join([chunk async for chunk in gen])

        probe = asyncio.ensure_future(drain(oai._BreakerGate(request, "gemini-flash", "hi")))
        await asyncio.sleep(0.05)                       # 探测请求此刻卡在谷歌那边
        second = await drain(oai._BreakerGate(request, "gemini-flash", "hi"))
        release.set()
        return await probe, second

    body1, body2 = asyncio.run(run())
    assert _content(body1) == "probe answer"
    assert _content(body2) == "answered by fallback"
    assert len(world.stream) == 1, "只有探测请求调了谷歌"


def test_breaker_gate_hands_out_one_probe(world, monkeypatch):
    import app.routers.openai as oai

    _half_open(monkeypatch)
    request = SimpleNamespace(app=world.http.app)
    first = oai._BreakerGate(request, "gemini-flash", "hi")
    second = oai._BreakerGate(request, "gemini-flash", "hi")
    assert first.check() is False and first.ticket.is_probe
    assert second.check() is True
    first.release_probe()
    first.release_probe()                     # 幂等
    third = oai._BreakerGate(request, "gemini-flash", "hi")
    assert third.check() is False and third.ticket.is_probe


def test_probe_timeout_is_the_requests_real_budget_plus_acquire_plus_30(world, monkeypatch):
    import app.routers.openai as oai
    from app.config import settings

    _half_open(monkeypatch, "flash-lite")
    monkeypatch.setattr(settings, "acquire_timeout", 60.0)
    gate = oai._BreakerGate(SimpleNamespace(app=world.http.app), "gemini-flash-lite", "画一张猫的图片")
    gate.check()
    st = model_breaker._families["flash-lite"]
    assert st.probe_timeout == pytest.approx(180 + 60 + 30), "生图意图取大的预算 + acquire_timeout + 30"

"""默认档 low 上线后真流式路径的两处加固 + 几处兼容收尾。

1. 退回重试：默认档开着时，不传思考参数的真流式请求也走思考 payload。上游拒收思考
   payload（还没发出任何正文）时，要像非流式 / buffered / Responses 真流式一样原样退回
   不思考重试一次 —— 否则 v1.6.42 能答的请求会变成硬失败。
2. 思考期间的保活：不回传的思考在 iter_with_keepalive **之前**滤掉，思考期间到点照发
   保活帧；否则上游每隔几秒一个 thoughts 事件把保活计时器一次次重置，客户端在整段思考
   期间收到零字节（Gemini 原生流连首字节都没有）。
3. 只勾了 gemini-flash-thinking 的旧访问密钥，模型列表不能变空。
4. Gemini thinkingBudget 的整数值浮点（0.0）照整数认。
"""

import asyncio
import json

import pytest

import app.core.access_key_store as store_module
from app.config import settings
from app.core import stream as stream_mod
from app.core.access_context import set_current_access_key
from app.core.access_key_store import AccessKeyStore
from app.core.gemini_client import (
    THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW, HTTPStatusError, parse_gemini_thinking_config,
)

_AUTH = {"Authorization": "Bearer sk-test-key"}
ANSWER = "不思考重试的答案"
SECRET = "SECRET-THOUGHT"

_CHAT = {"model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True}
_CLAUDE = {"model": "gemini-flash", "max_tokens": 64, "stream": True,
           "messages": [{"role": "user", "content": "hi"}]}
_RESP = {"model": "gemini-flash", "input": "hi", "stream": True}
_NATIVE = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}

# 四条真流式（无工具）路径
STREAMS = {
    "openai": ("/v1/chat/completions", _CHAT),
    "anthropic": ("/v1/messages", _CLAUDE),
    "gemini": ("/v1beta/models/gemini-flash:streamGenerateContent", _NATIVE),
    "responses": ("/v1/responses", _RESP),
}


def _routers():
    import app.routers.claude as cl
    import app.routers.gemini as ge
    import app.routers.openai as oai
    import app.routers.responses as rp
    return oai, rp, cl, ge


def _post_stream(client, path, body) -> str:
    with client.stream("POST", path, json=body, headers=_AUTH) as r:
        assert r.status_code == 200
        return "".join(r.iter_text())


def _json_objects(body: str) -> list:
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _strings(body: str) -> str:
    parts = []

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for obj in _json_objects(body):
        walk(obj)
    return "".join(parts)


def _has_error(body: str) -> bool:
    for obj in _json_objects(body):
        if isinstance(obj, dict) and ("error" in obj or obj.get("type") in ("error", "response.failed")):
            return True
    return False


def _install(monkeypatch, *, stream_fails_when, partial: str = ""):
    """假上游：generate_stream 在 stream_fails_when(extended_thinking) 为真时抛错（可先吐一段
    partial 正文），否则正常回答；generate（重试用）永远成功、回 ANSWER。"""
    calls = []
    exc_box = {"exc": HTTPStatusError(400, "rejected thinking")}

    async def stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                     account_id=None, extended_thinking=False):
        calls.append(("stream", extended_thinking))
        if stream_fails_when(extended_thinking):
            if partial:
                yield {"type": "delta", "text": partial}
            raise exc_box["exc"]
        yield {"type": "delta", "text": "流式答案"}
        yield {"type": "final", "text": "流式答案", "conversation_id": "", "images": [],
               "thoughts": ""}

    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                  account_id=None, extended_thinking=False):
        calls.append(("gen", extended_thinking))
        return {"text": ANSWER, "images": [], "conversation_id": "", "thoughts": ""}

    for mod in _routers():
        monkeypatch.setattr(mod.gemini_client, "generate_stream", stream)
        monkeypatch.setattr(mod.gemini_client, "generate", gen)
    return calls, exc_box


@pytest.fixture(autouse=True)
def _default_low(monkeypatch):
    monkeypatch.setattr(settings, "default_thinking_level", "low")
    monkeypatch.setattr(settings, "extended_thinking_enabled", True)


# ---------------------------------------------------------------------------
# 1. 真流式：思考路径失败 → 退回不思考重试一次
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(STREAMS))
def test_rejected_thinking_on_a_real_stream_falls_back_to_no_thinking(gem_client, monkeypatch,
                                                                      case):
    path, body = STREAMS[case]
    calls, _ = _install(monkeypatch, stream_fails_when=bool)
    out = _post_stream(gem_client, path, body)

    assert calls == [("stream", THINKING_LEVEL_LOW), ("gen", False)]
    assert ANSWER in _strings(out)
    assert not _has_error(out), out
    assert "rejected thinking" not in out


@pytest.mark.parametrize("case", sorted(STREAMS))
def test_default_off_never_needs_the_retry(gem_client, monkeypatch, case):
    """off 与 v1.6.42 一样：一次上游、不思考，不白打第二次。"""
    monkeypatch.setattr(settings, "default_thinking_level", "off")
    path, body = STREAMS[case]
    calls, _ = _install(monkeypatch, stream_fails_when=bool)
    out = _post_stream(gem_client, path, body)
    assert calls == [("stream", False)]
    assert "流式答案" in _strings(out)


@pytest.mark.parametrize("case", ["openai", "anthropic", "gemini"])
def test_a_failure_after_text_was_streamed_is_not_retried(gem_client, monkeypatch, case):
    """正文已经发出去了就不能再重答一遍（客户端会看到两段答案拼在一起）。"""
    path, body = STREAMS[case]
    calls, _ = _install(monkeypatch, stream_fails_when=bool, partial="半截")
    out = _post_stream(gem_client, path, body)
    assert calls == [("stream", THINKING_LEVEL_LOW)]
    assert "半截" in _strings(out)
    assert _has_error(out)
    assert ANSWER not in _strings(out)


@pytest.mark.parametrize("case", ["openai", "anthropic", "gemini"])
def test_a_generation_timeout_is_not_retried(gem_client, monkeypatch, case):
    """超时不在退回名单里（与 generate_with_thinking_fallback 同一份口径）：生成期超时已经
    吃掉整个预算，再打一次只会把等待时间翻倍。"""
    path, body = STREAMS[case]
    calls, box = _install(monkeypatch, stream_fails_when=bool)
    box["exc"] = TimeoutError("took too long")
    out = _post_stream(gem_client, path, body)
    assert calls == [("stream", THINKING_LEVEL_LOW)]
    assert _has_error(out)


def test_an_explicit_request_that_fails_also_falls_back(gem_client, monkeypatch):
    """明确要了思考也一样退回（与非流式口径一致）；退回后没有思考可回传。"""
    calls, _ = _install(monkeypatch, stream_fails_when=bool)
    out = _post_stream(gem_client, "/v1/chat/completions", {**_CHAT, "reasoning_effort": "high"})
    assert calls == [("stream", THINKING_LEVEL_HIGH), ("gen", False)]
    assert ANSWER in _strings(out)
    assert not _has_error(out)


def test_anthropic_fallback_after_a_thinking_block_keeps_a_valid_block_order(gem_client,
                                                                            monkeypatch):
    """明确要了 thinking、思考块已经开了才失败：退回的正文必须开在 index 1 的文本块里，
    thinking 块先正常关掉（Anthropic 规定的块顺序）。"""
    import app.routers.claude as cl
    calls = []

    async def stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                     account_id=None, extended_thinking=False):
        calls.append(("stream", extended_thinking))
        yield {"type": "thoughts", "text": "想一想"}
        raise HTTPStatusError(400, "rejected thinking")

    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                  account_id=None, extended_thinking=False):
        calls.append(("gen", extended_thinking))
        return {"text": ANSWER, "images": [], "conversation_id": "", "thoughts": ""}

    monkeypatch.setattr(cl.gemini_client, "generate_stream", stream)
    monkeypatch.setattr(cl.gemini_client, "generate", gen)
    out = _post_stream(gem_client, "/v1/messages", {
        **_CLAUDE, "thinking": {"type": "enabled", "budget_tokens": 1024}})

    events = [o for o in _json_objects(out) if isinstance(o, dict) and "type" in o]
    seq = [(e["type"], e.get("index"), (e.get("content_block") or e.get("delta") or {}).get("type"))
           for e in events if e["type"].startswith("content_block")]
    assert seq == [
        ("content_block_start", 0, "thinking"),
        ("content_block_delta", 0, "thinking_delta"),
        ("content_block_stop", 0, None),
        ("content_block_start", 1, "text"),
        ("content_block_delta", 1, "text_delta"),
        ("content_block_stop", 1, None),
    ]
    assert [e["type"] for e in events][-1] == "message_stop"
    assert calls == [("stream", THINKING_LEVEL_LOW), ("gen", False)]


def test_openai_conversation_retry_actually_sends_the_retried_text(gem_client, monkeypatch):
    """续接会话失败后的完整 prompt 重试，拿到的正文过去只进了持久化、没发给客户端。"""
    import app.routers.openai as oai
    calls, _ = _install(monkeypatch, stream_fails_when=lambda et: True)

    class _Conv:
        gemini_conv_id = "c_old"

        def add_message(self, *a):
            pass

    async def _get(*a, **k):
        return _Conv()

    async def _update(*a, **k):
        return None

    monkeypatch.setattr(oai.conversation_store, "get", _get)
    monkeypatch.setattr(oai.conversation_store, "update", _update)
    out = _post_stream(gem_client, "/v1/chat/completions",
                       {**_CHAT, "conversation_id": "conv1"})
    assert calls == [("stream", THINKING_LEVEL_LOW), ("gen", False)]
    assert ANSWER in _strings(out)
    assert not _has_error(out)


# ---------------------------------------------------------------------------
# 2. 不回传的思考期间照发保活帧
# ---------------------------------------------------------------------------

def _slow_thinker(monkeypatch, *, thoughts_for: float = 0.6, every: float = 0.03):
    async def stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                     account_id=None, extended_thinking=False):
        loop = asyncio.get_running_loop()
        end = loop.time() + thoughts_for
        while loop.time() < end:
            await asyncio.sleep(every)
            yield {"type": "thoughts", "text": SECRET}
        yield {"type": "delta", "text": "答"}
        yield {"type": "final", "text": "答", "conversation_id": "", "images": [],
               "thoughts": SECRET}

    for mod in _routers():
        monkeypatch.setattr(mod.gemini_client, "generate_stream", stream)


def _keepalives_before_first_content(case: str, out: str) -> int:
    if case == "gemini":
        n = 0
        for line in out.split("\n")[:-1]:
            if line.strip():
                break
            n += 1
        return n
    first = out.find("答")
    return out[:first].count(": ping")


@pytest.mark.parametrize("case", sorted(STREAMS))
def test_hidden_thinking_does_not_starve_the_keepalive(gem_client, monkeypatch, case):
    """保活间隔 0.1s、上游每 0.03s 一个 thoughts 事件、想 0.6s：过去一个保活帧都没有
    （每个 thoughts 事件都把 iter_with_keepalive 的计时器重置了）。"""
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.1)
    _slow_thinker(monkeypatch)
    path, body = STREAMS[case]
    out = _post_stream(gem_client, path, body)

    assert _keepalives_before_first_content(case, out) >= 2, out
    assert SECRET not in out                     # 合规红线照旧：思考一个字都不出去
    assert "答" in _strings(out)


def test_gemini_native_first_byte_is_a_keepalive_while_thinking(gem_client, monkeypatch):
    """Gemini 原生流在思考期间连首字节都没有 → 过不了前置代理的首字节超时。"""
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.1)
    _slow_thinker(monkeypatch)
    path, body = STREAMS["gemini"]
    out = _post_stream(gem_client, path, body)
    assert out.startswith("\n")


def test_explicitly_requested_thinking_is_still_streamed(gem_client, monkeypatch):
    """过滤只作用于不回传的思考：明确要了的照旧逐帧发出 reasoning_content。"""
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.1)
    _slow_thinker(monkeypatch, thoughts_for=0.1)
    out = _post_stream(gem_client, "/v1/chat/completions", {**_CHAT, "reasoning_effort": "low"})
    assert SECRET in _strings(out)


# ---------------------------------------------------------------------------
# 3. 只勾了已下线名的旧访问密钥：列表照旧列出它
# ---------------------------------------------------------------------------

@pytest.fixture
def _key_store(monkeypatch, tmp_path):
    set_current_access_key(None)
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    yield fresh
    set_current_access_key(None)


def _ids(gem_client, key):
    h = {"Authorization": f"Bearer {key}"}
    return (
        [m["id"] for m in gem_client.get("/v1/models", headers=h).json()["data"]],
        [m["id"] for m in gem_client.get("/claude/v1/models", headers=h).json()["data"]],
        [m["name"] for m in gem_client.get("/v1beta/models", headers=h).json()["models"]],
        gem_client.get("/claude/v1/models/gemini-flash-thinking", headers=h).status_code,
    )


def test_a_key_restricted_to_the_retired_name_still_lists_it(gem_client, _key_store):
    key = _key_store.create("old", allowed_models=["gemini-flash-thinking"]).key
    oai, claude, native, detail = _ids(gem_client, key)
    assert oai == ["gemini-flash-thinking"]
    assert claude == ["gemini-flash-thinking"]
    assert native == ["models/gemini-flash-thinking"]
    assert detail == 200


def test_keys_that_did_not_pick_the_retired_name_do_not_see_it(gem_client, _key_store):
    key = _key_store.create("new", allowed_models=["gemini-flash"]).key
    oai, claude, native, detail = _ids(gem_client, key)
    assert oai == ["gemini-flash"] and claude == ["gemini-flash"]
    assert native == ["models/gemini-flash"]
    assert detail == 404
    # 不限模型 / 没有访问密钥：列表里也没有它
    env = [m["id"] for m in gem_client.get("/v1/models", headers=_AUTH).json()["data"]]
    assert "gemini-flash-thinking" not in env


# ---------------------------------------------------------------------------
# 4. thinkingBudget 的整数值浮点
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("budget,expected", [
    (0.0, False), (0, False), (1024.0, THINKING_LEVEL_LOW), (8192.0, THINKING_LEVEL_HIGH),
    (1.5, None),            # 带小数的不是合法 token 数：按"没给出可认的预算"
])
def test_integral_float_budgets_are_read_as_integers(budget, expected):
    requested, _show = parse_gemini_thinking_config({"thinkingBudget": budget})
    assert requested == expected
    if expected is False:
        assert requested is False


def test_float_zero_budget_turns_thinking_off_end_to_end(gem_client, monkeypatch):
    calls, _ = _install(monkeypatch, stream_fails_when=lambda et: False)
    _post_stream(gem_client, STREAMS["gemini"][0], {
        **_NATIVE, "generationConfig": {"thinkingConfig": {"thinkingBudget": 0.0}}})
    assert calls == [("stream", False)]

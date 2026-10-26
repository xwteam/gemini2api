"""真流式扣住疑似失败套话（v1.6.46 规格 A.5），以及「先出思考、正文才是套话」怎么记账（H.2）。

真流式是逐帧把正文增量发出去的：等整段收完再判就晚了 —— 套话的前半句早已流给客户端，池也不能再
换号（已经吐过内容）。所以回答开头规范化后仍是某条套话的前缀时先扣住正文（思考照常发），一旦分叉
立即把扣住的部分连同新增量一起放出去；整条流结束时还扣着且整段命中，就抛 GeminiFailureReply ——
此时正文一个字都没发出，路由可以兜底。扣住只影响回答开头不超过最长套话长度的那一小段。

H.2：默认思考档是 low，大多数流在套话之前就先发了思考事件，池的 emitted_any 因此为真、不能换号，
走 _release_failed。它不是超时，过去就落进「连败 3 次即 EXPIRED」那条通道 —— flash 故障期间会把
账号一个个打成 EXPIRED（同账号的 pro / flash-lite 一起下线）。它和 5xx 一样是谷歌那边的瞬时故障，
按瞬时故障记账。
"""

import asyncio
import json
import logging

import pytest

from app.core import gemini_client as gc
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.gemini_client import GeminiWebClient

PHRASE = "I seem to be encountering an error. Can I try something else for you?"
_AUTH = {"Authorization": "Bearer sk-test-key"}


def _payload(text=None, thoughts=None, images=False):
    cand = ["rc_1", [text] if text is not None else None]
    if images:
        meta = [None, 1, "a.png", "https://lh3.googleusercontent.com/x", "image/png", [1, 1, 1]]
        cand += [None] * (12 - len(cand)) + [[None] * 7 + [[[[[None, None, None, meta]]]]]]
    if thoughts is not None:
        cand += [None] * (37 - len(cand)) + [[[thoughts]]]
    return [None, ["c_1", "r_1"], None, None, [cand]]


def _raw(*frames) -> str:
    """frames: 每个元素是 (text, thoughts[, images]) → 累积式的 wrb.fr 帧序列。"""
    elems = []
    for f in frames:
        text, thoughts = f[0], f[1]
        images = f[2] if len(f) > 2 else False
        elems.append(["wrb.fr", None, json.dumps(_payload(text, thoughts, images)),
                      None, None, None, "generic"])
    return ")]}'\n\n" + json.dumps(elems)


_SESSIONS: dict = {}   # impersonate target → 那个 client 的原始响应流（多个 client 共用一个替身类）


def _client(monkeypatch, *, stream_raw: str, post_raw: str | None = None, chunk_size: int = 41):
    """真的 GeminiWebClient（generate_stream / generate 都是真代码），HTTP 层是替身。

    gc.AsyncSession 是模块级的，同一个测试里的多个 client 共用一个替身类；按 client 各自的
    _current_target 找回它自己的响应流。
    """
    target = f"chrome120-{len(_SESSIONS)}-{id(stream_raw)}"
    data = stream_raw.encode()
    _SESSIONS[target] = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

    class _Resp:
        status_code = 200
        cookies: dict = {}
        headers: dict = {}

        def __init__(self, chunks):
            self._chunks = chunks

        def aiter_content(self):
            async def gen():
                for c in self._chunks:
                    yield c

            return gen()

    class _CM:
        def __init__(self, chunks):
            self._chunks = chunks

        async def __aenter__(self):
            return _Resp(self._chunks)

        async def __aexit__(self, *a):
            return False

    class _Session:
        def __init__(self, *a, impersonate=None, **kw):
            self._chunks = _SESSIONS[impersonate]
            self._owner = _OWNERS[impersonate]

        def stream(self, *a, **kw):
            self._owner.stream_calls += 1
            return _CM(self._chunks)

        async def close(self):
            return None

    class _PostResp:
        status_code = 200
        cookies: dict = {}
        headers: dict = {}
        text = post_raw if post_raw is not None else stream_raw

    class _Http:
        async def post(self, url, data=None, **kw):
            client.posts += 1
            return _PostResp()

    class _Jar:
        def update_from_response(self, resp):
            return None

    async def _noop(*a, **kw):
        return None

    async def _image_entry(img, cookies):
        return {"b64": "x", "mime": "image/png"}

    monkeypatch.setattr(gc, "AsyncSession", _Session)
    monkeypatch.setattr(gc, "apply_jitter", _noop)
    client = GeminiWebClient.__new__(GeminiWebClient)
    client._healthy = True
    client._heal_lock = asyncio.Lock()
    client._session_token = "TOKEN"
    client._current_target = target
    client._family_model = {}
    client._session_uuid = "SESSION-UUID"
    client._push_id = ""
    client._cookie_jar = _Jar()
    client._http = _Http()
    client.stream_calls = 0
    client.posts = 0
    _OWNERS[target] = client
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_clear_session_cookies", lambda: None)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    monkeypatch.setattr(client, "_build_image_entry", _image_entry)
    return client


_OWNERS: dict = {}


def _collect(agen):
    """跑完一个流，返回 (事件列表, 异常或 None)。"""
    async def run():
        events = []
        try:
            async for evt in agen:
                events.append(evt)
        except Exception as e:  # noqa: BLE001
            return events, e
        return events, None

    return asyncio.run(run())


def _deltas(events):
    return [e["text"] for e in events if e["type"] == "delta"]


# ---------------------------------------------------------------------------
# 扣住 / 放行
# ---------------------------------------------------------------------------

def test_a_stream_that_ends_as_the_failure_phrase_raises_without_leaking_a_single_char(monkeypatch):
    client = _client(monkeypatch, stream_raw=_raw(
        ("I", None), ("I seem to be", None), ("I seem to be encountering an error.", None),
        (PHRASE, None),
    ))
    events, err = _collect(client.generate_stream("只回答一个字：好", "gemini-flash"))

    assert isinstance(err, gc.GeminiFailureReply), (events, err)
    assert _deltas(events) == [], "套话的任何一部分都不能流给客户端"
    assert not [e for e in events if e["type"] == "final"]


def test_a_diverging_answer_is_released_at_once_with_the_held_part(monkeypatch):
    client = _client(monkeypatch, stream_raw=_raw(
        ("I", None), ("I seem", None), ("I seem to like cats", None),
        ("I seem to like cats. And dogs.", None),
    ))
    events, err = _collect(client.generate_stream("hi", "gemini-flash"))

    assert err is None, err
    assert _deltas(events) == ["I seem to like cats", ". And dogs."], \
        "分叉那一帧把扣住的部分连同新增量一起发出，之后恢复逐帧增量"
    assert events[-1]["type"] == "final" and events[-1]["text"] == "I seem to like cats. And dogs."


def test_an_answer_that_never_looked_like_the_phrase_is_not_held(monkeypatch):
    client = _client(monkeypatch, stream_raw=_raw(("好", None), ("好的", None), ("好的，明白", None)))
    events, err = _collect(client.generate_stream("hi", "gemini-flash"))

    assert err is None
    assert _deltas(events) == ["好", "的", "，明白"]


def test_a_held_answer_that_is_not_the_phrase_is_flushed_before_final(monkeypatch):
    """整个回答就是 "I"：一直扣着、但不是套话 → 先把扣住的正文作为 delta 发出，再发 final。"""
    client = _client(monkeypatch, stream_raw=_raw(("I", None)))
    events, err = _collect(client.generate_stream("Who are you? One letter.", "gemini-flash"))

    assert err is None
    assert [e["type"] for e in events] == ["delta", "final"]
    assert events[0]["text"] == "I"
    assert events[1]["text"] == "I"


def test_thought_increments_flow_while_the_body_is_held(monkeypatch):
    client = _client(monkeypatch, stream_raw=_raw(
        (None, "思考一"), ("I seem", "思考一，思考二"), (PHRASE, "思考一，思考二"),
    ))
    events, err = _collect(client.generate_stream("hi", "gemini-flash", extended_thinking=1))

    assert isinstance(err, gc.GeminiFailureReply)
    assert [e["text"] for e in events if e["type"] == "thoughts"] == ["思考一", "，思考二"]
    assert _deltas(events) == []


def test_echo_guard_holds_until_the_end_then_flushes(monkeypatch):
    client = _client(monkeypatch, stream_raw=_raw(("I seem to be", None), (PHRASE, None)))
    events, err = _collect(client.generate_stream(f"Repeat exactly: {PHRASE}", "gemini-flash"))

    assert err is None
    assert [e["type"] for e in events] == ["delta", "final"], "扣到最后：先补发扣住的正文，再发 final"
    assert events[-1]["text"] == PHRASE
    # 补发的是「稳定前缀」（末尾的 ? 照既有口径被 code_event 标记的模板扣着），final 带全文，
    # 路由按「补发缺失尾部」把剩下的发出去 —— 与逐帧增量的既有约定一致。
    assert events[0]["text"] and PHRASE.startswith(events[0]["text"])


def test_a_stream_with_generated_images_is_never_judged(monkeypatch):
    client = _client(monkeypatch, stream_raw=_raw((PHRASE, None, True)))
    events, err = _collect(client.generate_stream("画一只猫", "gemini-flash"))

    assert err is None
    assert events[-1]["type"] == "final" and len(events[-1]["images"]) == 1


def test_a_non_cumulative_frame_that_turns_the_body_into_the_phrase_still_raises(monkeypatch):
    """放行之后不再逐帧检查（A.5），但非累积的替换帧可以把整段正文换掉（帧循环里「非累积/缩短帧」
    那条分支本来就在防它）。正文从 "Let me check" 整段换成了套话：已经发出的几个字收不回来，可这句
    套话绝不能作为 final.text 交出去 —— 路由拿 final.text 存会话记录（A.6）。照样按上游失败抛出。"""
    client = _client(monkeypatch, stream_raw=_raw(("Let me check", None), (PHRASE, None)))
    events, err = _collect(client.generate_stream("hi", "gemini-flash"))

    assert isinstance(err, gc.GeminiFailureReply), (events, err)
    assert _deltas(events) == ["Let me check"]
    assert not [e for e in events if e["type"] == "final"]


def test_a_non_cumulative_frame_with_a_normal_answer_still_finishes(monkeypatch):
    """零回归：替换成的是正常回答时照旧收尾（final 带权威全文）。"""
    client = _client(monkeypatch, stream_raw=_raw(("Let me check", None), ("Here is the answer.", None)))
    events, err = _collect(client.generate_stream("hi", "gemini-flash"))

    assert err is None, err
    assert _deltas(events) == ["Let me check"]
    assert events[-1]["type"] == "final" and events[-1]["text"] == "Here is the answer."


def test_openai_stream_never_stores_a_phrase_that_replaced_the_body(gem_client, monkeypatch, tmp_path):
    """端到端（真池 + 真 client，只有 HTTP 层是替身）：客户端在已发出的正文之后收到 api_error 帧，
    会话记录里没有这句套话（过去 final.text 被当成整段回答存了进去，客户端看到的却是 "Let me check"）。"""
    import app.core.conversation_store as store_module
    import app.routers.openai as oai
    from app.core.conversation_store import ConversationStore

    monkeypatch.setattr(store_module, "DATA_DIR", tmp_path / "conversations")
    store = ConversationStore()
    monkeypatch.setattr(oai, "conversation_store", store)
    client = _client(monkeypatch, stream_raw=_raw(("Let me check", None), (PHRASE, None)))
    monkeypatch.setattr(oai, "gemini_client", _pool([client]))

    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "stream": True, "conversation_id": "thread-1",
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    datas = [json.loads(line[5:].strip()) for line in body.splitlines()
             if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")]
    content = "".join((ch.get("delta") or {}).get("content") or ""
                      for d in datas for ch in d.get("choices") or [])
    assert content == "Let me check", body
    assert [(d["error"]["type"], d["error"]["code"]) for d in datas if "error" in d] == [("api_error", 502)]
    assert not [d for d in datas for ch in d.get("choices") or [] if ch.get("finish_reason") == "stop"]
    conv = asyncio.run(store.get(oai.scoped_conversation_id("thread-1")))
    assert PHRASE not in json.dumps(conv.messages if conv else [], ensure_ascii=False)
    files = list((tmp_path / "conversations").glob("*.json"))
    assert all(PHRASE not in f.read_text(encoding="utf-8") for f in files)


def test_configured_phrases_are_held_too(monkeypatch):
    monkeypatch.setattr(gc.settings, "gemini_failure_replies", "我好像遇到了错误。", raising=False)
    client = _client(monkeypatch, stream_raw=_raw(("我好像", None), ("我好像遇到了错误。", None)))
    events, err = _collect(client.generate_stream("hi", "gemini-flash"))

    assert isinstance(err, gc.GeminiFailureReply)
    assert _deltas(events) == []


# ---------------------------------------------------------------------------
# 账号池记账（H.2）
# ---------------------------------------------------------------------------

def _pool(clients) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"psid-{i}", psidts="", label=f"account-{i}",
                status=AccountStatus.ACTIVE, client=c)
        for i, c in enumerate(clients)
    ]
    pool._max_concurrent = 8
    pool._acquire_timeout = 2.0
    return pool


_THINK_THEN_PHRASE = _raw((None, "先想一想"), ("I seem", "先想一想"), (PHRASE, "先想一想"))


def test_before_any_output_the_pool_fails_over_like_a_5xx(monkeypatch):
    bad = _client(monkeypatch, stream_raw=_raw((PHRASE, None)))
    good = _client(monkeypatch, stream_raw=_raw(("好", None)))
    pool = _pool([bad, good])
    pool._robin_index = 1          # 轮转从下一个开始：让第一个被选中的是 bad（account-0）

    events, err = _collect(pool.generate_stream("hi", "gemini-flash"))

    assert err is None, err
    assert _deltas(events) == ["好"]
    assert bad.stream_calls == 1 and good.stream_calls == 1
    assert pool.accounts[0].cooldown_until > 0
    assert pool.accounts[0].consecutive_failures == 0


def test_after_thoughts_the_failure_is_accounted_as_a_transient_upstream_fault(monkeypatch, caplog):
    client = _client(monkeypatch, stream_raw=_THINK_THEN_PHRASE)
    pool = _pool([client])

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            events, err = _collect(pool.generate_stream("hi", "gemini-flash", extended_thinking=1))
            assert isinstance(err, gc.GeminiFailureReply)
            assert [e["type"] for e in events] == ["thoughts"], "前提：失败前已经发过思考事件"

    account = pool.accounts[0]
    assert account.status == AccountStatus.ACTIVE, "3 次「先思考、正文是套话」把账号推成了 EXPIRED"
    assert account.consecutive_failures == 0
    assert account.cooldown_until > 0, "照瞬时上游故障记账：软冷却"
    assert account.error_count == 3
    assert account.last_error == "GeminiFailureReply (HTTP 502)"
    assert account.active_requests == 0
    assert client.stream_calls == 3
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(account.id in w and "generic failure reply" in w for w in warnings), warnings


def test_openai_stream_falls_back_after_thoughts_then_the_phrase(gem_client, monkeypatch):
    """H.2 的完整链路：同一账号连续 3 次「先思考、正文是套话」的流 —— 每次都由第三方兜底答出，
    账号始终 ACTIVE、consecutive_failures 不变、处于冷却。"""
    import app.routers.openai as oai

    client = _client(monkeypatch, stream_raw=_THINK_THEN_PHRASE, post_raw=_raw((PHRASE, None)))
    pool = _pool([client])
    monkeypatch.setattr(oai, "gemini_client", pool)
    fallbacks = []

    async def fake_fallback(request, req, messages_raw, exclude_model=""):
        fallbacks.append(exclude_model)
        return {"id": "chatcmpl-fb", "object": "chat.completion", "created": 0, "model": "tp",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "from fallback"}}]}

    monkeypatch.setattr(oai, "_fallback_result", fake_fallback)

    for _ in range(3):
        with gem_client.stream("POST", "/v1/chat/completions", json={
            "model": "gemini-flash", "stream": True,
            "messages": [{"role": "user", "content": "只回答一个字：好"}],
        }, headers=_AUTH) as r:
            body = "".join(r.iter_text())
        assert "from" in body and "fallback" in body, body
        assert PHRASE not in body
        assert '"error"' not in body

    account = pool.accounts[0]
    assert len(fallbacks) == 3
    assert account.status == AccountStatus.ACTIVE
    assert account.consecutive_failures == 0
    assert account.cooldown_until > 0
    assert client.stream_calls == 3

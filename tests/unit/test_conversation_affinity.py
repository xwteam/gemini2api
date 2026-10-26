"""多轮续接要钉同一个账号（v1.6.45 规格 B.3）。

会话 id 是账号私有的：第二轮按轮询落到别的账号，别的账号根本接不上这个会话。所以：
  - 会话记录服务它的账号 id（持久化；旧文件没有这个字段也要能读）；
  - 账号池的 generate / generate_stream 结果带回实际服务的账号 id；
  - 账号池提供「这个账号此刻能不能被钉住」的只读判断，路由据此决定续不续接。
"""

import asyncio
import json

import pytest

import app.core.account_pool as pool_module
import app.core.conversation_store as store_module
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.conversation_store import Conversation, ConversationStore
from app.core.gemini_client import HTTPStatusError

TRIPLE = ["c_9a1b2c3d4e5f6789", "r_0011223344556677", "rc_8899aabbccddeeff"]


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------

def test_conversation_records_the_serving_account():
    conv = Conversation("thread-1")
    assert conv.account_id == ""
    conv.gemini_conv_id = json.dumps(TRIPLE)
    conv.account_id = "account-2"
    data = conv.to_dict()
    assert data["account_id"] == "account-2"
    assert data["gemini_conv_id"] == json.dumps(TRIPLE)
    again = Conversation.from_dict(data)
    assert (again.account_id, again.gemini_conv_id) == ("account-2", json.dumps(TRIPLE))


def test_old_conversation_files_without_an_account_still_load():
    old = {"id": "thread-1", "gemini_conv_id": "['c_abc', 'r_def']", "model": "gemini-pro",
           "messages": [], "created_at": 1.0, "updated_at": 2.0}
    conv = Conversation.from_dict(old)
    assert conv.account_id == ""
    assert conv.gemini_conv_id == "['c_abc', 'r_def']"


@pytest.mark.parametrize("bad", [None, 5, ["account-1"], {"id": "x"}])
def test_a_malformed_account_field_reads_as_no_account(bad):
    conv = Conversation.from_dict({"id": "t", "gemini_conv_id": "", "account_id": bad})
    assert conv.account_id == ""


def test_account_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "DATA_DIR", tmp_path / "conversations")

    async def run():
        store = ConversationStore()
        conv = await store.create("thread-1", "gemini-pro")
        conv.gemini_conv_id = json.dumps(TRIPLE)
        conv.account_id = "account-7"
        await store.update(conv)
        # 新进程：从磁盘重新加载
        reloaded = await ConversationStore().get("thread-1")
        return reloaded

    conv = asyncio.run(run())
    assert conv is not None
    assert conv.account_id == "account-7"
    assert conv.gemini_conv_id == json.dumps(TRIPLE)


def test_old_file_on_disk_loads(tmp_path, monkeypatch):
    import time

    d = tmp_path / "conversations"
    d.mkdir()
    (d / "index.json").write_text(json.dumps([{"id": "old", "updated_at": time.time()}]))
    (d / "old.json").write_text(json.dumps({
        "id": "old", "gemini_conv_id": "['c_abc', 'r_def']", "model": "gemini-pro",
        "messages": [], "created_at": time.time(), "updated_at": time.time(),
    }))
    monkeypatch.setattr(store_module, "DATA_DIR", d)

    conv = asyncio.run(ConversationStore().get("old"))
    assert conv is not None and conv.account_id == ""


# ---------------------------------------------------------------------------
# 账号池：结果带回服务的账号 id
# ---------------------------------------------------------------------------

class _Client:
    def __init__(self, name, *, fail=None, healthy=True):
        self.name = name
        self._healthy = healthy
        self._heal_lock = asyncio.Lock()
        self._fail = fail
        self.calls = []

    @property
    def is_healthy(self):
        return self._healthy

    async def generate(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False):
        self.calls.append(conversation_id)
        if self._fail is not None:
            raise self._fail
        return {"text": f"from {self.name}", "images": [], "thoughts": "",
                "conversation_id": json.dumps(TRIPLE)}

    async def generate_stream(self, prompt, model, conversation_id="", attachments=None,
                              gem_id=None, extended_thinking=False):
        self.calls.append(conversation_id)
        if self._fail is not None:
            raise self._fail
        yield {"type": "delta", "text": "hi"}
        yield {"type": "final", "text": "hi", "images": [], "thoughts": "",
               "conversation_id": json.dumps(TRIPLE)}


def _pool(clients, statuses=None) -> AccountPool:
    pool = AccountPool()
    statuses = statuses or [AccountStatus.ACTIVE] * len(clients)
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"psid-{i}", psidts="", label=f"account-{i}",
                status=st, client=c)
        for i, (c, st) in enumerate(zip(clients, statuses))
    ]
    pool._max_concurrent = 2
    pool._acquire_timeout = 1.0
    return pool


def test_generate_result_names_the_account_that_served_it():
    pool = _pool([_Client("a"), _Client("b")])
    result = asyncio.run(pool.generate("p", "gemini-flash", account_id="account-1"))
    assert result["account_id"] == "account-1"
    assert result["text"] == "from b"


def test_generate_result_names_the_failover_account():
    """第一个账号 503 → 换号：记录的必须是真正吐出答案的那个账号。"""
    a = _Client("a")
    b = _Client("b", fail=HTTPStatusError(503, "busy"))
    pool = _pool([a, b])
    pool._robin_index = 0   # 轮询从 _robin_index + 1 开始：先选到 b

    result = asyncio.run(pool.generate("p", "gemini-flash"))
    assert b.calls and a.calls, "前提不成立：本该先打 b、失败后换到 a"
    assert result["account_id"] == "account-0"


def test_stream_final_event_names_the_account_and_deltas_are_untouched():
    pool = _pool([_Client("a"), _Client("b")])

    async def run():
        return [e async for e in pool.generate_stream("p", "gemini-flash", account_id="account-0")]

    events = asyncio.run(run())
    assert events[0] == {"type": "delta", "text": "hi"}
    final = events[-1]
    assert final["type"] == "final"
    assert final["account_id"] == "account-0"
    assert final["conversation_id"] == json.dumps(TRIPLE)


# ---------------------------------------------------------------------------
# 账号池：能不能钉住
# ---------------------------------------------------------------------------

def test_pinnable_only_when_active_healthy_and_known():
    pool = _pool(
        [_Client("a"), _Client("b"), _Client("c", healthy=False), _Client("d")],
        [AccountStatus.ACTIVE, AccountStatus.EXPIRED, AccountStatus.ACTIVE, AccountStatus.DISABLED],
    )
    assert pool.account_pinnable("account-0") is True
    assert pool.account_pinnable("account-1") is False   # 过期
    assert pool.account_pinnable("account-2") is False   # 会话失效
    assert pool.account_pinnable("account-3") is False   # 停用
    assert pool.account_pinnable("account-9") is False   # 已删除 / 不存在
    assert pool.account_pinnable("") is False
    assert pool.account_pinnable(None) is False


def test_not_pinnable_when_the_access_key_does_not_allow_it(monkeypatch):
    pool = _pool([_Client("a"), _Client("b")])
    monkeypatch.setattr(pool_module, "current_bound_account_ids", lambda: {"account-1"})
    assert pool.account_pinnable("account-0") is False
    assert pool.account_pinnable("account-1") is True


def test_a_full_account_is_not_pinnable_when_others_exist():
    """钉住 = 排除其它所有账号；池里还有别的账号时，满载的账号会被 acquire 当场判不可用
    （不排队），所以不算可钉。只有它一个账号时 acquire 照常排队，满载不算不可钉。"""
    pool = _pool([_Client("a"), _Client("b")])
    pool.accounts[0].active_requests = pool._max_concurrent
    assert pool.account_pinnable("account-0") is False
    assert pool.account_pinnable("account-1") is True

    solo = _pool([_Client("a")])
    solo.accounts[0].active_requests = solo._max_concurrent
    assert solo.account_pinnable("account-0") is True


# ---------------------------------------------------------------------------
# 路由：两轮对话（mock 上游 = 真账号池 + 每个账号一个假 client）
# ---------------------------------------------------------------------------
# 两个账号、轮询：不钉的话第二轮一定落到另一个账号（_pick_round_robin 从上次的下一个开始），
# 所以「第二轮打到了第一轮的账号」本身就证明钉住了。

_AUTH = {"Authorization": "Bearer sk-test-key"}
U1 = {"role": "user", "content": "u1"}
A1 = {"role": "assistant", "content": "a1"}
U2 = {"role": "user", "content": "u2"}
FULL_HISTORY = "Human: u1\n\nAssistant: a1\n\nHuman: u2"
_TOOLS = [{"type": "function", "function": {
    "name": "get_weather", "description": "w",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
}}]


class _Upstream:
    """假的 GeminiWebClient：每个账号有自己的会话，按真实形态回 [cid, rid, rcid]。"""

    def __init__(self, tag: str):
        self.tag = tag
        self.calls: list[dict] = []
        self._healthy = True
        self._heal_lock = asyncio.Lock()
        self._turn = 0
        # 谷歌那边不认续接参数（会话真过期）时抛这个；新会话照常回答
        self.reject_resume = None

    @property
    def is_healthy(self):
        return self._healthy

    def triple(self, turn: int) -> list:
        return [f"c_{self.tag * 16}", f"r_{self.tag}{turn:015d}", f"rc_{self.tag}{turn:015d}"]

    def _answer(self, prompt, conversation_id, gem_id, extended_thinking, stream):
        self.calls.append({"prompt": prompt, "conv": conversation_id, "gem_id": gem_id,
                           "thinking": extended_thinking, "stream": stream})
        if conversation_id and self.reject_resume is not None:
            raise self.reject_resume
        self._turn += 1
        return {"text": f"answer from {self.tag}", "images": [], "thoughts": "",
                "conversation_id": json.dumps(self.triple(self._turn))}

    async def generate(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False):
        return self._answer(prompt, conversation_id, gem_id, extended_thinking, False)

    async def generate_stream(self, prompt, model, conversation_id="", attachments=None,
                              gem_id=None, extended_thinking=False):
        result = self._answer(prompt, conversation_id, gem_id, extended_thinking, True)
        yield {"type": "delta", "text": result["text"]}
        yield {"type": "final", **result}


@pytest.fixture
def wired(gem_client, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.routers import openai as oai

    monkeypatch.setattr(store_module, "DATA_DIR", tmp_path / "conversations")
    store = ConversationStore()
    monkeypatch.setattr(oai, "conversation_store", store)
    ups = [_Upstream("a"), _Upstream("b")]
    pool = _pool(ups)
    pool._max_concurrent = 8
    monkeypatch.setattr(oai, "gemini_client", pool)
    return SimpleNamespace(http=gem_client, store=store, pool=pool, ups=ups, app=gem_client.app)


def _chat(w, messages, *, stream=False, tools=None, model="gemini-pro", conversation_id="t1"):
    body = {"model": model, "messages": messages, "conversation_id": conversation_id, "stream": stream}
    if tools:
        body["tools"] = tools
    if stream:
        with w.http.stream("POST", "/v1/chat/completions", json=body, headers=_AUTH) as r:
            text = "".join(r.iter_text())
            assert r.status_code == 200, text
            assert '"error"' not in text, text
            return text
    r = w.http.post("/v1/chat/completions", json=body, headers=_AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _stored(w, conv_id="t1"):
    return asyncio.run(w.store.get(conv_id))


def _seed(w, gemini_conv_id, account_id="", conv_id="t1"):
    async def run():
        conv = await w.store.create(conv_id, "gemini-pro")
        conv.gemini_conv_id = gemini_conv_id
        conv.account_id = account_id
        await w.store.update(conv)

    asyncio.run(run())


def _first_turn(w, **kw):
    """跑第一轮，返回 (服务它的上游, 账号下标)。"""
    _chat(w, [U1], **kw)
    served = [i for i, u in enumerate(w.ups) if u.calls]
    assert len(served) == 1, [u.calls for u in w.ups]
    return w.ups[served[0]], served[0]


def test_second_turn_is_pinned_to_the_first_turns_account_with_the_triple(wired):
    w = wired
    first, idx = _first_turn(w)
    conv = _stored(w)
    assert conv.account_id == f"account-{idx}"
    assert json.loads(conv.gemini_conv_id) == first.triple(1)

    _chat(w, [U1, A1, U2])

    other = w.ups[1 - idx]
    assert other.calls == [], "第二轮没钉住，落到了另一个账号"
    call = first.calls[-1]
    assert call["prompt"] == "u2", "续接只发最后一条用户消息"
    assert call["conv"] == json.dumps(first.triple(1)), "续接参数要带三元组"
    # 存储更新成第二轮的三元组，账号不变
    conv = _stored(w)
    assert json.loads(conv.gemini_conv_id) == first.triple(2)
    assert conv.account_id == f"account-{idx}"


def test_third_turn_continues_from_the_second_answer(wired):
    w = wired
    first, idx = _first_turn(w)
    _chat(w, [U1, A1, U2])
    _chat(w, [U1, A1, U2, {"role": "assistant", "content": "a2"}, {"role": "user", "content": "u3"}])
    assert first.calls[-1]["conv"] == json.dumps(first.triple(2))
    assert first.calls[-1]["prompt"] == "u3"
    assert w.ups[1 - idx].calls == []


def test_unavailable_account_resends_the_full_history_and_updates_the_store(wired):
    w = wired
    first, idx = _first_turn(w)
    w.pool.accounts[idx].status = AccountStatus.EXPIRED
    other = w.ups[1 - idx]

    _chat(w, [U1, A1, U2])

    assert len(first.calls) == 1, "过期的账号不该再被打"
    assert len(other.calls) == 1, f"预判接不上就直接发完整历史，不该先白打一轮: {other.calls}"
    call = other.calls[-1]
    assert call["prompt"] == FULL_HISTORY, "接不上就必须发完整历史，不能只发最后一句"
    assert call["conv"] == "", "新开会话不能带续接参数"
    assert call["thinking"], "预判出接不上时是正常的新请求，思考档位不该被降成不思考"
    conv = _stored(w)
    assert conv.account_id == f"account-{1 - idx}"
    assert json.loads(conv.gemini_conv_id) == other.triple(1)


def test_account_excluded_by_the_access_key_whitelist_resends_the_full_history(wired, monkeypatch):
    w = wired
    first, idx = _first_turn(w)
    other_id = f"account-{1 - idx}"
    monkeypatch.setattr(pool_module, "current_bound_account_ids", lambda: {other_id})

    _chat(w, [U1, A1, U2])

    assert len(first.calls) == 1
    call = w.ups[1 - idx].calls[-1]
    assert (call["prompt"], call["conv"]) == (FULL_HISTORY, "")
    assert call["thinking"], "思考档位不该被降成不思考"
    assert _stored(w).account_id == other_id


def test_pinned_account_failing_at_send_time_falls_back_to_the_full_history(wired, monkeypatch):
    """预判时还能钉、真发的时候池子报 unavailable（竞态）：同样改发完整历史、不带续接参数。"""
    w = wired
    first, idx = _first_turn(w)
    w.pool.accounts[idx].status = AccountStatus.EXPIRED
    monkeypatch.setattr(w.pool, "account_pinnable", lambda account_id: True)

    _chat(w, [U1, A1, U2])

    other = w.ups[1 - idx]
    assert other.calls, "钉不住之后没有改发"
    call = other.calls[-1]
    assert (call["prompt"], call["conv"]) == (FULL_HISTORY, "")
    assert _stored(w).account_id == f"account-{1 - idx}"


# ---------------------------------------------------------------------------
# 钉住的账号真发时才不可用（预判之后被抢满 / 过期）：PinnedAccountUnavailable
# ---------------------------------------------------------------------------
# account_pinnable 只是快照。它说能钉、真发时 acquire 却拿不到这个账号时，池子当场报错（不打上游）。
# 过去这条报错是普通 RuntimeError：先被当成思考失败、钉着同一个账号退回不思考再试一次（必然再失败），
# 然后完整历史重试写死不思考 —— 这一轮白白丢了思考档位；它若也失败，classify_error 拿到「Pinned gem
# account」文案回 500，会话场景的日志还写成 gem。


def _record_pool_calls(w, monkeypatch):
    """记录路由调了几次账号池（generate / generate_stream），各钉的哪个账号、什么思考档位。"""
    seen = []
    real_generate, real_stream = w.pool.generate, w.pool.generate_stream

    async def generate(*a, **k):
        seen.append(("generate", k.get("account_id"), k.get("extended_thinking")))
        return await real_generate(*a, **k)

    def generate_stream(*a, **k):
        seen.append(("generate_stream", k.get("account_id"), k.get("extended_thinking")))
        return real_stream(*a, **k)

    monkeypatch.setattr(w.pool, "generate", generate)
    monkeypatch.setattr(w.pool, "generate_stream", generate_stream)
    return seen


def test_a_pinned_account_that_is_unavailable_raises_a_dedicated_error():
    from app.core.gemini_client import PinnedAccountUnavailable

    pool = _pool([_Client("a"), _Client("b")])
    pool.accounts[0].active_requests = pool._max_concurrent    # 被抢满

    async def run():
        with pytest.raises(PinnedAccountUnavailable) as plain:
            await pool.generate("p", "gemini-flash", account_id="account-0")
        with pytest.raises(PinnedAccountUnavailable) as gem:
            await pool.generate("p", "gemini-flash", gem_id="gem-1", account_id="account-0")
        with pytest.raises(PinnedAccountUnavailable) as streamed:
            async for _ in pool.generate_stream("p", "gemini-flash", account_id="account-0"):
                pass
        return plain.value, gem.value, streamed.value

    plain, gem, streamed = asyncio.run(run())
    assert isinstance(plain, RuntimeError), "仍是 RuntimeError：既有的 except / 映射照常接得住"
    # 会话钉号不再写成 gem；Gem 钉号的文案逐字不变
    assert str(plain) == "Pinned account 'account-0' unavailable (expired/busy/cooldown)"
    assert str(gem) == "Pinned gem account 'account-0' unavailable (expired/busy/cooldown)"
    assert str(streamed) == str(plain)
    assert [a.active_requests for a in pool.accounts] == [pool._max_concurrent, 0], "槽位不能漏"


def test_pinned_account_unavailable_is_a_503_and_not_a_thinking_failure():
    from app.core.gemini_client import (PinnedAccountUnavailable, classify_error,
                                        should_retry_without_thinking)

    exc = PinnedAccountUnavailable("Pinned account 'account-0' unavailable (expired/busy/cooldown)")
    assert classify_error(exc) == (503, "api_error", None)
    assert should_retry_without_thinking(exc, 2) is False
    # 零回归：别的 RuntimeError 照旧
    assert classify_error(RuntimeError("boom")) == (500, "api_error", None)
    assert should_retry_without_thinking(RuntimeError("boom"), 2) is True


@pytest.mark.parametrize("mode", ["nonstream", "stream", "buffered"])
def test_a_pin_lost_at_send_time_goes_straight_to_the_full_history_and_keeps_thinking(
        wired, monkeypatch, mode):
    w = wired
    first, idx = _first_turn(w)
    other = w.ups[1 - idx]
    w.pool.accounts[idx].status = AccountStatus.EXPIRED                       # 真发时已经不可用
    monkeypatch.setattr(w.pool, "account_pinnable", lambda account_id: True)  # 预判时还能钉
    seen = _record_pool_calls(w, monkeypatch)

    kw = {"stream": mode != "nonstream", "tools": _TOOLS if mode == "buffered" else None}
    _chat(w, [U1, A1, U2], **kw)

    pinned = [c for c in seen if c[1] == f"account-{idx}"]
    assert len(pinned) == 1, f"钉着同一个不可用的账号退回不思考再试，只会原样失败: {seen}"
    assert len(seen) == 2, seen
    thinking = pinned[0][2]
    assert thinking, "前提不成立：这一轮本该走思考路径（默认档）"
    call = other.calls[-1]
    assert call["conv"] == "", "改发完整历史 = 新开会话，不带续接参数"
    if mode == "buffered":
        assert "Human: u1" in call["prompt"] and "Human: u2" in call["prompt"]
    else:
        assert call["prompt"] == FULL_HISTORY
    assert call["thinking"] == thinking, "完整历史重试把这一轮的思考档位丢了"
    assert _stored(w).account_id == f"account-{1 - idx}"


def test_the_kept_thinking_level_still_falls_back_when_thinking_itself_fails(wired, monkeypatch):
    """保留思考档位的完整历史重试，若思考路径自己失败，照常退回不思考（不把这一轮变成硬失败）。"""
    w = wired
    first, idx = _first_turn(w)
    other = w.ups[1 - idx]
    w.pool.accounts[idx].status = AccountStatus.EXPIRED
    monkeypatch.setattr(w.pool, "account_pinnable", lambda account_id: True)
    original = other._answer

    def reject_thinking(prompt, conversation_id, gem_id, extended_thinking, stream):
        if extended_thinking:
            other.calls.append({"prompt": prompt, "conv": conversation_id, "gem_id": gem_id,
                                "thinking": extended_thinking, "stream": stream})
            raise HTTPStatusError(400, "thinking payload rejected")
        return original(prompt, conversation_id, gem_id, extended_thinking, stream)

    other._answer = reject_thinking
    body = _chat(w, [U1, A1, U2])

    assert body["choices"][0]["message"]["content"] == f"answer from {other.tag}"
    assert [bool(c["thinking"]) for c in other.calls] == [True, False], other.calls
    assert all(c["prompt"] == FULL_HISTORY and c["conv"] == "" for c in other.calls)


def test_a_gem_pinned_account_that_is_unavailable_is_a_503(wired):
    """Gem 钉住的账号不可用：不再白退一次不思考，回 503 而不是 500，文案照旧写 gem。"""
    w = wired
    w.pool.accounts[1].status = AccountStatus.EXPIRED
    w.app.state.gem_mapping.set("my-gem", {"gem_id": "gem-1", "base_model": "gemini-pro",
                                           "account_id": "account-1"})

    r = w.http.post("/v1/chat/completions", json={"model": "my-gem", "messages": [U1]},
                    headers=_AUTH)

    assert r.status_code == 503, r.text
    assert r.json()["error"]["type"] == "api_error"
    assert "Pinned gem account 'account-1'" in r.json()["error"]["message"]
    assert [u.calls for u in w.ups] == [[], []]


def test_google_rejecting_the_resume_retries_with_the_full_history(wired):
    """「续接失败 → 用完整 prompt 重试」保留：谷歌那边会话真过期时照旧补救，且存新会话。"""
    w = wired
    first, idx = _first_turn(w)
    first.reject_resume = HTTPStatusError(400, "conversation not found")

    _chat(w, [U1, A1, U2])

    fresh = [c for u in w.ups for c in u.calls if c["conv"] == "" and c["prompt"] == FULL_HISTORY]
    assert fresh, [u.calls for u in w.ups]
    conv = _stored(w)
    assert conv.account_id in ("account-0", "account-1")
    served = w.ups[int(conv.account_id[-1])]
    assert json.loads(conv.gemini_conv_id) == served.triple(served._turn)


def test_the_nonstream_full_history_retry_keeps_the_attachments(wired, monkeypatch):
    """「续接失败 → 改发完整历史」是新开会话：历史里的图片也得一起发过去。非流式这一步过去不带
    attachments（真流式 / buffered 都带），新会话里看不到用户发过的图。"""
    from app.utils.prompt import extract_attachments

    w = wired
    first, idx = _first_turn(w)
    first.reject_resume = HTTPStatusError(400, "conversation not found")
    seen = []
    real_generate = w.pool.generate

    async def recording_generate(*a, **k):
        seen.append({"conv": a[2] if len(a) > 2 else k.get("conversation_id", ""),
                     "attachments": a[3] if len(a) > 3 else k.get("attachments")})
        return await real_generate(*a, **k)

    monkeypatch.setattr(w.pool, "generate", recording_generate)
    with_image = {"role": "user", "content": [
        {"type": "text", "text": "u1"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
    ]}
    messages = [with_image, A1, U2]

    _chat(w, messages)

    fresh = [c for c in seen if not c["conv"]]
    assert fresh, seen
    assert fresh[-1]["attachments"] == extract_attachments(messages) != [], \
        "完整历史重试把历史里的图片丢了"


@pytest.mark.parametrize("stored", ["garbage", "gemini-conv-1", "[1, 2]"])
def test_bad_stored_metadata_resends_the_full_history(wired, stored, caplog):
    w = wired
    _seed(w, stored, account_id="account-0")

    import logging
    with caplog.at_level(logging.WARNING, logger="app.core.gemini_client"):
        _chat(w, [U1, A1, U2])

    calls = [c for u in w.ups for c in u.calls]
    assert [(c["prompt"], c["conv"]) for c in calls] == [(FULL_HISTORY, "")]
    assert any("conversation metadata" in r.getMessage() for r in caplog.records)
    conv = _stored(w)
    assert conv.account_id and parse_triple(conv.gemini_conv_id)


def parse_triple(value):
    from app.core.gemini_client import parse_conversation_metadata
    return parse_conversation_metadata(value)


def test_old_repr_metadata_with_a_recorded_account_resumes(wired):
    w = wired
    a = w.ups[0]
    _seed(w, f"['{a.triple(1)[0]}', '{a.triple(1)[1]}']", account_id="account-0")

    _chat(w, [U1, A1, U2])

    call = a.calls[-1]
    assert call["prompt"] == "u2"
    assert call["conv"] == json.dumps([a.triple(1)[0], a.triple(1)[1], None])
    assert w.ups[1].calls == []


def test_old_file_without_an_account_resends_the_full_history_then_records_one(wired, caplog):
    import logging

    w = wired
    a = w.ups[0]
    _seed(w, f"['{a.triple(1)[0]}', '{a.triple(1)[1]}']", account_id="")

    with caplog.at_level(logging.INFO, logger="app.routers.openai"):
        _chat(w, [U1, A1, U2])

    assert any("no recorded account" in r.getMessage() for r in caplog.records), \
        "日志要说清为什么没续接"

    calls = [c for u in w.ups for c in u.calls]
    assert [(c["prompt"], c["conv"]) for c in calls] == [(FULL_HISTORY, "")]
    assert _stored(w).account_id in ("account-0", "account-1")


def test_the_gem_binding_wins_over_the_conversation_account(wired):
    """Gem 钉的账号和会话记录的账号冲突：以 Gem 为准，不续接（发完整历史）。"""
    w = wired
    a, b = w.ups
    _seed(w, json.dumps(a.triple(1)), account_id="account-0")
    w.app.state.gem_mapping.set("my-gem", {"gem_id": "gem-1", "base_model": "gemini-pro",
                                           "account_id": "account-1"})

    _chat(w, [U1, A1, U2], model="my-gem")

    assert a.calls == []
    call = b.calls[-1]
    assert (call["prompt"], call["conv"], call["gem_id"]) == (FULL_HISTORY, "", "gem-1")
    assert _stored(w).account_id == "account-1"


def test_the_gem_binding_on_the_same_account_resumes(wired):
    w = wired
    a, b = w.ups
    _seed(w, json.dumps(b.triple(1)), account_id="account-1")
    w.app.state.gem_mapping.set("my-gem", {"gem_id": "gem-1", "base_model": "gemini-pro",
                                           "account_id": "account-1"})

    _chat(w, [U1, A1, U2], model="my-gem")

    call = b.calls[-1]
    assert (call["prompt"], call["conv"]) == ("u2", json.dumps(b.triple(1)))


def test_real_stream_second_turn_is_pinned_and_updates_the_store(wired):
    w = wired
    first, idx = _first_turn(w)

    _chat(w, [U1, A1, U2], stream=True)

    assert w.ups[1 - idx].calls == []
    call = first.calls[-1]
    assert call["stream"] is True
    assert (call["prompt"], call["conv"]) == ("u2", json.dumps(first.triple(1)))
    conv = _stored(w)
    assert json.loads(conv.gemini_conv_id) == first.triple(2)
    assert conv.account_id == f"account-{idx}"


def test_real_stream_with_an_unavailable_account_resends_the_full_history(wired):
    w = wired
    first, idx = _first_turn(w)
    w.pool.accounts[idx].status = AccountStatus.EXPIRED

    _chat(w, [U1, A1, U2], stream=True)

    other = w.ups[1 - idx]
    assert len(other.calls) == 1, other.calls
    call = other.calls[-1]
    assert (call["prompt"], call["conv"], call["stream"]) == (FULL_HISTORY, "", True), \
        "预判接不上时照样真流式发完整历史"
    assert _stored(w).account_id == f"account-{1 - idx}"


def test_buffered_tool_stream_second_turn_is_pinned(wired):
    w = wired
    first, idx = _first_turn(w)

    _chat(w, [U1, A1, U2], stream=True, tools=_TOOLS)

    assert w.ups[1 - idx].calls == []
    call = first.calls[-1]
    assert call["conv"] == json.dumps(first.triple(1))
    assert "u2" in call["prompt"] and "Human: u1" not in call["prompt"]
    assert json.loads(_stored(w).gemini_conv_id) == first.triple(2)


def test_buffered_full_history_retry_keeps_the_tool_definitions(wired):
    """buffered（带工具）路径的「续接失败 → 完整 prompt 重试」此前丢了工具说明：重试的回答
    不会是工具调用，客户端的工具循环就断了。"""
    w = wired
    first, idx = _first_turn(w)
    first.reject_resume = HTTPStatusError(400, "conversation not found")

    _chat(w, [U1, A1, U2], stream=True, tools=_TOOLS)

    fresh = [c for u in w.ups for c in u.calls
             if c["conv"] == "" and "Human: u1" in c["prompt"] and "Human: u2" in c["prompt"]]
    assert fresh, [u.calls for u in w.ups]
    assert all("get_weather" in c["prompt"] for c in fresh), fresh


# ---------------------------------------------------------------------------
# 一直用流式的客户端：自带 conversation_id 时同样建会话记录
# ---------------------------------------------------------------------------
# 过去只有非流式会新建会话记录，流式只在记录已存在时回写：一直用 stream:true、自带
# conversation_id 的客户端，第一轮什么都不落盘，之后每一轮都发完整历史、新开会话，永远续接不上。

@pytest.mark.parametrize("mode", ["stream", "buffered"])
def test_a_streaming_client_with_its_own_conversation_id_gets_continuation(wired, mode):
    w = wired
    kw = {"stream": True, "tools": _TOOLS if mode == "buffered" else None}

    _chat(w, [U1], **kw)

    conv = _stored(w)
    assert conv is not None, "流式第一轮没建会话记录，之后每一轮都续接不上"
    served = [i for i, u in enumerate(w.ups) if u.calls]
    assert len(served) == 1, [u.calls for u in w.ups]
    idx = served[0]
    first = w.ups[idx]
    assert conv.account_id == f"account-{idx}"
    assert json.loads(conv.gemini_conv_id) == first.triple(1)

    _chat(w, [U1, A1, U2], **kw)

    assert w.ups[1 - idx].calls == [], "第二轮没钉住"
    call = first.calls[-1]
    assert call["conv"] == json.dumps(first.triple(1))
    assert "u2" in call["prompt"] and "Human: u1" not in call["prompt"]
    assert json.loads(_stored(w).gemini_conv_id) == first.triple(2)


@pytest.mark.parametrize("mode", ["stream", "buffered"])
def test_a_streaming_request_without_a_conversation_id_stores_nothing(wired, mode):
    """流式响应里没有地方把服务端生成的 id 回给客户端：没带 conversation_id 就不建记录。"""
    w = wired
    body = {"model": "gemini-pro", "messages": [U1], "stream": True}
    if mode == "buffered":
        body["tools"] = _TOOLS
    with w.http.stream("POST", "/v1/chat/completions", json=body, headers=_AUTH) as r:
        text = "".join(r.iter_text())
    assert r.status_code == 200, text
    assert asyncio.run(w.store.list_all()) == []


def test_a_streaming_turn_answered_by_the_fallback_creates_no_record(with_fallback):
    """兜底答了的那一轮 Gemini 根本没见过：流式第一轮由兜底回答时不建记录（下一轮照常发完整历史）。"""
    from app.core.gemini_client import GenerationTimedOut

    w = with_fallback
    for u in w.ups:
        u.reject_resume = None

        def boom(*a, **k):
            raise GenerationTimedOut(120, 120.5, TimeoutError())

        u._answer = boom
    _chat(w, [U1], stream=True)
    assert _stored(w) is None


# ---------------------------------------------------------------------------
# 工具 JSON 畸形 → 重新生成：客户端拿到的是哪一版，续接点就记哪一版
# ---------------------------------------------------------------------------
# 重新生成也发在同一个续接点上（谷歌那边是第一次回答的兄弟分支）。过去续接点只在第一次回答之后记，
# 客户端拿到重新生成的合法 tool_calls 时，存储里仍是被丢掉的那个畸形回答的 [cid, rid, rcid]：下一轮
# 从那条分支接着走，Gemini 看到的上一轮与客户端看到的不一致。

MALFORMED_TOOL_JSON = '{"tool_calls": [{"name": "get_weather", "arguments": {"city": "Par'
VALID_TOOL_JSON = '{"tool_calls": [{"name": "get_weather", "arguments": {"city": "Paris"}}]}'


def _script_answers(upstream, texts):
    """让这个上游接下来的回答依次是 texts（会话元数据照常每次一个新的 rid / rcid）。"""
    queue = list(texts)
    original = upstream._answer

    def scripted(*a, **k):
        result = original(*a, **k)
        return {**result, "text": queue.pop(0)} if queue else result

    upstream._answer = scripted


def _tool_names(body, mode):
    if mode == "nonstream":
        calls = body["choices"][0]["message"].get("tool_calls") or []
        return [c["function"]["name"] for c in calls]
    return ["get_weather"] if '"tool_calls"' in body and "get_weather" in body else []


@pytest.mark.parametrize("mode", ["nonstream", "buffered"])
def test_a_regenerated_tool_answer_moves_the_resume_point(wired, mode):
    w = wired
    first, idx = _first_turn(w)
    _script_answers(first, [MALFORMED_TOOL_JSON, VALID_TOOL_JSON])

    body = _chat(w, [U1, A1, U2], stream=mode != "nonstream", tools=_TOOLS)

    assert _tool_names(body, mode) == ["get_weather"], body
    regen = first.calls[-1]
    assert regen["conv"] == json.dumps(first.triple(1)), "前提：重新生成发在同一个续接点上"
    conv = _stored(w)
    assert json.loads(conv.gemini_conv_id) == first.triple(3), \
        "客户端拿到的是重新生成的那一版，续接点却还记着被丢掉的畸形回答"
    assert conv.account_id == f"account-{idx}"


@pytest.mark.parametrize("mode", ["nonstream", "buffered"])
def test_a_regenerated_tool_answer_that_is_not_used_keeps_the_first_resume_point(wired, mode):
    """重新生成仍然畸形：客户端拿到的是第一次回答的降级提示，续接点照旧记第一次回答。"""
    w = wired
    first, idx = _first_turn(w)
    _script_answers(first, [MALFORMED_TOOL_JSON, MALFORMED_TOOL_JSON])

    _chat(w, [U1, A1, U2], stream=mode != "nonstream", tools=_TOOLS)

    assert len(first.calls) == 3, "前提：本该重新生成一次"
    assert json.loads(_stored(w).gemini_conv_id) == first.triple(2)


# ---------------------------------------------------------------------------
# 新一轮不是「一条用户消息」：不续接，改发完整历史
# ---------------------------------------------------------------------------
# 续接只发上一轮回答之后新来的那一条用户消息。agent 的工具循环里，第二轮是 [问题, assistant(tool_calls),
# tool(结果)]：过去续接分支只取最后一条 role=user（= 原来的问题），工具结果整段丢了，Gemini 在同一个
# 会话里又收到一遍同样的问题。上一轮回答之后不止一条、或带工具结果的，一律发完整历史。

TOOL_CALL = {"role": "assistant", "content": None, "tool_calls": [{
    "id": "call_1", "type": "function",
    "function": {"name": "get_weather", "arguments": "{\"city\": \"Paris\"}"},
}]}
TOOL_RESULT = {"role": "tool", "tool_call_id": "call_1", "content": "sunny, 25C"}


@pytest.mark.parametrize("mode", ["nonstream", "stream", "buffered"])
def test_a_turn_carrying_tool_results_resends_the_full_history(wired, mode, caplog):
    import logging

    w = wired
    first, idx = _first_turn(w)
    marks = _call_marks(w)

    kw = {"stream": mode != "nonstream", "tools": _TOOLS if mode == "buffered" else None}
    with caplog.at_level(logging.INFO, logger="app.routers.openai"):
        _chat(w, [U1, TOOL_CALL, TOOL_RESULT], **kw)

    new_calls = _calls_since(w, marks)
    assert len(new_calls) == 1, new_calls
    call = new_calls[0]
    assert call["conv"] == "", "接不上（只发一句会丢工具结果）就新开会话，不带续接参数"
    assert "sunny, 25C" in call["prompt"], "工具结果被丢了"
    assert "Human: u1" in call["prompt"] and "get_weather" in call["prompt"]
    assert any("not a single user message" in r.getMessage() for r in caplog.records), \
        "日志要说清为什么没续接"
    # 成功后照常记下新会话，下一轮（普通的一条用户消息）恢复续接
    conv = _stored(w)
    served = w.ups[int(conv.account_id[-1])]
    assert json.loads(conv.gemini_conv_id) == served.triple(served._turn)


@pytest.mark.parametrize("messages", [
    [U1, TOOL_CALL, TOOL_RESULT, U2],                                        # 工具结果后又追问
    [U1, A1, {"role": "user", "content": "u2a"}, {"role": "user", "content": "u2b"}],  # 连发两条
    [U1, A1, U2, {"role": "assistant", "content": "prefill"}],              # 以 assistant 收尾
    [U1, A1, {"role": "user", "content": [                                   # Anthropic 式工具结果块
        {"type": "tool_result", "tool_use_id": "t1", "content": "sunny, 25C"},
        {"type": "text", "text": "u2"},
    ]}],
], ids=["tool-result-then-question", "two-user-messages", "ends-with-assistant",
        "tool-result-block"])
def test_anything_but_one_new_user_message_resends_the_full_history(wired, messages):
    from app.utils.prompt import build_prompt_from_messages

    w = wired
    _first_turn(w)
    marks = _call_marks(w)

    _chat(w, messages)

    new_calls = _calls_since(w, marks)
    assert [(c["prompt"], c["conv"]) for c in new_calls] == \
        [(build_prompt_from_messages(messages), "")]


@pytest.mark.parametrize("messages", [
    [U1, A1, U2],
    [{"role": "system", "content": "be brief"}, U1, A1, U2],
    [{"role": "system", "content": "be brief"}, U2],      # 只发最新一条、靠服务端记上下文的客户端
    [U2],
], ids=["plain", "with-system", "latest-only-with-system", "latest-only"])
def test_one_new_user_message_still_resumes(wired, messages):
    w = wired
    first, idx = _first_turn(w)

    _chat(w, messages)

    call = first.calls[-1]
    assert (call["prompt"], call["conv"]) == ("u2", json.dumps(first.triple(1)))
    assert w.ups[1 - idx].calls == []


# ---------------------------------------------------------------------------
# 第三方兜底答了这一轮：续接点作废
# ---------------------------------------------------------------------------
# 续接真正生效之后，存储里的 [cid, rid, rcid] 必须与客户端的历史同步。某一轮由第三方兜底
# 回答（超时现在也会走兜底）时，Gemini 那边的会话根本没见过这一轮的问答；下一轮若还从旧的
# 续接点只发最后一句，这一轮就静默丢了。所以兜底一旦答了，就清掉续接点，下一轮发完整历史。
# 报错（没有兜底）不清：客户端多半原样重试这一轮，从原来的续接点接着走正好。

U3 = {"role": "user", "content": "u3"}
FB_ANSWER = "fallback answer"
TURN3 = [U1, A1, U2, {"role": "assistant", "content": FB_ANSWER}, U3]
TURN3_HISTORY = f"Human: u1\n\nAssistant: a1\n\nHuman: u2\n\nAssistant: {FB_ANSWER}\n\nHuman: u3"


def _fallback_data():
    return {"id": "chatcmpl-fb", "object": "chat.completion", "created": 0, "model": "tp",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": FB_ANSWER}}]}


@pytest.fixture
def with_fallback(wired, monkeypatch):
    from app.routers import openai as oai

    async def fake_fallback(request, req, messages_raw, exclude_model=""):
        return _fallback_data()

    async def fake_fallback_stream(request, req, messages_raw, exclude_model, completion_id, model_name):
        yield 'data: {"choices": [{"delta": {"content": "fallback answer"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(oai, "_fallback_result", fake_fallback)
    monkeypatch.setattr(oai, "_maybe_fallback_stream", fake_fallback_stream)
    return wired


def _fail_resume_with(upstream, exc):
    upstream.reject_resume = exc


def _call_marks(w):
    return [len(u.calls) for u in w.ups]


def _calls_since(w, marks):
    return [c for u, m in zip(w.ups, marks) for c in u.calls[m:]]


@pytest.mark.parametrize("mode", ["nonstream", "stream", "buffered"])
def test_a_turn_answered_by_the_fallback_invalidates_the_resume_point(with_fallback, mode):
    from app.core.gemini_client import GenerationTimedOut

    w = with_fallback
    first, idx = _first_turn(w)
    _fail_resume_with(first, GenerationTimedOut(120, 120.5, TimeoutError()))

    kw = {"stream": mode != "nonstream", "tools": _TOOLS if mode == "buffered" else None}
    body = _chat(w, [U1, A1, U2], **kw)
    assert FB_ANSWER in json.dumps(body), body

    conv = _stored(w)
    assert (conv.gemini_conv_id, conv.account_id) == ("", ""), "兜底答了这一轮，续接点还留着"

    # 下一轮：发完整历史（含兜底那一轮的问答）、不带续接参数
    first.reject_resume = None
    marks = _call_marks(w)
    _chat(w, TURN3)
    new_calls = _calls_since(w, marks)
    assert [(c["prompt"], c["conv"]) for c in new_calls] == [(TURN3_HISTORY, "")]


def test_an_empty_gemini_answer_replaced_by_the_fallback_invalidates_the_resume_point(with_fallback):
    w = with_fallback
    first, idx = _first_turn(w)

    async def empty(prompt, model, conversation_id="", attachments=None, gem_id=None,
                    extended_thinking=False):
        first.calls.append({"prompt": prompt, "conv": conversation_id})
        return {"text": "", "images": [], "thoughts": "",
                "conversation_id": json.dumps(first.triple(9))}

    first.generate = empty
    _chat(w, [U1, A1, U2])
    assert (_stored(w).gemini_conv_id, _stored(w).account_id) == ("", "")


def test_an_error_without_fallback_keeps_the_resume_point(wired):
    """没有兜底、回了错误：续接点保留（客户端重试同一轮时从原来的续接点接着走）。"""
    from app.core.gemini_client import GenerationTimedOut

    w = wired
    first, idx = _first_turn(w)
    before = _stored(w).gemini_conv_id
    first.reject_resume = GenerationTimedOut(120, 120.5, TimeoutError())

    r = w.http.post("/v1/chat/completions", json={
        "model": "gemini-pro", "messages": [U1, A1, U2], "conversation_id": "t1",
    }, headers=_AUTH)
    assert r.status_code == 504, r.text
    assert _stored(w).gemini_conv_id == before
    assert _stored(w).account_id == f"account-{idx}"


@pytest.mark.parametrize("mode", ["nonstream", "stream", "buffered"])
def test_a_gemini_answer_without_a_resume_point_drops_the_stale_one(wired, mode):
    """Gemini 答了这一轮、响应里却没有可用的续接元数据（比如谷歌改了 id 格式）：旧的续接点已经
    落后于这一轮，留着它下一轮就会从更早的地方只发最后一句。清掉，下一轮发完整历史。"""
    w = wired
    first, idx = _first_turn(w)
    original = first._answer

    def no_metadata(*a, **k):
        result = original(*a, **k)
        return {**result, "conversation_id": ""}

    first._answer = no_metadata
    kw = {"stream": mode != "nonstream", "tools": _TOOLS if mode == "buffered" else None}
    _chat(w, [U1, A1, U2], **kw)
    assert first.calls[-1]["conv"], "前提不成立：第二轮本该续接"
    assert (_stored(w).gemini_conv_id, _stored(w).account_id) == ("", "")

    first._answer = original
    marks = _call_marks(w)
    _chat(w, [U1, A1, U2, {"role": "assistant", "content": "a2"}, U3])
    new_calls = _calls_since(w, marks)
    assert [c["conv"] for c in new_calls] == [""]
    assert new_calls[0]["prompt"].startswith("Human: u1")

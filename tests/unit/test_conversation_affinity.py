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
    call = other.calls[-1]
    assert call["prompt"] == FULL_HISTORY, "接不上就必须发完整历史，不能只发最后一句"
    assert call["conv"] == "", "新开会话不能带续接参数"
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


def test_old_file_without_an_account_resends_the_full_history_then_records_one(wired):
    w = wired
    a = w.ups[0]
    _seed(w, f"['{a.triple(1)[0]}', '{a.triple(1)[1]}']", account_id="")

    _chat(w, [U1, A1, U2])

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
    call = other.calls[-1]
    assert (call["prompt"], call["conv"]) == (FULL_HISTORY, "")
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

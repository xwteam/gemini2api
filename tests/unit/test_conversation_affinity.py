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

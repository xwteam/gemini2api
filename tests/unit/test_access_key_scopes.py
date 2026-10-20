"""访问密钥的两类范围限制真的生效：

- 账号绑定：本次请求只能用 bound_account_ids 里的账号；绑定的账号全不可用时 fail-closed，
  绝不静默回退到池里其他账号（那等于绕过绑定）。
- 模型限制：allowed_models 非空时，不在列表里的模型被拒；列表端点也要跟着收窄。

没有访问密钥（env API_KEY 直连）时，这两条都必须是零行为变化。
"""

import asyncio
import time

import pytest

import app.core.access_key_store as store_module
from app.core.access_context import set_current_access_key
from app.core.access_key_store import AccessKeyStore
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.gemini_client import BOUND_ACCOUNT_UNAVAILABLE_MSG, classify_error

_AUTH = {"Authorization": "Bearer sk-test-key"}


class _FakeClient:
    def __init__(self, healthy: bool = True):
        self._healthy = healthy
        self._heal_lock = asyncio.Lock()
        self.reload_calls = 0

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def reload_cookies(self, psid=None, psidts=None) -> dict:
        self.reload_calls += 1
        return {"success": False, "error": "nope"}

    async def check_account(self) -> dict:
        return {"valid": self._healthy}

    async def generate(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False) -> dict:
        return {"text": "ok", "images": [], "conversation_id": "c1"}

    async def generate_stream(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                              extended_thinking=False):
        yield {"type": "final", "text": "ok", "images": [], "conversation_id": "c1"}


def _make_pool(clients, *, max_concurrent=8, acquire_timeout=1.0) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"psid-{i}", psidts="", label=f"account-{i}",
                status=AccountStatus.ACTIVE, client=c)
        for i, c in enumerate(clients)
    ]
    pool._max_concurrent = max_concurrent
    pool._acquire_timeout = acquire_timeout
    return pool


@pytest.fixture(autouse=True)
def _clear_access_key_context():
    """每个用例前后都把请求上下文清干净，避免 contextvar 串到别的用例。"""
    set_current_access_key(None)
    yield
    set_current_access_key(None)


def _isolate(monkeypatch, tmp_path) -> AccessKeyStore:
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    return fresh


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ------------------------------------------------------------- 账号绑定（池级）

def test_acquire_without_binding_can_pick_any_account():
    """零回归：没有访问密钥时 acquire 的选号范围不受任何约束。"""
    pool = _make_pool([_FakeClient(), _FakeClient()])
    picked = {asyncio.run(pool.acquire()).id for _ in range(1)}
    assert picked <= {"account-0", "account-1"}


def test_acquire_only_picks_bound_account(tmp_path, monkeypatch):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("bound", bound_account_ids=["account-1"])
    _, entry = store.validate_and_consume(key.key)
    set_current_access_key(entry)

    pool = _make_pool([_FakeClient(), _FakeClient(), _FakeClient()])

    async def _run():
        picked = []
        for _ in range(6):
            account = await pool.acquire()
            picked.append(account.id)
            await pool.release(account, success=True)
        return picked

    picked = asyncio.run(_run())
    assert set(picked) == {"account-1"}, f"绑定 account-1 却选到了 {set(picked)}"


def test_binding_still_rotates_within_the_bound_set(tmp_path, monkeypatch):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("two", bound_account_ids=["account-0", "account-2"])
    _, entry = store.validate_and_consume(key.key)
    set_current_access_key(entry)

    pool = _make_pool([_FakeClient(), _FakeClient(), _FakeClient()])

    async def _run():
        picked = []
        for _ in range(6):
            account = await pool.acquire()
            picked.append(account.id)
            await pool.release(account, success=True)
        return picked

    picked = asyncio.run(_run())
    assert set(picked) == {"account-0", "account-2"}, "绑定集内应轮换，且绝不外溢"


def test_bound_account_unavailable_fails_closed_instead_of_falling_back(tmp_path, monkeypatch):
    """绑定的账号不健康、而池里另有健康账号：必须快速、准确地报错，绝不悄悄用别的账号。

    「快速 + 准确文案」不是锦上添花：如果 acquire 的 "有没有可用账号" 谓词忘了带上
    绑定白名单，它会把池里**别人的**健康账号算成"只是忙"，于是每个请求都白等满
    acquire_timeout 再报一条槽位占用为 0 的假 "All accounts busy"（529，诱发无限重试）。
    这正是 issue #11 那条谓词不一致的 bug 在绑定场景下的翻版，必须钉住。
    """
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("b", bound_account_ids=["account-0"])
    _, entry = store.validate_and_consume(key.key)
    set_current_access_key(entry)

    pool = _make_pool([_FakeClient(healthy=False), _FakeClient(healthy=True)], acquire_timeout=5.0)

    t0 = time.monotonic()
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(pool.acquire())
    elapsed = time.monotonic() - t0
    msg = str(ei.value)

    assert elapsed < 1.0, f"acquire 等了 {elapsed:.2f}s，绑定账号坏了应当立即失败"
    assert "All accounts busy" not in msg, f"报了一条假的池打满: {msg}"
    assert "account-1" not in msg
    status, err_type, _ = classify_error(RuntimeError(msg))
    assert (status, err_type) != (529, "overloaded_error"), "绑定账号坏了不该诱导客户端无限重试"
    # 健康的那个账号从头到尾没被占用过 —— 证明没有发生回退
    assert pool.accounts[1].active_requests == 0


def test_bound_account_not_in_pool_fails_closed(tmp_path, monkeypatch):
    """绑定的账号被删了：立即报可识别的错误（而不是回退到剩下的账号）。"""
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("ghost", bound_account_ids=["account-99"])
    _, entry = store.validate_and_consume(key.key)
    set_current_access_key(entry)

    pool = _make_pool([_FakeClient(), _FakeClient()])
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(pool.acquire())
    assert BOUND_ACCOUNT_UNAVAILABLE_MSG in str(ei.value)
    assert all(a.active_requests == 0 for a in pool.accounts)


def test_bound_account_unavailable_maps_to_503_not_529():
    """529 的语义是"过载了稍后重试"，但绑定账号坏了再等也不会好 —— 必须 503。"""
    status, err_type, retry_after = classify_error(
        RuntimeError(f"{BOUND_ACCOUNT_UNAVAILABLE_MSG}: ['account-0']")
    )
    assert (status, err_type, retry_after) == (503, "api_error", None)


def test_bound_account_busy_still_queues_instead_of_failing_fast(tmp_path, monkeypatch):
    """绑定账号只是满载（不是坏了）时必须排队等槽位，不能退化成立即 503。"""
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("busy", bound_account_ids=["account-0"])
    _, entry = store.validate_and_consume(key.key)
    set_current_access_key(entry)

    pool = _make_pool([_FakeClient(), _FakeClient()], max_concurrent=1, acquire_timeout=5.0)

    async def _run():
        first = await pool.acquire()
        assert first.id == "account-0"

        waiter = asyncio.create_task(pool.acquire())
        await asyncio.sleep(0.05)
        assert not waiter.done(), "绑定账号满载时应当排队，而不是立刻报错"

        await pool.release(first, success=True)
        return await asyncio.wait_for(waiter, timeout=2.0)

    second = asyncio.run(_run())
    assert second.id == "account-0"


def test_explicit_only_argument_overrides_context(tmp_path, monkeypatch):
    """显式传 only 的调用方（将来的内部任务）不该被请求上下文悄悄改写。"""
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("b", bound_account_ids=["account-0"])
    _, entry = store.validate_and_consume(key.key)
    set_current_access_key(entry)

    pool = _make_pool([_FakeClient(), _FakeClient()])
    account = asyncio.run(pool.acquire(only={"account-1"}))
    assert account.id == "account-1"


# ------------------------------------------------------------------- 模型限制

def test_model_not_in_allowed_list_is_rejected_on_every_protocol(gem_client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("only-flash", allowed_models=["gemini-flash"]).key

    cases = [
        ("POST", "/v1/chat/completions",
         {"model": "gemini-pro", "messages": [{"role": "user", "content": "hi"}]}),
        ("POST", "/v1/messages",
         {"model": "gemini-pro", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}),
        ("POST", "/v1beta/models/gemini-pro:generateContent",
         {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}),
        ("POST", "/v1/responses",
         {"model": "gemini-pro", "input": "hi"}),
    ]
    for method, path, body in cases:
        r = gem_client.request(method, path, json=body, headers=_bearer(key))
        assert r.status_code == 403, f"{path} 没拦住不被允许的模型: {r.status_code}"
        assert r.json()["detail"]["error"]["type"] == "access_key_model_denied"


def test_allowed_model_passes_the_gate(gem_client, monkeypatch, tmp_path):
    """允许的模型必须过闸 —— 否则"全拒"也能让上面那条用例变绿。"""
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("only-flash", allowed_models=["gemini-flash"]).key

    import app.routers.openai as oai
    pool = _make_pool([_FakeClient()])
    monkeypatch.setattr(oai, "gemini_client", pool)

    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_bearer(key))
    assert r.status_code == 200, r.text


def test_no_model_restriction_lets_everything_through(gem_client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("unrestricted").key

    import app.routers.openai as oai
    pool = _make_pool([_FakeClient()])
    monkeypatch.setattr(oai, "gemini_client", pool)

    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-pro", "stream": False,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_bearer(key))
    assert r.status_code == 200, r.text


def test_model_lists_are_narrowed_for_the_access_key(gem_client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("only-flash", allowed_models=["gemini-flash"]).key

    data = gem_client.get("/v1/models", headers=_bearer(key)).json()["data"]
    assert [m["id"] for m in data] == ["gemini-flash"]

    claude = gem_client.get("/claude/v1/models", headers=_bearer(key)).json()["data"]
    assert [m["id"] for m in claude] == ["gemini-flash"]

    # 被挡掉的模型在详情端点也必须 404，和列表保持一致
    assert gem_client.get("/claude/v1/models/gemini-pro", headers=_bearer(key)).status_code == 404
    assert gem_client.get("/claude/v1/models/gemini-flash", headers=_bearer(key)).status_code == 200


def test_model_lists_are_untouched_for_env_api_key(gem_client, monkeypatch, tmp_path):
    """零回归：env key 看到的模型列表不受任何访问密钥影响。"""
    store = _isolate(monkeypatch, tmp_path)
    store.create("only-flash", allowed_models=["gemini-flash"])
    ids = [m["id"] for m in gem_client.get("/v1/models", headers=_AUTH).json()["data"]]
    assert len(ids) > 1
    assert "gemini-pro" in ids


def test_model_gate_also_covers_images_tokens_and_deepresearch(gem_client, monkeypatch, tmp_path):
    """除了四个对话入口，生图/算 token/深度研究这几条也会真的跑账号池，
    漏掉任何一条，模型限制就有个绕过口。"""
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("only-flash", allowed_models=["gemini-flash"]).key

    import app.routers.research as research
    monkeypatch.setattr(research, "gemini_client", _make_pool([_FakeClient()]))

    r = gem_client.post("/v1/images/generations",
                        json={"model": "gemini-pro", "prompt": "a cat"}, headers=_bearer(key))
    assert r.status_code == 403, f"/v1/images/generations 没过模型闸: {r.status_code}"

    r = gem_client.post("/v1/messages/count_tokens", json={
        "model": "gemini-pro", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_bearer(key))
    assert r.status_code == 403, f"count_tokens 没过模型闸: {r.status_code}"

    r = gem_client.post("/gemini/v1beta/deepresearch",
                        json={"model": "gemini-pro", "query": "q"}, headers=_bearer(key))
    assert r.status_code == 403, f"deepresearch 没过模型闸: {r.status_code}"

    # 允许的模型必须能过闸（否则"全拒"也能让上面三条变绿）
    r = gem_client.post("/v1/messages/count_tokens", json={
        "model": "gemini-flash", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=_bearer(key))
    assert r.status_code == 200, r.text

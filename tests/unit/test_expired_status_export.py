"""对外如实报 expired（v1.6.44 保活修复的 A 部分，账号池 / admin 侧）。

线上 v1.6.43：两个账号的谷歌会话死了 37 小时，GET /admin/status 却对三个账号都报
`"status": "active"`、`consecutive_failures: 0`、`last_error: ""`（只有 is_healthy 是 false）。
浏览器保活插件 v1.2.3 每 60 秒查一次 /admin/status，**只在 status == "expired" 时**才去刷新
浏览器标签页、读 cookie、推给中转站 —— 于是那两个账号它一直看不见，一次都没推过。

要钉死的：
- 派生口径：ACTIVE + client 不健康 + auth_expired → 对外 "expired"，last_error 为空时补上原因；
  client 恢复健康后自动回到 "active"；**非**「打回登录页」原因的不健康仍报 active；
  池内部状态机一个字都不改（_find_available / 自愈 / 恢复路径照旧按 a.status 走）。
- PUT cookies / POST reload-cookies 成功后，池内该账号当场 ACTIVE + consecutive_failures=0（持锁），
  不再依赖调用方随后调 /check（面板「更新 Cookie」和脚本从来不调）。
"""

import asyncio

import pytest

from app.core import account_pool as ap
from app.core.account_pool import Account, AccountPool, AccountStatus

_AUTH = {"Authorization": "Bearer sk-test-key"}
SESSION_EXPIRED = "Google session expired (login redirect)"


class _Client:
    """池与 admin 路由会碰到的最小 client 面：健康位、auth_expired、reload、检测。"""

    def __init__(self, healthy=True, auth_expired=False, reload_ok=True):
        self._healthy = healthy
        self._auth_expired = auth_expired
        self.reload_ok = reload_ok
        self.reload_calls: list[tuple] = []
        self.check_calls = 0
        self._heal_lock = asyncio.Lock()

    @property
    def is_healthy(self):
        return self._healthy

    @property
    def auth_expired(self):
        return self._auth_expired

    async def reload_cookies(self, psid=None, psidts=None):
        self.reload_calls.append((psid, psidts))
        if self.reload_ok:
            self._healthy = True
            self._auth_expired = False
            return {"success": True}
        return {"success": False, "error": "Cookie expired - redirected to Google login page"}

    async def check_account(self):
        self.check_calls += 1
        return {"valid": self._healthy}


class _LegacyClient:
    """只有 is_healthy 的替身（既有测试里的形态）：没有 auth_expired 也不能把状态导出搞崩。"""

    def __init__(self, healthy):
        self._healthy = healthy

    @property
    def is_healthy(self):
        return self._healthy


def _pool(*accounts: Account) -> AccountPool:
    pool = AccountPool.__new__(AccountPool)
    pool._accounts = list(accounts)
    pool._cond = asyncio.Condition()
    pool._strategy = type("S", (), {"value": "round-robin"})()
    pool._max_concurrent = 3
    return pool


def _acc(id="account-0", **kw) -> Account:
    base = dict(id=id, psid=f"PSID-{id}", psidts="t", label=id)
    base.update(kw)
    return Account(**base)


def _info(account: Account) -> dict:
    return _pool(account).get_status()["accounts"][0]


# --------------------------------------------------------------------------
# 派生的对外 status
# --------------------------------------------------------------------------

def test_dead_session_on_an_active_account_is_reported_expired():
    a = _acc(client=_Client(healthy=False, auth_expired=True))

    info = _info(a)

    assert info["status"] == "expired"
    assert info["is_healthy"] is False


def test_the_derived_status_does_not_touch_the_pools_state_machine():
    a = _acc(client=_Client(healthy=False, auth_expired=True), consecutive_failures=0)
    pool = _pool(a)

    pool.get_status()

    assert a.status is AccountStatus.ACTIVE, "对外口径不许回写池内部状态"
    assert a.consecutive_failures == 0
    assert a.last_error == ""
    # 自愈路径（ACTIVE 但不健康）照旧够得着它
    assert pool._unhealthy_active() == [a]


def test_recovered_client_goes_back_to_active():
    client = _Client(healthy=False, auth_expired=True)
    a = _acc(client=client)
    assert _info(a)["status"] == "expired"

    client._healthy = True
    client._auth_expired = False

    info = _info(a)
    assert info["status"] == "active"
    assert info["last_error"] == "", "恢复之后不该还挂着派生出来的原因"


def test_healthy_client_with_a_stale_auth_flag_is_still_active():
    """刷新循环的宽限期（还没连败 3 次）：会话可能刚被打回、但 client 还算健康 —— 不报 expired。"""
    assert _info(_acc(client=_Client(healthy=True, auth_expired=True)))["status"] == "active"


def test_unhealthy_for_other_reasons_is_still_active():
    """网络抖动 / 5xx 造成的不健康不是「会话失效」，不能叫插件去刷新浏览器。"""
    info = _info(_acc(client=_Client(healthy=False, auth_expired=False)))

    assert info["status"] == "active"
    assert info["is_healthy"] is False
    assert info["last_error"] == ""


def test_client_without_an_auth_flag_is_treated_as_not_expired():
    info = _info(_acc(client=_LegacyClient(healthy=False)))
    assert info["status"] == "active"


def test_account_without_a_client_is_reported_as_is():
    assert _info(_acc(client=None))["status"] == "active"
    assert _info(_acc(client=None, status=AccountStatus.EXPIRED))["status"] == "expired"


def test_the_reason_is_filled_into_an_empty_last_error():
    info = _info(_acc(client=_Client(healthy=False, auth_expired=True)))

    assert info["last_error"] == SESSION_EXPIRED
    assert info["last_error_at"] is None


def test_an_existing_last_error_is_kept():
    a = _acc(client=_Client(healthy=False, auth_expired=True), last_error="HTTPStatusError (HTTP 401)")
    assert _info(a)["last_error"] == "HTTPStatusError (HTTP 401)"


def test_an_internally_expired_account_also_gets_the_reason():
    """启动就没起来（_init_account_client 标 EXPIRED）的账号 last_error 是空的：同样补上原因。"""
    a = _acc(client=_Client(healthy=False, auth_expired=True), status=AccountStatus.EXPIRED)

    info = _info(a)

    assert info["status"] == "expired"
    assert info["last_error"] == SESSION_EXPIRED


def test_disabled_account_is_not_relabelled():
    a = _acc(client=_Client(healthy=False, auth_expired=True), status=AccountStatus.DISABLED)

    info = _info(a)

    assert info["status"] == "disabled"
    assert info["last_error"] == ""


def test_top_level_active_count_matches_the_exported_statuses():
    pool = _pool(
        _acc("a", client=_Client(healthy=True)),
        _acc("b", client=_Client(healthy=False, auth_expired=True)),
        _acc("c", client=_Client(healthy=False, auth_expired=False)),
        _acc("d", client=_Client(healthy=False, auth_expired=True), status=AccountStatus.EXPIRED),
    )

    status = pool.get_status()

    assert [i["status"] for i in status["accounts"]] == ["active", "expired", "active", "expired"]
    assert status["total"] == 4
    assert status["active"] == 2


def test_admin_status_endpoint_reports_the_dead_session_as_expired(gem_client, monkeypatch):
    """端到端：插件读的就是这个接口。"""
    live = _acc("account-1", client=_Client(healthy=True))
    dead = _acc("account-2", client=_Client(healthy=False, auth_expired=True),
                psid="g.a000-a-long-secret-psid-value")
    monkeypatch.setattr(ap.account_pool, "_accounts", [live, dead])

    body = gem_client.get("/admin/status", headers=_AUTH).json()

    by_id = {a["id"]: a for a in body["accounts"]}
    assert by_id["account-1"]["status"] == "active"
    assert by_id["account-2"]["status"] == "expired"
    assert by_id["account-2"]["is_healthy"] is False
    assert by_id["account-2"]["last_error"] == SESSION_EXPIRED
    assert "secret" not in by_id["account-2"]["psid"], "psid 照旧脱敏"
    assert body["active"] == 1


# --------------------------------------------------------------------------
# 池方法：reload 成功后当场回到 ACTIVE
# --------------------------------------------------------------------------

def test_mark_cookies_reloaded_restores_active_and_resets_failures():
    a = _acc(client=_Client(), status=AccountStatus.EXPIRED, consecutive_failures=3,
             consecutive_empty=2, error_count=7, last_error="HTTPStatusError (HTTP 401)")
    pool = _pool(a)

    asyncio.run(pool.mark_cookies_reloaded(a))

    assert a.status is AccountStatus.ACTIVE
    assert a.consecutive_failures == 0
    # 与 /check 判定 valid 时一致：只动这两格
    assert a.consecutive_empty == 2
    assert a.error_count == 7
    assert a.last_error == "HTTPStatusError (HTTP 401)"


def test_mark_cookies_reloaded_holds_the_pool_lock():
    a = _acc(client=_Client(), status=AccountStatus.EXPIRED, consecutive_failures=3)
    pool = _pool(a)

    async def _run():
        await pool._cond.acquire()
        task = asyncio.create_task(pool.mark_cookies_reloaded(a))
        await asyncio.sleep(0.02)
        still_waiting = a.status is AccountStatus.EXPIRED
        pool._cond.release()
        await asyncio.wait_for(task, timeout=5)
        return still_waiting

    assert asyncio.run(_run()) is True, "必须持池锁改状态（别人持锁时得等）"
    assert a.status is AccountStatus.ACTIVE


def test_mark_cookies_reloaded_wakes_queued_acquirers():
    a = _acc(client=_Client(), status=AccountStatus.EXPIRED, consecutive_failures=3)
    pool = _pool(a)

    async def _run():
        async def _waiter():
            async with pool._cond:
                await pool._cond.wait()

        waiter = asyncio.create_task(_waiter())
        await asyncio.sleep(0.02)
        await pool.mark_cookies_reloaded(a)
        await asyncio.wait_for(waiter, timeout=5)

    asyncio.run(_run())


def test_a_reloaded_account_is_immediately_selectable():
    a = _acc(client=_Client(healthy=True), status=AccountStatus.EXPIRED, consecutive_failures=3)
    pool = _pool(a)

    async def _run():
        before = pool._find_available()
        await pool.mark_cookies_reloaded(a)
        return before, pool._find_available()

    before, after = asyncio.run(_run())
    assert before is None
    assert after is a


# --------------------------------------------------------------------------
# admin 接口：成功后当场恢复，失败不动
# --------------------------------------------------------------------------

@pytest.fixture
def singleton(monkeypatch, tmp_path):
    """真 account_pool 单例，账号换成替身；accounts.json 写到临时目录。"""
    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))

    def _install(*accounts):
        monkeypatch.setattr(ap.account_pool, "_accounts", list(accounts))
        return accounts

    return _install


def test_put_cookies_success_puts_the_account_back_without_a_check(gem_client, singleton):
    client = _Client(healthy=False, auth_expired=True, reload_ok=True)
    (a,) = singleton(_acc("account-1", client=client, status=AccountStatus.EXPIRED,
                          consecutive_failures=3))

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-NEW", "psidts": "PSIDTS-NEW"}, headers=_AUTH)

    assert r.status_code == 200
    assert a.status is AccountStatus.ACTIVE
    assert a.consecutive_failures == 0
    assert client.check_calls == 0, "不该依赖随后的 /check"


def test_put_cookies_failure_leaves_the_pool_state_alone(gem_client, singleton):
    client = _Client(healthy=False, auth_expired=True, reload_ok=False)
    (a,) = singleton(_acc("account-1", client=client, status=AccountStatus.EXPIRED,
                          consecutive_failures=3))

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-BAD", "psidts": "PSIDTS-BAD"}, headers=_AUTH)

    assert r.status_code == 503
    assert a.status is AccountStatus.EXPIRED
    assert a.consecutive_failures == 3


def test_post_reload_cookies_success_puts_the_account_back(gem_client, singleton):
    client = _Client(healthy=False, auth_expired=True, reload_ok=True)
    (a,) = singleton(_acc("account-0", client=client, status=AccountStatus.EXPIRED,
                          consecutive_failures=3))

    r = gem_client.post("/admin/reload-cookies",
                        json={"psid": "PSID-NEW", "psidts": "PSIDTS-NEW"}, headers=_AUTH)

    assert r.status_code == 200
    assert a.status is AccountStatus.ACTIVE
    assert a.consecutive_failures == 0


def test_post_reload_cookies_from_env_puts_the_account_back(gem_client, singleton, monkeypatch):
    """单账号（.env）模式：不带请求体时从 .env 重读。"""
    monkeypatch.setenv("GEMINI_PSID", "PSID-FROM-ENV")
    monkeypatch.setenv("GEMINI_PSIDTS", "PSIDTS-FROM-ENV")
    client = _Client(healthy=False, auth_expired=True, reload_ok=True)
    (a,) = singleton(_acc("account-0", client=client, status=AccountStatus.EXPIRED,
                          consecutive_failures=3))

    r = gem_client.post("/admin/reload-cookies", headers=_AUTH)

    assert r.status_code == 200
    assert client.reload_calls == [("PSID-FROM-ENV", "PSIDTS-FROM-ENV")]
    assert a.status is AccountStatus.ACTIVE
    assert a.consecutive_failures == 0


def test_post_reload_cookies_failure_leaves_the_pool_state_alone(gem_client, singleton):
    client = _Client(healthy=False, auth_expired=True, reload_ok=False)
    (a,) = singleton(_acc("account-0", client=client, status=AccountStatus.EXPIRED,
                          consecutive_failures=3))

    r = gem_client.post("/admin/reload-cookies",
                        json={"psid": "PSID-BAD", "psidts": "PSIDTS-BAD"}, headers=_AUTH)

    assert r.status_code == 503
    assert a.status is AccountStatus.EXPIRED
    assert a.consecutive_failures == 3

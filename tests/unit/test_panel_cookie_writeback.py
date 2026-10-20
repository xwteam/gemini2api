"""面板换上的 cookie 必须回写 accounts.json，否则重启就白换了。

PUT /admin/accounts/{id}/cookies 走 client.reload_cookies()，它只改运行态 +
data/cookies/<hash>.json，从不回写 accounts.json（全仓找不到任何 `.psidts = ` 赋值点）。
而启动时的"配置值"恰恰来自 accounts.json —— 面板上刚救活的账号，下次重启又拿着
"添加账号那一刻"的旧 cookie 起来。
"""

import json

import pytest

from app.core.account_pool import Account, AccountPool, AccountStatus


@pytest.fixture
def pool(tmp_path, monkeypatch):
    from app.core import account_pool as ap

    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))
    p = AccountPool()
    p._accounts = [
        Account(id="account-1", psid="PSID-1", psidts="PSIDTS-AT-SETUP", label="a1",
                status=AccountStatus.ACTIVE),
        Account(id="account-2", psid="PSID-2", psidts="PSIDTS-2", label="a2",
                status=AccountStatus.ACTIVE),
    ]
    return p, tmp_path / "accounts.json"


def _saved(path) -> dict:
    return {a["id"]: a for a in json.loads(path.read_text(encoding="utf-8"))["accounts"]}


def test_new_cookies_land_in_accounts_file(pool):
    p, path = pool

    assert p.persist_account_cookies("account-1", "PSID-1", "PSIDTS-FROM-PANEL") is True

    rows = _saved(path)
    assert rows["account-1"]["psidts"] == "PSIDTS-FROM-PANEL"
    assert rows["account-1"]["psid"] == "PSID-1"
    assert rows["account-2"]["psidts"] == "PSIDTS-2", "别的账号一个字都不能动"


def test_values_are_cleaned_like_add_account(pool):
    """面板粘贴来的值常带引号/分号，清洗口径必须与 add_account / reload_cookies 逐字一致。"""
    p, path = pool

    p.persist_account_cookies("account-1", ' "PSID-NEW" ', " 'PSIDTS-NEW' ")

    rows = _saved(path)
    assert rows["account-1"]["psid"] == "PSID-NEW"
    assert rows["account-1"]["psidts"] == "PSIDTS-NEW"


def test_empty_psidts_is_persisted_as_empty(pool):
    """只给 PSID（PSIDTS 留空）是合法用法：不能把旧的 psidts 留在文件里。"""
    p, path = pool

    p.persist_account_cookies("account-1", "PSID-1", "")

    assert _saved(path)["account-1"]["psidts"] == ""


def test_blank_psid_does_not_wipe_the_credential(pool):
    p, path = pool

    p.persist_account_cookies("account-1", "", "PSIDTS-NEW")

    rows = _saved(path)
    assert rows["account-1"]["psid"] == "PSID-1"
    assert rows["account-1"]["psidts"] == "PSIDTS-NEW"


def test_unknown_account_is_a_no_op(pool):
    p, path = pool

    assert p.persist_account_cookies("account-404", "x", "y") is False
    assert not path.exists(), "不认识的账号不该触发落盘"


def test_status_fields_are_untouched(pool):
    """只碰凭据字段：账号状态/计数器是账号池的红线，这条路径一律不许动。"""
    p, _path = pool
    a = p._accounts[0]
    a.consecutive_failures = 2
    a.status = AccountStatus.EXPIRED

    p.persist_account_cookies("account-1", "PSID-1", "PSIDTS-NEW")

    assert a.consecutive_failures == 2
    assert a.status is AccountStatus.EXPIRED


def test_admin_endpoint_writes_back_after_a_successful_reload(gem_client, monkeypatch):
    """端到端：面板更新 cookie 成功后必须调回写。"""
    import app.routers.admin as admin

    calls = []

    class _Client:
        async def reload_cookies(self, psid=None, psidts=None):
            return {"success": True}

    acc = Account(id="account-1", psid="PSID-1", psidts="PSIDTS-OLD", label="a1")
    acc.client = _Client()

    monkeypatch.setattr(type(admin.account_pool), "accounts",
                        property(lambda self: [acc]), raising=False)
    monkeypatch.setattr(admin.account_pool, "persist_account_cookies",
                        lambda *a: calls.append(a) or True)

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-NEW", "psidts": "PSIDTS-NEW"},
                       headers={"Authorization": "Bearer sk-test-key"})

    assert r.status_code == 200
    assert calls == [("account-1", "PSID-NEW", "PSIDTS-NEW")]


def test_admin_endpoint_does_not_write_back_on_failure(gem_client, monkeypatch):
    """reload 失败时绝不能把一份换不上的 cookie 写进 accounts.json。"""
    import app.routers.admin as admin

    calls = []

    class _Client:
        async def reload_cookies(self, psid=None, psidts=None):
            return {"success": False, "error": "SNlM0e token not found"}

    acc = Account(id="account-1", psid="PSID-1", psidts="PSIDTS-OLD", label="a1")
    acc.client = _Client()

    monkeypatch.setattr(type(admin.account_pool), "accounts",
                        property(lambda self: [acc]), raising=False)
    monkeypatch.setattr(admin.account_pool, "persist_account_cookies",
                        lambda *a: calls.append(a) or True)

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "BAD", "psidts": "BAD"},
                       headers={"Authorization": "Bearer sk-test-key"})

    assert r.status_code == 503
    assert calls == []

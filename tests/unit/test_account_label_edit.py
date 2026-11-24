"""账号标签在线修改（v1.6.55 规格 C2 / B2，思路来自外部 PR #13）。

PATCH /admin/accounts/{account_id} {label}：去首尾空白后 1～64 个字符、不含控制字符，否则 400
invalid_request_error；账号不存在 404 not_found；成功原子写回 accounts.json，/admin/status、/admin/accounts
立即反映。只改标签：凭据、状态、计数、保活方式一概不碰。
"""

import json

import pytest

from app.core import account_pool as ap
from app.core import keepalive_modes as km
from app.core.account_pool import Account, AccountPool, AccountStatus

AUTH = {"Authorization": "Bearer sk-test-key"}


class _Client:
    is_healthy = True
    keepalive_mode = "browser"


@pytest.fixture
def two_accounts(monkeypatch, tmp_path):
    path = tmp_path / "accounts.json"
    monkeypatch.setattr(ap.settings, "accounts_file", str(path))
    a1 = Account(id="account-1", psid="PSID-ONE", psidts="TS-ONE", label="old one")
    a1.client = _Client()
    a1.status = AccountStatus.EXPIRED
    a1.consecutive_failures = 2
    a1.request_count = 7
    a2 = Account(id="account-2", psid="PSID-TWO", psidts="TS-TWO", label="two")
    monkeypatch.setattr(ap.account_pool, "_accounts", [a1, a2])
    ap.account_pool._save_to_file()
    return path


NO_BODY = object()


def _patch(gem_client, account_id, body):
    return gem_client.patch(f"/admin/accounts/{account_id}", json=body, headers=AUTH)


def _saved(path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["accounts"]


def test_patch_trims_the_label_persists_it_and_touches_nothing_else(gem_client, two_accounts):
    before = _saved(two_accounts)

    r = _patch(gem_client, "account-1", {"label": "  工作号 🚀  "})

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "account": {"id": "account-1", "label": "工作号 🚀"}}
    after = _saved(two_accounts)
    assert after[0] == {**before[0], "label": "工作号 🚀"}
    assert after[1] == before[1]
    a1 = ap.account_pool.accounts[0]
    assert (a1.psid, a1.psidts, a1.status, a1.consecutive_failures, a1.request_count) == (
        "PSID-ONE", "TS-ONE", AccountStatus.EXPIRED, 2, 7)
    assert isinstance(a1.client, _Client)


def test_status_and_accounts_reflect_the_new_label_at_once(gem_client, two_accounts):
    assert _patch(gem_client, "account-2", {"label": "renamed"}).status_code == 200

    for path in ("/admin/status", "/admin/accounts"):
        labels = {a["id"]: a["label"] for a in gem_client.get(path, headers=AUTH).json()["accounts"]}
        assert labels == {"account-1": "old one", "account-2": "renamed"}, path


def test_the_new_label_survives_a_restart(gem_client, two_accounts):
    assert _patch(gem_client, "account-1", {"label": "kept"}).status_code == 200

    reloaded = AccountPool()
    reloaded._load_from_file(two_accounts)

    assert [(a.id, a.label, a.psid, a.psidts) for a in reloaded.accounts] == [
        ("account-1", "kept", "PSID-ONE", "TS-ONE"), ("account-2", "two", "PSID-TWO", "TS-TWO")]


def test_the_keepalive_mode_is_not_touched(gem_client, two_accounts):
    km.set_mode("PSID-TWO", "browser")

    assert _patch(gem_client, "account-2", {"label": "x"}).status_code == 200

    assert km.get_mode("PSID-TWO") == "browser"


@pytest.mark.parametrize("label", ["a", "x" * 64, "名" * 64, "  " + "y" * 64 + "\t"],
                         ids=["one", "64-ascii", "64-cjk", "64-after-trim"])
def test_boundary_lengths_are_accepted(gem_client, two_accounts, label):
    r = _patch(gem_client, "account-1", {"label": label})

    assert r.status_code == 200, r.text
    assert r.json()["account"]["label"] == label.strip()


@pytest.mark.parametrize("body", [
    {"label": ""},
    {"label": "   \t "},
    {"label": "x" * 65},
    {"label": "名" * 65},
    {"label": "a\x00b"},
    {"label": "a\nb"},
    {"label": "a\x1bb"},
    {"label": "a\x7fb"},
    {"label": "a\u0085b"},
    {"label": None},
    {},
    {"label": 5},
    {"label": True},
    {"label": ["x"]},
    {"label": {"x": 1}},
    NO_BODY,
], ids=["empty", "blank", "65-ascii", "65-cjk", "nul", "newline", "esc", "del", "c1-nel", "null", "missing",
        "number", "bool", "list", "object", "no-body"])
def test_invalid_labels_are_400_and_change_nothing(gem_client, two_accounts, body):
    before = two_accounts.read_bytes()

    if body is NO_BODY:
        r = gem_client.patch("/admin/accounts/account-1", headers=AUTH)
    else:
        r = _patch(gem_client, "account-1", body)

    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert two_accounts.read_bytes() == before
    assert ap.account_pool.accounts[0].label == "old one"


def test_a_lone_surrogate_is_400_not_a_failed_write(gem_client, two_accounts):
    """JSON 里的 "\\ud800" 解析成孤立代理码位：写不进 UTF-8 文件，要在校验时就拒绝。"""
    r = gem_client.patch("/admin/accounts/account-1", content='{"label": "a\\ud800b"}',
                         headers={**AUTH, "Content-Type": "application/json"})

    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert _saved(two_accounts)[0]["label"] == "old one"


def test_unknown_account_is_404(gem_client, two_accounts):
    before = two_accounts.read_bytes()

    r = _patch(gem_client, "account-9", {"label": "x"})

    assert r.status_code == 404
    assert r.json()["error"]["type"] == "not_found"
    assert two_accounts.read_bytes() == before


def test_a_failed_write_keeps_the_old_label(gem_client, two_accounts, monkeypatch):
    def _disk_full(*a, **kw):
        raise OSError("No space left on device")

    monkeypatch.setattr(ap, "atomic_write_text", _disk_full)

    r = _patch(gem_client, "account-1", {"label": "never"})

    assert r.status_code == 500
    assert ap.account_pool.accounts[0].label == "old one"
    assert _saved(two_accounts)[0]["label"] == "old one"


def test_a_write_that_cannot_encode_is_a_500_not_a_bad_label(gem_client, two_accounts):
    """写盘时的 UnicodeEncodeError 也是 ValueError：别把它当成「标签不合法」回 400。
    （v1.6.55 之前的 accounts.json 里、或别的路径塞进来的标签可能写不进 UTF-8。）"""
    ap.account_pool.accounts[1].label = "bad\ud800"
    before = two_accounts.read_bytes()

    r = _patch(gem_client, "account-1", {"label": "fine"})

    assert r.status_code == 500, r.text
    assert r.json()["error"]["type"] == "persist_error"
    assert ap.account_pool.accounts[0].label == "old one"
    assert two_accounts.read_bytes() == before


# ---------------------------------------------------------------------------
# POST /admin/accounts 的 label 与 PATCH 同一套规则（空 = 用账号 ID）
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_pool(monkeypatch, tmp_path):
    path = tmp_path / "accounts.json"
    monkeypatch.setattr(ap.settings, "accounts_file", str(path))
    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    monkeypatch.setattr(ap.account_pool, "_next_id_seq", 0)
    inits = []

    async def _init(self, account, **kw):
        inits.append(account.id)
        account.client = _Client()
        account.status = AccountStatus.ACTIVE

    monkeypatch.setattr(AccountPool, "_init_account_client", _init)
    return inits


def _post_raw(gem_client, content):
    return gem_client.post("/admin/accounts", content=content,
                           headers={**AUTH, "Content-Type": "application/json"})


@pytest.mark.parametrize("label_json", [
    '"a\\u0000b"', '"a\\nb"', '"' + "x" * 65 + '"', '"bad\\ud800"',
], ids=["nul", "newline", "65-ascii", "lone-surrogate"])
def test_post_rejects_a_label_the_edit_dialog_would_refuse(gem_client, empty_pool, label_json):
    r = _post_raw(gem_client, '{"psid": "PSID-NEW", "psidts": "t", "label": ' + label_json + '}')

    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert ap.account_pool.accounts == [] and empty_pool == [], "不合法的标签不能进池、也不该联网初始化"


@pytest.mark.parametrize("label,expected", [
    ("", "account-0"), ("   ", "account-0"), ("  work  ", "work"),
], ids=["empty", "blank", "trimmed"])
def test_post_label_is_trimmed_and_an_empty_one_falls_back_to_the_id(gem_client, empty_pool, label, expected):
    r = gem_client.post("/admin/accounts", json={"psid": "PSID-NEW", "psidts": "t", "label": label}, headers=AUTH)

    assert r.status_code == 200, r.text
    assert r.json()["account"]["label"] == expected
    assert ap.account_pool.accounts[0].label == expected


def test_after_a_rejected_post_label_patch_still_saves(gem_client, empty_pool):
    """v1.6.55 首版：POST 收下了孤立代理码位的标签 → 账号进池却写不进文件，之后改任何账号的标签都失败。"""
    assert _post_raw(gem_client, '{"psid": "PSID-BAD", "label": "bad\\ud800"}').status_code == 400
    assert gem_client.post("/admin/accounts", json={"psid": "PSID-OK"}, headers=AUTH).status_code == 200

    r = _patch(gem_client, "account-0", {"label": "fine"})

    assert r.status_code == 200, r.text
    assert ap.account_pool.accounts[0].label == "fine"

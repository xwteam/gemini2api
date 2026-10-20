"""/admin/access-keys 的 CRUD 与输入校验。"""

from datetime import datetime, timedelta, timezone

import app.core.access_key_store as store_module
from app.core.access_key_store import AccessKeyStore

_AUTH = {"Authorization": "Bearer sk-test-key"}


def _isolate(monkeypatch, tmp_path) -> AccessKeyStore:
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    return fresh


def test_issue_list_toggle_reset_delete(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)

    r = client.post("/admin/access-keys", json={"name": "张三", "request_limit": 10}, headers=_AUTH)
    assert r.status_code == 200
    issued = r.json()["key"]
    assert issued["key"].startswith("sk-")
    assert issued["name"] == "张三"
    assert issued["state"] == "pending"
    kid = issued["id"]

    listed = client.get("/admin/access-keys", headers=_AUTH).json()["keys"]
    assert [k["id"] for k in listed] == [kid]
    assert listed[0]["key"] == issued["key"], "列表必须给出明文，否则分发不出去"

    r = client.patch(f"/admin/access-keys/{kid}", json={"enabled": False}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["key"]["enabled"] is False
    assert r.json()["key"]["state"] == "disabled"

    store.consume(kid)
    assert store.get(kid).request_count == 1
    r = client.post(f"/admin/access-keys/{kid}/reset-usage", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["key"]["request_count"] == 0

    assert client.delete(f"/admin/access-keys/{kid}", headers=_AUTH).status_code == 200
    assert client.get("/admin/access-keys", headers=_AUTH).json()["keys"] == []


def test_batch_issue_names_are_suffixed(client, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = client.post("/admin/access-keys", json={"name": "team", "count": 3}, headers=_AUTH)
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert [k["name"] for k in keys] == ["team-1", "team-2", "team-3"]
    assert len({k["key"] for k in keys}) == 3, "批量签发不得给出重复密钥"


def test_count_is_capped(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    assert client.post("/admin/access-keys", json={"count": 51}, headers=_AUTH).status_code == 400
    assert client.post("/admin/access-keys", json={"count": 0}, headers=_AUTH).status_code == 400
    assert store.list_keys() == []


def test_validity_fields_are_mutually_exclusive(client, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = client.post("/admin/access-keys", json={
        "name": "x", "duration_days": 3,
        "expires_at": "2030-01-01T00:00:00+00:00",
    }, headers=_AUTH)
    assert r.status_code == 400


def test_bad_expires_at_is_rejected(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    r = client.post("/admin/access-keys", json={"name": "x", "expires_at": "tomorrow-ish"}, headers=_AUTH)
    assert r.status_code == 400
    assert store.list_keys() == []


def test_update_scopes_and_clear(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    kid = client.post("/admin/access-keys", json={
        "name": "scoped",
        "bound_account_ids": ["account-0", "account-1"],
        "allowed_models": ["gemini-3-pro"],
        "request_limit": 5,
    }, headers=_AUTH).json()["key"]["id"]

    assert store.get(kid).bound_account_ids == ["account-0", "account-1"]

    r = client.patch(f"/admin/access-keys/{kid}", json={
        "bound_account_ids": ["account-1"],
    }, headers=_AUTH)
    assert r.json()["key"]["bound_account_ids"] == ["account-1"]

    r = client.patch(f"/admin/access-keys/{kid}", json={
        "clear": ["bound_account_ids", "allowed_models", "request_limit"],
    }, headers=_AUTH)
    body = r.json()["key"]
    assert body["bound_account_ids"] is None
    assert body["allowed_models"] is None
    assert body["request_limit"] is None


def test_update_rejects_unknown_clear_field_and_empty_patch(client, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    kid = client.post("/admin/access-keys", json={"name": "k"}, headers=_AUTH).json()["key"]["id"]
    assert client.patch(f"/admin/access-keys/{kid}", json={"clear": ["key"]}, headers=_AUTH).status_code == 400
    assert client.patch(f"/admin/access-keys/{kid}", json={}, headers=_AUTH).status_code == 400


def test_missing_key_returns_404(client, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert client.patch("/admin/access-keys/777", json={"name": "x"}, headers=_AUTH).status_code == 404
    assert client.delete("/admin/access-keys/777", headers=_AUTH).status_code == 404
    assert client.post("/admin/access-keys/777/reset-usage", headers=_AUTH).status_code == 404


def test_state_field_reflects_expiry_and_quota(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    expired = store.create("gone", expires_at=past)
    full = store.create("full", request_limit=1)
    store.validate_and_consume(full.key)

    by_id = {k["id"]: k for k in client.get("/admin/access-keys", headers=_AUTH).json()["keys"]}
    assert by_id[expired.id]["state"] == "expired"
    assert by_id[full.id]["state"] == "quota_exceeded"


def test_options_lists_accounts_and_models(client, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = client.get("/admin/access-keys/options", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["accounts"], list)
    assert "gemini-pro" in body["models"], "面板的模型勾选框拿不到候选项就等于没法限制模型"


def test_admin_endpoints_require_admin_key(client, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert client.get("/admin/access-keys").status_code == 401
    assert client.post("/admin/access-keys", json={"name": "x"}).status_code == 401

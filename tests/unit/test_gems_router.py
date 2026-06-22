# tests/unit/test_gems_router.py
"""Unit tests for /admin/gems and /admin/gem-mapping routes."""

_AUTH = {"Authorization": "Bearer sk-test-key"}  # conftest 设的 API_KEY


def test_gem_mapping_crud(gem_client):
    # 新增映射
    r = gem_client.post("/admin/gem-mapping", json={
        "model_name": "my-gem", "gem_id": "g1",
        "base_model": "gemini-pro", "account_id": "account-0",
    }, headers=_AUTH)
    assert r.status_code == 200
    assert "my-gem" in r.json()["mappings"]
    # 列出
    r = gem_client.get("/admin/gem-mapping", headers=_AUTH)
    assert r.json()["mappings"]["my-gem"]["gem_id"] == "g1"
    # 删除
    r = gem_client.delete("/admin/gem-mapping/my-gem", headers=_AUTH)
    assert r.status_code == 200
    assert "my-gem" not in r.json()["mappings"]


def test_list_gems_proxies_account_pool(gem_client, monkeypatch):
    import app.routers.gems as gems_mod

    async def fake_list(account_id):
        assert account_id == "account-0"
        return [{"id": "g1", "name": "n", "description": "", "prompt": ""}]

    monkeypatch.setattr(gems_mod.account_pool, "list_gems", fake_list)
    r = gem_client.get("/admin/gems?account_id=account-0", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["gems"][0]["id"] == "g1"

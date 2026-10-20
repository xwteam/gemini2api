"""访问密钥在 verify_api_key 上的接线，以及两条红线：

红线 1（零回归）：一把访问密钥都没签发时，.env 的 API_KEY 行为与本功能引入前逐字节一致。
红线 2（权限隔离）：访问密钥只能打业务 API，/admin/* 必须 401。
"""

from datetime import datetime, timedelta, timezone

import app.core.access_key_store as store_module
from app.core.access_key_store import AccessKeyStore

_AUTH = {"Authorization": "Bearer sk-test-key"}  # conftest 设的 API_KEY

# 任意一条业务 API 的 GET：不碰账号池、不发网络，只用来观察鉴权结果
_API_PATH = "/v1/models"


def _isolate(monkeypatch, tmp_path) -> AccessKeyStore:
    """把模块级单例换成临时文件版，避免污染仓库根的 data/access_keys.json。"""
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    return fresh


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ------------------------------------------------------------- 红线 1 零回归

def test_env_api_key_still_works_with_zero_access_keys(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    assert store.has_keys() is False

    assert client.get(_API_PATH, headers=_AUTH).status_code == 200

    r = client.get(_API_PATH, headers=_bearer("sk-wrong"))
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["message"] == "Invalid API key."
    assert r.json()["detail"]["error"]["type"] == "auth_error"

    r = client.get(_API_PATH)
    assert r.status_code == 401
    assert "Missing API key" in r.json()["detail"]["error"]["message"]


def test_wrong_key_response_is_identical_with_and_without_access_keys(client, monkeypatch, tmp_path):
    """签发了访问密钥之后，"不存在的 key" 的 401 信封仍必须和零密钥时一字不差，
    不能泄漏"这个服务上有没有访问密钥库"。"""
    store = _isolate(monkeypatch, tmp_path)
    empty = client.get(_API_PATH, headers=_bearer("sk-wrong")).json()
    store.create("someone")
    populated = client.get(_API_PATH, headers=_bearer("sk-wrong")).json()
    assert empty == populated


def test_env_api_key_is_never_counted_against_any_access_key(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("k", request_limit=1)
    for _ in range(5):
        assert client.get(_API_PATH, headers=_AUTH).status_code == 200
    assert store.get(key.id).request_count == 0, "env key 的请求不得记到任何访问密钥头上"


# ---------------------------------------------------------- 红线 2 权限隔离

def test_access_key_cannot_reach_admin_endpoints(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    issued = store.create("tenant").key

    for path in ("/admin/accounts", "/admin/access-keys", "/admin/settings", "/admin/logs"):
        r = client.get(path, headers=_bearer(issued))
        assert r.status_code == 401, f"{path} 竟然放访问密钥进来了"

    # 同一把 key 打业务 API 是可以的 —— 证明上面的 401 不是因为 key 本身无效
    assert client.get(_API_PATH, headers=_bearer(issued)).status_code == 200


def test_access_key_cannot_create_more_access_keys(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    issued = store.create("tenant").key
    r = client.post("/admin/access-keys", json={"name": "self-service"}, headers=_bearer(issued))
    assert r.status_code == 401
    assert len(store.list_keys()) == 1


# ------------------------------------------------------------------ 四态

def test_valid_access_key_is_accepted_and_counted(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("ok")
    assert client.get(_API_PATH, headers=_bearer(key.key)).status_code == 200
    assert store.get(key.id).request_count == 1
    assert store.get(key.id).last_used_at is not None


def test_disabled_access_key_gets_its_own_error(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("off")
    store.update(key.id, enabled=False)
    r = client.get(_API_PATH, headers=_bearer(key.key))
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["type"] == "access_key_disabled"


def test_expired_access_key_gets_its_own_error(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    key = store.create("gone", expires_at=past)
    r = client.get(_API_PATH, headers=_bearer(key.key))
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["type"] == "access_key_expired"


def test_lazily_expired_access_key_gets_expired_error(client, monkeypatch, tmp_path):
    """惰性密钥：首次使用放行并开始计时，把 activated_at 回拨后必须变成已过期。"""
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("lazy", duration_days=1)
    assert client.get(_API_PATH, headers=_bearer(key.key)).status_code == 200

    long_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    store.update(key.id, expires_at=long_ago)
    r = client.get(_API_PATH, headers=_bearer(key.key))
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["type"] == "access_key_expired"


def test_quota_exceeded_access_key_gets_429(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("quota", request_limit=2)
    assert client.get(_API_PATH, headers=_bearer(key.key)).status_code == 200
    assert client.get(_API_PATH, headers=_bearer(key.key)).status_code == 200

    r = client.get(_API_PATH, headers=_bearer(key.key))
    assert r.status_code == 429
    assert r.json()["detail"]["error"]["type"] == "access_key_quota_exceeded"
    assert store.get(key.id).request_count == 2, "被拒的那次不得计数"


def test_unknown_access_key_is_indistinguishable_from_a_wrong_key(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    store.create("decoy")
    r = client.get(_API_PATH, headers=_bearer("sk-" + "0" * 32))
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["type"] == "auth_error"


# ---------------------------------------------------- 其它 key 提取通道

def test_access_key_works_via_x_api_key_and_query_token(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("channels")
    assert client.get(_API_PATH, headers={"x-api-key": key.key}).status_code == 200
    assert client.get(f"{_API_PATH}?token={key.key}").status_code == 200
    assert store.get(key.id).request_count == 2


def test_public_paths_stay_open_and_are_never_counted(client, monkeypatch, tmp_path):
    store = _isolate(monkeypatch, tmp_path)
    key = store.create("k", request_limit=1)
    assert client.get("/health").status_code == 200
    assert store.get(key.id).request_count == 0

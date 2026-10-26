# tests/unit/test_fallback_toggle.py
import pytest
from app.config import settings
import app.routers.api_keys as ak
from app.core import fallback

_AUTH = {"Authorization": "Bearer sk-test-key"}


@pytest.fixture(autouse=True)
def _restore_fallback():
    """settings 是模块级单例，测试间复位 fallback_enabled，避免串扰。"""
    old = getattr(settings, "fallback_enabled", False)
    yield
    object.__setattr__(settings, "fallback_enabled", old)


def test_get_fallback_reflects_setting(client):
    object.__setattr__(settings, "fallback_enabled", True)
    r = client.get("/admin/api-keys/fallback", headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"enabled": True}
    object.__setattr__(settings, "fallback_enabled", False)
    assert client.get("/admin/api-keys/fallback", headers=_AUTH).json() == {"enabled": False}


def test_patch_fallback_on_updates_persists_and_gates(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(ak, "_update_env_file", lambda updates: captured.update(updates))
    object.__setattr__(settings, "fallback_enabled", False)

    r = client.patch("/admin/api-keys/fallback", json={"enabled": True}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"success": True, "enabled": True}
    assert settings.fallback_enabled is True            # 内存即时生效
    assert captured == {"fallback_enabled": True}        # 持久化入参正确
    assert fallback.fallback_enabled() is True           # 运行时门控跟随


def test_patch_fallback_off(client, monkeypatch):
    monkeypatch.setattr(ak, "_update_env_file", lambda updates: None)
    object.__setattr__(settings, "fallback_enabled", True)
    r = client.patch("/admin/api-keys/fallback", json={"enabled": False}, headers=_AUTH)
    assert r.status_code == 200
    assert settings.fallback_enabled is False
    assert fallback.fallback_enabled() is False


def test_patch_fallback_invalid_body_422(client):
    r = client.patch("/admin/api-keys/fallback", json={"enabled": "notabool"}, headers=_AUTH)
    assert r.status_code == 422   # FastAPI/pydantic body 校验


def test_patch_fallback_persist_failure_rolls_back(client, monkeypatch):
    def boom(updates):
        raise OSError("disk full")
    monkeypatch.setattr(ak, "_update_env_file", boom)
    object.__setattr__(settings, "fallback_enabled", False)
    r = client.patch("/admin/api-keys/fallback", json={"enabled": True}, headers=_AUTH)
    assert r.status_code == 500
    assert settings.fallback_enabled is False   # 写盘失败 → 内存回滚，不留半更新


# ---------------------------------------------------------------------------
# v1.6.49：开关写进 data/settings-overrides.json（挂载卷、启动回放、优先级高于环境变量）。
# 过去只写 .env —— 容器里那是镜像层的 /app/.env，升级重建容器后被宿主机 .env 的值顶回去
# （10-26 中转站：面板 22:13 关掉兜底，宿主机 .env 仍是 true，下一次部署就会悄悄重新打开）。
# ---------------------------------------------------------------------------

def test_patch_fallback_persists_into_the_overrides_file(client, monkeypatch):
    from app.core import settings_overrides as so

    monkeypatch.setattr(ak, "_update_env_file", lambda updates: None)
    object.__setattr__(settings, "fallback_enabled", True)
    r = client.patch("/admin/api-keys/fallback", json={"enabled": False}, headers=_AUTH)
    assert r.status_code == 200
    assert so.load_overrides()["fallback_enabled"] is False

    class _Fresh:                      # 「重建容器后」的 Settings：环境变量里是 true
        fallback_enabled = True

    fresh = _Fresh()
    so.apply_overrides(fresh)
    assert fresh.fallback_enabled is False, "启动回放后面板的选择压过环境变量"


def test_a_failed_env_write_rolls_the_overrides_file_back(client, monkeypatch, tmp_path):
    import json
    from app.core import settings_overrides as so

    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"fallback_enabled": True, "default_thinking_level": "low"}))
    monkeypatch.setattr(so, "OVERRIDES_PATH", path)

    def boom(updates):
        raise OSError("read-only .env")

    monkeypatch.setattr(ak, "_update_env_file", boom)
    object.__setattr__(settings, "fallback_enabled", True)
    r = client.patch("/admin/api-keys/fallback", json={"enabled": False}, headers=_AUTH)
    assert r.status_code == 500
    assert "tmp" not in r.text and "read-only" not in r.text, "报错不回显路径 / 异常细节"
    assert settings.fallback_enabled is True
    assert json.loads(path.read_text()) == {"fallback_enabled": True, "default_thinking_level": "low"}, \
        "覆盖文件要回滚到改之前（过去的写法会把 false 留在文件里）"

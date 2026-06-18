"""Smoke / integration tests for the FastAPI app.

The app-import tests require the runtime deps (fastapi, pydantic, ...) and are
auto-skipped via fixtures when those are absent (e.g. a bare local checkout);
they run in full in CI. The static source-regression guards need no deps and
run everywhere.
"""

import os
from pathlib import Path

# API_KEY is set deterministically by tests/conftest.py before app import.
TEST_API_KEY = os.environ.get("API_KEY", "sk-test-key")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# App-level smoke tests (require runtime deps -> skipped if fastapi missing)   #
# --------------------------------------------------------------------------- #
def test_app_is_fastapi(app_main):
    from fastapi import FastAPI

    assert isinstance(app_main.app, FastAPI)


def test_openapi_mounts_all_protocols(app_main):
    schema = app_main.app.openapi()
    paths = schema.get("paths", {})
    # 三协议入口 + 健康检查 + deepresearch 均应挂载
    for expected in (
        "/health",
        "/v1/chat/completions",   # OpenAI
        "/v1/messages",           # Claude
        "/gemini/v1beta/deepresearch",  # Deep Research
    ):
        assert expected in paths, f"missing route in OpenAPI schema: {expected}"


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "gemini2api"}


def test_protected_endpoint_requires_auth(client):
    # 无 key 访问受保护端点应 401（全局鉴权依赖生效）
    resp = client.get("/v1/models")
    assert resp.status_code == 401


def test_health_exempt_but_models_protected(client):
    # 反向确认：带正确 key 不应是鉴权失败（401）
    resp = client.get("/v1/models", headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    assert resp.status_code != 401


def test_deepresearch_model_contract(app_main):
    # 批次1 P0-1 回归护栏：DeepResearchRequest 必须有 max_sources 字段
    from app.models.gemini import DeepResearchRequest

    assert "max_sources" in DeepResearchRequest.model_fields
    assert "max_s" not in DeepResearchRequest.model_fields


# --------------------------------------------------------------------------- #
# Dependency-free static regression guards (always run)                        #
# --------------------------------------------------------------------------- #
def test_research_uses_max_sources_not_truncated_attr():
    """批次1 P0-1: research.py 必须用 request.max_sources，不得残留 request.max_s)。"""
    src = (_REPO_ROOT / "app" / "routers" / "research.py").read_text(encoding="utf-8")
    assert "request.max_sources" in src
    assert "request.max_s)" not in src


def test_account_pool_release_protected_by_finally():
    """批次1 P0-6: account_pool 的 generate/stream 需有 try/finally 兜底释放槽位。"""
    src = (_REPO_ROOT / "app" / "core" / "account_pool.py").read_text(encoding="utf-8")
    assert "finally:" in src


def test_no_module_level_runtime_family_model():
    """批次1 P0-5: 模块级全局 _RUNTIME_FAMILY_MODEL 应已移除（改按实例）。"""
    src = (_REPO_ROOT / "app" / "core" / "gemini_client.py").read_text(encoding="utf-8")
    # 不应再出现模块级赋值（行首，无缩进）
    assert "\n_RUNTIME_FAMILY_MODEL" not in src

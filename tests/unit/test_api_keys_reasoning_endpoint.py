"""reasoning_effort 校验与端点(直接调用端点协程,无网络/无鉴权)。"""

import types
import asyncio
import pytest
from fastapi import HTTPException

import app.routers.api_keys as ak
from app.core.api_key_store import ApiKeyPool


def _req_with_pool(pool):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(api_key_pool=pool)))


def test_validate_effort_accepts():
    assert ak._validate_effort(None) is None
    assert ak._validate_effort("") is None
    assert ak._validate_effort("  ") is None
    assert ak._validate_effort("none") == "none"
    assert ak._validate_effort("high") == "high"
    assert ak._validate_effort("minimal") == "minimal"
    assert ak._validate_effort("2048") == "2048"
    assert ak._validate_effort(" high ") == "high"


def test_validate_effort_rejects():
    for bad in ["x" * 33, "a b", "a\tb"]:
        with pytest.raises(HTTPException):
            ak._validate_effort(bad)


def test_add_key_with_effort(tmp_path):
    pool = ApiKeyPool(file_path=str(tmp_path / "k.json"))
    req = ak.AddKeyRequest(provider="openai", models=["m"], api_key="sk",
                           base_url="https://x/v1", reasoning_effort="high")
    asyncio.run(ak.add_key(req, _req_with_pool(pool)))
    entries = list(pool.entries.values())
    assert entries and entries[0].reasoning_effort == "high"


def test_patch_reasoning_effort(tmp_path):
    pool = ApiKeyPool(file_path=str(tmp_path / "k.json"))
    e = pool.add(provider="openai", model="m", api_key="sk", base_url="https://x/v1")
    body = ak.UpdateReasoningEffortRequest(reasoning_effort="low")
    asyncio.run(ak.update_reasoning_effort(e.id, body, _req_with_pool(pool)))
    assert pool.get(e.id).reasoning_effort == "low"
    # 非法值 → 400
    with pytest.raises(HTTPException):
        asyncio.run(ak.update_reasoning_effort(
            e.id, ak.UpdateReasoningEffortRequest(reasoning_effort="a b"), _req_with_pool(pool)))


def test_patch_reasoning_effort_not_found(tmp_path):
    pool = ApiKeyPool(file_path=str(tmp_path / "k.json"))
    resp = asyncio.run(ak.update_reasoning_effort(
        "ghost", ak.UpdateReasoningEffortRequest(reasoning_effort="low"), _req_with_pool(pool)))
    assert getattr(resp, "status_code", None) == 404

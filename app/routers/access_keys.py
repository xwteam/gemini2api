"""访问密钥（Access Key）管理端点。

挂在 /admin/access-keys，由 verify_admin_key 把守（见 app/main.py 的 _admin_deps）——
访问密钥本身永远进不来这里，只能调业务 API。

注意与 app/routers/api_keys.py（/admin/api-keys，第三方出站 key）完全无关。
"""

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import access_key_store as store_module
from app.core.access_key_store import AccessKey
from app.core.account_pool import account_pool
from app.core.token_pricing import estimate_cost_usd

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/access-keys", tags=["Access Keys"])

MAX_CREATE_COUNT = 50


class CreateAccessKeyRequest(BaseModel):
    name: Optional[str] = None
    count: Optional[int] = 1
    expires_at: Optional[str] = None
    duration_days: Optional[float] = None
    request_limit: Optional[int] = None
    bound_account_ids: Optional[List[str]] = None
    allowed_models: Optional[List[str]] = None
    enabled: bool = True


class UpdateAccessKeyRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    expires_at: Optional[str] = None
    duration_days: Optional[float] = None
    request_limit: Optional[int] = None
    bound_account_ids: Optional[List[str]] = None
    allowed_models: Optional[List[str]] = None
    # 显式清空语义：JSON 里传 null 既可能是"不改"也可能是"清空"，Pydantic 区分不了。
    # 要清空 expires_at/duration_days/request_limit/绑定/模型，把字段名放进 clear 里。
    clear: Optional[List[str]] = None


_CLEARABLE = {
    "expires_at", "duration_days", "request_limit",
    "bound_account_ids", "allowed_models",
}


def _state_of(entry: AccessKey, now: Optional[datetime] = None) -> str:
    """面板展示用的状态：disabled / expired / quota_exceeded / pending / valid。"""
    now = now or datetime.now(timezone.utc)
    if not entry.enabled:
        return "disabled"
    expires_at = store_module.parse_timestamp(entry.expires_at)
    if expires_at is not None and now >= expires_at:
        return "expired"
    if entry.request_limit is not None and entry.request_count >= entry.request_limit:
        return "quota_exceeded"
    if entry.activated_at is None:
        return "pending"
    return "valid"


def _serialize(entry: AccessKey) -> dict:
    data = asdict(entry)
    data["state"] = _state_of(entry)
    data["display_name"] = entry.display_name
    # 估算美元**现算不落盘**：改了 TOKEN_PRICES 之后历史估算随之更新，不留一堆按旧价
    # 冻结的数字。算不出来（价格表里没有那个模型 / 完全没有用量）时是 None，面板显示 "—"
    # —— "这把密钥没花钱"和"我们不知道这个模型多少钱"是两件事，不能都显示成 0。
    data["estimated_cost_usd"] = estimate_cost_usd(entry.tokens_by_model)
    return data


def _store():
    return store_module.access_key_store


@router.get("")
@router.get("/")
async def list_access_keys():
    return {"keys": [_serialize(k) for k in _store().list_keys()]}


@router.get("/options")
async def access_key_options(request: Request):
    """面板签发表单的候选项：账号池里的账号 + 对外可见的模型名。

    模型名的口径与 GET /v1/models 保持一致（公开模型 + 第三方条目 + 已暴露的 gem），
    否则管理员在这里勾了一个客户端根本调不到的名字，限制就成了空气。
    """
    accounts = [
        {"id": a.id, "label": a.label or a.id, "status": a.status.value}
        for a in account_pool.accounts
    ]

    models = list(account_pool.models)
    pool = getattr(request.app.state, "api_key_pool", None)
    if pool:
        for entry in pool.entries.values():
            if entry.status == "active" and entry.model not in models:
                models.append(entry.model)
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    if gem_mapping:
        for gem_model_name in gem_mapping.get_all().keys():
            if gem_model_name not in models:
                models.append(gem_model_name)
    return {"accounts": accounts, "models": models}


@router.post("")
@router.post("/")
async def create_access_keys(req: CreateAccessKeyRequest):
    # 显式传 0 是输入错误，不能被 `or 1` 悄悄当成「默认签发 1 把」
    count = 1 if req.count is None else int(req.count)
    if count < 1 or count > MAX_CREATE_COUNT:
        raise HTTPException(status_code=400, detail=f"count must be between 1 and {MAX_CREATE_COUNT}")
    if req.expires_at and req.duration_days:
        raise HTTPException(
            status_code=400,
            detail="expires_at and duration_days are mutually exclusive",
        )
    if req.expires_at and store_module.parse_timestamp(req.expires_at) is None:
        raise HTTPException(status_code=400, detail="expires_at is not a valid ISO8601 timestamp")

    base = (req.name or "").strip()
    names = [
        (f"{base}-{i + 1}" if base and count > 1 else base)
        for i in range(count)
    ]
    try:
        # create_many：整批只做一次落盘。逐把 create() 会在事件循环线程上做 count 次
        # 全量 fsync（写出的字节数 O(n²)），批量签发时整个网关都卡在那里。
        created = _store().create_many(
            names,
            expires_at=req.expires_at,
            duration_days=req.duration_days,
            request_limit=req.request_limit,
            bound_account_ids=req.bound_account_ids,
            allowed_models=req.allowed_models,
            enabled=req.enabled,
        )
    except (TypeError, ValueError, OverflowError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        # 落盘失败绝不能回 200：管理员会把一把其实没存下来的明文密钥发出去，
        # 重启后持有人直接 401。
        raise HTTPException(status_code=500, detail=f"failed to persist access keys: {e}")
    return {"keys": [_serialize(k) for k in created], "key": _serialize(created[0])}


@router.patch("/{key_id}")
async def update_access_key(key_id: int, req: UpdateAccessKeyRequest):
    fields = {k: v for k, v in req.model_dump(exclude_unset=True).items()
              if k != "clear" and v is not None}
    for field in (req.clear or []):
        if field not in _CLEARABLE:
            raise HTTPException(status_code=400, detail=f"field '{field}' cannot be cleared")
        fields[field] = None
    if not fields:
        raise HTTPException(status_code=400, detail="no updatable field provided")
    if fields.get("expires_at") and store_module.parse_timestamp(fields["expires_at"]) is None:
        raise HTTPException(status_code=400, detail="expires_at is not a valid ISO8601 timestamp")
    try:
        entry = _store().update(key_id, **fields)
    except (TypeError, ValueError, OverflowError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"failed to persist access keys: {e}")
    if entry is None:
        raise HTTPException(status_code=404, detail="access key not found")
    return {"key": _serialize(entry)}


@router.delete("/{key_id}")
async def delete_access_key(key_id: int):
    try:
        deleted = _store().delete(key_id)
    except OSError as e:
        # 吊销没落盘就回 success=true，重启后这把密钥会原地复活。
        raise HTTPException(status_code=500, detail=f"failed to persist access keys: {e}")
    if not deleted:
        raise HTTPException(status_code=404, detail="access key not found")
    return {"success": True}


@router.post("/{key_id}/reset-usage")
async def reset_access_key_usage(key_id: int):
    try:
        entry = _store().reset_usage(key_id)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"failed to persist access keys: {e}")
    if entry is None:
        raise HTTPException(status_code=404, detail="access key not found")
    return {"key": _serialize(entry)}

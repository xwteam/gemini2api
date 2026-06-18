import logging
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.api_key_store import ApiKeyPool, PROVIDER_CATALOG
from app.utils.net_guard import assert_safe_url, UnsafeURLError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/api-keys", tags=["API Keys"])


class AddKeyRequest(BaseModel):
    provider: str
    models: List[str]
    api_key: str
    base_url: Optional[str] = None
    label: Optional[str] = None


class ImportKeysRequest(BaseModel):
    keys: List[AddKeyRequest]


class UpdateStatusRequest(BaseModel):
    status: str


class UpdateLabelRequest(BaseModel):
    label: str


class BatchDeleteRequest(BaseModel):
    ids: List[str]


class FetchModelsRequest(BaseModel):
    provider: str
    api_key: str
    base_url: str


@router.get("")
async def list_keys(request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    keys = pool.list_keys(masked=True)
    return {"keys": keys}


@router.get("/catalog")
async def get_catalog():
    return {"catalog": PROVIDER_CATALOG}


@router.post("")
async def add_key(req: AddKeyRequest, request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    added = 0
    for model in req.models:
        pool.add(
            provider=req.provider,
            model=model,
            api_key=req.api_key,
            base_url=req.base_url,
            label=req.label,
        )
        added += 1
    return {"success": True, "added": added}


@router.post("/import")
async def import_keys(req: ImportKeysRequest, request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    added = 0
    failed = 0
    errors = []

    for key_data in req.keys:
        try:
            for model in key_data.models:
                pool.add(
                    provider=key_data.provider,
                    model=model,
                    api_key=key_data.api_key,
                    base_url=key_data.base_url,
                    label=key_data.label,
                )
                added += 1
        except Exception as e:
            failed += 1
            errors.append({"provider": key_data.provider, "error": str(e)})

    return {"success": True, "added": added, "failed": failed, "errors": errors}


@router.get("/export")
async def export_keys(request: Request, reveal: bool = False):
    pool: ApiKeyPool = request.app.state.api_key_pool
    # VULN-002：默认脱敏导出；需明文密钥须显式 ?reveal=true（已在 admin 鉴权保护下）。
    # 注意：前端"导出"如需可再导入的明文，请改调 /export?reveal=true。
    keys = pool.list_keys(masked=not reveal)
    return {"keys": keys}


@router.delete("/{key_id}")
async def delete_key(key_id: str, request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    success = pool.delete(key_id)
    if not success:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Key {key_id} not found", "type": "not_found"}},
        )
    return {"success": True}


@router.patch("/{key_id}/status")
async def update_status(key_id: str, req: UpdateStatusRequest, request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    success = pool.update_status(key_id, req.status)
    if not success:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Key {key_id} not found", "type": "not_found"}},
        )
    return {"success": True}


@router.patch("/{key_id}/label")
async def update_label(key_id: str, req: UpdateLabelRequest, request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    success = pool.update_label(key_id, req.label)
    if not success:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Key {key_id} not found", "type": "not_found"}},
        )
    return {"success": True}


@router.post("/batch-delete")
async def batch_delete(req: BatchDeleteRequest, request: Request):
    pool: ApiKeyPool = request.app.state.api_key_pool
    deleted = 0
    for key_id in req.ids:
        if pool.delete(key_id):
            deleted += 1
    return {"success": True, "deleted": deleted}


@router.post("/models")
async def fetch_models(req: FetchModelsRequest):
    base_url = req.base_url.rstrip('/')
    headers = {"Authorization": f"Bearer {req.api_key}"}

    if req.provider == "anthropic":
        headers = {
            "x-api-key": req.api_key,
            "anthropic-version": "2023-06-01",
        }
        url = f"{base_url}/models"
    elif req.provider == "gemini":
        url = f"{base_url}/models?key={req.api_key}"
        headers = {}
    else:
        url = f"{base_url}/models"

    # SSRF 防护（VULN-004）：base_url 来自请求体，校验目标不指向内网/环回/链路本地/云元数据。
    # 拦截时返回通用错误，不回显解析到的内网地址。
    try:
        assert_safe_url(url)
    except UnsafeURLError:
        logger.warning("Blocked SSRF attempt in fetch_models base_url")
        raise HTTPException(status_code=400, detail="base_url is not allowed")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            models = []
            if "data" in data:
                for model in data["data"]:
                    models.append({
                        "id": model.get("id", ""),
                        "display_name": model.get("id", ""),
                    })
            elif "models" in data:
                for model in data["models"]:
                    name = model.get("name", "").replace("models/", "")
                    models.append({
                        "id": name,
                        "display_name": model.get("displayName", name),
                    })

            return {"models": models}

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid API key")
        elif e.response.status_code == 502:
            raise HTTPException(status_code=502, detail="Bad gateway")
        else:
            raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Request timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch models: {str(e)}")

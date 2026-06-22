import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.account_pool import account_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Gems"])


class CreateGemRequest(BaseModel):
    account_id: str
    name: str
    prompt: str
    description: str = ""


class UpdateGemRequest(BaseModel):
    account_id: str
    name: str
    prompt: str
    description: str = ""


class GemMappingRequest(BaseModel):
    model_name: str
    gem_id: str
    base_model: str = "gemini-pro"
    account_id: str


@router.get("/gems")
async def list_gems(account_id: str):
    try:
        gems = await account_pool.list_gems(account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"gems": gems}


@router.post("/gems")
async def create_gem(req: CreateGemRequest):
    if not req.name or not req.prompt:
        raise HTTPException(status_code=400, detail="name and prompt are required")
    try:
        gem_id = await account_pool.create_gem(req.account_id, req.name, req.prompt, req.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not gem_id:
        raise HTTPException(status_code=502, detail="Gemini did not return a gem id")
    return {"success": True, "gem_id": gem_id}


@router.put("/gems/{gem_id}")
async def update_gem(gem_id: str, req: UpdateGemRequest):
    if not req.name or not req.prompt:
        raise HTTPException(status_code=400, detail="name and prompt are required")
    try:
        ok = await account_pool.update_gem(req.account_id, gem_id, req.name, req.prompt, req.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not ok:
        raise HTTPException(status_code=502, detail="update failed at Gemini")
    return {"success": True}


@router.delete("/gems/{gem_id}")
async def delete_gem(gem_id: str, account_id: str):
    try:
        ok = await account_pool.delete_gem(account_id, gem_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not ok:
        raise HTTPException(status_code=502, detail="delete failed at Gemini")
    return {"success": True}


@router.get("/gem-mapping")
async def get_gem_mappings(request: Request):
    gm = request.app.state.gem_mapping
    return {"mappings": gm.get_all()}


@router.post("/gem-mapping")
async def set_gem_mapping(req: GemMappingRequest, request: Request):
    if not req.model_name or not req.gem_id or not req.account_id:
        raise HTTPException(status_code=400, detail="model_name, gem_id, account_id are required")
    gm = request.app.state.gem_mapping
    gm.set(req.model_name, {
        "gem_id": req.gem_id,
        "base_model": req.base_model,
        "account_id": req.account_id,
    })
    return {"success": True, "mappings": gm.get_all()}


@router.delete("/gem-mapping/{model_name}")
async def delete_gem_mapping(model_name: str, request: Request):
    gm = request.app.state.gem_mapping
    if not gm.delete(model_name):
        raise HTTPException(status_code=404, detail=f"Mapping '{model_name}' not found")
    return {"success": True, "mappings": gm.get_all()}

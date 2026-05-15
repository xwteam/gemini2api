import asyncio
import logging
from collections import deque
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.core.account_pool import account_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

# 内存日志缓冲区
log_buffer = deque(maxlen=200)


class BufferLogHandler(logging.Handler):
    def emit(self, record):
        entry = self.format(record)
        log_buffer.append(entry)


_buffer_handler = BufferLogHandler()
_buffer_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_buffer_handler)


class ReloadCookiesRequest(BaseModel):
    psid: Optional[str] = None
    psidts: Optional[str] = None


class AddAccountRequest(BaseModel):
    psid: str
    psidts: str = ""
    label: str = ""


@router.post("/reload-cookies")
async def reload_cookies(req: ReloadCookiesRequest = None):
    if req and (req.psid or req.psidts):
        for account in account_pool.accounts:
            if account.client:
                result = await account.client.reload_cookies(psid=req.psid, psidts=req.psidts)
                if result.get("success"):
                    return {"status": "ok", "message": "Cookies reloaded successfully", "healthy": True}
        return JSONResponse(
            status_code=503,
            content={"error": {"message": result.get("error", "Cookie reload failed"), "type": "reload_error"}},
        )
    else:
        from app.config import Settings
        try:
            fresh = Settings()
            for account in account_pool.accounts:
                if account.client:
                    result = await account.client.reload_cookies(
                        psid=fresh.gemini_psid,
                        psidts=fresh.gemini_psidts,
                    )
                    if result.get("success"):
                        return {"status": "ok", "message": "Cookies reloaded successfully", "healthy": True}
            return JSONResponse(
                status_code=503,
                content={"error": {"message": result.get("error", "Cookie reload failed"), "type": "reload_error"}},
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": {"message": f"Failed to read .env: {e}", "type": "config_error"}},
            )

    return JSONResponse(
        status_code=503,
        content={"error": {"message": "No accounts available", "type": "reload_error"}},
    )


@router.get("/status")
async def admin_status():
    return account_pool.get_status()


@router.get("/check-account")
async def check_all_accounts():
    results = await account_pool.check_all()
    return {"accounts": results}


@router.get("/health-history")
async def health_history():
    history = []
    for account in account_pool.accounts:
        if account.client:
            history.extend(
                {**r, "account_id": account.id} for r in account.client.check_history
            )
    history.sort(key=lambda x: x.get("checked_at", ""), reverse=True)
    return {"total": len(history), "records": history[:50]}


@router.get("/accounts")
async def list_accounts():
    return account_pool.get_status()


@router.post("/accounts")
async def add_account(req: AddAccountRequest):
    try:
        account = await account_pool.add_account(
            psid=req.psid,
            psidts=req.psidts,
            label=req.label,
        )
        return {
            "status": "ok",
            "account": {
                "id": account.id,
                "label": account.label,
                "status": account.status.value,
            },
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": "add_account_error"}},
        )


@router.delete("/accounts/{account_id}")
async def remove_account(account_id: str):
    removed = await account_pool.remove_account(account_id)
    if removed:
        return {"status": "ok", "message": f"Account {account_id} removed"}
    return JSONResponse(
        status_code=404,
        content={"error": {"message": f"Account {account_id} not found", "type": "not_found"}},
    )


@router.get("/accounts/{account_id}/check")
async def check_single_account(account_id: str):
    try:
        result = await account_pool.check_account(account_id)
        return result
    except ValueError as e:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": str(e), "type": "not_found"}},
        )


class UpdateCookiesRequest(BaseModel):
    psid: str
    psidts: str = ""


@router.put("/accounts/{account_id}/cookies")
async def update_account_cookies(account_id: str, req: UpdateCookiesRequest):
    for account in account_pool.accounts:
        if account.id == account_id:
            if account.client:
                result = await account.client.reload_cookies(psid=req.psid, psidts=req.psidts)
                if result.get("success"):
                    return {"status": "ok", "message": f"Account {account_id} cookies updated"}
                return JSONResponse(
                    status_code=503,
                    content={"error": {"message": result.get("error", "Cookie reload failed"), "type": "reload_error"}},
                )
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Account client not initialized", "type": "client_error"}},
            )
    return JSONResponse(
        status_code=404,
        content={"error": {"message": f"Account {account_id} not found", "type": "not_found"}},
    )


@router.get("/verify")
async def verify_token():
    return {"status": "ok"}


@router.get("/logs/stream")
async def stream_logs(request: Request):
    async def event_generator():
        last_idx = len(log_buffer)
        for entry in list(log_buffer):
            yield f"data: {entry}\n\n"
        while True:
            if await request.is_disconnected():
                break
            current = list(log_buffer)
            current_len = len(current)
            if current_len > last_idx:
                for entry in current[last_idx:]:
                    yield f"data: {entry}\n\n"
            last_idx = current_len
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

import logging
import os
import platform
import sys
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import APP_VERSION
from app.core.account_pool import account_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

_start_time = time.time()


class ReloadCookiesRequest(BaseModel):
    psid: Optional[str] = None
    psidts: Optional[str] = None


class AddAccountRequest(BaseModel):
    psid: str
    psidts: str = ""
    label: str = ""


@router.post("/reload-cookies")
async def reload_cookies(req: ReloadCookiesRequest = None):
    import httpx
    proxy_url = os.environ.get("BROWSER_PROXY_URL", "http://refresher:8001")

    psid = ""
    psidts = ""
    if req and (req.psid or req.psidts):
        psid = req.psid
        psidts = req.psidts or ""
    else:
        from app.config import Settings
        try:
            fresh = Settings()
            psid = fresh.gemini_psid
            psidts = fresh.gemini_psidts
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": {"message": f"Failed to read .env: {e}", "type": "config_error"}},
            )

    if not psid:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "No PSID provided", "type": "invalid_request"}},
        )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{proxy_url}/update-cookies",
                json={"account_id": "account-0", "psid": psid, "psidts": psidts},
            )
        if resp.status_code == 200:
            return {"status": "ok", "message": "Cookies reloaded, browser session refreshed", "healthy": True}
        detail = resp.json().get("detail", "Unknown error") if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
        return JSONResponse(
            status_code=503,
            content={"error": {"message": f"Browser reload failed: {detail}", "type": "reload_error"}},
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": f"Failed to reach browser proxy: {e}", "type": "proxy_error"}},
        )


@router.get("/status")
async def admin_status():
    return account_pool.get_status()


@router.get("/system-info")
async def system_info():
    import psutil
    proc = psutil.Process(os.getpid())
    mem = proc.memory_info()
    total_mem = psutil.virtual_memory().total
    uptime_seconds = int(time.time() - _start_time)

    return {
        "version": APP_VERSION,
        "python_version": platform.python_version(),
        "server_time": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "os": f"{platform.system()} {platform.release()}",
        "memory_usage": mem.rss // (1024 * 1024),
        "memory_total": total_mem // (1024 * 1024),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "pid": os.getpid(),
        "run_mode": "Docker" if os.path.exists("/.dockerenv") else "直接运行",
        "uptime_seconds": uptime_seconds,
    }


@router.get("/check-account")
async def check_all_accounts():
    import httpx
    proxy_url = os.environ.get("BROWSER_PROXY_URL", "http://refresher:8001")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{proxy_url}/check-all")
        if resp.status_code == 200:
            return resp.json()
        return {"accounts": []}
    except Exception as e:
        return {"accounts": [], "error": str(e)}


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
    import httpx
    proxy_url = os.environ.get("BROWSER_PROXY_URL", "http://refresher:8001")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{proxy_url}/check-account/{account_id}")
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            return JSONResponse(status_code=404, content={"error": {"message": f"Account {account_id} not found", "type": "not_found"}})
        return {"valid": False, "account_id": account_id, "error": resp.text[:200]}
    except Exception as e:
        return {"valid": False, "account_id": account_id, "error": str(e)}


class UpdateCookiesRequest(BaseModel):
    psid: str
    psidts: str = ""


@router.put("/accounts/{account_id}/cookies")
async def update_account_cookies(account_id: str, req: UpdateCookiesRequest):
    import httpx
    proxy_url = os.environ.get("BROWSER_PROXY_URL", "http://refresher:8001")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{proxy_url}/update-cookies",
                json={"account_id": account_id, "psid": req.psid, "psidts": req.psidts},
            )
        if resp.status_code == 200:
            return {"status": "ok", "message": f"Account {account_id} cookies updated, browser reloaded"}
        detail = resp.json().get("detail", "Unknown error") if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
        return JSONResponse(
            status_code=503,
            content={"error": {"message": f"Browser reload failed: {detail}", "type": "reload_error"}},
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": f"Failed to reach browser proxy: {e}", "type": "proxy_error"}},
        )


@router.get("/verify")
async def verify_token():
    return {"status": "ok"}


@router.post("/restart")
async def restart_server():
    import threading
    import signal

    def _restart():
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_restart, daemon=True).start()
    return {"status": "ok", "message": "Server restarting..."}

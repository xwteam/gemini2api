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

from app.config import APP_VERSION, mask_secret
from app.core.account_pool import account_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

_start_time = time.time()


def _masked_status() -> dict:
    """VULN-003：在响应层对 psid（Google 登录态 Cookie）脱敏，不改 account_pool 内部数据。
    get_status() 每次返回新 dict，可安全就地掩码。保留字段，仅掩码值。"""
    status = account_pool.get_status()
    for acc in status.get("accounts", []):
        if acc.get("psid"):
            acc["psid"] = mask_secret(acc["psid"])
    return status


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
    return _masked_status()


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
    return _masked_status()


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


@router.post("/restart")
async def restart_server(confirm: bool = False):
    """重启服务（已受 admin 鉴权保护）。需 confirm=true 防误触，
    避免无意/单击直接触发进程级 SIGTERM 造成可用性中断（VULN-009）。"""
    if not confirm:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "重启需二次确认，请带查询参数 ?confirm=true", "type": "confirmation_required"}},
        )
    import threading
    import signal

    def _restart():
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_restart, daemon=True).start()
    return {"status": "ok", "message": "Server restarting..."}


@router.get("/check-update")
async def check_update():
    """Check if a new version is available via GitHub Releases"""
    import httpx

    current = APP_VERSION
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.github.com/repos/xwteam/gemini2api/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            if resp.status_code == 200:
                data = resp.json()
                latest = data.get("tag_name", "").lstrip("v")
                return {
                    "current": current,
                    "latest": latest,
                    "has_update": latest != current and latest != "",
                    "update_url": data.get("html_url", "https://github.com/xwteam/gemini2api/releases"),
                    "release_notes": data.get("body", "")
                }
    except Exception as e:
        logger.error(f"Failed to check update: {e}")

    return {"current": current, "latest": current, "has_update": False, "update_url": "https://github.com/xwteam/gemini2api/releases"}


@router.post("/update")
async def perform_update():
    """Return update instructions"""
    return {
        "status": "ok",
        "message": "Please run the following command on your server to update:",
        "command": "cd /home/ubuntu/gemini2api && git pull origin main && docker compose up -d --build"
    }


class CleanupWebChatsRequest(BaseModel):
    keep_hours: float = 24.0
    skip_pinned: bool = True


@router.get("/web-chats")
async def list_web_chats(recent: int = 300):
    """列出账号在 Gemini 网页端的会话（只读，用于排查/确认清理范围）。"""
    try:
        return {"accounts": await account_pool.list_web_chats(recent=recent)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


_cleanup_bg_tasks: set = set()


@router.post("/cleanup-web-chats")
async def cleanup_web_chats(req: CleanupWebChatsRequest = None):
    """清理超过 keep_hours 的网页端会话（置顶可保留）。手动触发。
    后台异步执行立即返回：清理重度堆积账号可能耗时数分钟（每删一个间隔 0.3s），
    同步等待会让 HTTP 请求超时。结果在服务端日志可见。
    """
    req = req or CleanupWebChatsRequest()
    import asyncio

    async def _run():
        try:
            await account_pool.cleanup_web_chats(
                keep_hours=req.keep_hours, skip_pinned=req.skip_pinned
            )
        except Exception as e:
            logger.warning(f"[cleanup-web-chats] 后台清理异常: {e}")

    task = asyncio.create_task(_run())
    _cleanup_bg_tasks.add(task)
    task.add_done_callback(_cleanup_bg_tasks.discard)
    return {"status": "started", "message": "清理已在后台开始，结果见服务端日志"}


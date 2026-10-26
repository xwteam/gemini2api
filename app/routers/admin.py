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
from app.core import keepalive_modes
from app.core.account_pool import account_pool
from app.core.model_breaker import model_breaker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

_start_time = time.time()


def _masked_status() -> dict:
    """VULN-003：在响应层对 psid（Google 登录态 Cookie）脱敏，不改 account_pool 内部数据。
    get_status() 每次返回新 dict，可安全就地掩码。保留字段，仅掩码值。

    model_breakers：模型熔断各族的状态（v1.6.46 规格 C.7）。加在这里而不是只加在 admin_status 上：
    /admin/status（仪表盘）与 /admin/accounts（账号页 loadAccounts，横幅显示在那一页）共用它（I.7）。
    """
    status = account_pool.get_status()
    for acc in status.get("accounts", []):
        if acc.get("psid"):
            acc["psid"] = mask_secret(acc["psid"])
    status["model_breakers"] = model_breaker.snapshot()
    return status


def _push_source(request: Request) -> str:
    """这次推 cookie 的来源 = 这份 cookie 由谁保活（keepalive_modes.mode_from_headers）。

    浏览器保活插件推的（X-Gemini2API-Keepalive 头，或 Origin 为 chrome-extension://）→ browser，
    服务端从此不再轮换它；面板手动「更新 Cookie」、脚本 → server。在 reload **之前**就算好并传给
    client.reload_cookies(keepalive_mode=...)：reload 进行中的兜底轮换也要按它挡住（新 PSID 的
    记录要等成功后才写）。
    """
    return keepalive_modes.mode_from_headers(request.headers)


def _record_keepalive_mode(account, mode: str) -> None:
    """把这个账号记成 mode，写在 client **当前**的 PSID 名下（client 自己知道换上的是哪个 PSID，
    含引号 / 分号清洗之后的值）。同步、绝不抛：cookie 已经换上 / 账号已经加上了，记不下保活方式
    只影响「服务端要不要轮换它」，绝不能把这次成功的操作报成失败（插件会当成没推上去、反复重推）。
    """
    try:
        recorded = account.client.set_keepalive_mode(mode)
    except Exception as e:
        logger.warning(f"Account {account.id}: could not record keepalive mode {mode}: {e}")
        return
    if recorded:  # 落盘失败时 keepalive_modes 自己已经告警过
        logger.info(f"Account {account.id}: keepalive mode -> {mode}")


async def _after_cookie_reload(account, mode: str) -> None:
    """换 cookie 成功之后的收尾（PUT /accounts/{id}/cookies 与 POST /reload-cookies 共用）。

    1. 记下这个账号由谁保活（mode 见 _push_source）。只在 reload 成功之后写，写在 reload 之后的
       **新** PSID 名下。先写它：从 reload 返回到这里没有 await、写记录本身也是同步的，浏览器推来
       的新 PSID 从换上到记成 browser 之间，刷新循环 / 自愈插不进来替它轮换（reload 进行中由
       keepalive_mode 参数挡着）。
    2. 池内状态当场回到可用（ACTIVE + consecutive_failures=0），不再依赖调用方随后调 /check。
    """
    _record_keepalive_mode(account, mode)
    await account_pool.mark_cookies_reloaded(account)


class ReloadCookiesRequest(BaseModel):
    psid: Optional[str] = None
    psidts: Optional[str] = None


class AddAccountRequest(BaseModel):
    psid: str
    psidts: str = ""
    label: str = ""


@router.post("/reload-cookies")
async def reload_cookies(request: Request, req: ReloadCookiesRequest = None):
    # 修复：result 仅在 `if account.client:` 内赋值，若账号池为空或所有账号无 client，
    # 循环体不执行、result 始终未绑定，后续 result.get(...) 会抛 UnboundLocalError
    # （显式 cookie 分支直接 500，.env 分支被误判为 "Failed to read .env"），
    # 且末尾 "No accounts available" 成为死代码。初始化 result=None 并在循环后兜底返回 503。
    mode = _push_source(request)
    if req and (req.psid or req.psidts):
        result = None
        for account in account_pool.accounts:
            if account.client:
                result = await account.client.reload_cookies(
                    psid=req.psid, psidts=req.psidts, keepalive_mode=mode,
                )
                if result.get("success"):
                    await _after_cookie_reload(account, mode)
                    return {"status": "ok", "message": "Cookies reloaded successfully", "healthy": True}
        if result is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "No accounts available", "type": "reload_error"}},
            )
        return JSONResponse(
            status_code=503,
            content={"error": {"message": result.get("error", "Cookie reload failed"), "type": "reload_error"}},
        )
    else:
        from app.config import Settings
        try:
            fresh = Settings()
            result = None
            for account in account_pool.accounts:
                if account.client:
                    result = await account.client.reload_cookies(
                        psid=fresh.gemini_psid,
                        psidts=fresh.gemini_psidts,
                        keepalive_mode=mode,
                    )
                    if result.get("success"):
                        await _after_cookie_reload(account, mode)
                        return {"status": "ok", "message": "Cookies reloaded successfully", "healthy": True}
            if result is None:
                return JSONResponse(
                    status_code=503,
                    content={"error": {"message": "No accounts available", "type": "reload_error"}},
                )
            return JSONResponse(
                status_code=503,
                content={"error": {"message": result.get("error", "Cookie reload failed"), "type": "reload_error"}},
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": {"message": f"Failed to read .env: {e}", "type": "config_error"}},
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
async def add_account(req: AddAccountRequest, request: Request):
    try:
        account = await account_pool.add_account(
            psid=req.psid,
            psidts=req.psidts,
            label=req.label,
        )
        # 新添加的账号同样按来源记保活方式（面板 / 脚本 → server）。记录按 PSID 存、删账号时不清：
        # 不记的话，删掉一个浏览器保活的账号、再用同一份 cookie 加回来，会直接继承旧的 browser ——
        # 服务端不轮换、插件也不再推，几小时后过期。
        _record_keepalive_mode(account, _push_source(request))
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
async def update_account_cookies(account_id: str, req: UpdateCookiesRequest, request: Request):
    for account in account_pool.accounts:
        if account.id == account_id:
            if account.client:
                mode = _push_source(request)
                result = await account.client.reload_cookies(
                    psid=req.psid, psidts=req.psidts, keepalive_mode=mode,
                )
                if result.get("success"):
                    # 回写 accounts.json：否则面板刚救活的账号在下次重启时又拿着添加账号
                    # 那一刻的旧 cookie 起来（启动时的"配置值"就是 accounts.json 里这一份）。
                    account_pool.persist_account_cookies(account_id, req.psid, req.psidts)
                    await _after_cookie_reload(account, mode)
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


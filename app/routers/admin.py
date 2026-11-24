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
from app.core.account_pool import DuplicateAccountError, account_pool, client_says
from app.core.fingerprint.cookie_jar import (
    GOOGLE_DOMAIN,
    CookieImportError,
    StoredCookie,
    clean_cookie_value,
    cookies_from_browser,
    cookies_from_header,
)
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


def _sync_persisted_config(account, psid: str, psidts: str) -> None:
    """整套 Cookie 换上并回写 accounts.json 之后，让下次启动认得这份磁盘缓存（见
    GeminiWebClient.sync_persisted_config）。同步、绝不抛：cookie 已经换上了，这一步失败只影响重启后
    要不要再推一次，绝不能把这次成功的操作报成失败。"""
    try:
        account.client.sync_persisted_config(psid, psidts)
    except Exception as e:
        logger.warning(f"Account {account.id}: could not sync the cookie cache with accounts.json: {e}")


def _sync_legacy_writeback(account, psid: str, psidts: str) -> None:
    """旧格式 PUT（只带 psid / psidts）回写 accounts.json 之后：PSID 没变就把配置快照跟上（见
    GeminiWebClient.sync_persisted_psidts），否则整套 Cookie 换上之后的一次旧格式 PUT 会让下次启动清空
    整罐。PSID 变了照 v1.6.52 什么都不做。reload_cookies 的调用方式不变。同步、绝不抛：cookie 已经换上了。"""
    sync = getattr(account.client, "sync_persisted_psidts", None)
    if sync is None:
        return
    try:
        sync(psid, psidts)
    except Exception as e:
        logger.warning(f"Account {account.id}: could not sync the cookie cache with accounts.json: {e}")


def _accounts_for_full_set(psid: str) -> list:
    """POST /admin/reload-cookies 带整套 Cookie（插件没填账号 ID 时走这条）该依次试哪些账号。

    v1.6.52 拿同一份 Cookie 在池里逐个试、第一个成功的就换上；那时被覆盖的只有 PSID / PSIDTS，重启后
    还能从 accounts.json 找回来。整套 Cookie 不在 accounts.json 里，重启时又因 PSID 对不上被清掉，覆盖
    了就找不回来。所以：
    ①当前用的就是这套 Cookie 的谷歌登录（__Secure-1PSID 一致）的账号：只换给它，失败也不往下试；
    ②没有：单账号池照旧换给那唯一的账号（浏览器重新登录、PSID 变了的常见情况）；多账号池只试还没有
      自己整套 Cookie 的账号。全都有的话返回空列表，由调用方报 409。
    """
    candidates = [a for a in account_pool.accounts if a.client]
    owners = [a for a in candidates if client_says(a.client, "owns_cookie_set", psid)]
    if owners:
        return owners
    if len(candidates) <= 1:
        return candidates
    return [a for a in candidates if not client_says(a.client, "has_full_cookie_set")]


NO_MATCHING_ACCOUNT = (
    "This cookie set's __Secure-1PSID belongs to no account, and every account already holds its own "
    "full cookie set: set the account ID in the browser plugin (PUT /admin/accounts/{id}/cookies)"
    " / 这套 Cookie 的 __Secure-1PSID 不属于池里任何账号，而每个账号都已有自己的整套 Cookie："
    "请在浏览器插件里填账号 ID（走 PUT /admin/accounts/{id}/cookies）"
)


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


class BrowserCookie(BaseModel):
    """浏览器插件推来的一条 Cookie，字段名照 chrome.cookies.Cookie（sameSite / storeId 等多余字段忽略）。"""
    name: str
    value: str
    domain: str
    path: Optional[str] = "/"
    expirationDate: Optional[float] = None
    secure: Optional[bool] = None
    httpOnly: Optional[bool] = None
    hostOnly: Optional[bool] = None


class ReloadCookiesRequest(BaseModel):
    psid: Optional[str] = None
    psidts: Optional[str] = None
    # 整套 Cookie（谷歌 11-20 改版后光有 PSID / PSIDTS 只能以访客身份打开 /app）：
    # cookies = 浏览器插件 ≥1.4.0 推来的 chrome.cookies.Cookie 列表；cookie_header = 面板粘贴的整段
    # `Cookie:` 请求头。二选一；都不带 = 旧插件 / 旧脚本，行为与 v1.6.52 一致。
    cookies: Optional[list[BrowserCookie]] = None
    cookie_header: Optional[str] = None


def _full_cookie_set(req) -> list[StoredCookie] | None:
    """请求里带的整套 Cookie（已转成罐里的条目、域名已定），没带返回 None。不合法抛 CookieImportError。"""
    header = (req.cookie_header or "").strip()
    if req.cookies is not None and header:
        raise CookieImportError("send either cookies or cookie_header, not both")
    if req.cookies is not None:
        items = cookies_from_browser([c.model_dump() for c in req.cookies])
    elif header:
        items = cookies_from_header(header)
    else:
        return None
    if not items:
        raise CookieImportError("the cookie set contains no usable google.com cookies")
    return items


def _session_pair_of(items: list[StoredCookie], psid: Optional[str], psidts: Optional[str]) -> tuple[str, str]:
    """整套 Cookie 里 .google.com 的 __Secure-1PSID / __Secure-1PSIDTS 必须与请求的 psid / psidts 一致。

    psid / psidts 为 None（POST /admin/reload-cookies 可以不填）时取整套里的值。返回清洗后的
    (psid, psidts)。不一致抛 CookieImportError —— 消息里不带任何值。
    """
    by_name = {c.name: c.value for c in items if c.domain == GOOGLE_DOMAIN}
    set_psid = by_name.get("__Secure-1PSID", "")
    set_psidts = by_name.get("__Secure-1PSIDTS", "")
    if not set_psid:
        raise CookieImportError("the cookie set has no __Secure-1PSID for .google.com")
    want_psid = set_psid if psid is None else clean_cookie_value(psid)
    want_psidts = set_psidts if psidts is None else clean_cookie_value(psidts)
    if want_psid != set_psid or want_psidts != set_psidts:
        raise CookieImportError(
            "psid / psidts do not match __Secure-1PSID / __Secure-1PSIDTS in the cookie set"
        )
    return want_psid, want_psidts


def _invalid_cookies(e: CookieImportError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"message": str(e), "type": "invalid_cookies"}},
    )


def _log_full_cookie_set(account_id: str, items: list[StoredCookie]) -> None:
    """只记条数和有没有 OSID，绝不记值。"""
    has_osid = any(c.name in ("OSID", "__Secure-OSID") for c in items)
    logger.info(
        f"Account {account_id}: full cookie set applied ({len(items)} cookies, "
        f"OSID {'present' if has_osid else 'missing'})"
    )


class AddAccountRequest(BaseModel):
    # 整套 Cookie（v1.6.55 规格 C1）：cookies / cookie_header 同 ReloadCookiesRequest，二选一。带了整套
    # psid / psidts 可以不填（取整套里 .google.com 的 __Secure-1PSID/1PSIDTS），填了必须一致；都没带时
    # psid 必填（400），其余与 v1.6.54 一致。
    psid: Optional[str] = None
    psidts: Optional[str] = None
    label: str = ""
    cookies: Optional[list[BrowserCookie]] = None
    cookie_header: Optional[str] = None


MISSING_PSID = (
    "psid is required unless the full cookie set is sent (cookies or cookie_header)"
    " / 不带整段 Cookie（cookies / cookie_header）时 psid 必填"
)


def _invalid_request(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"message": message, "type": "invalid_request_error"}},
    )


def _without_cookie_values(text: str, values) -> str:
    """异常消息原样回给面板之前，把这次请求带来的 Cookie 值抹掉（错误信息里绝不能出现 Cookie 值）。
    太短的值（< 8 个字符）不当成凭据，免得把消息里的普通字样抹花。"""
    for value in sorted({v for v in values if v and len(v) >= 8}, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


@router.post("/reload-cookies")
async def reload_cookies(request: Request, req: ReloadCookiesRequest = None):
    # 修复：result 仅在 `if account.client:` 内赋值，若账号池为空或所有账号无 client，
    # 循环体不执行、result 始终未绑定，后续 result.get(...) 会抛 UnboundLocalError
    # （显式 cookie 分支直接 500，.env 分支被误判为 "Failed to read .env"），
    # 且末尾 "No accounts available" 成为死代码。初始化 result=None 并在循环后兜底返回 503。
    mode = _push_source(request)
    full = None
    psid, psidts = (req.psid, req.psidts) if req else (None, None)
    if req:
        try:
            full = _full_cookie_set(req)
            if full is not None:
                psid, psidts = _session_pair_of(full, req.psid or None, req.psidts or None)
        except CookieImportError as e:
            return _invalid_cookies(e)
    if req and (psid or psidts):
        extra = {"cookies": full} if full is not None else {}
        if full is not None:
            # 整套 Cookie 只换给它所属的账号（见 _accounts_for_full_set）
            targets = _accounts_for_full_set(psid)
            if not targets and any(a.client for a in account_pool.accounts):
                return JSONResponse(
                    status_code=409,
                    content={"error": {"message": NO_MATCHING_ACCOUNT, "type": "no_matching_account"}},
                )
        else:
            targets = [a for a in account_pool.accounts if a.client]  # 旧格式：照旧逐个试
        result = None
        for account in targets:
            result = await account.client.reload_cookies(
                psid=psid, psidts=psidts, keepalive_mode=mode, **extra,
            )
            if result.get("success"):
                if full is not None:
                    _log_full_cookie_set(account.id, full)
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
        full = _full_cookie_set(req)
        if full is not None:
            psid, psidts = _session_pair_of(
                full, clean_cookie_value(req.psid) or None, clean_cookie_value(req.psidts) or None,
            )
        else:
            psid, psidts = clean_cookie_value(req.psid), req.psidts or ""
    except CookieImportError as e:
        return _invalid_cookies(e)
    if not psid:
        return _invalid_request(MISSING_PSID)
    # 整套 Cookie 由 add_account 交给新账号的第一次初始化，在第一次 GET /app 之前装罐（见
    # GeminiWebClient.initialize）；装罐用的是与 reload_cookies 同一个 replace_cookies。
    extra = {"cookies": full} if full is not None else {}
    try:
        account = await account_pool.add_account(psid=psid, psidts=psidts, label=req.label, **extra)
    except DuplicateAccountError as e:
        return JSONResponse(
            status_code=409,
            content={"error": {"message": str(e), "type": "duplicate_account"}},
        )
    except Exception as e:
        values = [psid, psidts, req.psid, req.psidts, *(c.value for c in full or ())]
        return JSONResponse(
            status_code=500,
            content={"error": {"message": _without_cookie_values(str(e), values), "type": "add_account_error"}},
        )
    if full is not None:
        # 与 PUT /admin/accounts/{id}/cookies 同口径：add_account 已把 psid / psidts 写进 accounts.json，
        # 让罐文件名与配置快照跟上，下次启动才认得这份整套 Cookie
        _log_full_cookie_set(account.id, full)
        _sync_persisted_config(account, account.psid, account.psidts)
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
        "full_cookie_set": full is not None,
    }


class UpdateLabelRequest(BaseModel):
    # 缺字段 / null 一律按不合法处理（400，见 clean_label），不走 FastAPI 的 422
    label: Optional[str] = None


@router.patch("/accounts/{account_id}")
async def update_account_label(account_id: str, req: UpdateLabelRequest):
    """在线改账号标签（v1.6.55 规格 C2）：只改标签，凭据、状态、保活方式一概不碰。"""
    try:
        account = account_pool.set_label(account_id, req.label)
    except ValueError as e:
        return _invalid_request(str(e))
    except OSError as e:
        logger.error(f"Account {account_id}: could not save the new label: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": f"Could not save accounts file: {e}", "type": "persist_error"}},
        )
    if account is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Account {account_id} not found", "type": "not_found"}},
        )
    return {"status": "ok", "account": {"id": account.id, "label": account.label}}


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
    # 见 ReloadCookiesRequest：整套 Cookie，二选一；带了就整套换上，且 psid / psidts 必须与其中的
    # __Secure-1PSID / __Secure-1PSIDTS 一致（不一致 400）。完整 Cookie 只进该账号的 Cookie 罐文件
    # （data/cookies/<hash>.json），accounts.json 照旧只存 psid / psidts。
    cookies: Optional[list[BrowserCookie]] = None
    cookie_header: Optional[str] = None


@router.put("/accounts/{account_id}/cookies")
async def update_account_cookies(account_id: str, req: UpdateCookiesRequest, request: Request):
    try:
        full = _full_cookie_set(req)
        if full is not None:
            _session_pair_of(full, req.psid, req.psidts)
    except CookieImportError as e:
        return _invalid_cookies(e)
    extra = {"cookies": full} if full is not None else {}
    for account in account_pool.accounts:
        if account.id == account_id:
            if account.client:
                mode = _push_source(request)
                result = await account.client.reload_cookies(
                    psid=req.psid, psidts=req.psidts, keepalive_mode=mode, **extra,
                )
                if result.get("success"):
                    # 回写 accounts.json：否则面板刚救活的账号在下次重启时又拿着添加账号
                    # 那一刻的旧 cookie 起来（启动时的"配置值"就是 accounts.json 里这一份）。
                    persisted = account_pool.persist_account_cookies(account_id, req.psid, req.psidts)
                    if full is not None:
                        _log_full_cookie_set(account_id, full)
                        if persisted:
                            _sync_persisted_config(account, req.psid, req.psidts)
                    elif persisted:
                        # 旧格式也要让配置快照跟上，否则下次启动会清掉之前换上的整套 Cookie
                        _sync_legacy_writeback(account, req.psid, req.psidts)
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


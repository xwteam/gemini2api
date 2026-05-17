"""
Gemini Playwright Proxy — 浏览器代理服务

所有 Gemini 对话请求通过真实 Chromium 浏览器发送，
继承浏览器的 Cookie、TLS 指纹和 JS 执行环境，
Google 只看到一个真实 Chrome 在操作。
"""
import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("/app/data")
STATE_DIR = DATA_DIR / "browser_states"
GEMINI_APP_URL = "https://gemini.google.com/app"
GENERATE_URL = (
    "https://gemini.google.com/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)

KEEPALIVE_INTERVAL = 300
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "3"))

# PLACEHOLDER_REST


class AccountContext:
    def __init__(self, account_id: str, context: BrowserContext, page: Page):
        self.account_id = account_id
        self.context = context
        self.page = page
        self.session_token = ""
        self.healthy = False
        self.last_refresh = 0.0

    async def obtain_token(self):
        try:
            await self.page.goto(GEMINI_APP_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
            content = await self.page.content()
            match = re.search(r'"SNlM0e":"([^"]+)"', content)
            if match:
                self.session_token = match.group(1)
                self.healthy = True
                self.last_refresh = time.time()
                logger.info(f"[{self.account_id}] Session token obtained")
                return True
            else:
                if "accounts.google.com" in content or "ServiceLogin" in content:
                    logger.error(f"[{self.account_id}] Cookie expired - login redirect")
                else:
                    logger.error(f"[{self.account_id}] Token not found in page")
                self.healthy = False
                return False
        except Exception as e:
            logger.error(f"[{self.account_id}] Failed to obtain token: {e}")
            self.healthy = False
            return False


class BrowserPool:
    def __init__(self):
        self.browser: Browser | None = None
        self.accounts: dict[str, AccountContext] = {}
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._playwright = None
        self._keepalive_task = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--single-process",
                "--no-zygote",
                "--disable-extensions",
                "--js-flags=--expose-gc",
            ]
        )
        logger.info("Chromium browser started")
        await self._init_accounts()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _init_accounts(self):
        accounts = self._load_account_configs()
        for acc in accounts:
            await self._create_account_context(acc["id"], acc.get("psid", ""), acc.get("psidts", ""))

    def _load_account_configs(self) -> list[dict]:
        accounts_file = DATA_DIR / "refresher_accounts.json"
        if accounts_file.exists():
            with open(accounts_file) as f:
                return json.load(f)
        psid = os.environ.get("GEMINI_PSID", "")
        psidts = os.environ.get("GEMINI_PSIDTS", "")
        if psid:
            return [{"id": "account-0", "psid": psid, "psidts": psidts}]
        return []

    async def _create_account_context(self, account_id: str, psid: str, psidts: str):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{account_id}.json"

        if not state_file.exists() and psid:
            state = {
                "cookies": [
                    {"name": "__Secure-1PSID", "value": psid, "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
                    {"name": "__Secure-1PSIDTS", "value": psidts, "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
                ],
                "origins": []
            }
            with open(state_file, "w") as f:
                json.dump(state, f)

        kwargs = {"storage_state": str(state_file)} if state_file.exists() else {}
        context = await self.browser.new_context(**kwargs)
        page = await context.new_page()
        acc_ctx = AccountContext(account_id, context, page)
        await acc_ctx.obtain_token()
        if acc_ctx.healthy:
            await context.storage_state(path=str(state_file))
        self.accounts[account_id] = acc_ctx
        logger.info(f"[{account_id}] Context created, healthy={acc_ctx.healthy}")

    async def generate(self, prompt: str, model: str, account_id: str, conversation_id: str, model_headers: dict) -> dict:
        acc = self.accounts.get(account_id)
        if not acc:
            if self.accounts:
                acc = next(iter(self.accounts.values()))
            else:
                raise HTTPException(503, "No accounts available")

        if not acc.healthy:
            raise HTTPException(503, f"Account {acc.account_id} is unhealthy")

        async with self.semaphore:
            return await self._do_generate(acc, prompt, model, conversation_id, model_headers)

    async def _do_generate(self, acc: AccountContext, prompt: str, model: str, conversation_id: str, model_headers: dict) -> dict:
        conv_param = conversation_id if conversation_id else None
        inner = json.dumps([[prompt], None, conv_param, model])
        encoded = json.dumps([None, inner])

        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Origin": "https://gemini.google.com",
            "Referer": "https://gemini.google.com/",
            "X-Same-Domain": "1",
        }
        headers.update(model_headers)

        form_body = f"at={acc.session_token}&f.req={encoded}"

        try:
            resp = await acc.page.request.post(
                GENERATE_URL,
                data=form_body,
                headers=headers,
                timeout=90000,
            )
            status = resp.status
            body = await resp.text()

            if status >= 400:
                logger.error(f"[{acc.account_id}] Gemini returned {status}")
                if status in (401, 403):
                    acc.healthy = False
                raise HTTPException(status, f"Gemini error: {status}")

            return {"raw_response": body, "status": status}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[{acc.account_id}] Request failed: {e}")
            raise HTTPException(500, f"Request failed: {e}")

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            for acc_id, acc in self.accounts.items():
                try:
                    if time.time() - acc.last_refresh > KEEPALIVE_INTERVAL:
                        logger.info(f"[{acc_id}] Keepalive refresh...")
                        await acc.obtain_token()
                        if acc.healthy:
                            state_file = STATE_DIR / f"{acc_id}.json"
                            await acc.context.storage_state(path=str(state_file))
                except Exception as e:
                    logger.error(f"[{acc_id}] Keepalive error: {e}")

    async def update_account_cookies(self, account_id: str, psid: str, psidts: str) -> bool:
        if account_id in self.accounts:
            old_acc = self.accounts[account_id]
            await old_acc.context.close()
            del self.accounts[account_id]
        await self._create_account_context(account_id, psid, psidts)
        return self.accounts.get(account_id, None) is not None and self.accounts[account_id].healthy

    async def stop(self):
        if self._keepalive_task:
            self._keepalive_task.cancel()
        for acc in self.accounts.values():
            await acc.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()


pool = BrowserPool()


class GenerateRequest(BaseModel):
    prompt: str
    model: str = "gemini-3-flash"
    account_id: str = ""
    conversation_id: str = ""
    model_headers: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.start()
    yield
    await pool.stop()


app = FastAPI(lifespan=lifespan)


@app.post("/generate")
async def generate(req: GenerateRequest):
    result = await pool.generate(
        prompt=req.prompt,
        model=req.model,
        account_id=req.account_id,
        conversation_id=req.conversation_id,
        model_headers=req.model_headers,
    )
    return result


@app.get("/health")
async def health():
    accounts_status = []
    for acc_id, acc in pool.accounts.items():
        accounts_status.append({
            "id": acc_id,
            "healthy": acc.healthy,
            "last_refresh": acc.last_refresh,
        })
    return {
        "status": "ok" if any(a["healthy"] for a in accounts_status) else "unhealthy",
        "browser": pool.browser is not None,
        "accounts": accounts_status,
    }


class UpdateCookiesRequest(BaseModel):
    account_id: str = "account-0"
    psid: str
    psidts: str = ""


@app.post("/update-cookies")
async def update_cookies(req: UpdateCookiesRequest):
    success = await pool.update_account_cookies(req.account_id, req.psid, req.psidts)
    if success:
        return {"status": "ok", "message": f"Account {req.account_id} cookies updated and browser reloaded"}
    raise HTTPException(503, f"Account {req.account_id} failed to initialize with new cookies")


@app.get("/check-account/{account_id}")
async def check_account(account_id: str):
    acc = pool.accounts.get(account_id)
    if not acc:
        raise HTTPException(404, f"Account {account_id} not found")
    await acc.obtain_token()
    if acc.healthy:
        state_file = STATE_DIR / f"{account_id}.json"
        await acc.context.storage_state(path=str(state_file))
    return {
        "account_id": account_id,
        "valid": acc.healthy,
        "has_token": bool(acc.session_token),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/check-all")
async def check_all():
    results = []
    for acc_id, acc in pool.accounts.items():
        await acc.obtain_token()
        if acc.healthy:
            state_file = STATE_DIR / f"{acc_id}.json"
            await acc.context.storage_state(path=str(state_file))
        results.append({
            "account_id": acc_id,
            "valid": acc.healthy,
            "has_token": bool(acc.session_token),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    return {"accounts": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

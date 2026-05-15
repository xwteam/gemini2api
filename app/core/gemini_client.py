import re
import json
import hashlib
import asyncio
import logging
from pathlib import Path
from threading import Lock
from collections import deque
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)


class HTTPStatusError(Exception):
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {text[:200]}")

GEMINI_APP_URL = "https://gemini.google.com/app"
GEMINI_HOME_URL = "https://gemini.google.com/?hl=en"
GEMINI_APP_EN_URL = "https://gemini.google.com/app?hl=en"
GOOGLE_HOME_URL = "https://www.google.com/"
ROTATE_COOKIES_URL = "https://accounts.google.com/RotateCookies"
GENERATE_URL = (
    "https://gemini.google.com/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)

COOKIE_CACHE_DIR = Path(".cookies")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "X-Same-Domain": "1",
    "Origin": "https://gemini.google.com",
    "Referer": "https://gemini.google.com/",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


class GeminiWebClient:
    def __init__(self, psid: str | None = None, psidts: str | None = None):
        self._psid = psid or settings.gemini_psid
        self._psidts = psidts or settings.gemini_psidts
        self._session_token: str = ""
        self._available_models: list[str] = []
        self._lock = Lock()
        self._healthy = False
        self._refresh_task: asyncio.Task | None = None
        self._health_check_task: asyncio.Task | None = None
        self._http: AsyncSession | None = None
        self._check_history: deque[dict] = deque(maxlen=20)
        self._last_check_result: dict | None = None

    async def initialize(self):
        self._http = AsyncSession(
            impersonate="chrome120",
            headers=DEFAULT_HEADERS,
            timeout=60,
        )
        self._load_cached_cookies()
        await self._obtain_session_token()

        if self._session_token:
            self._healthy = True
            logger.info("Gemini client ready")
        else:
            logger.warning("Token not found, rotating cookies")
            if await self._rotate_cookies():
                await self._obtain_session_token()
                if self._session_token:
                    self._healthy = True
                    logger.info("Client ready after rotation")

        if self._healthy:
            self._save_cookies_to_cache()
            self._ensure_refresh_task()

        if settings.health_check_enabled:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def models(self) -> list[str]:
        return list(self._available_models)

    @property
    def last_check_result(self) -> dict | None:
        return self._last_check_result

    @property
    def check_history(self) -> list[dict]:
        return list(self._check_history)

    async def check_account(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        try:
            cookies = self._build_cookies()
            resp = await self._http.get(GEMINI_APP_EN_URL, cookies=cookies)

            if resp.status_code != 200:
                result = {
                    "valid": False,
                    "has_token": False,
                    "models_count": 0,
                    "checked_at": now,
                    "error": f"HTTP {resp.status_code}",
                }
            else:
                body = resp.text
                token_match = re.search(r'"SNlM0e":"([^"]+)"', body)
                model_hits = re.findall(r"gemini-[a-zA-Z0-9.\-]+", body)
                models_found = sorted(set(m for m in model_hits if len(m) > 10))

                result = {
                    "valid": token_match is not None,
                    "has_token": token_match is not None,
                    "models_count": len(models_found),
                    "checked_at": now,
                }
        except Exception as e:
            result = {
                "valid": False,
                "has_token": False,
                "models_count": 0,
                "checked_at": now,
                "error": str(e),
            }

        self._last_check_result = result
        self._check_history.append(result)
        return result

    async def _health_check_loop(self):
        interval = settings.health_check_interval * 60
        consecutive_failures = 0
        while True:
            await asyncio.sleep(interval)
            try:
                result = await self.check_account()
                if result["valid"]:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f"Health check failed ({consecutive_failures}x)")
                    if consecutive_failures >= 3:
                        self._healthy = False
                        logger.error("Account unhealthy: 3 consecutive check failures")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")

    def _cookie_cache_path(self) -> Path:
        digest = hashlib.sha256(self._psid.encode()).hexdigest()[:16]
        return COOKIE_CACHE_DIR / f"{digest}.txt"

    def _load_cached_cookies(self):
        path = self._cookie_cache_path()
        if path.exists():
            cached = path.read_text().strip()
            if cached and not self._psidts:
                self._psidts = cached
                logger.info("Loaded PSIDTS from cache")

    def _save_cookies_to_cache(self):
        if not self._psidts:
            return
        COOKIE_CACHE_DIR.mkdir(exist_ok=True)
        self._cookie_cache_path().write_text(self._psidts)

    def _build_cookies(self) -> dict[str, str]:
        cookies = {"__Secure-1PSID": self._psid}
        if self._psidts:
            cookies["__Secure-1PSIDTS"] = self._psidts
        return cookies

    async def _obtain_session_token(self):
        try:
            cookies = self._build_cookies()
            await self._http.get(GOOGLE_HOME_URL, cookies=cookies)
            await self._http.get(GEMINI_HOME_URL, cookies=cookies)
            resp = await self._http.get(GEMINI_APP_EN_URL, cookies=cookies)

            if resp.status_code != 200:
                logger.error(f"App page status: {resp.status_code}")
                return

            body = resp.text
            token_match = re.search(r'"SNlM0e":"([^"]+)"', body)
            if token_match:
                self._session_token = token_match.group(1)
                logger.info("Session token acquired")
            else:
                logger.error("SNlM0e not found in response")
                return

            model_hits = re.findall(r"gemini-[a-zA-Z0-9.\-]+", body)
            discovered = sorted(set(m for m in model_hits if len(m) > 10))
            if discovered:
                self._available_models = discovered
                logger.info(f"Discovered {len(discovered)} models")
        except Exception as e:
            logger.error(f"Token extraction failed: {e}")

    async def _rotate_cookies(self) -> bool:
        try:
            cookies = self._build_cookies()
            body = '[000,"-0000000000000000000"]'
            resp = await self._http.post(
                ROTATE_COOKIES_URL,
                content=body.encode(),
                cookies=cookies,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://accounts.google.com",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"RotateCookies returned {resp.status_code}")
                return False
            new_ts = resp.cookies.get("__Secure-1PSIDTS")
            if new_ts:
                with self._lock:
                    self._psidts = new_ts
                self._save_cookies_to_cache()
                logger.info("PSIDTS rotated via set-cookie")
                return True
            logger.debug("RotateCookies 200 but no new PSIDTS (session still valid)")
            return True
        except Exception as e:
            logger.error(f"Rotation failed: {e}")
            return False

    async def _auto_refresh_loop(self):
        interval = settings.refresh_interval * 60
        while True:
            await asyncio.sleep(interval)
            try:
                rotated = await self._rotate_cookies()
                if not rotated:
                    logger.warning("Rotation failed, re-fetching token directly")
                await self._obtain_session_token()
                if self._session_token:
                    self._healthy = True
                    logger.info("Auto-refresh: session token refreshed")
                else:
                    self._healthy = False
                    logger.error("Auto-refresh failed, client unhealthy")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Refresh loop error: {e}")

    def _encode_payload(self, prompt: str, model: str) -> str:
        inner = json.dumps([[prompt], None, None, model])
        outer = json.dumps([None, inner])
        return outer

    async def generate(self, prompt: str, model: str) -> dict:
        if not self._healthy:
            raise RuntimeError("Client not ready")

        if model not in self._available_models:
            raise ValueError(
                f"Model '{model}' unavailable. "
                f"Options: {', '.join(self._available_models[:10])}"
            )

        last_err = None
        for attempt in range(settings.max_retries):
            try:
                return await self._send_request(prompt, model)
            except HTTPStatusError as e:
                last_err = e
                status = e.status_code
                if 400 <= status < 500:
                    if status in (401, 403):
                        self._healthy = False
                    raise
                wait = 2 ** attempt
                logger.warning(f"Attempt {attempt+1}: status {status}, wait {wait}s")
                await asyncio.sleep(wait)
            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(f"Attempt {attempt+1}: {e}, wait {wait}s")
                await asyncio.sleep(wait)

        raise RuntimeError(f"Exhausted {settings.max_retries} retries: {last_err}")

    async def _send_request(self, prompt: str, model: str) -> dict:
        encoded = self._encode_payload(prompt, model)
        form_data = {"at": self._session_token, "f.req": encoded}
        cookies = self._build_cookies()
        resp = await self._http.post(GENERATE_URL, data=form_data, cookies=cookies)
        if resp.status_code >= 400:
            raise HTTPStatusError(resp.status_code, resp.text[:200])
        return self._parse_output(resp.text)

    def _parse_output(self, raw: str) -> dict:
        lines = raw.strip().split("\n")
        text_content = ""
        conv_id = ""

        for line in lines:
            line = line.strip()
            if not line or line.startswith(")]}'"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list):
                continue

            for item in data:
                if not isinstance(item, list) or len(item) < 3:
                    continue
                raw_payload = item[2]
                if not isinstance(raw_payload, str):
                    continue
                try:
                    payload = json.loads(raw_payload)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(payload, list) or len(payload) < 5:
                    continue

                candidates = payload[4]
                if not isinstance(candidates, list) or not candidates:
                    continue
                candidate = candidates[0]
                if isinstance(candidate, list) and len(candidate) > 1:
                    parts = candidate[1]
                    if isinstance(parts, list) and parts and isinstance(parts[0], str):
                        text_content = parts[0]
                if payload[1]:
                    conv_id = str(payload[1])

        return {"text": text_content, "conversation_id": conv_id}

    async def shutdown(self):
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.close()

    async def reload_cookies(self, psid: str | None = None, psidts: str | None = None):
        if psid:
            self._psid = psid.strip().strip('"').strip("'").rstrip(";")
        if psidts:
            self._psidts = psidts.strip().strip('"').strip("'").rstrip(";")

        self._session_token = ""
        self._healthy = False

        await self._obtain_session_token()
        if self._session_token:
            self._healthy = True
            self._save_cookies_to_cache()
            self._ensure_refresh_task()
            logger.info("Cookies reloaded successfully")
            return True

        rotated = await self._rotate_cookies()
        if rotated:
            await self._obtain_session_token()
            if self._session_token:
                self._healthy = True
                self._save_cookies_to_cache()
                self._ensure_refresh_task()
                logger.info("Cookies reloaded after rotation")
                return True

        logger.error("Cookie reload failed")
        return False

    def _ensure_refresh_task(self):
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
            logger.info("Auto-refresh loop started")


gemini_client = GeminiWebClient()

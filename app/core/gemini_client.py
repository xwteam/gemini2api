import re
import json
import hashlib
import asyncio
import logging
from pathlib import Path
from threading import Lock

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

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
    def __init__(self):
        self._psid = settings.gemini_psid
        self._psidts = settings.gemini_psidts
        self._session_token: str = ""
        self._available_models: list[str] = []
        self._lock = Lock()
        self._healthy = False
        self._refresh_task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None

    async def initialize(self):
        self._http = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
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
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def models(self) -> list[str]:
        return list(self._available_models)

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
                content=body,
                cookies=cookies,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            for hdr in resp.headers.get_list("set-cookie"):
                if "__Secure-1PSIDTS=" in hdr:
                    new_ts = hdr.split("__Secure-1PSIDTS=")[1].split(";")[0]
                    with self._lock:
                        self._psidts = new_ts
                    self._save_cookies_to_cache()
                    logger.info("Cookies rotated")
                    return True
            logger.warning("PSIDTS not in rotation response")
            return False
        except Exception as e:
            logger.error(f"Rotation failed: {e}")
            return False

    async def _auto_refresh_loop(self):
        interval = settings.refresh_interval * 60
        while True:
            await asyncio.sleep(interval)
            try:
                if not await self._rotate_cookies():
                    logger.warning("Rotation failed in refresh, re-fetching token")
                await self._obtain_session_token()
                if not self._session_token:
                    self._healthy = False
                    logger.error("Refresh failed, client unhealthy")
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
            except httpx.HTTPStatusError as e:
                last_err = e
                status = e.response.status_code
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
        resp.raise_for_status()
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
        if self._http:
            await self._http.aclose()


gemini_client = GeminiWebClient()

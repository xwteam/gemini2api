import re
import json
import asyncio
import logging
from pathlib import Path
from threading import Lock
from collections import deque
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession

from app.config import settings
from app.core.fingerprint.config import fingerprint_config
from app.core.fingerprint.header_builder import header_builder
from app.core.fingerprint.cookie_jar import PersistentCookieJar
from app.core.fingerprint.jitter import apply_jitter, random_delay_factor

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
BATCHEXECUTE_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"


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
        self._cookie_jar: PersistentCookieJar | None = None
        self._current_target: str = ""
        self._check_history: deque[dict] = deque(maxlen=20)
        self._last_check_result: dict | None = None
        self._last_reload_error: str = ""

    async def initialize(self):
        fingerprint_config.load()

        self._cookie_jar = PersistentCookieJar(self._psid)
        self._cookie_jar.set("__Secure-1PSID", self._psid)
        if self._psidts:
            self._cookie_jar.set("__Secure-1PSIDTS", self._psidts)

        self._current_target = header_builder.get_impersonate_target()
        self._http = AsyncSession(
            impersonate=self._current_target,
            timeout=60,
        )

        await self._obtain_session_token()

        if self._session_token:
            self._healthy = True
            await self._send_heartbeat()
            logger.info("Gemini client ready")
        else:
            logger.warning("Token not found, rotating cookies")
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

    async def _ensure_session_current(self):
        """检查 impersonate 目标是否需要更新"""
        target = header_builder.get_impersonate_target()
        if self._current_target != target:
            logger.info(f"TLS 指纹更新: {self._current_target} -> {target}")
            await self._http.close()
            self._http = AsyncSession(impersonate=target, timeout=60)
            self._current_target = target

    def _get_cookies(self) -> dict[str, str]:
        return self._cookie_jar.get_all()

    def _get_headers(self, method: str = "GET", content_type: str | None = None) -> dict:
        return dict(header_builder.build(url=GEMINI_APP_URL, method=method, content_type=content_type))

    async def check_account(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self._ensure_session_current()
            self._clear_session_cookies()
            cookies = self._get_cookies()
            headers = self._get_headers("GET")
            resp = await self._http.get(GEMINI_APP_EN_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

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
            await asyncio.sleep(interval * random_delay_factor())
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

    def _clear_session_cookies(self):
        """Clear curl_cffi's internal cookie jar to prevent cross-domain accumulation."""
        try:
            self._http.cookies.clear()
        except Exception:
            pass

    async def _obtain_session_token(self):
        try:
            await self._ensure_session_current()
            cookies = self._get_cookies()
            headers = self._get_headers("GET")

            await apply_jitter("navigation")
            self._clear_session_cookies()
            resp = await self._http.get(GOOGLE_HOME_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            await apply_jitter("navigation")
            self._clear_session_cookies()
            cookies = self._get_cookies()
            resp = await self._http.get(GEMINI_HOME_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            await apply_jitter("navigation")
            self._clear_session_cookies()
            cookies = self._get_cookies()
            resp = await self._http.get(GEMINI_APP_EN_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            if resp.status_code != 200:
                msg = f"Gemini returned HTTP {resp.status_code}"
                logger.error(msg)
                self._last_reload_error = msg
                self._session_token = ""
                return

            body = resp.text
            token_match = re.search(r'"SNlM0e":"([^"]+)"', body)
            if token_match:
                self._session_token = token_match.group(1)
                logger.info("Session token acquired")
            else:
                self._session_token = ""
                if "accounts.google.com" in body or "ServiceLogin" in body:
                    msg = "Cookie expired - redirected to Google login page"
                elif len(body) < 1000:
                    msg = f"Invalid response (body too short: {len(body)} bytes)"
                else:
                    msg = "SNlM0e token not found (cookie may be invalid or expired)"
                logger.error(msg)
                self._last_reload_error = msg
                return

            model_hits = re.findall(r"gemini-[a-zA-Z0-9.\-]+", body)
            discovered = sorted(set(m for m in model_hits if len(m) > 10))
            if discovered:
                self._available_models = discovered
                logger.info(f"Discovered {len(discovered)} models")
        except Exception as e:
            msg = f"Token extraction failed: {e}"
            logger.error(msg)
            self._last_reload_error = msg
            self._session_token = ""

    async def _rotate_cookies(self) -> bool:
        try:
            await apply_jitter("cookie_rotate")
            await self._ensure_session_current()
            self._clear_session_cookies()
            cookies = self._get_cookies()
            cookie_names = sorted(cookies.keys())
            logger.debug(f"RotateCookies sending {len(cookies)} cookies: {cookie_names}")
            body = '[000,"-0000000000000000000"]'
            resp = await self._http.post(
                ROTATE_COOKIES_URL,
                data=body.encode(),
                cookies=cookies,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://accounts.google.com",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"RotateCookies returned {resp.status_code}")
                return False

            self._cookie_jar.update_from_response(resp)

            new_ts = resp.cookies.get("__Secure-1PSIDTS")
            if new_ts:
                with self._lock:
                    self._psidts = new_ts
                self._cookie_jar.set("__Secure-1PSIDTS", new_ts)
                logger.info("PSIDTS rotated successfully")
                return True

            resp_text = resp.text[:200] if resp.text else "(empty)"
            logger.warning(f"RotateCookies 200 but no new PSIDTS. Response: {resp_text}")
            return False
        except Exception as e:
            logger.error(f"Rotation failed: {e}")
            return False

    async def _send_heartbeat(self) -> bool:
        """Send batchexecute RPC to simulate browser activity (settings sync)."""
        if not self._session_token:
            return False
        try:
            await apply_jitter("api_call")
            await self._ensure_session_current()
            self._clear_session_cookies()

            rpc_id = "otAQ7b"
            inner_payload = json.dumps([None, None, None, None, None, None, None, None, [1]])
            req_data = json.dumps([[rpc_id, inner_payload, None, "generic"]])
            form_data = {"f.req": req_data, "at": self._session_token}

            cookies = self._get_cookies()
            headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")

            resp = await self._http.post(
                BATCHEXECUTE_URL, data=form_data, cookies=cookies, headers=headers
            )
            self._cookie_jar.update_from_response(resp)

            if resp.status_code == 200:
                logger.debug("Heartbeat OK")
                return True
            else:
                logger.warning(f"Heartbeat returned {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")
            return False

    async def _auto_refresh_loop(self):
        interval = settings.refresh_interval * 60
        consecutive_failures = 0
        while True:
            await asyncio.sleep(interval * random_delay_factor())
            try:
                rotated = await self._rotate_cookies()
                if not rotated:
                    consecutive_failures += 1
                    logger.warning(f"Rotation returned no new PSIDTS ({consecutive_failures}x)")
                else:
                    consecutive_failures = 0

                await self._obtain_session_token()
                if self._session_token:
                    self._healthy = True
                    await self._send_heartbeat()
                    logger.info("Auto-refresh: token OK")
                else:
                    self._healthy = False
                    logger.error("Auto-refresh: token fetch failed, client unhealthy")
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
        await apply_jitter("api_call")
        await self._ensure_session_current()
        self._clear_session_cookies()

        encoded = self._encode_payload(prompt, model)
        form_data = {"at": self._session_token, "f.req": encoded}
        cookies = self._get_cookies()
        headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")

        resp = await self._http.post(GENERATE_URL, data=form_data, cookies=cookies, headers=headers)
        self._cookie_jar.update_from_response(resp)

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

    async def reload_cookies(self, psid: str | None = None, psidts: str | None = None) -> dict:
        if psid:
            self._psid = psid.strip().strip('"').strip("'").rstrip(";")
        if psidts:
            self._psidts = psidts.strip().strip('"').strip("'").rstrip(";")

        self._session_token = ""
        self._healthy = False
        self._last_reload_error = ""

        # Recreate HTTP session to avoid accumulated cookie conflicts
        if self._http:
            await self._http.close()
        self._http = AsyncSession(impersonate=self._current_target, timeout=60)

        self._cookie_jar.set("__Secure-1PSID", self._psid)
        if self._psidts:
            self._cookie_jar.set("__Secure-1PSIDTS", self._psidts)

        await self._obtain_session_token()
        if self._session_token:
            self._healthy = True
            self._ensure_refresh_task()
            logger.info("Cookies reloaded successfully")
            return {"success": True}

        first_error = self._last_reload_error or "SNlM0e token not found"

        rotated = await self._rotate_cookies()
        if rotated:
            await self._obtain_session_token()
            if self._session_token:
                self._healthy = True
                self._ensure_refresh_task()
                logger.info("Cookies reloaded after rotation")
                return {"success": True}

        error_msg = self._last_reload_error or first_error
        logger.error(f"Cookie reload failed: {error_msg}")
        return {"success": False, "error": error_msg}

    def _ensure_refresh_task(self):
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
            logger.info("Auto-refresh loop started")


gemini_client = GeminiWebClient()

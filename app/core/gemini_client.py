import re
import json
import time
import random
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
from app.core.usage_metrics import live_metrics

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

MODEL_HEADER_KEY = "x-goog-ext-525001261-jspb"

GEMINI_MODELS = {
    "gemini-3-pro": {"id": "9d8ca3786ebdfbea", "capacity": 1, "pro_only": False, "family": "pro"},
    "gemini-3-flash": {"id": "fbb127bbb056c959", "capacity": 1, "pro_only": False, "family": "flash"},
    "gemini-3-flash-thinking": {"id": "5bf011840784117a", "capacity": 1, "pro_only": False, "family": "flash-thinking"},
    "gemini-3-pro-plus": {"id": "e6fa609c3fa255c0", "capacity": 4, "pro_only": True, "family": "pro"},
    "gemini-3-flash-plus": {"id": "56fdd199312815e2", "capacity": 4, "pro_only": True, "family": "flash"},
    "gemini-3-flash-thinking-plus": {"id": "e051ce1aa80aa576", "capacity": 4, "pro_only": True, "family": "flash-thinking"},
    "gemini-3-pro-advanced": {"id": "e6fa609c3fa255c0", "capacity": 2, "pro_only": True, "family": "pro"},
    "gemini-3-flash-advanced": {"id": "56fdd199312815e2", "capacity": 2, "pro_only": True, "family": "flash"},
    "gemini-3-flash-thinking-advanced": {"id": "e051ce1aa80aa576", "capacity": 2, "pro_only": True, "family": "flash-thinking"},
}

# 对外暴露的稳定模型名（永不变，API 契约）。客户端只认这 3 个，
# 内部按账号当前真实可用的模型动态映射，账号订阅等级/Google 灰度怎么变都不影响 API。
PUBLIC_MODELS = ["gemini-pro", "gemini-flash", "gemini-flash-thinking"]
_PUBLIC_FAMILY = {
    "gemini-pro": "pro",
    "gemini-flash": "flash",
    "gemini-flash-thinking": "flash-thinking",
}
# 每个 family 的默认内部模型（账号没拉到真实模型时的兜底，按基础版）
_FAMILY_DEFAULT = {
    "pro": "gemini-3-pro",
    "flash": "gemini-3-flash",
    "flash-thinking": "gemini-3-flash-thinking",
}

MODEL_ALIASES = {
    # 旧版别名 → 公开名（再由公开名按账号动态解析），保留兼容
    "gemini-2.5-pro": "gemini-pro",
    "gemini-2.5-flash": "gemini-flash",
    "gemini-2.5-flash-thinking": "gemini-flash-thinking",
    "gemini-2.5-pro-preview-05-06": "gemini-pro",
    "gemini-2.5-flash-preview-04-17": "gemini-flash",
    "gemini-2.5-flash-preview-05-20": "gemini-flash",
    "gemini-2.0-flash": "gemini-flash",
    "gemini-2.0-flash-thinking": "gemini-flash-thinking",
    "gemini-2.0-flash-lite": "gemini-flash",
    "gemini-1.5-pro": "gemini-pro",
    "gemini-1.5-flash": "gemini-flash",
}

KNOWN_MODELS = list(GEMINI_MODELS.keys())


def _build_id_alias_map() -> dict[str, str]:
    """内部 model_id -> 内部模型名（用于状态接口解析）。"""
    return {info["id"]: name for name, info in GEMINI_MODELS.items()}



def _resolve_model(model_name: str, family_model: dict[str, str] | None = None) -> str:
    """把用户请求的模型名解析为账号当前真实可用的内部模型名。
    1. 旧别名 → 公开名
    2. 公开名（gemini-pro/flash/flash-thinking）→ 账号当前该 family 真实可用的内部模型
       （family_model 为账号实例映射，缺省/未命中则用 family 默认）
    3. 已经是内部模型名（gemini-3-*）→ 原样

    family_model: 账号实例的 family→真实模型映射（P0-5：避免模块级全局被多账号污染）。
                  路由层仅做模型名校验时不传，退回 _FAMILY_DEFAULT。
    """
    name = MODEL_ALIASES.get(model_name, model_name)
    if name in _PUBLIC_FAMILY:
        family = _PUBLIC_FAMILY[name]
        fm = family_model or {}
        return fm.get(family) or _FAMILY_DEFAULT[family]
    return name


def _build_model_header(model_name: str) -> dict[str, str]:
    resolved = _resolve_model(model_name)
    model_info = GEMINI_MODELS.get(resolved)
    if not model_info:
        return {}
    return {
        MODEL_HEADER_KEY: f'[1,null,null,null,"{model_info["id"]}",null,null,0,[4],null,null,{model_info["capacity"]}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0]",
    }


MODELS_CACHE_FILE = Path("data/models_cache.json")

# 生图/找图时模型回复文本里会带这种 googleusercontent 占位 URL（无实际意义，
# 真图在 images 字段里；image_retrieval/image_collection 是检索占位，客户端访问无效）。
# 流式与非流式都要过滤掉，避免显示成网址。预编译复用。
_IMAGE_GEN_PLACEHOLDER_RE = re.compile(
    r'https?://googleusercontent\.com/(?:image_generation_content|image_retrieval|image_collection)[/\w]*\d*'
)


def _scan_complete_wrb_frames(buf: str) -> tuple[list, int]:
    """从流式累积 buffer 中切出所有完整的 `["wrb.fr",...]` 顶层元素。

    Gemini StreamGenerate 的响应是 `)]}'\\n\\n` 前缀 + 一个不断增长的 JSON 数组，
    元素形如 `["wrb.fr",null,"<json字符串>",...]` 逐个流式追加（chunk 边界随意切，
    一帧可能跨多个 chunk）。这里用括号深度扫描（正确处理字符串与转义）切出每个
    已闭合的完整元素，返回 (已解析的元素列表, 已消费到的 buffer 偏移量)。
    未闭合的尾部留给下一个 chunk 继续累积。
    """
    frames: list = []
    consumed = 0
    i = 0
    n = len(buf)
    while i < n:
        start = buf.find('["wrb.fr"', i)
        if start == -1:
            break
        # 从 start 开始做括号深度匹配，切出完整的 [...] 元素
        depth = 0
        in_str = False
        esc = False
        end = -1
        j = start
        while j < n:
            c = buf[j]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            j += 1
        if end == -1:
            # 这个元素还没接收完整，停在这里，下个 chunk 再来
            break
        elem_str = buf[start:end + 1]
        try:
            elem = json.loads(elem_str)
            frames.append(elem)
        except Exception:
            pass
        consumed = end + 1
        i = end + 1
    return frames, consumed


def _extract_text_from_wrb(elem: list) -> tuple[str | None, str]:
    """从单个 wrb.fr 帧提取 (累积文本, 会话ID)。非文本帧返回 (None, "")。
    文本路径 payload[4][0][1][0]；会话ID 用 str(payload[1])，与非流式 _parse_output
    逐字节一致（会话ID 会存进 conversation_store，下轮回传给 _encode_payload 续接会话，
    流式与非流式必须同格式，否则多轮对话续接会错乱）。
    """
    try:
        if not isinstance(elem, list) or len(elem) < 3 or elem[0] != "wrb.fr":
            return None, ""
        rp = elem[2]
        if not isinstance(rp, str):
            return None, ""
        payload = json.loads(rp)
        if not isinstance(payload, list) or len(payload) < 5:
            return None, ""
        conv = str(payload[1]) if payload[1] else ""
        text = None
        cands = payload[4]
        if isinstance(cands, list) and cands:
            c0 = cands[0]
            if isinstance(c0, list) and len(c0) > 1 and isinstance(c0[1], list) \
                    and c0[1] and isinstance(c0[1][0], str):
                text = c0[1][0]
        return text, conv
    except Exception:
        return None, ""


MODEL_VALID_PATTERN = re.compile(
    r"gemini-(\d+)\.(\d+)-([a-z]+)(?:-([a-z]+))?(?:-preview)?(?:-\d{2}-\d{2})?"
)


def _filter_valid_models(raw_hits: list[str]) -> list[str]:
    """只保留格式正确的模型名，排除明显无效的"""
    valid = []
    seen = set()
    for m in raw_hits:
        if m in seen:
            continue
        if not MODEL_VALID_PATTERN.match(m):
            continue
        if len(m) < 12 or len(m) > 50:
            continue
        # 排除明显是版本号片段的（如 gemini-1.0-ultra-latest-something-else）
        parts = m.split("-")
        if len(parts) > 7:
            continue
        seen.add(m)
        valid.append(m)
    return sorted(valid)


def _load_models_cache() -> list[str]:
    try:
        if MODELS_CACHE_FILE.exists():
            with open(MODELS_CACHE_FILE, "r") as f:
                data = json.load(f)
            return data.get("models", [])
    except Exception:
        pass
    return []


def _save_models_cache(models: list[str]):
    try:
        MODELS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MODELS_CACHE_FILE, "w") as f:
            json.dump({"models": models, "updated_at": time.time()}, f)
    except Exception:
        pass


# 文件上传需要的 push_id；从 Gemini 页面 body 提取，抓不到用兜底值
_DEFAULT_PUSH_ID = "feeds/mcudyrk2a4khkz"


def _extract_push_id(body: str) -> str:
    """从 Gemini 页面 HTML 里提取 push_id（上传文件用）。
    常见形态为 feeds/<id>。抓不到回退到已知兜底值。
    """
    m = re.search(r'feeds/([a-zA-Z0-9_-]+)', body)
    if m:
        return f"feeds/{m.group(1)}"
    return _DEFAULT_PUSH_ID


def _rand_reqid() -> int:
    """batchexecute 需要的 _reqid 参数。"""
    return random.randint(10000, 99999)



class GeminiWebClient:
    def __init__(self, psid: str | None = None, psidts: str | None = None):
        self._psid = psid or settings.gemini_psid
        self._psidts = psidts or settings.gemini_psidts
        self._session_token: str = ""
        self._push_id: str = ""
        self._available_models: list[str] = []
        self._lock = Lock()
        # 按账号实例存储 family→真实内部模型，避免模块级全局被多账号互相覆盖（P0-5）
        self._family_model: dict[str, str] = {}
        # 自愈单飞锁（asyncio）：并发命中 "not ready" 时只触发一次 reload_cookies（Issue#1-C）。
        # 注意：上面的 self._lock 是 threading.Lock，不支持 async with，故另设异步锁。
        self._heal_lock = asyncio.Lock()
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
        # cookie_jar 启动时已从磁盘加载持久化 Cookie。
        # 若磁盘有有效的 PSID/PSIDTS（面板更新后持久化的最新值），优先用磁盘的，
        # 避免被 .env 里的旧值覆盖导致重启丢 Cookie。
        persisted = self._cookie_jar.get_all()
        disk_psid = persisted.get("__Secure-1PSID")
        disk_psidts = persisted.get("__Secure-1PSIDTS")
        if disk_psid:
            self._psid = disk_psid
            if disk_psidts:
                self._psidts = disk_psidts
            logger.info("Loaded persisted cookies from disk")
        else:
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
                model_hits = re.findall(r"gemini-\d+\.\d+[a-zA-Z0-9.\-]+", body)
                models_found = _filter_valid_models(model_hits)

                if token_match:
                    self._session_token = token_match.group(1)
                    self._push_id = _extract_push_id(body)
                    self._healthy = True
                    await self._send_heartbeat()  # 拉取账号真实可用模型

                result = {
                    "valid": token_match is not None,
                    "has_token": token_match is not None,
                    "models_count": len(self._available_models) or len(models_found),
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
                self._push_id = _extract_push_id(body)
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

            # 不再用正则从 HTML 抓模型（会抓到过时/不可用的脏数据）。
            # 真实可用模型由 _send_heartbeat 调 otAQ7b 状态接口解析。
            # 对外始终是固定公开名（API 稳定契约），状态接口只决定内部映射到哪个真实模型。
            if not self._available_models:
                self._available_models = list(PUBLIC_MODELS)
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
                live_metrics.record_rotation(False)
                return False

            self._cookie_jar.update_from_response(resp)

            new_ts = resp.cookies.get("__Secure-1PSIDTS")
            if new_ts:
                with self._lock:
                    self._psidts = new_ts
                self._cookie_jar.set("__Secure-1PSIDTS", new_ts)
                logger.info("PSIDTS rotated successfully")
                live_metrics.record_rotation(True)
                return True

            resp_text = resp.text[:200] if resp.text else "(empty)"
            logger.warning(f"RotateCookies 200 but no new PSIDTS. Response: {resp_text}")
            live_metrics.record_rotation(False)
            return False
        except Exception as e:
            logger.error(f"Rotation failed: {e}")
            live_metrics.record_rotation(False)
            return False

    async def _send_heartbeat(self) -> bool:
        """调 otAQ7b(GetUserStatus) RPC：既保活又拉取账号真实可用模型。
        必须带正确的 URL params 和 x-goog-ext header，否则 Google 返回 400。
        """
        if not self._session_token:
            return False
        try:
            await apply_jitter("api_call")
            await self._ensure_session_current()
            self._clear_session_cookies()

            rpc_id = "otAQ7b"
            # RPCData.serialize 格式：[rpcid, payload, null, "generic"]，外层再包一层 [[...]]
            req_data = json.dumps([[[rpc_id, "[]", None, "generic"]]])
            form_data = {"f.req": req_data, "at": self._session_token}

            params = {
                "rpcids": rpc_id,
                "hl": "en",
                "_reqid": str(_rand_reqid()),
                "rt": "c",
                "source-path": "/app",
            }

            cookies = self._get_cookies()
            headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
            headers.update({
                "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
                "x-goog-ext-73010989-jspb": "[0]",
                "X-Same-Domain": "1",
            })

            resp = await self._http.post(
                BATCHEXECUTE_URL, params=params, data=form_data, cookies=cookies, headers=headers
            )
            self._cookie_jar.update_from_response(resp)

            if resp.status_code == 200:
                logger.debug("Heartbeat OK")
                self._parse_models_from_status(resp.text)
                return True
            else:
                logger.warning(f"Heartbeat returned {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")
            return False

    async def _batchexecute(self, rpc_id: str, payload_str: str) -> str | None:
        """通用 batchexecute 调用，复用心跳的 URL params + headers 模板。
        成功返回响应文本，失败返回 None。payload_str 是已 json.dumps 的内层 payload。
        """
        if not self._session_token:
            return None
        try:
            await apply_jitter("api_call")
            await self._ensure_session_current()
            self._clear_session_cookies()

            req_data = json.dumps([[[rpc_id, payload_str, None, "generic"]]])
            form_data = {"f.req": req_data, "at": self._session_token}
            params = {
                "rpcids": rpc_id,
                "hl": "en",
                "_reqid": str(_rand_reqid()),
                "rt": "c",
                "source-path": "/app",
            }
            cookies = self._get_cookies()
            headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
            headers.update({
                "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
                "x-goog-ext-73010989-jspb": "[0]",
                "X-Same-Domain": "1",
            })
            resp = await self._http.post(
                BATCHEXECUTE_URL, params=params, data=form_data, cookies=cookies, headers=headers
            )
            self._cookie_jar.update_from_response(resp)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"batchexecute {rpc_id} returned {resp.status_code}")
            return None
        except Exception as e:
            logger.warning(f"batchexecute {rpc_id} error: {e}")
            return None

    @staticmethod
    def _parse_wrb_body(raw: str, rpc_id: str):
        """从 batchexecute 响应里取出指定 rpc 的 body（已 json.loads）。找不到返回 None。"""
        if not raw:
            return None
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line.startswith("[["):
                continue
            try:
                outer = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            for item in outer:
                if not (isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr"):
                    continue
                # item[1] 是 rpc id（有时为 None），item[2] 是 body 字符串
                if item[1] not in (rpc_id, None):
                    continue
                body_str = item[2]
                if not isinstance(body_str, str):
                    continue
                try:
                    return json.loads(body_str)
                except (json.JSONDecodeError, ValueError):
                    continue
        return None

    async def list_web_chats(self, recent: int = 300) -> list[dict]:
        """列出账号在 Gemini 网页端的会话（MaZiqc / LIST_CHATS）。
        发两次（[N,None,[1,None,1]] + [N,None,[0,None,1]]）合并去重，
        每项解析 cid=[0] title=[1] pinned=[2] timestamp=[5]([秒,纳秒])。
        返回 [{cid, title, pinned, ts}]，按 ts 降序。失败返回 []。
        """
        rpc_id = "MaZiqc"
        seen: dict[str, dict] = {}
        for flag in (1, 0):
            payload = json.dumps([recent, None, [flag, None, 1]])
            raw = await self._batchexecute(rpc_id, payload)
            body = self._parse_wrb_body(raw, rpc_id)
            if not isinstance(body, list) or len(body) < 3:
                continue
            chat_list = body[2]
            if not isinstance(chat_list, list):
                continue
            for chat in chat_list:
                if not (isinstance(chat, list) and chat and isinstance(chat[0], str)):
                    continue
                cid = chat[0]
                if cid in seen:
                    continue
                title = chat[1] if len(chat) > 1 and isinstance(chat[1], str) else ""
                pinned = bool(chat[2]) if len(chat) > 2 else False
                ts = 0.0
                if len(chat) > 5 and isinstance(chat[5], list) and chat[5]:
                    try:
                        sec = float(chat[5][0])
                        nanos = float(chat[5][1]) if len(chat[5]) > 1 else 0.0
                        ts = sec + nanos / 1e9
                    except (TypeError, ValueError, IndexError):
                        ts = 0.0
                seen[cid] = {"cid": cid, "title": title, "pinned": pinned, "ts": ts}
        return sorted(seen.values(), key=lambda c: c["ts"], reverse=True)

    async def delete_web_chat(self, cid: str) -> bool:
        """删除一个网页端会话（两步 RPC：GzXR5e -> qWymEb，两步都必须执行）。
        cid 是 c_xxx 形式的会话 id。两步都返回 200 视为成功。
        """
        if not cid or not cid.startswith("c_"):
            logger.warning(f"delete_web_chat: 无效 cid {cid!r}")
            return False
        raw1 = await self._batchexecute("GzXR5e", json.dumps([cid]))
        if raw1 is None:
            return False
        raw2 = await self._batchexecute("qWymEb", json.dumps([cid, [1, None, 0, 1]]))
        if raw2 is None:
            return False
        return True

    async def cleanup_old_web_chats(self, keep_hours: float = 24.0,
                                    skip_pinned: bool = True) -> dict:
        """清理超过 keep_hours 的网页端会话（置顶可选跳过）。
        返回 {listed, deleted, skipped, failed}。

        循环拉取+删除直到没有可删的为止：list_web_chats 单轮有上限（默认300），
        重度账号堆积可能 >上限，最旧的会话排在列表外永远清不到。每轮删完重新拉，
        删空一轮（本轮 deleted=0）或达到安全上限就停。
        keep_hours 下界保护：至少保留 1 小时，防止误传 0/负值清空所有会话。
        """
        keep_hours = max(1.0, keep_hours)
        total_listed = total_deleted = total_skipped = total_failed = 0
        max_rounds = 50  # 安全上限：单账号最多清 50 轮（每轮最多 300），防极端情况死循环
        for _ in range(max_rounds):
            chats = await self.list_web_chats()
            if not chats:
                break
            cutoff = time.time() - keep_hours * 3600
            round_deleted = 0
            round_skipped = 0
            for chat in chats:
                if skip_pinned and chat.get("pinned"):
                    total_skipped += 1
                    round_skipped += 1
                    continue
                ts = chat.get("ts", 0.0)
                # ts<=0 说明时间戳没解析出来，保守跳过不删（避免误删）
                if ts <= 0 or ts >= cutoff:
                    total_skipped += 1
                    round_skipped += 1
                    continue
                ok = await self.delete_web_chat(chat["cid"])
                if ok:
                    total_deleted += 1
                    round_deleted += 1
                else:
                    total_failed += 1
                await asyncio.sleep(0.3)  # 轻微间隔，避免触发限流
            total_listed += len(chats)
            # 本轮没删任何会话（剩下的要么置顶、要么在保留窗口内）→ 没有更多可清的，停止
            if round_deleted == 0:
                break
        logger.info(f"网页会话清理：deleted={total_deleted} skipped={total_skipped} failed={total_failed}")
        return {"listed": total_listed, "deleted": total_deleted,
                "skipped": total_skipped, "failed": total_failed}

    def _parse_models_from_status(self, raw: str):
        """从 otAQ7b（GetUserStatus）响应解析账号真实可用模型。
        响应结构：part_body[15] 是模型数组，每项 [model_id, display_name, description]。
        把账号真实可用的内部模型按 family 记录到本实例 self._family_model，
        供 _resolve_model 把固定公开名映射到该账号真实模型（P0-5：实例隔离，避免全局污染）。
        _available_models 始终是固定的公开名（API 稳定契约），不随账号变化。
        """
        try:
            lines = raw.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line.startswith("[["):
                    continue
                try:
                    outer = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                for item in outer:
                    if not (isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr"):
                        continue
                    body_str = item[2]
                    if not isinstance(body_str, str):
                        continue
                    try:
                        body = json.loads(body_str)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    models_list = body[15] if isinstance(body, list) and len(body) > 15 else None
                    if not isinstance(models_list, list):
                        continue
                    discovered_ids = []
                    for m in models_list:
                        if isinstance(m, list) and m and isinstance(m[0], str):
                            discovered_ids.append(m[0])
                    # 内部 model_id -> 内部模型名 -> 按 family 记录账号真实可用模型
                    id_to_name = _build_id_alias_map()
                    family_model = {}
                    for mid in discovered_ids:
                        name = id_to_name.get(mid)
                        if name and name in GEMINI_MODELS:
                            fam = GEMINI_MODELS[name]["family"]
                            family_model.setdefault(fam, name)
                    if family_model:
                        # 账号拉到了 pro/flash，按同 capacity 等级补全 thinking
                        caps = {GEMINI_MODELS[n]["capacity"] for n in family_model.values()}
                        for name, info in GEMINI_MODELS.items():
                            if info["capacity"] in caps:
                                family_model.setdefault(info["family"], name)
                        self._family_model.update(family_model)
                        # 对外永远是固定公开名
                        self._available_models = list(PUBLIC_MODELS)
                        logger.info(f"Account models resolved: {family_model} -> public {PUBLIC_MODELS}")
                        return
        except Exception as e:
            logger.debug(f"Model parse from status skipped: {e}")

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

    def _encode_payload(self, prompt: str, model: str, conversation_id: str = "",
                        file_ids: list | None = None) -> str:
        conv_param = conversation_id if conversation_id else None
        if file_ids:
            # 有附件：第 0 位用带文件的 message_content 替换纯 [prompt]
            file_data = [[[fid], fname] for fid, fname in file_ids]
            message_content = [prompt, 0, None, file_data, None, None, 0]
            inner = json.dumps([message_content, None, conv_param, model])
        else:
            # 纯文本：保持原结构，逐字节不变（防回归）
            inner = json.dumps([[prompt], None, conv_param, model])
        outer = json.dumps([None, inner])
        return outer

    async def generate(self, prompt: str, model: str, conversation_id: str = "",
                       attachments: list | None = None) -> dict:
        if not self._healthy:
            # 单账号自愈：抛错前单飞重载一次 Cookie，缓解会话约 2h 到期后的硬失败（Issue#1-C）
            async with self._heal_lock:
                if not self._healthy:
                    try:
                        await self.reload_cookies()
                    except Exception as e:
                        logger.warning(f"Self-heal reload_cookies failed: {e}")
            if not self._healthy:
                raise RuntimeError("Client not ready")

        resolved = _resolve_model(model, self._family_model)
        if resolved not in GEMINI_MODELS:
            raise ValueError(
                f"Model '{model}' unavailable. "
                f"Options: {', '.join(PUBLIC_MODELS)}"
            )

        last_err = None
        # 5xx（含 Google 503 限流）同账号只快速重试少量次，不长退避空耗；
        # 仍失败则抛出（带 status_code），由 account_pool 换账号 failover。
        max_5xx = max(0, settings.same_account_5xx_retries)
        for attempt in range(settings.max_retries):
            try:
                return await self._send_request(prompt, model, conversation_id, attachments)
            except HTTPStatusError as e:
                last_err = e
                status = e.status_code
                if 400 <= status < 500:
                    if status in (401, 403):
                        self._healthy = False
                    raise
                # 5xx：同账号快速重试上限内短退避；超过则直接抛给 pool 做 failover
                if attempt >= max_5xx:
                    raise
                wait = 0.5 * (attempt + 1)
                logger.warning(f"Attempt {attempt+1}: status {status}, quick retry in {wait}s (then failover)")
                await asyncio.sleep(wait)
            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(f"Attempt {attempt+1}: {e}, wait {wait}s")
                await asyncio.sleep(wait)

        raise RuntimeError(f"Exhausted {settings.max_retries} retries: {last_err}")

    async def generate_stream(self, prompt: str, model: str, conversation_id: str = "",
                              attachments: list | None = None):
        """真流式：用独立临时 AsyncSession 流式读 StreamGenerate，逐帧产出文本增量。

        产出事件：
          {"type": "delta", "text": <新增文本>}        —— 流式过程中多次
          {"type": "final", "text": <完整文本>,
           "conversation_id": <会话ID>, "images": [...]}  —— 收尾一次

        关键约束（见记忆 gemini2api-project 真流式段）：
        - curl_cffi 0.7.4 并发流式会串号（#612），故每请求用独立 session（不复用 self._http）。
        - 流式 timeout 可能失效（#215），故用 asyncio.wait_for 兜底每个 chunk 的等待。
        - 帧是累积式，逐帧 diff 出增量。生图/附件场景在最后帧统一处理。
        """
        if not self._healthy:
            # 单账号自愈：抛错前单飞重载一次 Cookie（Issue#1-C）
            async with self._heal_lock:
                if not self._healthy:
                    try:
                        await self.reload_cookies()
                    except Exception as e:
                        logger.warning(f"Self-heal reload_cookies failed: {e}")
            if not self._healthy:
                raise RuntimeError("Client not ready")

        resolved = _resolve_model(model, self._family_model)
        if resolved not in GEMINI_MODELS:
            raise ValueError(
                f"Model '{model}' unavailable. Options: {', '.join(PUBLIC_MODELS)}"
            )

        await apply_jitter("api_call")
        await self._ensure_session_current()
        cookies = self._get_cookies()

        # 附件上传仍复用共享 session 的逻辑（与对话同账号同会话），上传完再走流式对话
        file_ids = None
        if attachments:
            from app.core.file_upload import upload_files
            base_headers = self._get_headers("POST")
            file_ids = await upload_files(
                self._http, cookies, base_headers, self._push_id, attachments
            )
            if not file_ids:
                logger.warning("All attachment uploads failed, streaming text-only")

        encoded = self._encode_payload(prompt, resolved, conversation_id, file_ids)
        form_data = {"at": self._session_token, "f.req": encoded}
        headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
        model_headers = _build_model_header(resolved)
        if model_headers:
            headers.update(model_headers)

        buf = ""
        emitted = ""             # 已 yield 出去的完整文本（用于和新帧比前缀算增量）
        last_text = ""           # 最新一帧的完整文本
        last_conv = ""
        last_images: list = []
        chunk_timeout = 120      # 单个 chunk 最长等待（兜底 #215 timeout 失效）

        session = AsyncSession(impersonate=self._current_target, timeout=180)
        try:
            async with session.stream(
                "POST", GENERATE_URL,
                data=form_data, cookies=cookies, headers=headers,
            ) as resp:
                try:
                    if resp.status_code >= 400:
                        body = await resp.atext()
                        raise HTTPStatusError(resp.status_code, body[:200])

                    aiter = resp.aiter_content()
                    while True:
                        try:
                            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=chunk_timeout)
                        except StopAsyncIteration:
                            break
                        if not chunk:
                            continue
                        buf += chunk.decode("utf-8", "replace")
                        frames, consumed = _scan_complete_wrb_frames(buf)
                        if consumed:
                            buf = buf[consumed:]
                        for elem in frames:
                            text, conv = _extract_text_from_wrb(elem)
                            if conv:
                                last_conv = conv
                            imgs = self._images_from_wrb(elem)
                            if imgs:
                                last_images = imgs
                            if text is None:
                                continue
                            # 生图/找图时帧文本会带 googleusercontent 占位 URL，流式增量也要先过滤，
                            # 否则会流给客户端（这类占位串只在生图/检索时出现，纯文本回复不含，过滤安全）
                            if "googleusercontent.com/image" in text:
                                text = _IMAGE_GEN_PLACEHOLDER_RE.sub("", text)
                            last_text = text
                            # 帧是累积式：当前帧文本 = 已发送文本 + 新增尾部。
                            # 与「已 emit 的文本」(emitted) 比前缀，决定是追加增量还是整段被替换。
                            if text == emitted:
                                continue  # 文本没变（如重复帧），不重复发
                            if len(text) >= len(emitted) and text.startswith(emitted):
                                delta = text[len(emitted):]
                                emitted = text
                                if delta:
                                    yield {"type": "delta", "text": delta}
                            else:
                                # 极少数：帧文本非纯累积（被替换/重排），整段重置补发
                                emitted = text
                                logger.warning("[stream] 非累积帧，整段重置补发（_replace）")
                                yield {"type": "delta", "text": text, "_replace": True}
                finally:
                    # 无论正常结束/4xx/超时，都尝试更新 PSIDTS（流式下 resp 头部 cookie 可读），
                    # 避免流式错误路径漏掉 Cookie 轮换（与非流式 _send_request 行为对齐）
                    try:
                        self._cookie_jar.update_from_response(resp)
                    except Exception:
                        pass
        finally:
            try:
                await session.close()
            except Exception:
                pass

        yield await self._finalize_stream(last_text, last_conv, last_images)

    def _images_from_wrb(self, elem: list) -> list:
        """从单个 wrb.fr 帧提取 AI 生成图片（复用 _extract_generated_images）。"""
        try:
            if not isinstance(elem, list) or len(elem) < 3 or elem[0] != "wrb.fr":
                return []
            payload = json.loads(elem[2]) if isinstance(elem[2], str) else None
            if not isinstance(payload, list) or len(payload) < 5:
                return []
            cands = payload[4]
            if not isinstance(cands, list) or not cands:
                return []
            return self._extract_generated_images(cands[0])
        except Exception:
            return []

    async def _finalize_stream(self, text: str, conv_id: str, images: list) -> dict:
        """流式收尾：下载/存生成图、过滤占位 URL，组装与 _send_request 一致的 final 结果。"""
        result_images: list = []
        if images:
            import base64 as _b64
            from app.core import image_store
            cookies = self._get_cookies()
            for img in images:
                data = await self._download_generated_image(img["url"], cookies)
                if not data:
                    logger.warning(f"[imagegen] 流式下载失败: {img['url'][:60]}")
                    continue
                mime = img.get("mime", "image/png")
                entry = {
                    "b64": _b64.b64encode(data).decode(),
                    "mime": mime,
                    "width": img.get("width"),
                    "height": img.get("height"),
                }
                try:
                    entry["id"] = image_store.save_image(data, mime)
                except Exception as e:
                    logger.warning(f"[imagegen] 存盘失败: {e}")
                result_images.append(entry)
            # 生图时模型文本里的占位 URL 无意义，过滤掉（与 _parse_output 一致）
            text = _IMAGE_GEN_PLACEHOLDER_RE.sub("", text).strip()
        return {
            "type": "final",
            "text": text,
            "conversation_id": conv_id,
            "images": result_images,
        }

    async def _send_request(self, prompt: str, model: str, conversation_id: str = "",
                           attachments: list | None = None) -> dict:
        await apply_jitter("api_call")
        await self._ensure_session_current()
        self._clear_session_cookies()

        resolved = _resolve_model(model, self._family_model)
        cookies = self._get_cookies()

        # 上传附件（与对话同账号同会话），拿到文件标识符
        file_ids = None
        if attachments:
            from app.core.file_upload import upload_files
            base_headers = self._get_headers("POST")
            file_ids = await upload_files(
                self._http, cookies, base_headers, self._push_id, attachments
            )
            if not file_ids:
                logger.warning("All attachment uploads failed, falling back to text-only")

        encoded = self._encode_payload(prompt, resolved, conversation_id, file_ids)
        form_data = {"at": self._session_token, "f.req": encoded}
        headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")

        model_headers = _build_model_header(resolved)
        if model_headers:
            headers.update(model_headers)

        resp = await self._http.post(GENERATE_URL, data=form_data, cookies=cookies, headers=headers)
        self._cookie_jar.update_from_response(resp)

        if resp.status_code >= 400:
            raise HTTPStatusError(resp.status_code, resp.text[:200])

        result = self._parse_output(resp.text)

        # AI 生成图片：lh3 URL 客户端直接访问会 403，服务端带 cookie 代下载，
        # 同时存盘（供对话接口返回可渲染 URL）+ 转 base64（供 images/generations 接口）
        if result.get("images"):
            import base64 as _b64
            from app.core import image_store
            downloaded = []
            for img in result["images"]:
                data = await self._download_generated_image(img["url"], cookies)
                if not data:
                    logger.warning(f"[imagegen] 下载失败: {img['url'][:60]}")
                    continue
                mime = img.get("mime", "image/png")
                entry = {
                    "b64": _b64.b64encode(data).decode(),
                    "mime": mime,
                    "width": img.get("width"),
                    "height": img.get("height"),
                }
                try:
                    entry["id"] = image_store.save_image(data, mime)
                except Exception as e:
                    logger.warning(f"[imagegen] 存盘失败: {e}")
                downloaded.append(entry)
            result["images"] = downloaded

        return result

    async def _download_generated_image(self, url: str, cookies: dict) -> bytes | None:
        """下载 AI 生成的图片字节（全分辨率原图）。
        - lh3 URL 不加尺寸后缀时只给压缩缩略图（如 512px）；加 `=s0` 拿原始全分辨率图（实测）。
        - lh3 URL 会多级 302（lh3→fife→lh3），curl_cffi 默认跟随会在跨域时丢 cookie 致 403。
          正确方式：先 allow_redirects=False 拿首个 302 的 location，
          再对该 location 带 cookie allow_redirects=True 跟随到最终 PNG。
        """
        # 加 =s0 取原始全分辨率（不重复加；URL 已带 = 尺寸参数则保留）
        full_url = url if ("=s" in url.rsplit("/", 1)[-1] or "=w" in url.rsplit("/", 1)[-1]) else url + "=s0"
        headers = {"Referer": "https://gemini.google.com/"}
        try:
            r1 = await self._http.get(full_url, cookies=cookies, headers=headers, allow_redirects=False)
            loc = r1.headers.get("location", "")
            if r1.status_code == 200 and r1.headers.get("content-type", "").startswith("image/"):
                return r1.content  # 少数情况直接返回图
            if not loc:
                logger.warning(f"[imagegen] 无重定向且非图片: status={r1.status_code}")
                return None
            r2 = await self._http.get(loc, cookies=cookies, headers=headers, allow_redirects=True)
            if r2.status_code == 200 and r2.headers.get("content-type", "").startswith("image/"):
                return r2.content
            logger.warning(f"[imagegen] 最终下载非图片: status={r2.status_code} type={r2.headers.get('content-type')}")
            return None
        except Exception as e:
            logger.warning(f"[imagegen] 下载异常: {e}")
            return None

    def _parse_output(self, raw: str) -> dict:
        lines = raw.strip().split("\n")
        text_content = ""
        conv_id = ""
        images: list[dict] = []

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
                # AI 生成图片：candidate[12][7][0] 是图片数组（实测确认）
                imgs = self._extract_generated_images(candidate)
                if imgs:
                    images = imgs  # 生图是流式响应，用含图的最新帧
                if payload[1]:
                    conv_id = str(payload[1])

        # 生图/找图时模型文本里会带 googleusercontent 占位 URL（无实际意义，真图在 images 里；
        # image_retrieval/image_collection 是检索占位客户端访问无效），无条件过滤，避免显示成网址
        if "googleusercontent.com/image" in text_content:
            had_placeholder = bool(_IMAGE_GEN_PLACEHOLDER_RE.search(text_content))
            text_content = _IMAGE_GEN_PLACEHOLDER_RE.sub("", text_content).strip()
            # 过滤后文本空了且没有真图：Gemini 走了"检索图片"而非"生成"（模糊措辞如"来张X图"易触发）。
            # 占位URL客户端用不了，给友好提示引导用明确生图措辞，而不是返回空。
            if had_placeholder and not text_content and not images:
                text_content = "（没有生成图片。试试更明确的生成指令，如「画一张…」「生成一张…的图片」。）"

        return {"text": text_content, "conversation_id": conv_id, "images": images}

    @staticmethod
    def _extract_generated_images(candidate: list) -> list[dict]:
        """从 candidate[12][7][0] 提取 AI 生成的图片（区别于用户上传的图）。
        实测结构：每张图 img[0][3] = [null,1,文件名,URL,...,"image/png",...,[宽,高,size]]
        返回 [{url, mime, width, height, filename}, ...]；无图返回 []。
        """
        try:
            if not isinstance(candidate, list) or len(candidate) <= 12:
                return []
            c12 = candidate[12]
            if not isinstance(c12, list) or len(c12) <= 7:
                return []
            arr = c12[7]
            if not isinstance(arr, list) or not arr:
                return []
            img_list = arr[0]
            if not isinstance(img_list, list):
                return []
            out = []
            for img in img_list:
                try:
                    meta = img[0][3]  # [null,1,文件名,URL,...,mime,...,[w,h,size]]
                    url = meta[3]
                    if not isinstance(url, str) or not url.startswith("http"):
                        continue
                    filename = meta[2] if len(meta) > 2 and isinstance(meta[2], str) else "generated.png"
                    mime = "image/png"
                    width = height = None
                    for el in meta:
                        if isinstance(el, str) and el.startswith("image/"):
                            mime = el
                        elif isinstance(el, list) and len(el) >= 2 \
                                and isinstance(el[0], int) and isinstance(el[1], int):
                            width, height = el[0], el[1]
                    out.append({"url": url, "mime": mime, "width": width,
                                "height": height, "filename": filename})
                except (IndexError, TypeError, KeyError):
                    continue
            return out
        except (IndexError, TypeError, KeyError):
            return []

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
            await self._send_heartbeat()  # 拉取账号真实可用模型
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

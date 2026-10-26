"""每个账号的 cookie「由谁保活」的持久化记录：``data/keepalive-modes.json``。

Google 的 ``__Secure-1PSIDTS`` 要定期调 RotateCookies 换新。现在有两方可能去换：

- ``server``（默认）：本服务的 ``GeminiWebClient._auto_refresh_loop`` 定时轮换；
- ``browser``：浏览器保活插件（xwteam/gemini2api-plugin）所在的那个浏览器自己在换，插件把
  浏览器里的新 cookie 推给本服务（``PUT /admin/accounts/{id}/cookies``）。

两方**不能同时换**：浏览器和服务端用的是同一个谷歌会话，各自调 RotateCookies 时，后一方
拿着已被对方换掉的旧 PSIDTS 去换就 401、整个会话被踢下线（线上实证：服务端独自轮换 3 天
零失败，浏览器一回来当晚就开始 401，用户看到的是「经常掉线要重登」）。所以插件推过来的
账号记成 browser，服务端从此不再轮换它 —— 唯一的闸口在 ``GeminiWebClient._rotate_cookies``
开头。面板手动「更新 Cookie」、脚本调用记成 server（比如改用无痕窗口取的 cookie：那个窗口
一关就没人轮换了，必须交回服务端）。

键是 ``sha256(PSID)[:16]`` —— 与 ``data/cookies/<hash>.json`` 的文件名同一算法。PSID 在 PSIDTS
轮换中保持不变、重新登录才会变，所以重登之后旧记录自然不再命中，回到默认的 server。
值是 ``{"mode": "browser"|"server", "updated_at": "<ISO8601 UTC>"}``。文件里**只有哈希**，
不含任何 cookie 值；手写进来的非哈希键既不认、下一次写入时也会被清掉。

读：文件缺失 / 损坏 / 结构不对一律当空（= 全部 server），绝不让一份坏文件拖垮轮换或状态
接口。每次查询都读盘（文件只有几百字节），所以运维手改文件不用重启；原文没变就复用上一次
的解析结果，坏文件也只告警一次。
写：整段读-改-写持锁；落盘走同目录临时文件 + ``os.replace``（``app.utils.atomic_io``）。

本模块只依赖标准库和 ``app.utils.atomic_io``（不 import config / account_pool），
tests/conftest.py 会在导入 app 之前把 ``MODES_PATH`` 重定向到临时目录。
"""

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# data/ 在 docker-compose 里是 bind mount（./data:/app/data），重启/升级都不丢。
MODES_PATH = Path("data/keepalive-modes.json")

MODE_SERVER = "server"
MODE_BROWSER = "browser"
MODES = (MODE_SERVER, MODE_BROWSER)
DEFAULT_MODE = MODE_SERVER

# 新版插件（v1.3.0 起）推 cookie 时带这个头，值形如 "gemini2api-plugin/1.3.0"。只看在不在。
KEEPALIVE_HEADER = "X-Gemini2API-Keepalive"
# 现有 v1.2.3 插件不带上面的头，只能靠扩展发起请求时浏览器自动带上的 Origin 认出来。
EXTENSION_ORIGIN_PREFIX = "chrome-extension://"

_KEY_RE = re.compile(r"^[0-9a-f]{16}$")

_PathLike = Optional[Union[str, Path]]

_lock = threading.Lock()
# (文件路径, 原文, 解析结果)。/admin/status 每次轮询、每个账号都会查一次，原文没变就不重复
# 解析，坏文件也只在内容变化时告警一次。只在持有 _lock 时读写。
_parsed: Optional[tuple] = None


def psid_key(psid: str) -> str:
    """记录的键：sha256(PSID) 的前 16 个十六进制字符（与 Cookie 缓存文件名同一算法）。"""
    return hashlib.sha256(psid.encode()).hexdigest()[:16]


def _resolve(path: _PathLike) -> Path:
    return Path(path) if path is not None else MODES_PATH


def _parse(raw: str, path: Path) -> dict:
    try:
        data = json.loads(raw)
    except ValueError as e:
        logger.warning(f"Ignoring corrupt keepalive modes file {path}: {e}")
        return {}
    if not isinstance(data, dict):
        logger.warning(f"Ignoring keepalive modes file {path}: expected a JSON object")
        return {}
    out: dict = {}
    for key, entry in data.items():
        # 只认「哈希键 + 合法模式」的记录；其余逐条忽略（= 那个账号按默认 server 处理）
        if not isinstance(key, str) or not _KEY_RE.match(key):
            continue
        if not isinstance(entry, dict) or entry.get("mode") not in MODES:
            continue
        out[key] = {"mode": entry["mode"], "updated_at": str(entry.get("updated_at") or "")}
    return out


def _load(path: Path) -> dict:
    """读出 {键: 记录} 的一份副本。调用方须持有 _lock。"""
    global _parsed
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:  # ValueError：UnicodeDecodeError（不是 UTF-8）
        if _parsed is None or _parsed[:2] != (str(path), None):
            logger.warning(f"Ignoring unreadable keepalive modes file {path}: {e}")
        _parsed = (str(path), None, {})
        return {}
    if _parsed is None or _parsed[:2] != (str(path), raw):
        _parsed = (str(path), raw, _parse(raw, path))
    return dict(_parsed[2])


def get_mode(psid: Optional[str], path: _PathLike = None) -> str:
    """这个 PSID 的保活方式；没有记录（或文件读不出来）就是默认的 server。绝不抛异常。"""
    if not psid:
        return DEFAULT_MODE
    target = _resolve(path)
    with _lock:
        entry = _load(target).get(psid_key(psid))
    return entry["mode"] if entry else DEFAULT_MODE


def set_mode(psid: Optional[str], mode: str, path: _PathLike = None) -> bool:
    """记下这个 PSID 的保活方式。落盘成功返回 True；参数不对或落盘失败返回 False（只记日志，不抛）。"""
    if not psid or mode not in MODES:
        logger.warning(f"Refusing to record keepalive mode {mode!r} for an empty or invalid account")
        return False
    target = _resolve(path)
    key = psid_key(psid)
    with _lock:
        modes = _load(target)
        modes[key] = {
            "mode": mode,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            atomic_write_json(target, modes, indent=2)
        except OSError as e:
            logger.warning(f"Could not persist keepalive mode to {target}: {e}")
            return False
    logger.info(f"Keepalive mode for account {key} set to {mode}")
    return True


def mode_from_headers(headers: Mapping[str, Any]) -> str:
    """按推 cookie 的请求来源判定保活方式（路由只在 reload 成功之后才用它写记录）。

    - 带 ``X-Gemini2API-Keepalive`` 头（新插件 v1.3.0 起）→ browser；
    - 否则 ``Origin`` 以 ``chrome-extension://`` 开头（兼容现有 v1.2.3 插件）→ browser；
    - 否则（面板手动「更新 Cookie」、脚本调用）→ server。
    """
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    if KEEPALIVE_HEADER.lower() in lowered:
        return MODE_BROWSER
    if lowered.get("origin", "").strip().lower().startswith(EXTENSION_ORIGIN_PREFIX):
        return MODE_BROWSER
    return MODE_SERVER

"""完整 Cookie 持久化管理 — 自动捕获、存储、过期清理、回放"""

import json
import hashlib
import logging
import time
from pathlib import Path
from threading import Lock
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

COOKIE_STORE_DIR = Path("data/cookies")


@dataclass
class StoredCookie:
    name: str
    value: str
    domain: str = ".google.com"
    path: str = "/"
    expires: float = 0
    secure: bool = True
    http_only: bool = True


class PersistentCookieJar:
    """基于 JSON 文件的持久化 Cookie 管理器"""

    def __init__(self, account_id: str):
        self._account_id = account_id
        self._cookies: dict[str, StoredCookie] = {}
        self._lock = Lock()
        self._load()

    def get_all(self, domain: str = "google.com") -> dict[str, str]:
        """获取指定域名下所有有效 Cookie"""
        with self._lock:
            self._cleanup_expired()
            result = {}
            for cookie in self._cookies.values():
                if domain in cookie.domain or cookie.domain.endswith(domain):
                    result[cookie.name] = cookie.value
            return result

    def update_from_response(self, response) -> None:
        """从 curl_cffi 响应中提取并存储所有 Cookie（含 Set-Cookie 头解析）"""
        if not hasattr(response, "cookies"):
            return
        changed = False
        for name, value in response.cookies.items():
            with self._lock:
                existing = self._cookies.get(name)
                if existing is None or existing.value != value:
                    self._cookies[name] = StoredCookie(
                        name=name,
                        value=value,
                        domain=".google.com",
                        secure=name.startswith("__Secure"),
                    )
                    changed = True

        # 从 Set-Cookie 响应头补充捕获
        raw_headers = getattr(response, "headers", None)
        if raw_headers:
            sc_values = []
            if hasattr(raw_headers, "get_list"):
                sc_values = raw_headers.get_list("set-cookie")
            elif hasattr(raw_headers, "getlist"):
                sc_values = raw_headers.getlist("set-cookie")
            else:
                v = raw_headers.get("set-cookie")
                if v:
                    sc_values = [v]
            for sc in sc_values:
                parsed = self._parse_set_cookie_header(sc)
                if parsed:
                    cn, cv = parsed
                    with self._lock:
                        ex = self._cookies.get(cn)
                        if ex is None or ex.value != cv:
                            self._cookies[cn] = StoredCookie(
                                name=cn,
                                value=cv,
                                domain=".google.com",
                                secure=cn.startswith("__Secure"),
                            )
                            changed = True

        if changed:
            self._persist()
            names = sorted(self._cookies.keys())
            logger.debug(f"Cookie jar updated: {len(self._cookies)} - {names}")

    @staticmethod
    def _parse_set_cookie_header(raw: str):
        """解析单条 Set-Cookie 头"""
        if not raw:
            return None
        try:
            pair = raw.split(";", 1)[0].strip()
            if "=" not in pair:
                return None
            n, v = pair.split("=", 1)
            n = n.strip()
            v = v.strip()
            if not n:
                return None
            return (n, v)
        except Exception:
            return None

    def cookie_names(self) -> list:
        """返回当前所有 Cookie 名称"""
        with self._lock:
            return sorted(self._cookies.keys())

    def set(self, name: str, value: str, **kwargs) -> None:
        """手动设置单个 Cookie"""
        with self._lock:
            self._cookies[name] = StoredCookie(name=name, value=value, **kwargs)
        self._persist()

    def get(self, name: str) -> str | None:
        """获取单个 Cookie 值"""
        with self._lock:
            cookie = self._cookies.get(name)
            if cookie:
                return cookie.value
        return None

    def remove(self, name: str) -> None:
        """移除单个 Cookie"""
        with self._lock:
            self._cookies.pop(name, None)
        self._persist()

    def _cleanup_expired(self):
        """清理过期 Cookie"""
        now = time.time()
        expired = [
            name for name, c in self._cookies.items()
            if c.expires > 0 and c.expires < now
        ]
        for name in expired:
            del self._cookies[name]
        if expired:
            self._persist()

    def _store_path(self) -> Path:
        digest = hashlib.sha256(self._account_id.encode()).hexdigest()[:16]
        return COOKIE_STORE_DIR / f"{digest}.json"

    def _load(self):
        path = self._store_path()
        if not path.exists():
            self._try_migrate_legacy()
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                self._cookies[item["name"]] = StoredCookie(
                    name=item["name"],
                    value=item["value"],
                    domain=item.get("domain", ".google.com"),
                    path=item.get("path", "/"),
                    expires=item.get("expires", 0),
                    secure=item.get("secure", True),
                    http_only=item.get("http_only", True),
                )
            logger.info(f"已加载 {len(self._cookies)} 个持久化 Cookie")
        except Exception as e:
            logger.warning(f"Cookie 加载失败: {e}")

    def _try_migrate_legacy(self):
        """从旧的 .cookies/ 目录迁移"""
        legacy_dir = Path(".cookies")
        if not legacy_dir.exists():
            return
        digest = hashlib.sha256(self._account_id.encode()).hexdigest()[:16]
        legacy_path = legacy_dir / f"{digest}.txt"
        if legacy_path.exists():
            psidts = legacy_path.read_text().strip()
            if psidts:
                logger.info("从旧缓存迁移 PSIDTS Cookie")
                self._cookies["__Secure-1PSIDTS"] = StoredCookie(
                    name="__Secure-1PSIDTS",
                    value=psidts,
                    secure=True,
                )

    def _persist(self):
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(c) for c in self._cookies.values()]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

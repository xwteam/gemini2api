"""完整 Cookie 持久化管理 — 自动捕获、存储、过期清理、回放"""

import json
import hashlib
import logging
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock
from dataclasses import dataclass, asdict

from app.utils.atomic_io import atomic_write_json

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

    @staticmethod
    def _iter_response_cookies(cookies) -> list:
        """把响应 cookie 容器摊平成 [(name, value)]，同名跨域做确定性取舍。

        curl_cffi 的 ``Cookies.items()``（经 MutableMapping → ``get()``）在同名 Cookie
        跨域并存时抛 ``CookieConflict``：
            Multiple cookies exist with name=NID on www.google.com and .google.com.hk
        Google 把用户跳到国家域名（.google.com.hk/.com.tw/.co.jp …）时必现，异常会一路
        冒到 ``_obtain_session_token`` 让 token 置空、账号被判 unhealthy（issue #10）。
        因此这里直接遍历底层 ``http.cookiejar.CookieJar``——每个条目是独立 Cookie 对象，
        自带 name/value/domain，天然没有同名冲突。

        同名多域的取舍**只由域名决定**，不依赖遍历顺序的偶然性：优先取 domain 以
        ``google.com`` 结尾的规范域；若候选同级（都规范或都不规范）才取最后一个。
        """
        jar = getattr(cookies, "jar", None)
        if jar is None:
            # 非 curl_cffi 容器（如普通 dict）：保持原有 items() 行为
            return list(cookies.items())

        picked: dict[str, tuple[int, str]] = {}
        for c in jar:
            name = getattr(c, "name", None)
            if not name:
                continue
            value = getattr(c, "value", None) or ""
            domain = (getattr(c, "domain", None) or "").strip().rstrip(".").lower()
            rank = 1 if domain.endswith("google.com") else 0
            prev = picked.get(name)
            # rank 严格更高才抢占；同级则后者覆盖前者（"last wins"）。
            # 规范域已在手时，任何非规范域都无法覆盖它 —— 与遍历顺序无关。
            if prev is not None and prev[0] > rank:
                continue
            picked[name] = (rank, value)
        return [(n, v) for n, (_, v) in picked.items()]

    def update_from_response(self, response) -> None:
        """从 curl_cffi 响应中提取并存储所有 Cookie（含 Set-Cookie 头解析）。

        纵深防御：整段包 try/except，Cookie 层的任何异常只记 warning。Cookie 更新失败
        顶多是少存一个 Cookie，绝不能再像 issue #10 那样打断调用方的 token 获取。
        """
        try:
            self._update_from_response(response)
        except Exception as e:
            logger.warning(f"Cookie 更新失败（已忽略，不影响调用方流程）: {e}")

    def _update_from_response(self, response) -> None:
        if not hasattr(response, "cookies"):
            return
        changed = False
        for name, value in self._iter_response_cookies(response.cookies):
            with self._lock:
                # 空值视为服务端删除指令：删除而非用空值覆盖有效凭据 Cookie。
                if not value:
                    if name in self._cookies:
                        del self._cookies[name]
                        changed = True
                    continue
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
                    cn, cv, expires = parsed
                    with self._lock:
                        # 删除指令（空值 / Max-Age<=0 / Expires 已过期）：删除现有 Cookie，
                        # 绝不用空值或已过期值覆盖仍有效的认证 Cookie（VULN-010 写容错）。
                        is_deletion = (not cv) or (expires is not None and expires <= time.time())
                        if is_deletion:
                            if cn in self._cookies:
                                del self._cookies[cn]
                                changed = True
                            continue
                        ex = self._cookies.get(cn)
                        new_expires = expires if expires is not None else 0
                        if ex is None or ex.value != cv or ex.expires != new_expires:
                            self._cookies[cn] = StoredCookie(
                                name=cn,
                                value=cv,
                                domain=".google.com",
                                expires=new_expires,
                                secure=cn.startswith("__Secure"),
                            )
                            changed = True

        if changed:
            self._persist()
            names = sorted(self._cookies.keys())
            logger.debug(f"Cookie jar updated: {len(self._cookies)} - {names}")

    @staticmethod
    def _parse_set_cookie_header(raw: str):
        """解析单条 Set-Cookie 头，返回 (name, value, expires) 三元组。

        expires 为绝对 Unix 时间戳（秒）；无 Expires/Max-Age 属性时为 None。
        Max-Age 优先级高于 Expires（RFC 6265）。Max-Age<=0 或 Expires 在过去 →
        expires 取一个过去时间戳，供上层据此识别为删除指令。
        """
        if not raw:
            return None
        try:
            parts = raw.split(";")
            pair = parts[0].strip()
            if "=" not in pair:
                return None
            n, v = pair.split("=", 1)
            n = n.strip()
            v = v.strip()
            if not n:
                return None

            expires = None
            max_age = None
            expires_attr = None
            for attr in parts[1:]:
                if "=" not in attr:
                    continue
                k, av = attr.split("=", 1)
                k = k.strip().lower()
                av = av.strip()
                if k == "max-age":
                    max_age = av
                elif k == "expires":
                    expires_attr = av

            if max_age is not None:
                try:
                    expires = time.time() + int(max_age)
                except (ValueError, TypeError):
                    expires = None
            elif expires_attr:
                try:
                    dt = parsedate_to_datetime(expires_attr)
                    if dt is not None:
                        expires = dt.timestamp()
                except (TypeError, ValueError, OverflowError):
                    expires = None

            return (n, v, expires)
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

    def clear(self) -> None:
        """丢掉该账号的整份 Cookie 缓存（含磁盘文件内容）。

        用于"配置里的 cookie 和磁盘缓存不一致"时：此时缓存里的 PSIDTS 已经陈旧，而与它
        同一批抓到的会话类 Cookie（NID/SIDCC/__Secure-1PSIDCC …）同样属于那个旧会话，
        只删 PSIDTS 会留下半新半旧的组合。整份清掉再按配置值重建最干净。
        """
        with self._lock:
            had = len(self._cookies)
            self._cookies.clear()
        self._persist()
        if had:
            logger.info(f"已清空 {had} 个持久化 Cookie（配置值与缓存不一致）")

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
        except Exception as e:
            logger.warning(f"Cookie 加载失败: {e}")
            return
        if not isinstance(data, list):
            return
        for item in data:
            try:
                self._cookies[item["name"]] = StoredCookie(
                    name=item["name"],
                    value=item["value"],
                    domain=item.get("domain", ".google.com"),
                    path=item.get("path", "/"),
                    expires=item.get("expires", 0),
                    secure=item.get("secure", True),
                    http_only=item.get("http_only", True),
                )
            except (KeyError, TypeError):
                continue  # 坏记录单条跳过，保留其余有效 Cookie（VULN-010 读容错）
        logger.info(f"已加载 {len(self._cookies)} 个持久化 Cookie")

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
        data = [asdict(c) for c in self._cookies.values()]
        # 原子写，避免写入中途崩溃损坏 Cookie 文件（VULN-010）
        atomic_write_json(path, data, ensure_ascii=False)

"""完整 Cookie 持久化管理 — 自动捕获、存储、过期清理、回放。

按 (name, domain, path) 存、按目标 URL 取（RFC 6265 的域匹配 / 路径匹配）。

为什么不能再按名字存一份、发给谁都一样：谷歌 11-20 改版后，/app 要浏览器里**完整**的谷歌
Cookie，外加 gemini.google.com 自己的 host-only Cookie `OSID` / `__Secure-OSID` 才会以登录态
加载；而这两个 host-only Cookie 一旦发到 lh3.google.com，生成图下载链的第二跳就会被当成匿名、
最后一跳 403。所以每条 Cookie 必须记住自己的域，只发给它该去的主机。

domain 的写法与 Chrome 导出、curl 的 Netscape 格式同一口径：以点开头 = 域 Cookie（匹配该域
及所有子域），不以点开头 = host-only（只匹配完全相同的主机）。
"""

import json
import hashlib
import logging
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import RLock
from dataclasses import dataclass, asdict, replace
from typing import NamedTuple
from urllib.parse import urlsplit

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

COOKIE_STORE_DIR = Path("data/cookies")

GOOGLE_DOMAIN = ".google.com"
GEMINI_HOST = "gemini.google.com"

# 内部记录专用的「域」（如启动时的配置快照 __cfg-1PSIDTS）：借 Cookie 罐落盘，但它不是 Cookie。
# 按 URL 取 Cookie 时一律跳过，绝不发往任何地方。
INTERNAL_DOMAIN = "config.local"

# 粘贴的 `Cookie:` 请求头不带域信息：这两个是 gemini.google.com 的 host-only Cookie，
# `__Host-` 前缀的按规范也只能是 host-only；其余一律按 .google.com 的域 Cookie 记。
_GEMINI_HOST_ONLY_NAMES = frozenset({"OSID", "__Secure-OSID"})

# 只有浏览器（插件 1.4.0 / 面板粘贴的整段 Cookie）才给得了的 Cookie：登录时签发，我们自己的请求从响应里
# 捕获不到（捕获到的只有 AEC / COMPASS / NID / *PSIDCC / *PSIDTS 之类）。罐里有其中任何一个，就说明这个
# 账号装着某个谷歌登录的整套 Cookie —— 它不在 accounts.json 里，覆盖掉就找不回来。
FULL_SET_MARKERS = frozenset({"OSID", "__Secure-OSID", "SID", "HSID", "SSID", "APISID", "SAPISID"})

# 被换掉的旧值记多久（见 PersistentCookieJar._superseded）。最长的请求（pro 的非流式 / 流式）预算是
# 300 秒，留足余量。
_SUPERSEDED_TTL = 15 * 60

# 导入整套 Cookie 时的上限（管理接口，鉴权后才能调；只防误传 / 滥用撑爆罐文件）
MAX_IMPORTED_COOKIES = 300
MAX_COOKIE_NAME_LEN = 256
MAX_COOKIE_VALUE_LEN = 4096


@dataclass
class StoredCookie:
    name: str
    value: str
    domain: str = GOOGLE_DOMAIN
    path: str = "/"
    expires: float = 0
    secure: bool = True
    http_only: bool = True

    @property
    def host_only(self) -> bool:
        """不以点开头的 domain = host-only（只发给完全相同的主机）。"""
        return not self.domain.startswith(".")

    @property
    def key(self) -> tuple:
        return (self.name, self.domain, self.path)

    @property
    def internal(self) -> bool:
        return self.domain.lstrip(".") == INTERNAL_DOMAIN


class CookieImportError(ValueError):
    """导入的整套 Cookie 不合法。消息里只说第几条 / 哪个名字，**绝不带 Cookie 值**。"""


# ---------------------------------------------------------------------------
# RFC 6265 的匹配规则
# ---------------------------------------------------------------------------

def normalize_domain(domain: str, host_only: bool | None = None) -> str:
    """统一 domain 写法：域 Cookie 带前导点、host-only 不带，一律小写。

    host_only 为 None 时按传入值自己有没有前导点判断（Chrome / curl 的口径）。
    """
    d = (domain or "").strip().lower()
    base = d.lstrip(".")
    if not base:
        return ""
    if host_only is None:
        host_only = not d.startswith(".")
    return base if host_only else "." + base


def is_google_domain(domain: str) -> bool:
    """google.com 本身或它的子域（.google.com.hk 这类国家域不算）。"""
    base = (domain or "").strip().lower().lstrip(".")
    return base == "google.com" or base.endswith(".google.com")


def domain_matches(host: str, cookie_domain: str) -> bool:
    """RFC 6265 §5.1.3：域 Cookie 匹配该域及其子域；host-only 只匹配完全相同的主机。"""
    if not host or not cookie_domain:
        return False
    if cookie_domain.startswith("."):
        base = cookie_domain[1:]
        return host == base or host.endswith("." + base)
    return host == cookie_domain


def path_matches(request_path: str, cookie_path: str) -> bool:
    """RFC 6265 §5.1.4 的路径前缀匹配（/foo 匹配 /foo、/foo/bar，不匹配 /foobar）。"""
    cookie_path = cookie_path or "/"
    if request_path == cookie_path:
        return True
    if request_path.startswith(cookie_path):
        return cookie_path.endswith("/") or request_path[len(cookie_path)] == "/"
    return False


def _default_path(request_path: str) -> str:
    """RFC 6265 §5.1.4 的 default-path：Set-Cookie 没给 Path 时取请求路径的「目录」。"""
    if not request_path or not request_path.startswith("/"):
        return "/"
    idx = request_path.rfind("/")
    return "/" if idx <= 0 else request_path[:idx]


def _url_parts(url) -> tuple[str, str, str]:
    """(scheme, host, path)。解析失败或不是绝对 URL 时 host 为空串。"""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return "", "", "/"
    return (parts.scheme or "").lower(), (parts.hostname or "").lower(), parts.path or "/"


def _to_cookiejar_cookie(c: StoredCookie):
    """转成 http.cookiejar.Cookie，供 curl_cffi 的 Cookies 罐按真实域名交给 curl。

    domain_specified 就是 curl Netscape 行里的「include subdomains」位：域 Cookie 为真、
    host-only 为假 —— curl 自己的 Cookie 引擎因此在每一跳（含重定向）都按域发送。
    """
    from http.cookiejar import Cookie

    return Cookie(
        version=0,
        name=c.name,
        value=c.value,
        port=None,
        port_specified=False,
        domain=c.domain,
        domain_specified=not c.host_only,
        domain_initial_dot=not c.host_only,
        path=c.path or "/",
        path_specified=True,
        secure=bool(c.secure),
        expires=int(c.expires) if c.expires else None,
        discard=not c.expires,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None} if c.http_only else {},
        rfc2109=False,
    )


# ---------------------------------------------------------------------------
# 整套 Cookie 的导入（浏览器插件推来的列表 / 面板粘贴的 Cookie 请求头）
# ---------------------------------------------------------------------------

_BAD_NAME_CHARS = re.compile(r"[\x00-\x20\x7f;,=\"\\]")
_BAD_VALUE_CHARS = re.compile(r"[\x00-\x1f\x7f;]")


def _check_name(raw, idx: int) -> str:
    name = str(raw or "").strip()
    if not name:
        raise CookieImportError(f"cookie #{idx} has no name")
    if len(name) > MAX_COOKIE_NAME_LEN or _BAD_NAME_CHARS.search(name):
        raise CookieImportError(f"cookie #{idx} has an invalid name")
    return name


def _check_value(raw, name: str) -> str:
    value = str(raw if raw is not None else "").strip()
    if len(value) > MAX_COOKIE_VALUE_LEN or _BAD_VALUE_CHARS.search(value):
        raise CookieImportError(f"cookie {name} has an invalid value")
    return value


def clean_cookie_value(value) -> str:
    """面板 / 插件提交的 PSID、PSIDTS 常带引号或分号：与 reload_cookies / 写回 accounts.json 同一清洗口径。"""
    return (value or "").strip().strip('"').strip("'").rstrip(";")


def _dedup(cookies: list[StoredCookie]) -> list[StoredCookie]:
    """同一 (name, domain, path) 只留最后一条，保持首次出现的顺序。"""
    by_key: dict[tuple, StoredCookie] = {}
    for c in cookies:
        by_key[c.key] = c
    return list(by_key.values())


def cookies_from_browser(items: list[dict]) -> list[StoredCookie]:
    """浏览器插件推来的 Cookie 列表（字段名照 chrome.cookies.Cookie）→ 罐里的条目。

    - domain + hostOnly 决定域：hostOnly 为真 = host-only（OSID / __Secure-OSID 就是
      gemini.google.com 的 host-only）；没给 hostOnly 时按 domain 有没有前导点判断。
    - 只收 google.com 及其子域的 Cookie，别的域静默丢掉（只记条数）。
    - 已过期的（expirationDate 在过去）丢掉；没给 expirationDate = 会话 Cookie。
    - 名字 / 值不合法（含分号、控制字符、超长）直接拒绝整套，错误消息不带值。
    """
    if len(items) > MAX_IMPORTED_COOKIES:
        raise CookieImportError(f"too many cookies ({len(items)} > {MAX_IMPORTED_COOKIES})")
    now = time.time()
    out: list[StoredCookie] = []
    skipped_domain = 0
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise CookieImportError(f"cookie #{idx} is not an object")
        name = _check_name(item.get("name"), idx)
        value = _check_value(item.get("value"), name)
        raw_domain = str(item.get("domain") or "").strip().lower()
        if not raw_domain.lstrip("."):
            raise CookieImportError(f"cookie {name} has no domain")
        host_only = item.get("hostOnly")
        domain = normalize_domain(raw_domain, None if host_only is None else bool(host_only))
        if not is_google_domain(domain):
            skipped_domain += 1
            continue
        path = str(item.get("path") or "/").strip() or "/"
        if not path.startswith("/"):
            raise CookieImportError(f"cookie {name} has an invalid path")
        try:
            expires = float(item.get("expirationDate") or 0)
        except (TypeError, ValueError):
            raise CookieImportError(f"cookie {name} has an invalid expirationDate") from None
        if expires and expires <= now:
            continue
        secure = item.get("secure")
        secure = True if secure is None else bool(secure)
        if name.startswith(("__Secure-", "__Host-")):
            secure = True
        if name.startswith("__Host-") and not (not domain.startswith(".") and path == "/"):
            # 浏览器不会接受这样的 __Host- Cookie，也就不会发它
            continue
        http_only = item.get("httpOnly")
        if not value:
            continue
        out.append(StoredCookie(
            name=name, value=value, domain=domain, path=path, expires=expires,
            secure=secure, http_only=True if http_only is None else bool(http_only),
        ))
    if skipped_domain:
        logger.info(f"Imported cookie set: skipped {skipped_domain} cookie(s) outside google.com")
    return _dedup(out)


def cookies_from_header(raw: str) -> list[StoredCookie]:
    """面板粘贴的整段 `Cookie:` 请求头 → 罐里的条目。

    请求头里没有域信息：`OSID` / `__Secure-OSID` / `__Host-*` 按 gemini.google.com 的
    host-only 记（这段头是浏览器发给 gemini.google.com 的），其余按 .google.com 的域 Cookie 记。
    同名出现多次时取第一个（浏览器把 path 更长 / 更早创建的排在前面）。
    """
    text = (raw or "").strip()
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:"):]
    out: list[StoredCookie] = []
    seen: set[str] = set()
    for idx, part in enumerate(re.split(r"[;\r\n]+", text)):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = _check_name(name, idx)
        value = _check_value(value, name)
        if not value or name in seen:
            continue
        if len(out) >= MAX_IMPORTED_COOKIES:
            raise CookieImportError(f"too many cookies (> {MAX_IMPORTED_COOKIES})")
        seen.add(name)
        if name in _GEMINI_HOST_ONLY_NAMES or name.startswith("__Host-"):
            domain = GEMINI_HOST
        else:
            domain = GOOGLE_DOMAIN
        out.append(StoredCookie(name=name, value=value, domain=domain, path="/", secure=True))
    return out


class _SetCookie(NamedTuple):
    name: str
    value: str
    expires: float | None
    domain: str = ""
    path: str = ""
    secure: bool = False
    http_only: bool = False


class PersistentCookieJar:
    """基于 JSON 文件的持久化 Cookie 管理器"""

    def __init__(self, account_id: str):
        self._account_id = account_id
        self._cookies: dict[tuple, StoredCookie] = {}
        # 被整套换上 / set 换掉的旧值：(name, domain, path, value) → 到期时间（只在内存里）。
        # 换上之前就发出去、还在路上的请求回来时，响应的 Cookie 列表里带着它发出去的那份旧值
        # （curl 原样回显，键与罐里一致）；不认出来就会把刚换上的新值改回旧值 —— 浏览器保活的
        # 账号上，这等于拿浏览器已经轮换掉的 PSIDTS 去请求，整个会话会被踢下线。
        self._superseded: dict[tuple, float] = {}
        # 可重入：_cleanup_expired 在持锁时会调 _persist，_persist 自己也要拿锁取快照
        self._lock = RLock()
        self._load()

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def get_all(self, domain: str = "google.com") -> dict[str, str]:
        """获取指定域名（及其子域）下所有有效 Cookie：name → value。

        不看目标 URL —— 只给「读 PSID / PSIDTS」这类调用方用；要发请求请用 cookies_for_url /
        request_cookies。同名多条时 .google.com 的域 Cookie 优先。内部记录（config.local）取不到。
        """
        domain = (domain or "").strip().lower().lstrip(".")
        with self._lock:
            self._cleanup_expired()
            result: dict[str, str] = {}
            ranks: dict[str, int] = {}
            for c in self._cookies.values():
                base = c.domain.lstrip(".")
                if not (base == domain or base.endswith("." + domain)):
                    continue
                rank = 1 if (base == domain and not c.host_only) else 0
                if ranks.get(c.name, -1) > rank:
                    continue
                result[c.name] = c.value
                ranks[c.name] = rank
            return result

    def _select_for_url(self, url: str) -> list[StoredCookie]:
        """给 url 该发的 Cookie（每个名字一条）。

        RFC 6265：域匹配 + 路径匹配；过期的不发；Secure 的只走 https；`__Host-` 前缀必须是
        host-only 且 path=/（旧版本把 accounts.google.com 的 __Host-GAPS 记成了 .google.com，
        浏览器从不把它发给别的主机）；内部记录永远不发。
        同名多条：path 更长者优先（RFC 6265 §5.4 的排序），其次 host-only、域更具体者优先。
        """
        scheme, host, path = _url_parts(url)
        if not host:
            return []
        now = time.time()
        with self._lock:
            candidates = []
            for c in self._cookies.values():
                if not c.value or c.internal:
                    continue
                if c.expires and c.expires <= now:
                    continue
                if c.secure and scheme != "https":
                    continue
                if c.name.startswith("__Host-") and not (c.host_only and c.path == "/"):
                    continue
                if not domain_matches(host, c.domain) or not path_matches(path, c.path):
                    continue
                candidates.append(c)
        candidates.sort(key=lambda c: (-len(c.path), not c.host_only, -len(c.domain.lstrip("."))))
        picked: dict[str, StoredCookie] = {}
        for c in candidates:
            picked.setdefault(c.name, c)
        return list(picked.values())

    def cookies_for_url(self, url: str) -> dict[str, str]:
        """给 url 该发哪些 Cookie：name → value（规则见 _select_for_url）。"""
        return {c.name: c.value for c in self._select_for_url(url)}

    def request_cookies(self, url: str):
        """同 cookies_for_url，但装进带真实域名的 curl_cffi Cookies 罐，直接当 cookies= 传给请求。

        为什么不传普通 dict：curl_cffi 会把 dict 里的每条 Cookie 都记成「请求主机的 host-only」，
        于是①重定向到别的主机时一条都不带（生成图下载、/app 跳登录页都会跨主机）；②响应里回来的
        Cookie 列表带着这个错误的域，再存回罐里就成了同名的第二份。带上真实域名，curl 自己的
        Cookie 引擎在每一跳都按域发送，回来的条目也与罐里的键一一对应。
        """
        from curl_cffi.requests import Cookies

        jar = Cookies()
        for c in self._select_for_url(url):
            jar.jar.set_cookie(_to_cookiejar_cookie(c))
        return jar

    def get(self, name: str) -> str | None:
        """获取单个 Cookie 值。同名多条时 .google.com 的域 Cookie 优先、其次 google.com 的子域，
        同级取最后写入的那条。"""
        with self._lock:
            best = None
            best_rank = -1
            for c in self._cookies.values():
                if c.name != name:
                    continue
                if c.domain == GOOGLE_DOMAIN:
                    rank = 2
                elif is_google_domain(c.domain):
                    rank = 1
                else:
                    rank = 0
                if rank >= best_rank:
                    best, best_rank = c, rank
            return best.value if best is not None else None

    def cookie_names(self) -> list:
        """返回当前所有 Cookie 名称（去重）"""
        with self._lock:
            return sorted({c.name for c in self._cookies.values()})

    @property
    def account_id(self) -> str:
        """罐文件挂在哪个账号标识（PSID）名下（文件名是它的哈希）。"""
        return self._account_id

    def holds_full_set(self) -> bool:
        """罐里装着浏览器推来的整套 Cookie（见 FULL_SET_MARKERS），而不只是 PSID / PSIDTS 和捕获来的那些。"""
        with self._lock:
            return any(c.name in FULL_SET_MARKERS and not c.internal for c in self._cookies.values())

    def entries(self) -> list[StoredCookie]:
        """整罐的副本（含内部记录），供 reload 失败时原样还原。"""
        with self._lock:
            return [replace(c) for c in self._cookies.values()]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def _supersede(self, old: StoredCookie, new: StoredCookie | None) -> None:
        """old 被 new 换掉了（new 为 None = 被删掉）：记下旧值，响应里回显的这份旧值不再写回。持锁调用。
        new 这个值重新成了当前值（如 reload 失败整罐还原）时撤掉它的旧记录。"""
        if new is not None:
            self._superseded.pop(new.key + (new.value,), None)
        if old.internal or (new is not None and new.value == old.value):
            return
        now = time.time()
        if len(self._superseded) > 512:
            self._superseded = {k: t for k, t in self._superseded.items() if t > now}
        self._superseded[old.key + (old.value,)] = now + _SUPERSEDED_TTL

    def _is_superseded(self, item: StoredCookie) -> bool:
        expires_at = self._superseded.get(item.key + (item.value,))
        return expires_at is not None and expires_at > time.time()

    def set(self, name: str, value: str, **kwargs) -> None:
        """手动设置单个 Cookie（默认 .google.com 的域 Cookie）"""
        cookie = StoredCookie(name=name, value=value, **kwargs)
        cookie.domain = normalize_domain(cookie.domain) or GOOGLE_DOMAIN
        with self._lock:
            old = self._cookies.get(cookie.key)
            if old is not None:
                self._supersede(old, cookie)
            else:
                self._superseded.pop(cookie.key + (cookie.value,), None)
            self._cookies[cookie.key] = cookie
        self._persist()

    def remove(self, name: str) -> None:
        """移除同名的所有 Cookie（不论域）"""
        with self._lock:
            for key in [k for k in self._cookies if k[0] == name]:
                del self._cookies[key]
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

    def replace_cookies(self, cookies: list[StoredCookie]) -> int:
        """整套换上（浏览器插件 / 面板推来的完整 Cookie）：罐里除内部记录以外的条目全部丢掉，
        换成这一套。之前从响应里捕获的 NID / COMPASS 之类同样属于旧会话，一并丢掉。返回条数。"""
        incoming = _dedup([replace(c) for c in cookies if not c.internal])
        by_key = {c.key: c for c in incoming}
        with self._lock:
            for old in self._cookies.values():
                self._supersede(old, by_key.get(old.key))
            for c in incoming:
                self._superseded.pop(c.key + (c.value,), None)
            kept = {k: c for k, c in self._cookies.items() if c.internal}
            self._cookies = kept
            for c in incoming:
                self._cookies[c.key] = c
        self._persist()
        names = sorted({c.name for c in incoming})
        logger.info(f"Cookie jar replaced with {len(incoming)} cookies: {names}")
        return len(incoming)

    def restore(self, entries: list[StoredCookie]) -> None:
        """整罐还原成 entries()（含内部记录）。"""
        restored = {c.key: replace(c) for c in entries}
        with self._lock:
            for old in self._cookies.values():
                self._supersede(old, restored.get(old.key))
            for c in restored.values():
                self._superseded.pop(c.key + (c.value,), None)
            self._cookies = restored
        self._persist()

    def rebind(self, account_id: str) -> None:
        """罐文件改挂到另一个账号标识（PSID）名下：写新文件、删旧文件。

        罐文件按 PSID 的哈希命名，而启动时按 accounts.json 里的 PSID 找它。面板 / 插件换上
        一个新 PSID 并回写 accounts.json 之后，不搬的话下次启动找不到这份完整 Cookie。
        """
        if not account_id or account_id == self._account_id:
            return
        old_path = self._store_path()
        with self._lock:
            self._account_id = account_id
        self._persist()
        if old_path != self._store_path():
            try:
                old_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning(f"旧的 Cookie 缓存文件删除失败（不影响使用）: {e}")

    # ------------------------------------------------------------------
    # 从响应捕获
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_response_cookies(cookies, resp_host: str = "") -> list[StoredCookie]:
        """把响应 cookie 容器摊平成带真实域名的条目列表。

        curl_cffi 的 ``Cookies.items()``（经 MutableMapping → ``get()``）在同名 Cookie
        跨域并存时抛 ``CookieConflict``：
            Multiple cookies exist with name=NID on www.google.com and .google.com.hk
        Google 把用户跳到国家域名（.google.com.hk/.com.tw/.co.jp …）时必现，异常会一路
        冒到 ``_obtain_session_token`` 让 token 置空、账号被判 unhealthy（issue #10）。
        因此这里直接遍历底层 ``http.cookiejar.CookieJar``——每个条目是独立 Cookie 对象，
        自带 name/value/domain，天然没有同名冲突。

        现在每个条目按 (name, domain, path) 各存各的：国家域的 NID 记在国家域名下，域匹配
        决定它永远不会发给 *.google.com，不再需要「同名只留一个」的取舍。
        domain_specified 为假 = host-only（curl 对没有 Domain 属性的 Set-Cookie 就是这么记的）。
        """
        jar = getattr(cookies, "jar", None)
        if jar is None:
            # 非 curl_cffi 容器（如普通 dict）没有域信息：按 .google.com 记（与改动前一致）
            return [
                StoredCookie(name=n, value=v or "", secure=str(n).startswith("__Secure"))
                for n, v in cookies.items() if n
            ]
        out: list[StoredCookie] = []
        for c in jar:
            name = getattr(c, "name", None)
            if not name:
                continue
            value = getattr(c, "value", None) or ""
            raw_domain = (getattr(c, "domain", None) or "").strip().lower()
            if raw_domain.lstrip("."):
                domain = normalize_domain(raw_domain, not getattr(c, "domain_specified", True))
            else:
                domain = resp_host or GOOGLE_DOMAIN
            # curl_cffi 把 HttpOnly 记在非标准属性 http_only="True"/"False" 里
            rest = getattr(c, "_rest", None) or {}
            http_only = any(str(k).lower() in ("httponly", "http_only") and str(v) != "False"
                            for k, v in rest.items())
            out.append(StoredCookie(
                name=name,
                value=value,
                domain=domain,
                path=getattr(c, "path", None) or "/",
                expires=int(getattr(c, "expires", None) or 0),
                secure=bool(getattr(c, "secure", False)) or name.startswith(("__Secure-", "__Host-")),
                http_only=http_only,
            ))
        return out

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
        # 响应的最终主机：没有 Domain 属性的 Set-Cookie 是它的 host-only Cookie。
        # 测试替身 / 拿不到 URL 时为空，退回改动前的 .google.com。
        _, resp_host, resp_path = _url_parts(getattr(response, "url", "") or "")
        changed = False
        # 处理这个响应之前罐里的值：下面 Set-Cookie 换掉 / 删掉的，要把这里的旧值记成「已换掉」。
        # 不能拿写入那一刻的现值比 —— curl 的 Cookie 列表里同样是新值，第一段循环已经先写进去了，
        # 到 Set-Cookie 这一段时看到的现值已是新值，旧值就漏记了（复审：轮换后在路上的流式请求回显
        # 旧 PSIDTS，把罐改回谷歌已经换掉的那个）。
        with self._lock:
            before = dict(self._cookies)
        for item in self._iter_response_cookies(response.cookies, resp_host):
            with self._lock:
                # 空值视为服务端删除指令：删除而非用空值覆盖有效凭据 Cookie。
                if not item.value:
                    if self._cookies.pop(item.key, None) is not None:
                        changed = True
                    continue
                # 换上新值之前就发出去的请求，回来时带着旧值的回显：不写回（见 _superseded）
                if self._is_superseded(item):
                    continue
                # 只比值：响应的 Cookie 列表里也有我们自己发出去的那份（带着同样的域），
                # 值没变就是回显，不算更新。
                existing = self._cookies.get(item.key)
                if existing is None or existing.value != item.value:
                    self._cookies[item.key] = item
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
                if not parsed:
                    continue
                if parsed.domain:
                    domain = normalize_domain(parsed.domain, host_only=False)
                    if resp_host and not domain_matches(resp_host, domain):
                        continue  # Domain 属性不覆盖响应主机：浏览器会丢弃这条
                else:
                    domain = resp_host or GOOGLE_DOMAIN
                if parsed.path.startswith("/"):
                    path = parsed.path
                else:
                    path = _default_path(resp_path) if resp_host else "/"
                key = (parsed.name, domain, path)
                with self._lock:
                    # 删除指令（空值 / Max-Age<=0 / Expires 已过期）：删除现有 Cookie，
                    # 绝不用空值或已过期值覆盖仍有效的认证 Cookie（VULN-010 写容错）。
                    expires = parsed.expires
                    is_deletion = (not parsed.value) or (expires is not None and expires <= time.time())
                    prev = before.get(key)
                    if is_deletion:
                        if self._cookies.pop(key, None) is not None:
                            changed = True
                        if prev is not None:
                            self._supersede(prev, None)  # 在路上的旧值回显不能把它变回来
                        continue
                    ex = self._cookies.get(key)
                    new_expires = expires if expires is not None else 0
                    cookie = StoredCookie(
                        name=parsed.name,
                        value=parsed.value,
                        domain=domain,
                        path=path,
                        expires=new_expires,
                        secure=parsed.secure or parsed.name.startswith(("__Secure-", "__Host-")),
                        http_only=parsed.http_only,
                    )
                    if prev is not None:
                        # 服务端用 Set-Cookie 换了值：旧值记成已换掉（值没变时 _supersede 什么都不记）
                        self._supersede(prev, cookie)
                    if ex is None or ex.value != parsed.value or ex.expires != new_expires:
                        self._cookies[key] = cookie
                        changed = True

        if changed:
            self._persist()
            names = self.cookie_names()
            logger.debug(f"Cookie jar updated: {len(self._cookies)} - {names}")

    @staticmethod
    def _parse_set_cookie_header(raw: str) -> _SetCookie | None:
        """解析单条 Set-Cookie 头 → (name, value, expires, domain, path)。

        expires 为绝对 Unix 时间戳（秒）；无 Expires/Max-Age 属性时为 None。
        Max-Age 优先级高于 Expires（RFC 6265）。Max-Age<=0 或 Expires 在过去 →
        expires 取一个过去时间戳，供上层据此识别为删除指令。
        domain / path 是 Domain / Path 属性的原文，没有就是空串（由调用方按响应 URL 补）。
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
            domain_attr = ""
            path_attr = ""
            secure = False
            http_only = False
            for attr in parts[1:]:
                if "=" not in attr:
                    flag = attr.strip().lower()
                    if flag == "secure":
                        secure = True
                    elif flag == "httponly":
                        http_only = True
                    continue
                k, av = attr.split("=", 1)
                k = k.strip().lower()
                av = av.strip()
                if k == "max-age":
                    max_age = av
                elif k == "expires":
                    expires_attr = av
                elif k == "domain":
                    domain_attr = av
                elif k == "path":
                    path_attr = av

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

            return _SetCookie(n, v, expires, domain_attr, path_attr, secure, http_only)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _cleanup_expired(self):
        """清理过期 Cookie"""
        now = time.time()
        with self._lock:
            expired = [
                key for key, c in self._cookies.items()
                if c.expires > 0 and c.expires < now
            ]
            for key in expired:
                del self._cookies[key]
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
                # 旧版本的条目一律是 .google.com（没写 domain 的同样按 .google.com）
                domain = normalize_domain(item.get("domain") or GOOGLE_DOMAIN) or GOOGLE_DOMAIN
                cookie = StoredCookie(
                    name=item["name"],
                    value=item["value"],
                    domain=domain,
                    path=item.get("path") or "/",
                    expires=item.get("expires", 0) or 0,
                    secure=item.get("secure", True),
                    http_only=item.get("http_only", True),
                )
            except (KeyError, TypeError, AttributeError):
                continue  # 坏记录单条跳过，保留其余有效 Cookie（VULN-010 读容错）
            self._cookies[cookie.key] = cookie
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
                cookie = StoredCookie(name="__Secure-1PSIDTS", value=psidts, secure=True)
                self._cookies[cookie.key] = cookie

    def _persist(self):
        path = self._store_path()
        with self._lock:
            data = [asdict(c) for c in self._cookies.values()]
        # 原子写，避免写入中途崩溃损坏 Cookie 文件（VULN-010）
        atomic_write_json(path, data, ensure_ascii=False)

"""Cookie 罐按 (name, domain, path) 存、按 URL 取（谷歌 11-20 改版，v1.6.53 规格 A1 / A2）。

背景（北京 2026-11-24 东京线上只读探针）：只带 __Secure-1PSID/1PSIDTS 打开 /app 会被 302 到谷歌
登录页；要浏览器里完整的谷歌 Cookie，外加 gemini.google.com 自己的 host-only Cookie OSID /
__Secure-OSID。而 OSID 一旦发到 lh3.google.com，生成图下载链第二跳当成匿名、最后一跳 403。
所以罐必须记住每条 Cookie 的域，按目标 URL 只发该发的（RFC 6265 域匹配 / 路径匹配）。
"""

import json
import time

import pytest

from app.core.fingerprint import cookie_jar as cj_mod
from app.core.fingerprint.cookie_jar import (
    CookieImportError,
    PersistentCookieJar,
    StoredCookie,
    cookies_from_browser,
    cookies_from_header,
    domain_matches,
    path_matches,
)

curl_cookies = pytest.importorskip(
    "curl_cffi.requests.cookies", reason="curl_cffi not installed (runtime dep)"
)

GEMINI = "https://gemini.google.com/app"
ACCOUNTS = "https://accounts.google.com/RotateCookies"
LH3 = "https://lh3.google.com/u/0/d/abc=s2048"
LH3_GUC = "https://lh3.googleusercontent.com/gg/abc=s2048"


@pytest.fixture
def jar(tmp_path, monkeypatch):
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    return PersistentCookieJar("acct-domains")


def _fill(jar, cookies):
    jar.replace_cookies(cookies)
    return jar


def _full_set():
    """浏览器访问 gemini.google.com 时会发的那一套（值是假的）。"""
    return [
        StoredCookie("__Secure-1PSID", "psid-v"),
        StoredCookie("__Secure-1PSIDTS", "psidts-v"),
        StoredCookie("SID", "sid-v"),
        StoredCookie("HSID", "hsid-v", secure=False),
        StoredCookie("SAPISID", "sapisid-v"),
        StoredCookie("__Secure-1PSIDCC", "psidcc-v"),
        StoredCookie("OSID", "osid-v", domain="gemini.google.com"),
        StoredCookie("__Secure-OSID", "sosid-v", domain="gemini.google.com"),
    ]


# ---------------------------------------------------------------------------
# 1. RFC 6265 的域匹配 / 路径匹配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host,ok", [
    ("google.com", True),
    ("www.google.com", True),
    ("gemini.google.com", True),
    ("accounts.google.com", True),
    ("lh3.google.com", True),
    ("lh3.googleusercontent.com", False),
    ("evilgoogle.com", False),
    ("google.com.hk", False),
])
def test_domain_cookie_matches_the_domain_and_every_subdomain(host, ok):
    assert domain_matches(host, ".google.com") is ok


@pytest.mark.parametrize("host,ok", [
    ("gemini.google.com", True),
    ("accounts.google.com", False),
    ("lh3.google.com", False),
    ("google.com", False),
    ("x.gemini.google.com", False),
])
def test_host_only_cookie_matches_only_the_exact_host(host, ok):
    assert domain_matches(host, "gemini.google.com") is ok


@pytest.mark.parametrize("req,cookie,ok", [
    ("/", "/", True),
    ("/app", "/", True),
    ("/app", "/app", True),
    ("/app/x", "/app", True),
    ("/apps", "/app", False),
    ("/", "/app", False),
    ("/app/x", "/app/", True),
])
def test_path_prefix_matching(req, cookie, ok):
    assert path_matches(req, cookie) is ok


# ---------------------------------------------------------------------------
# 2. 按 URL 取
# ---------------------------------------------------------------------------

def test_gemini_gets_the_domain_cookies_and_its_own_host_only_osid(jar):
    _fill(jar, _full_set())
    sent = jar.cookies_for_url(GEMINI)
    assert sent["OSID"] == "osid-v"
    assert sent["__Secure-OSID"] == "sosid-v"
    assert sent["__Secure-1PSID"] == "psid-v"
    assert sent["SID"] == "sid-v"


@pytest.mark.parametrize("url", [ACCOUNTS, LH3, "https://www.google.com/"])
def test_other_hosts_never_get_gemini_host_only_cookies(jar, url):
    _fill(jar, _full_set())
    sent = jar.cookies_for_url(url)
    assert "OSID" not in sent and "__Secure-OSID" not in sent
    assert sent["__Secure-1PSID"] == "psid-v", "域 Cookie 照发"


def test_lh3_googleusercontent_gets_no_google_com_cookie_at_all(jar):
    _fill(jar, _full_set())
    assert jar.cookies_for_url(LH3_GUC) == {}


def test_expired_cookies_are_not_sent(jar):
    _fill(jar, [
        StoredCookie("__Secure-1PSID", "psid-v"),
        StoredCookie("OLD", "old-v", expires=time.time() - 10),
        StoredCookie("NEW", "new-v", expires=time.time() + 3600),
    ])
    sent = jar.cookies_for_url(GEMINI)
    assert "OLD" not in sent
    assert sent["NEW"] == "new-v"


def test_same_name_prefers_the_longer_path(jar):
    jar.set("NID", "root-v")
    jar.set("NID", "app-v", path="/app")
    assert jar.cookies_for_url("https://gemini.google.com/app")["NID"] == "app-v"
    assert jar.cookies_for_url("https://gemini.google.com/")["NID"] == "root-v"


def test_same_name_same_path_prefers_host_only(jar):
    jar.set("NID", "domain-v")
    jar.set("NID", "host-v", domain="gemini.google.com")
    assert jar.cookies_for_url(GEMINI)["NID"] == "host-v"
    assert jar.cookies_for_url(ACCOUNTS)["NID"] == "domain-v"


def test_internal_snapshot_record_is_never_sent_anywhere(jar):
    jar.set("__cfg-1PSIDTS", "snap-v", domain=cj_mod.INTERNAL_DOMAIN, secure=False)
    jar.set("__Secure-1PSID", "psid-v")
    for url in (GEMINI, ACCOUNTS, LH3, "https://config.local/", "http://config.local/"):
        assert "__cfg-1PSIDTS" not in jar.cookies_for_url(url)
    assert "__cfg-1PSIDTS" not in jar.get_all()
    assert jar.get("__cfg-1PSIDTS") == "snap-v", "快照照旧能按名字读回来"


def test_host_prefixed_cookie_on_a_domain_is_not_sent(jar):
    """旧版本把 accounts.google.com 的 __Host-GAPS 记成了 .google.com：浏览器从不把它发给别的主机。"""
    jar.set("__Host-GAPS", "legacy-v")
    jar.set("__Host-GAPS", "real-v", domain="accounts.google.com")
    assert "__Host-GAPS" not in jar.cookies_for_url(GEMINI)
    assert jar.cookies_for_url(ACCOUNTS)["__Host-GAPS"] == "real-v"


def test_secure_cookies_only_go_over_https(jar):
    _fill(jar, _full_set())
    sent = jar.cookies_for_url("http://gemini.google.com/app")
    assert sent == {"HSID": "hsid-v"}


def test_request_cookies_carry_the_real_domain_for_curl(jar):
    """交给 curl 的罐必须带真实域名：域 Cookie 的 include-subdomains 位为 TRUE、host-only 为 FALSE，
    curl 自己的 Cookie 引擎因此在重定向的每一跳都按域发送。"""
    _fill(jar, _full_set())
    transport = jar.request_cookies(GEMINI)

    class _Req:
        url = GEMINI
        headers = {}

    lines = {m.name: m.to_curl_format().split("\t") for m in transport.get_cookies_for_curl(_Req())}
    assert lines["OSID"][:2] == ["gemini.google.com", "FALSE"]
    assert lines["__Secure-1PSID"][:2] == [".google.com", "TRUE"]
    assert dict(transport)["SID"] == "sid-v", "也能当 name → value 的映射读"

    lh3 = {m.name for m in jar.request_cookies(LH3).get_cookies_for_curl(_Req())}
    assert "OSID" not in lh3 and "__Secure-1PSID" in lh3


# ---------------------------------------------------------------------------
# 3. 旧文件兼容
# ---------------------------------------------------------------------------

def test_v1652_cookie_file_still_loads(tmp_path, monkeypatch):
    """v1.6.52 的罐文件：按名字一条、domain 一律 .google.com（个别条目没写 domain）。"""
    store = tmp_path / "cookies"
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", store)
    probe = PersistentCookieJar("acct-legacy")
    path = probe._store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {"name": "__Secure-1PSID", "value": "psid-v", "domain": ".google.com", "path": "/",
         "expires": 0, "secure": True, "http_only": True},
        {"name": "__Secure-1PSIDTS", "value": "psidts-v"},
        {"name": "NID", "value": "nid-v", "domain": ".google.com", "expires": 0},
        {"name": "__cfg-1PSIDTS", "value": "snap-v", "domain": "config.local", "secure": False},
        {"name": "broken"},
    ]), encoding="utf-8")

    jar = PersistentCookieJar("acct-legacy")

    assert jar.get_all() == {"__Secure-1PSID": "psid-v", "__Secure-1PSIDTS": "psidts-v", "NID": "nid-v"}
    assert jar.cookies_for_url(GEMINI) == jar.get_all()
    assert jar.cookies_for_url(LH3)["__Secure-1PSIDTS"] == "psidts-v", "旧条目没写 domain 按 .google.com"
    assert jar.get("__cfg-1PSIDTS") == "snap-v"


def test_new_file_round_trips_domains(jar, tmp_path):
    _fill(jar, _full_set())
    again = PersistentCookieJar("acct-domains")
    assert again.cookies_for_url(GEMINI) == jar.cookies_for_url(GEMINI)
    assert "OSID" not in again.cookies_for_url(ACCOUNTS)


# ---------------------------------------------------------------------------
# 4. 从响应捕获：记下真实域名
# ---------------------------------------------------------------------------

class _Headers(dict):
    """模拟 curl_cffi 的多值头容器（Set-Cookie 可重复）。"""

    def __init__(self, set_cookies):
        super().__init__({"content-type": "text/html"})
        self._sc = list(set_cookies)

    def get_list(self, key):
        return list(self._sc) if key.lower() == "set-cookie" else []


class _Resp:
    def __init__(self, url, set_cookies=(), cookies=None):
        self.url = url
        self.headers = _Headers(set_cookies)
        self.cookies = cookies if cookies is not None else curl_cookies.Cookies()
        self.status_code = 200


def test_set_cookie_without_domain_is_host_only_of_the_response_host(jar):
    jar.update_from_response(_Resp(GEMINI, [
        "__Secure-OSID=fresh-v; Path=/; Secure; HttpOnly",
        "NID=nid-v; Domain=.google.com; Path=/; Secure",
    ]))

    assert jar.cookies_for_url(GEMINI)["__Secure-OSID"] == "fresh-v"
    assert "__Secure-OSID" not in jar.cookies_for_url(LH3), "没有 Domain 属性 = 只属于 gemini.google.com"
    assert jar.cookies_for_url(LH3)["NID"] == "nid-v"


def test_set_cookie_after_a_redirect_belongs_to_the_final_host(jar):
    """curl 跟随了重定向：resp.url 是落点，没 Domain 属性的 Set-Cookie 属于它（如 accounts 的 __Host-GAPS）。"""
    jar.update_from_response(_Resp("https://accounts.google.com/v3/signin/identifier", [
        "__Host-GAPS=gaps-v; Path=/; Secure; HttpOnly",
    ]))
    assert "__Host-GAPS" not in jar.cookies_for_url(GEMINI)
    assert jar.cookies_for_url(ACCOUNTS)["__Host-GAPS"] == "gaps-v"


def test_set_cookie_for_a_foreign_domain_is_ignored(jar):
    jar.update_from_response(_Resp(GEMINI, ["X=x-v; Domain=.youtube.com; Path=/"]))
    assert "X" not in jar.cookie_names()


def test_set_cookie_deletion_only_hits_the_same_domain(jar):
    jar.set("NID", "domain-v")
    jar.set("NID", "host-v", domain="gemini.google.com")
    jar.update_from_response(_Resp(GEMINI, ["NID=; Domain=.google.com; Path=/; Max-Age=0"]))
    assert jar.cookies_for_url(ACCOUNTS).get("NID") is None
    assert jar.cookies_for_url(GEMINI)["NID"] == "host-v"


def test_curl_jar_entries_keep_host_only_flag(jar):
    """curl 的 Cookie 列表：domain_specified 为假 = host-only（没 Domain 属性的 Set-Cookie）。"""
    from http.cookiejar import Cookie

    c = curl_cookies.Cookies()
    c.jar.set_cookie(Cookie(0, "OSID", "osid-new", None, False, "gemini.google.com", False, False,
                            "/", True, True, None, True, None, None, {}, False))
    c.set("SIDCC", "sidcc-new", ".google.com", secure=True)
    jar.update_from_response(_Resp(GEMINI, cookies=c))

    assert jar.cookies_for_url(GEMINI)["OSID"] == "osid-new"
    assert "OSID" not in jar.cookies_for_url(ACCOUNTS)
    assert jar.cookies_for_url(ACCOUNTS)["SIDCC"] == "sidcc-new"


def test_echo_of_what_we_sent_creates_no_duplicates(jar, monkeypatch):
    """响应的 Cookie 列表里也有我们发出去的那份（curl 原样回显，域名相同）：不能变出第二份、也不落盘。"""
    _fill(jar, _full_set())
    before = sorted((c.name, c.domain, c.path, c.value) for c in jar.entries())
    writes = []
    monkeypatch.setattr(jar, "_persist", lambda: writes.append(1))

    jar.update_from_response(_Resp(GEMINI, cookies=jar.request_cookies(GEMINI)))

    assert sorted((c.name, c.domain, c.path, c.value) for c in jar.entries()) == before
    assert writes == []


# ---------------------------------------------------------------------------
# 5. 整套换上 / 还原 / 搬家
# ---------------------------------------------------------------------------

def test_replace_cookies_keeps_only_the_internal_records(jar):
    jar.set("__cfg-1PSIDTS", "snap-v", domain=cj_mod.INTERNAL_DOMAIN, secure=False)
    jar.set("NID", "captured-old")
    jar.set("__Secure-1PSID", "old-psid")

    jar.replace_cookies(_full_set())

    assert jar.get("NID") is None, "旧会话捕获来的 Cookie 一并丢掉"
    assert jar.get("__Secure-1PSID") == "psid-v"
    assert jar.get("__cfg-1PSIDTS") == "snap-v", "内部快照条目保留"


def test_restore_puts_back_the_exact_previous_jar(jar):
    jar.set("__Secure-1PSID", "old-psid")
    jar.set("NID", "old-nid")
    backup = jar.entries()
    jar.replace_cookies(_full_set())
    jar.restore(backup)
    assert jar.get_all() == {"__Secure-1PSID": "old-psid", "NID": "old-nid"}


def test_rebind_moves_the_file_to_the_new_psid(tmp_path, monkeypatch):
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    jar = PersistentCookieJar("PSID-OLD")
    jar.replace_cookies(_full_set())
    old_path = jar._store_path()
    assert old_path.exists()

    jar.rebind("PSID-NEW")

    assert not old_path.exists(), "旧 PSID 名下不再留一份完整 Cookie"
    reloaded = PersistentCookieJar("PSID-NEW")
    assert reloaded.cookies_for_url(GEMINI)["OSID"] == "osid-v"


# ---------------------------------------------------------------------------
# 6. 导入：插件的 chrome.cookies.Cookie 列表 / 面板粘贴的 Cookie 头
# ---------------------------------------------------------------------------

def _chrome(name, value, domain, host_only, **kw):
    return {"name": name, "value": value, "domain": domain, "hostOnly": host_only, "path": "/",
            "secure": True, "httpOnly": True, "sameSite": "no_restriction", "storeId": "0",
            "session": False, **kw}


def test_browser_cookies_keep_their_domains():
    items = cookies_from_browser([
        _chrome("SID", "sid-v", ".google.com", False),
        _chrome("OSID", "osid-v", "gemini.google.com", True),
        _chrome("__Secure-OSID", "sosid-v", "gemini.google.com", True),
        _chrome("YSC", "yt-v", ".youtube.com", False),
        _chrome("STALE", "stale-v", ".google.com", False, expirationDate=time.time() - 5),
    ])
    by_name = {c.name: c for c in items}
    assert by_name["SID"].domain == ".google.com"
    assert by_name["OSID"].domain == "gemini.google.com" and by_name["OSID"].host_only
    assert by_name["__Secure-OSID"].domain == "gemini.google.com"
    assert "YSC" not in by_name, "google.com 以外的域不收"
    assert "STALE" not in by_name, "已过期的不收"


def test_browser_cookie_without_host_only_flag_uses_the_leading_dot():
    items = cookies_from_browser([
        {"name": "A", "value": "a", "domain": ".google.com"},
        {"name": "B", "value": "b", "domain": "gemini.google.com"},
    ])
    assert [c.domain for c in items] == [".google.com", "gemini.google.com"]


@pytest.mark.parametrize("bad", [
    {"name": "", "value": "v", "domain": ".google.com"},
    {"name": "A;B", "value": "v", "domain": ".google.com"},
    {"name": "A", "value": "v;x=1", "domain": ".google.com"},
    {"name": "A", "value": "v\tx", "domain": ".google.com"},
    {"name": "A", "value": "v", "domain": ""},
    {"name": "A", "value": "v", "domain": ".google.com", "path": "no-slash"},
])
def test_invalid_browser_cookie_is_rejected_without_echoing_the_value(bad):
    with pytest.raises(CookieImportError) as exc:
        cookies_from_browser([bad])
    assert "v;x=1" not in str(exc.value) and "v\tx" not in str(exc.value)


def test_too_many_cookies_are_rejected():
    with pytest.raises(CookieImportError):
        cookies_from_browser([{"name": f"C{i}", "value": "v", "domain": ".google.com"}
                              for i in range(cj_mod.MAX_IMPORTED_COOKIES + 1)])


def test_pasted_cookie_header_domains_are_inferred():
    items = cookies_from_header(
        "Cookie: SID=sid-v; OSID=osid-v; __Secure-OSID=sosid-v; __Host-GAPS=gaps-v; "
        "__Secure-1PSID=psid-v; __Secure-1PSIDTS=psidts-v; SID=dup-ignored"
    )
    by_name = {c.name: c for c in items}
    assert by_name["OSID"].domain == "gemini.google.com"
    assert by_name["__Secure-OSID"].domain == "gemini.google.com"
    assert by_name["__Host-GAPS"].domain == "gemini.google.com"
    assert by_name["SID"].domain == ".google.com"
    assert by_name["SID"].value == "sid-v", "同名取第一个"
    assert by_name["__Secure-1PSID"].domain == ".google.com"


def test_pasted_header_without_prefix_and_with_newlines():
    items = cookies_from_header("SID=a;\nOSID=b\r\n; empty=; junk")
    assert {c.name: c.domain for c in items} == {"SID": ".google.com", "OSID": "gemini.google.com"}


# ---------------------------------------------------------------------------
# 7. 换上新值之前发出去的请求：回来时带着旧值的回显不能把新值改回去
# ---------------------------------------------------------------------------

def test_stale_echo_after_a_full_replace_does_not_revert_the_new_set(jar):
    """插件刚推来整套新 Cookie，而一个 pro 流式请求（最长 300 秒）还拿着旧的那套在路上：它回来时
    响应的 Cookie 列表里是旧值（键与罐里一致）。写回去 = 拿浏览器已经轮换掉的 PSIDTS 去请求。"""
    _fill(jar, _full_set())
    in_flight = jar.request_cookies(GEMINI)  # 换之前发出去的那份

    fresh = [StoredCookie(c.name, c.value + "-NEW", domain=c.domain) for c in _full_set()]
    jar.replace_cookies(fresh)

    echo = curl_cookies.Cookies(in_flight)
    echo.set("NID", "genuinely-new", ".google.com", secure=True)
    jar.update_from_response(_Resp(GEMINI, cookies=echo))

    sent = jar.cookies_for_url(GEMINI)
    assert sent["__Secure-1PSIDTS"] == "psidts-v-NEW"
    assert sent["OSID"] == "osid-v-NEW"
    assert sent["NID"] == "genuinely-new", "同一个响应里真正新下发的 Cookie 照收"


def test_stale_echo_after_a_single_set_is_ignored_too(jar):
    """轮换 / 面板单值更新走 set()：同一个竞态。"""
    jar.set("__Secure-1PSIDTS", "ts-old")
    in_flight = jar.request_cookies(GEMINI)
    jar.set("__Secure-1PSIDTS", "ts-new")

    jar.update_from_response(_Resp(GEMINI, cookies=curl_cookies.Cookies(in_flight)))

    assert jar.get("__Secure-1PSIDTS") == "ts-new"


def test_restoring_an_old_set_accepts_its_values_again(jar):
    """reload 失败整罐还原后，旧值重新成了当前值：之后的正常更新照常生效。"""
    _fill(jar, _full_set())
    backup = jar.entries()
    jar.replace_cookies([StoredCookie("__Secure-1PSID", "other")])
    jar.restore(backup)
    jar.set("__Secure-1PSIDTS", "rotated")
    assert jar.get("__Secure-1PSIDTS") == "rotated"
    assert jar.cookies_for_url(GEMINI)["OSID"] == "osid-v"

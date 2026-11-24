"""谷歌 11-20 改版后恢复登录态（v1.6.53 规格 A1–A4，client 与 admin 接口两侧）。

证据（北京 2026-11-24 东京线上只读探针）：
- 只带 __Secure-1PSID/1PSIDTS 打开 /app → 302 到 accounts.google.com 的登录页（title「Sign in -
  Google Accounts」，cfb2h=boq_identityfrontendauthuiserver_…）。登录页里**照样有 SNlM0e**，
  服务端以为拿到了 token，账号一直是未登录访客：心跳只看得到 Auto，别的模型一律 HTTP 400。
- 要浏览器里完整的谷歌 Cookie + gemini.google.com 的 host-only OSID / __Secure-OSID；OSID 发到
  lh3.google.com 会让生成图下载链的第二跳当成匿名、最后一跳 403。
- otAQ7b 登录态下 payload 要 [1]（[] 回 400）。
"""

import asyncio
import json
import logging

import pytest

from app.core import gemini_client as gc
from app.core.fingerprint import cookie_jar as cj_mod
from app.core.fingerprint.cookie_jar import PersistentCookieJar, StoredCookie

curl_cookies = pytest.importorskip(
    "curl_cffi.requests.cookies", reason="curl_cffi not installed (runtime dep)"
)

SECRET_VALUES = {
    "__Secure-1PSID": "psid-SECRET-1111",
    "__Secure-1PSIDTS": "psidts-SECRET-2222",
    "SID": "sid-SECRET-3333",
    "HSID": "hsid-SECRET-4444",
    "SAPISID": "sapisid-SECRET-5555",
    "__Secure-1PSIDCC": "psidcc-SECRET-6666",
    "OSID": "osid-SECRET-7777",
    "__Secure-OSID": "sosid-SECRET-8888",
}

LOGGED_IN_PAGE = (
    "<html><head><title>Google Gemini</title></head><body>"
    + "y" * 2000
    + '<script>{"cfb2h":"boq_assistant-bard-web-server_20261119.18_p0","SNlM0e":"TOKEN-REAL"}</script>'
    + '<a href="https://accounts.google.com/SignOutOptions">x</a> feeds/abc123 </body></html>'
)
SIGNIN_URL = "https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Fgemini.google.com%2Fapp"


def _signin_page(*, title="Sign in - Google Accounts",
                 cfb2h="boq_identityfrontendauthuiserver_20261118.06_p0"):
    return (
        f"<html><head><title>{title}</title></head><body>" + "z" * 2000
        + f'<script>{{"cfb2h":"{cfb2h}","qwAQke":"AccountsSignInUi","SNlM0e":"TOKEN-GUEST"}}</script>'
        + "</body></html>"
    )


def _full_set(**override) -> list[StoredCookie]:
    values = {**SECRET_VALUES, **override}
    out = []
    for name, value in values.items():
        domain = "gemini.google.com" if name in ("OSID", "__Secure-OSID") else ".google.com"
        out.append(StoredCookie(name, value, domain=domain))
    return out


def _chrome_list(**override) -> list[dict]:
    values = {**SECRET_VALUES, **override}
    out = []
    for name, value in values.items():
        host_only = name in ("OSID", "__Secure-OSID")
        out.append({
            "name": name, "value": value,
            "domain": "gemini.google.com" if host_only else ".google.com",
            "hostOnly": host_only, "path": "/", "secure": True, "httpOnly": True,
            "sameSite": "no_restriction", "session": False, "storeId": "0",
            "expirationDate": 4102444800,
        })
    return out


def _as_dict(cookies) -> dict:
    return dict(cookies) if cookies is not None else {}


class _Resp:
    def __init__(self, status=200, text="", url="", headers=None, content=b""):
        self.status_code = status
        self.text = text
        self.url = url
        self.headers = headers or {}
        self.cookies = curl_cookies.Cookies()
        self.content = content


class _Http:
    """记录每一次请求带的 cookies；/app 按脚本回页面（可以是函数）。"""

    def __init__(self, app_page=LOGGED_IN_PAGE, app_url=gc.GEMINI_APP_EN_URL):
        self.app_page = app_page
        self.app_url = app_url
        self.calls: list[tuple] = []
        self.cookies = curl_cookies.Cookies()

    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url == gc.GEMINI_APP_EN_URL:
            return _Resp(200, self.app_page, self.app_url)
        return _Resp(200, "", url)

    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return _Resp(200, ")]}'\n", url)

    async def close(self):
        return None

    def sent(self, method, url) -> dict:
        for m, u, kw in self.calls:
            if m == method and u == url:
                return _as_dict(kw.get("cookies"))
        raise AssertionError(f"no {method} {url}")


async def _noop(*a, **kw):
    return None


def _client(monkeypatch, tmp_path, *, http=None, cookies=None, psid=None, psidts=None):
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    monkeypatch.setattr(gc, "apply_jitter", _noop)
    psid = psid or SECRET_VALUES["__Secure-1PSID"]
    psidts = psidts or SECRET_VALUES["__Secure-1PSIDTS"]
    c = gc.GeminiWebClient(psid=psid, psidts=psidts)
    c._cookie_jar = PersistentCookieJar(psid)
    c._cookie_jar.replace_cookies(cookies if cookies is not None else _full_set())
    c._http = http or _Http()
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **k: c._http)
    monkeypatch.setattr(c, "_ensure_session_current", _noop)
    monkeypatch.setattr(c, "_get_headers", lambda *a, **kw: {})
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    return c


# ---------------------------------------------------------------------------
# A1：每个请求按自己的目标 URL 带 Cookie
# ---------------------------------------------------------------------------

def test_token_fetch_sends_each_host_only_its_own_cookies(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    asyncio.run(c._obtain_session_token())

    assert c._session_token == "TOKEN-REAL"
    www = c._http.sent("GET", gc.GOOGLE_HOME_URL)
    app = c._http.sent("GET", gc.GEMINI_APP_EN_URL)
    assert "OSID" not in www and "__Secure-OSID" not in www, "www.google.com 不该收到 gemini 的 host-only"
    assert www["__Secure-1PSID"] == SECRET_VALUES["__Secure-1PSID"]
    assert app["OSID"] == SECRET_VALUES["OSID"]
    assert app["__Secure-OSID"] == SECRET_VALUES["__Secure-OSID"]
    assert app["SID"] == SECRET_VALUES["SID"]


def test_requests_hand_curl_a_domain_aware_jar(monkeypatch, tmp_path):
    """交给 curl 的是带真实域名的 Cookies 罐（不是 dict）：/app 跟随跳转时每一跳也按域发送。"""
    c = _client(monkeypatch, tmp_path)
    asyncio.run(c._obtain_session_token())
    for _m, _u, kw in c._http.calls:
        assert isinstance(kw["cookies"], curl_cookies.Cookies)


def test_rotate_cookies_does_not_send_gemini_host_only_cookies(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c._cookie_jar.set("__Host-GAPS", "gaps-v", domain="accounts.google.com")

    asyncio.run(c._rotate_cookies())

    sent = c._http.sent("POST", gc.ROTATE_COOKIES_URL)
    assert "OSID" not in sent and "__Secure-OSID" not in sent
    assert sent["__Secure-1PSIDTS"] == SECRET_VALUES["__Secure-1PSIDTS"]
    assert sent["__Host-GAPS"] == "gaps-v", "accounts.google.com 自己的 host-only 照发"


def test_batchexecute_sends_the_gemini_set(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c._session_token = "TOKEN-REAL"
    asyncio.run(c._send_heartbeat())
    sent = c._http.sent("POST", gc.BATCHEXECUTE_URL)
    assert sent["OSID"] == SECRET_VALUES["OSID"]
    assert "__Host-GAPS" not in sent


def test_upload_cookies_are_google_com_only_and_a_plain_dict(monkeypatch, tmp_path):
    """上传域不在 google.com 的 Cookie 域里：给普通 dict（curl_cffi 记成请求主机的），内容按网页端
    上传域 push.clients6.google.com 取 —— .google.com 的域 Cookie，不带 gemini 的 OSID。"""
    c = _client(monkeypatch, tmp_path)
    up = c._upload_cookies()
    assert type(up) is dict
    assert up["__Secure-1PSID"] == SECRET_VALUES["__Secure-1PSID"]
    assert "OSID" not in up and "__Secure-OSID" not in up


class _ImageHttp(_Http):
    def __init__(self, location):
        super().__init__()
        self.location = location

    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url.startswith("https://lh3.googleusercontent.com/gg/"):
            return _Resp(302, "", url, headers={"location": self.location})
        return _Resp(200, "", url, headers={"content-type": "image/png"}, content=b"PNG")


@pytest.mark.parametrize("location", [
    "https://lh3.google.com/u/0/d/xyz=s2048",
    "/u/0/d/xyz=s2048",  # 相对跳转按第一跳的 URL 补全
])
def test_generated_image_download_never_sends_osid_to_lh3(monkeypatch, tmp_path, location):
    http = _ImageHttp(location)
    c = _client(monkeypatch, tmp_path, http=http)

    data = asyncio.run(c._download_generated_image("https://lh3.googleusercontent.com/gg/abc"))

    assert data == b"PNG"
    (m1, u1, kw1), (m2, u2, kw2) = http.calls
    assert _as_dict(kw1["cookies"]) == {}, "lh3.googleusercontent.com 不在 google.com 的域里"
    if location.startswith("/"):
        assert u2 == "https://lh3.googleusercontent.com/u/0/d/xyz=s2048"
        return
    second = _as_dict(kw2["cookies"])
    assert "OSID" not in second and "__Secure-OSID" not in second
    assert second["SID"] == SECRET_VALUES["SID"]
    assert isinstance(kw2["cookies"], curl_cookies.Cookies), "后续跳转交给 curl 按域发送"


def test_image_entries_take_cookies_per_url_by_default(monkeypatch, tmp_path):
    http = _ImageHttp("https://lh3.google.com/u/0/d/xyz=s2048")
    c = _client(monkeypatch, tmp_path, http=http)
    monkeypatch.setattr("app.core.image_store.save_image", lambda data, mime: "img-1")

    entries = asyncio.run(c._build_image_entries([{"url": "https://lh3.googleusercontent.com/gg/abc"}]))

    assert entries and entries[0]["id"] == "img-1"
    assert "OSID" not in _as_dict(http.calls[1][2]["cookies"])


# ---------------------------------------------------------------------------
# A3：登录页守卫（三个信号任一）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page,url", [
    (_signin_page(title="Gemini", cfb2h="x"), SIGNIN_URL),            # 落在 accounts.google.com
    (_signin_page(title="Gemini"), gc.GEMINI_APP_EN_URL),             # cfb2h 含 identityfrontend
    (_signin_page(cfb2h="boq_other"), gc.GEMINI_APP_EN_URL),          # title 是登录页
], ids=["final-url", "cfb2h", "title"])
def test_signin_page_is_an_auth_failure_even_with_snlm0e(monkeypatch, tmp_path, page, url):
    c = _client(monkeypatch, tmp_path, http=_Http(page, url))

    asyncio.run(c._obtain_session_token())

    assert c._session_token == "", "登录页里的 SNlM0e 是访客 token，绝不采纳"
    assert c.auth_expired is True
    assert c._last_reload_error == gc.AUTH_FULL_COOKIE_REQUIRED
    assert "1.4.0" in gc.AUTH_FULL_COOKIE_REQUIRED and "OSID" in gc.AUTH_FULL_COOKIE_REQUIRED


def test_a_logged_in_page_with_account_links_is_not_a_signin_page(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    asyncio.run(c._obtain_session_token())
    assert c._session_token == "TOKEN-REAL"
    assert c.auth_expired is False


@pytest.mark.parametrize("title", [
    "Sign in - Google Accounts", "登录 - Google 账号", "登入 - Google 帳戶",
    "ログイン - Google アカウント", "로그인 - Google 계정", "Sign in – Google accounts",
])
def test_localized_signin_titles(title):
    assert gc._is_google_signin_page(f"<title>{title}</title>") is True


@pytest.mark.parametrize("title", ["Google Gemini", "Gemini", "‎Gemini - direct access to Google AI"])
def test_gemini_titles_are_not_signin(title):
    assert gc._is_google_signin_page(f'<title>{title}</title>"SNlM0e":"x"', gc.GEMINI_APP_URL) is False


def test_check_account_on_a_signin_page_reports_the_full_cookie_hint(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, http=_Http(_signin_page(), SIGNIN_URL))
    beats = []

    async def _hb():
        beats.append(1)
        return True

    monkeypatch.setattr(c, "_send_heartbeat", _hb)

    result = asyncio.run(c.check_account())

    assert result["valid"] is False and result["has_token"] is False
    assert result["error"] == gc.AUTH_FULL_COOKIE_REQUIRED
    assert c._session_token == "" and c.auth_expired is True
    assert beats == [], "访客态不拿 token、不发心跳"


def test_browser_kept_account_on_signin_page_never_calls_rotatecookies(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, http=_Http(_signin_page(), SIGNIN_URL))

    result = asyncio.run(c.reload_cookies(keepalive_mode="browser"))

    assert result == {"success": False, "error": gc.AUTH_FULL_COOKIE_REQUIRED}
    assert all(u != gc.ROTATE_COOKIES_URL for _m, u, _kw in c._http.calls)
    app_gets = [u for m, u, _kw in c._http.calls if u == gc.GEMINI_APP_EN_URL]
    # reload 既有的契约是「取一次 → 轮换（浏览器保活的跳过）→ 再取一次」，不为登录页另加任何重试
    assert len(app_gets) <= 2, "不为登录页对谷歌循环请求"


# ---------------------------------------------------------------------------
# A4：otAQ7b 的 payload 是 [1]
# ---------------------------------------------------------------------------

def test_heartbeat_sends_otaq7b_with_payload_1(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c._session_token = "TOKEN-REAL"

    asyncio.run(c._send_heartbeat())

    kw = next(kw for m, u, kw in c._http.calls if u == gc.BATCHEXECUTE_URL)
    assert json.loads(kw["data"]["f.req"]) == [[["otAQ7b", "[1]", None, "generic"]]]
    assert kw["params"]["rpcids"] == "otAQ7b"


# ---------------------------------------------------------------------------
# A2（client 侧）：整套换上 / 失败整罐还原 / 重启后还认得
# ---------------------------------------------------------------------------

def test_reload_with_a_full_set_replaces_the_jar(monkeypatch, tmp_path):
    old = [StoredCookie("__Secure-1PSID", "old-psid"), StoredCookie("NID", "captured-old")]
    c = _client(monkeypatch, tmp_path, cookies=old, psid="old-psid", psidts="old-ts")
    monkeypatch.setattr(c, "_send_heartbeat", _noop)
    c._cookie_jar.set("__cfg-1PSIDTS", "snap", domain=cj_mod.INTERNAL_DOMAIN, secure=False)

    new = _full_set()
    result = asyncio.run(c.reload_cookies(
        psid=SECRET_VALUES["__Secure-1PSID"], psidts=SECRET_VALUES["__Secure-1PSIDTS"], cookies=new,
    ))

    assert result == {"success": True}
    assert c._cookie_jar.get("NID") is None
    assert c._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL)["OSID"] == SECRET_VALUES["OSID"]
    assert c._cookie_jar.get("__cfg-1PSIDTS") == "snap"
    assert c._psid == SECRET_VALUES["__Secure-1PSID"]


def test_a_failed_full_reload_restores_the_whole_previous_jar(monkeypatch, tmp_path):
    old = _full_set(OSID="osid-OLD-working")
    c = _client(monkeypatch, tmp_path, cookies=old, http=_Http(_signin_page(), SIGNIN_URL))
    c._healthy = True
    c._session_token = "TOKEN-REAL"
    before = sorted((x.name, x.domain, x.value) for x in c._cookie_jar.entries())

    result = asyncio.run(c.reload_cookies(
        psid="psid-NEW", psidts="psidts-NEW",
        cookies=_full_set(**{"__Secure-1PSID": "psid-NEW", "__Secure-1PSIDTS": "psidts-NEW"}),
        keepalive_mode="browser",
    ))

    assert result["success"] is False
    assert sorted((x.name, x.domain, x.value) for x in c._cookie_jar.entries()) == before
    assert c._psid == SECRET_VALUES["__Secure-1PSID"]
    assert c._session_token == "TOKEN-REAL" and c.is_healthy


class _DummySession:
    def __init__(self, *a, **k):
        pass

    async def close(self):
        return None


def _restart(monkeypatch, psid, psidts):
    """跑一次真实的 initialize()（真罐子、磁盘在 tmp），网络全部摘掉。"""
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    client = gc.GeminiWebClient(psid=psid, psidts=psidts)

    async def _obtain():
        client._session_token = "TOKEN"

    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_send_heartbeat", _noop)
    monkeypatch.setattr(client, "_ensure_refresh_task", lambda: None)
    asyncio.run(client.initialize())
    return client


def test_full_set_survives_a_restart_after_accounts_json_writeback(monkeypatch, tmp_path):
    """PUT 成功后 accounts.json 写的是新 PSID / PSIDTS：不同步罐文件名和配置快照的话，下次启动要么
    找不到罐（PSID 换了），要么判成「配置变了」清空整罐 —— OSID 没了，账号又成访客。"""
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    first = _restart(monkeypatch, "PSID-OLD", "TS-AT-SETUP")
    new = _full_set(**{"__Secure-1PSID": "PSID-NEW", "__Secure-1PSIDTS": "TS-NEW"})
    first._cookie_jar.replace_cookies(new)
    first._psid, first._psidts = "PSID-NEW", "TS-NEW"

    first.sync_persisted_config(' "PSID-NEW" ', "TS-NEW;")

    again = _restart(monkeypatch, "PSID-NEW", "TS-NEW")
    sent = again._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL)
    assert sent["OSID"] == SECRET_VALUES["OSID"]
    assert again._psidts == "TS-NEW"


def test_without_the_sync_a_restart_would_drop_the_full_set(monkeypatch, tmp_path):
    """反证上一条的必要性（同 PSID、只是 PSIDTS 回写了）。"""
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    first = _restart(monkeypatch, "PSID-1", "TS-AT-SETUP")
    first._cookie_jar.replace_cookies(_full_set(**{"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "TS-NEW"}))

    again = _restart(monkeypatch, "PSID-1", "TS-NEW")
    assert "OSID" not in again._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL)


# ---------------------------------------------------------------------------
# A2（admin 接口）
# ---------------------------------------------------------------------------

AUTH = {"Authorization": "Bearer sk-test-key"}


class _RecordingClient:
    def __init__(self, success=True):
        self.calls = []
        self.synced = []
        self.success = success
        self.mode = None

    async def reload_cookies(self, psid=None, psidts=None, *, keepalive_mode=None, cookies=None):
        self.calls.append({"psid": psid, "psidts": psidts, "cookies": cookies})
        return {"success": True} if self.success else {"success": False, "error": "nope"}

    def sync_persisted_config(self, psid, psidts):
        self.synced.append((psid, psidts))

    def set_keepalive_mode(self, mode):
        self.mode = mode
        return True


class _LegacyClient:
    """v1.6.52 的签名：带了 cookies 关键字就会 TypeError。"""

    def __init__(self):
        self.calls = []

    async def reload_cookies(self, psid=None, psidts=None, *, keepalive_mode=None):
        self.calls.append((psid, psidts))
        return {"success": True}

    def set_keepalive_mode(self, mode):
        return True


@pytest.fixture
def one_account(monkeypatch):
    import app.routers.admin as admin
    from app.core.account_pool import Account

    persisted = []

    def install(client):
        acc = Account(id="account-1", psid="PSID-OLD", psidts="TS-OLD", label="a1")
        acc.client = client
        monkeypatch.setattr(type(admin.account_pool), "accounts",
                            property(lambda self: [acc]), raising=False)
        monkeypatch.setattr(admin.account_pool, "persist_account_cookies",
                            lambda *a: persisted.append(a) or True)

        async def _mark(account):
            return None

        monkeypatch.setattr(admin.account_pool, "mark_cookies_reloaded", _mark)
        return acc

    install.persisted = persisted
    return install


def _put(gem_client, body):
    return gem_client.put("/admin/accounts/account-1/cookies", json=body, headers=AUTH)


def test_put_with_cookies_replaces_the_set_and_keeps_accounts_json_to_psid_psidts(gem_client, one_account):
    client = _RecordingClient()
    one_account(client)

    r = _put(gem_client, {
        "psid": SECRET_VALUES["__Secure-1PSID"], "psidts": SECRET_VALUES["__Secure-1PSIDTS"],
        "cookies": _chrome_list() + [{"name": "YSC", "value": "yt", "domain": ".youtube.com"}],
    })

    assert r.status_code == 200, r.text
    (call,) = client.calls
    domains = {c.name: c.domain for c in call["cookies"]}
    assert domains["OSID"] == "gemini.google.com" and domains["SID"] == ".google.com"
    assert "YSC" not in domains
    assert one_account.persisted == [
        ("account-1", SECRET_VALUES["__Secure-1PSID"], SECRET_VALUES["__Secure-1PSIDTS"])
    ], "accounts.json 照旧只存 psid / psidts"
    assert client.synced == [(SECRET_VALUES["__Secure-1PSID"], SECRET_VALUES["__Secure-1PSIDTS"])]


@pytest.mark.parametrize("body_override", [
    {"psidts": "psidts-OTHER"},
    {"psid": "psid-OTHER"},
], ids=["psidts", "psid"])
def test_put_with_mismatching_psid_is_400_and_echoes_no_value(gem_client, one_account, body_override):
    client = _RecordingClient()
    one_account(client)
    body = {"psid": SECRET_VALUES["__Secure-1PSID"], "psidts": SECRET_VALUES["__Secure-1PSIDTS"],
            "cookies": _chrome_list(), **body_override}

    r = _put(gem_client, body)

    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_cookies"
    assert client.calls == [] and one_account.persisted == []
    for v in list(SECRET_VALUES.values()) + list(body_override.values()):
        assert v not in r.text


def test_put_with_a_set_missing_psid_is_400(gem_client, one_account):
    one_account(_RecordingClient())
    cookies = [c for c in _chrome_list() if c["name"] != "__Secure-1PSID"]
    r = _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"],
                          "psidts": SECRET_VALUES["__Secure-1PSIDTS"], "cookies": cookies})
    assert r.status_code == 400


def test_put_with_both_cookies_and_header_is_400(gem_client, one_account):
    one_account(_RecordingClient())
    r = _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"],
                          "psidts": SECRET_VALUES["__Secure-1PSIDTS"],
                          "cookies": _chrome_list(), "cookie_header": "SID=a"})
    assert r.status_code == 400


def test_put_without_cookies_behaves_like_v1652(gem_client, one_account):
    """旧插件 / 旧脚本：不带 cookies → 调用与 v1.6.52 逐字一致（不多传任何关键字）、不碰罐文件同步。"""
    client = _LegacyClient()
    one_account(client)
    r = _put(gem_client, {"psid": "PSID-NEW", "psidts": "TS-NEW"})
    assert r.status_code == 200
    assert client.calls == [("PSID-NEW", "TS-NEW")]
    assert one_account.persisted == [("account-1", "PSID-NEW", "TS-NEW")]


def test_put_with_a_pasted_cookie_header(gem_client, one_account):
    client = _RecordingClient()
    one_account(client)
    header = "Cookie: " + "; ".join(f"{k}={v}" for k, v in SECRET_VALUES.items())

    r = _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"],
                          "psidts": SECRET_VALUES["__Secure-1PSIDTS"], "cookie_header": header})

    assert r.status_code == 200, r.text
    domains = {c.name: c.domain for c in client.calls[0]["cookies"]}
    assert domains["OSID"] == "gemini.google.com"
    assert domains["__Secure-OSID"] == "gemini.google.com"
    assert domains["HSID"] == ".google.com"


def test_put_failure_writes_nothing(gem_client, one_account):
    client = _RecordingClient(success=False)
    one_account(client)
    r = _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"],
                          "psidts": SECRET_VALUES["__Secure-1PSIDTS"], "cookies": _chrome_list()})
    assert r.status_code == 503
    assert one_account.persisted == [] and client.synced == []


def test_validation_errors_on_admin_do_not_echo_the_cookies(gem_client, one_account):
    """缺 psid 时 FastAPI 默认的 422 会把整个请求体（整套 Cookie）原样回显。"""
    one_account(_RecordingClient())
    r = _put(gem_client, {"cookies": _chrome_list()})
    assert r.status_code == 422
    for v in SECRET_VALUES.values():
        assert v not in r.text


def test_post_reload_cookies_accepts_a_pasted_header_and_derives_psid(gem_client, one_account):
    client = _RecordingClient()
    one_account(client)
    header = "; ".join(f"{k}={v}" for k, v in SECRET_VALUES.items())

    r = gem_client.post("/admin/reload-cookies", json={"cookie_header": header}, headers=AUTH)

    assert r.status_code == 200, r.text
    (call,) = client.calls
    assert call["psid"] == SECRET_VALUES["__Secure-1PSID"]
    assert call["psidts"] == SECRET_VALUES["__Secure-1PSIDTS"]
    assert {c.name for c in call["cookies"]} == set(SECRET_VALUES)


def test_post_reload_cookies_with_a_plugin_list(gem_client, one_account):
    client = _RecordingClient()
    one_account(client)
    r = gem_client.post("/admin/reload-cookies", json={
        "psid": SECRET_VALUES["__Secure-1PSID"], "psidts": SECRET_VALUES["__Secure-1PSIDTS"],
        "cookies": _chrome_list(),
    }, headers=AUTH)
    assert r.status_code == 200
    assert len(client.calls[0]["cookies"]) == len(SECRET_VALUES)


def test_post_reload_cookies_without_cookies_is_unchanged(gem_client, one_account):
    client = _LegacyClient()
    one_account(client)
    r = gem_client.post("/admin/reload-cookies", json={"psid": "P", "psidts": "T"}, headers=AUTH)
    assert r.status_code == 200
    assert client.calls == [("P", "T")]


def test_end_to_end_put_never_logs_or_returns_cookie_values(gem_client, one_account, monkeypatch,
                                                            tmp_path, caplog):
    """真 client + 真罐子：整条 PUT 路径（含罐文件替换、取 token、心跳）在 DEBUG 级日志与响应里都不出现
    任何 Cookie 值；完整 Cookie 只落在该账号的罐文件里。"""
    c = _client(monkeypatch, tmp_path, cookies=[StoredCookie("__Secure-1PSID", "PSID-OLD")],
                psid="PSID-OLD", psidts="TS-OLD")
    one_account(c)

    # app.main 把 "app" 这棵 logger 设成了 LOG_LEVEL（测试里是 warning）：要看到 DEBUG 得对它单独开
    with caplog.at_level(logging.DEBUG, logger="app"):
        r = _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"],
                              "psidts": SECRET_VALUES["__Secure-1PSIDTS"], "cookies": _chrome_list()})
        bad = _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"], "psidts": "x",
                                "cookies": _chrome_list()})

    assert r.status_code == 200, r.text
    assert bad.status_code == 400
    text = caplog.text + r.text + bad.text
    for v in SECRET_VALUES.values():
        assert v not in text, "日志 / 接口响应里出现了 Cookie 值"
    assert "OSID present" in caplog.text
    jar_file = json.loads(c._cookie_jar._store_path().read_text(encoding="utf-8"))
    assert {"OSID", "__Secure-OSID", "SID"} <= {row["name"] for row in jar_file}


# ---------------------------------------------------------------------------
# 复审修复：/admin/status 报出完整 Cookie 的提示（规格 A3）
# ---------------------------------------------------------------------------

def _status_of(client, status=None, last_error=""):
    from app.core.account_pool import Account, AccountPool, AccountStatus

    acc = Account(id="account-1", psid="P", psidts="T", label="a1", last_error=last_error)
    acc.client = client
    acc.status = status or AccountStatus.EXPIRED
    pool = AccountPool.__new__(AccountPool)
    pool._accounts = [acc]
    pool._cond = asyncio.Condition()
    pool._strategy = type("S", (), {"value": "round-robin"})()
    pool._max_concurrent = 3
    (info,) = pool.get_status()["accounts"]
    return info


def test_status_tells_the_operator_the_full_cookie_set_is_required(monkeypatch, tmp_path):
    """上线当天三个账号都会被登录页守卫判失败（_init_account_client 标 EXPIRED、last_error 为空）。
    面板账号列表和浏览器插件读的是 /admin/status：这里也得是那句完整 Cookie 的提示，不是旧的笼统一句。"""
    c = _client(monkeypatch, tmp_path, http=_Http(_signin_page(), SIGNIN_URL))
    asyncio.run(c._obtain_session_token())

    info = _status_of(c)

    assert info["status"] == "expired"
    assert info["last_error"] == gc.AUTH_FULL_COOKIE_REQUIRED


def test_status_prefers_the_full_cookie_hint_over_an_older_request_error(monkeypatch, tmp_path):
    """运行中被打回登录页之前，访客态的请求已经 400 过几次、last_error 记着「HTTP 400」：那只是症状，
    提示才是原因。"""
    from app.core.account_pool import AccountStatus

    c = _client(monkeypatch, tmp_path, http=_Http(_signin_page(), SIGNIN_URL))
    asyncio.run(c._obtain_session_token())

    info = _status_of(c, status=AccountStatus.ACTIVE, last_error="HTTPStatusError (HTTP 400)")

    assert info["status"] == "expired"
    assert info["last_error"] == gc.AUTH_FULL_COOKIE_REQUIRED


def test_old_style_login_redirect_keeps_the_generic_reason(monkeypatch, tmp_path):
    """改版前的形态（页面里没 token、只有登录链接）不是「缺完整 Cookie」：照旧报笼统的那句。"""
    from app.core import account_pool as ap

    page = "<html><title>Gemini</title>" + "x" * 2000 + '<a href="https://accounts.google.com/ServiceLogin">'
    c = _client(monkeypatch, tmp_path, http=_Http(page, gc.GEMINI_APP_EN_URL))
    asyncio.run(c._obtain_session_token())

    assert c.auth_expired is True
    assert c.auth_error == ""
    assert _status_of(c)["last_error"] == ap.SESSION_EXPIRED_ERROR


def test_the_hint_clears_once_a_token_is_adopted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, http=_Http(_signin_page(), SIGNIN_URL))
    asyncio.run(c._obtain_session_token())
    assert c.auth_error == gc.AUTH_FULL_COOKIE_REQUIRED

    c._http.app_page, c._http.app_url = LOGGED_IN_PAGE, gc.GEMINI_APP_EN_URL
    asyncio.run(c._obtain_session_token())

    assert c.auth_expired is False and c.auth_error == ""


def test_check_account_on_a_signin_page_also_sets_the_hint(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, http=_Http(_signin_page(), SIGNIN_URL))
    asyncio.run(c.check_account())
    assert c.auth_error == gc.AUTH_FULL_COOKIE_REQUIRED


def test_a_failed_reload_restores_the_previous_hint(monkeypatch, tmp_path):
    """reload 失败整组状态回滚：auth_error 跟着 auth_expired 一起回到调用前。"""
    page = "<html><title>Gemini</title>" + "x" * 2000 + '<a href="https://accounts.google.com/ServiceLogin">'
    c = _client(monkeypatch, tmp_path, http=_Http(page, gc.GEMINI_APP_EN_URL))
    asyncio.run(c._obtain_session_token())
    assert c.auth_expired is True and c.auth_error == ""

    c._http.app_page, c._http.app_url = _signin_page(), SIGNIN_URL
    result = asyncio.run(c.reload_cookies(
        psid="psid-NEW", psidts="psidts-NEW",
        cookies=_full_set(**{"__Secure-1PSID": "psid-NEW", "__Secure-1PSIDTS": "psidts-NEW"}),
        keepalive_mode="browser",
    ))

    assert result["success"] is False
    assert c.auth_expired is True and c.auth_error == ""


# ---------------------------------------------------------------------------
# 复审修复：轮换换掉的旧 PSIDTS，在路上的请求回来时不能写回去
# ---------------------------------------------------------------------------

class _RotatingHttp(_Http):
    def __init__(self, new_ts):
        super().__init__()
        self.new_ts = new_ts

    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if url != gc.ROTATE_COOKIES_URL:
            return _Resp(200, ")]}'\n", url)
        resp = _Resp(200, "", url, headers={
            "set-cookie": f"__Secure-1PSIDTS={self.new_ts}; Domain=.google.com; Path=/; Secure; HttpOnly",
        })
        listed = curl_cookies.Cookies(kw.get("cookies"))
        listed.set("__Secure-1PSIDTS", self.new_ts, ".google.com", secure=True)
        resp.cookies = listed
        return resp


def test_a_stream_that_left_before_a_rotation_does_not_revert_psidts(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, http=_RotatingHttp("psidts-ROTATED"))
    in_flight = c._get_cookies(gc.GENERATE_URL)  # 流式请求（独立 session，最长 300 秒）出发时带的那份

    assert asyncio.run(c._rotate_cookies()) == gc.RotationResult.RENEWED
    assert c._cookie_jar.get("__Secure-1PSIDTS") == "psidts-ROTATED"

    c._cookie_jar.update_from_response(_Resp(200, "", gc.GENERATE_URL))
    stale = _Resp(200, "", gc.GENERATE_URL)
    stale.cookies = curl_cookies.Cookies(in_flight)
    c._cookie_jar.update_from_response(stale)

    assert c._cookie_jar.get("__Secure-1PSIDTS") == "psidts-ROTATED"
    assert c._get_cookies(gc.GENERATE_URL)["__Secure-1PSIDTS"] == "psidts-ROTATED"


# ---------------------------------------------------------------------------
# 复审修复：整套 PUT 之后的旧格式 PUT 不能让下次启动清空整罐
# ---------------------------------------------------------------------------

def _real_client_for_admin(monkeypatch, tmp_path, psidts="TS-AT-SETUP"):
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    monkeypatch.setattr(gc, "apply_jitter", _noop)
    return _restart(monkeypatch, SECRET_VALUES["__Secure-1PSID"], psidts)


def test_a_legacy_put_after_a_full_put_keeps_the_full_set_across_a_restart(gem_client, one_account,
                                                                         monkeypatch, tmp_path):
    """复审用探针复现过：整套 PUT 并同步之后，再来一次旧格式 PUT（插件 1.4.0 读不到整套时的退路、
    refresher 每 8 分钟一次、面板只填两项、另一台浏览器上的 1.3.0），新 PSIDTS 回写进 accounts.json
    而配置快照不跟着改，下次启动判成「配置变了」→ 整罐清空 → OSID / SID / HSID 全丢，账号又成访客。"""
    client = _real_client_for_admin(monkeypatch, tmp_path)
    one_account(client)
    psid = SECRET_VALUES["__Secure-1PSID"]

    assert _put(gem_client, {"psid": psid, "psidts": SECRET_VALUES["__Secure-1PSIDTS"],
                             "cookies": _chrome_list()}).status_code == 200
    assert _put(gem_client, {"psid": psid, "psidts": "TS-LEGACY"}).status_code == 200
    assert one_account.persisted[-1] == ("account-1", psid, "TS-LEGACY")

    again = _restart(monkeypatch, psid, "TS-LEGACY")  # accounts.json 里此时是 TS-LEGACY
    sent = again._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL)
    assert sent.get("OSID") == SECRET_VALUES["OSID"], "整套 Cookie 被重启清掉了"
    assert sent.get("SID") == SECRET_VALUES["SID"]
    assert again._psidts == "TS-LEGACY"


def test_a_legacy_put_with_another_psid_keeps_the_v1652_behaviour(gem_client, one_account,
                                                                 monkeypatch, tmp_path):
    """换了 PSID 的旧格式 PUT：和 v1.6.52 一样，罐文件不搬、快照不动（重启后按新 PSID 从头建罐）。"""
    client = _real_client_for_admin(monkeypatch, tmp_path)
    one_account(client)
    assert _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"],
                             "psidts": SECRET_VALUES["__Secure-1PSIDTS"],
                             "cookies": _chrome_list()}).status_code == 200
    path_before = client._cookie_jar._store_path()

    assert _put(gem_client, {"psid": "PSID-OTHER", "psidts": "TS-OTHER"}).status_code == 200

    assert client._cookie_jar._store_path() == path_before
    assert client._cookie_jar.get(gc._CFG_PSIDTS_SNAPSHOT) == SECRET_VALUES["__Secure-1PSIDTS"]


def test_a_legacy_put_whose_writeback_failed_syncs_nothing(gem_client, one_account, monkeypatch, tmp_path):
    import app.routers.admin as admin

    client = _real_client_for_admin(monkeypatch, tmp_path)
    one_account(client)
    monkeypatch.setattr(admin.account_pool, "persist_account_cookies", lambda *a: False)

    assert _put(gem_client, {"psid": SECRET_VALUES["__Secure-1PSID"], "psidts": "TS-LEGACY"}).status_code == 200
    assert client._cookie_jar.get(gc._CFG_PSIDTS_SNAPSHOT) == "TS-AT-SETUP"


# ---------------------------------------------------------------------------
# 复审修复：POST /admin/reload-cookies 带整套时只换给这套 Cookie 所属的账号
# ---------------------------------------------------------------------------

class _PoolClient(_RecordingClient):
    def __init__(self, psid, *, full=False, success=True):
        super().__init__(success=success)
        self.psid = psid
        self.full = full

    def owns_cookie_set(self, psid):
        return psid == self.psid

    def has_full_cookie_set(self):
        return self.full


@pytest.fixture
def pool_of(monkeypatch):
    import app.routers.admin as admin
    from app.core.account_pool import Account

    def install(*clients):
        accounts = []
        for i, client in enumerate(clients):
            acc = Account(id=f"account-{i}", psid=f"P{i}", psidts=f"T{i}", label=f"a{i}")
            acc.client = client
            accounts.append(acc)
        monkeypatch.setattr(type(admin.account_pool), "accounts",
                            property(lambda self: accounts), raising=False)

        async def _mark(account):
            return None

        monkeypatch.setattr(admin.account_pool, "mark_cookies_reloaded", _mark)
        return accounts

    return install


def _post_full(gem_client, **override):
    return gem_client.post("/admin/reload-cookies", json={"cookies": _chrome_list(**override)}, headers=AUTH)


def test_post_full_set_goes_only_to_the_account_that_owns_it(gem_client, pool_of):
    first = _PoolClient("psid-OTHER-ACCOUNT", full=True)
    owner = _PoolClient(SECRET_VALUES["__Secure-1PSID"], full=True)
    pool_of(first, owner)

    r = _post_full(gem_client)

    assert r.status_code == 200, r.text
    assert first.calls == [], "别的账号的整套 Cookie 被这套覆盖了"
    assert len(owner.calls) == 1


def test_post_full_set_does_not_fall_through_when_the_owner_fails(gem_client, pool_of):
    other = _PoolClient("psid-OTHER-ACCOUNT", full=True)
    owner = _PoolClient(SECRET_VALUES["__Secure-1PSID"], full=True, success=False)
    pool_of(owner, other)

    r = _post_full(gem_client)

    assert r.status_code == 503
    assert other.calls == []


def test_post_full_set_without_an_owner_skips_accounts_holding_their_own_full_set(gem_client, pool_of):
    """新 PSID（浏览器重新登录过）：不覆盖已经有自己整套 Cookie 的账号，落到还只有 PSID / PSIDTS 的那个。"""
    holder = _PoolClient("psid-A", full=True)
    legacy = _PoolClient("psid-B", full=False)
    pool_of(holder, legacy)

    r = _post_full(gem_client)

    assert r.status_code == 200, r.text
    assert holder.calls == []
    assert len(legacy.calls) == 1


def test_post_full_set_without_an_owner_is_409_when_every_account_holds_a_full_set(gem_client, pool_of):
    a, b = _PoolClient("psid-A", full=True), _PoolClient("psid-B", full=True)
    pool_of(a, b)

    r = _post_full(gem_client)

    assert r.status_code == 409
    assert r.json()["error"]["type"] == "no_matching_account"
    assert a.calls == [] and b.calls == []
    for v in SECRET_VALUES.values():
        assert v not in r.text


def test_post_full_set_on_a_single_account_pool_still_lands(gem_client, pool_of):
    """单账号池（插件没填账号 ID 的常见部署）：浏览器重新登录换了 PSID，照样换给这唯一的账号。"""
    only = _PoolClient("psid-OLD", full=True)
    pool_of(only)
    r = _post_full(gem_client)
    assert r.status_code == 200, r.text
    assert len(only.calls) == 1


def test_post_without_a_full_set_still_tries_every_account(gem_client, pool_of):
    """旧格式（不带整套）行为不变：逐个试。"""
    a = _PoolClient("psid-A", full=True, success=False)
    b = _PoolClient("psid-B", full=True)
    pool_of(a, b)
    r = gem_client.post("/admin/reload-cookies", json={"psid": "P", "psidts": "T"}, headers=AUTH)
    assert r.status_code == 200
    assert len(a.calls) == 1 and len(b.calls) == 1


def test_client_owns_and_full_set_helpers(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.owns_cookie_set(SECRET_VALUES["__Secure-1PSID"]) is True
    assert c.owns_cookie_set("psid-SOMEONE-ELSE") is False
    assert c.owns_cookie_set("") is False
    assert c.has_full_cookie_set() is True

    legacy = _client(monkeypatch, tmp_path / "b", cookies=[
        StoredCookie("__Secure-1PSID", "psid-L"), StoredCookie("__Secure-1PSIDTS", "ts-L"),
        StoredCookie("NID", "captured"),
    ], psid="psid-L", psidts="ts-L")
    assert legacy.has_full_cookie_set() is False
    assert legacy.owns_cookie_set("psid-L") is True

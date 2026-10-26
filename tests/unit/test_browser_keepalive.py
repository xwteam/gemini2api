"""「浏览器保活」账号不再由服务端轮换（v1.6.44 保活修复的 B 部分）。

根因二（双方轮换）：v1.6.40 及以前正常启动的服务端从不轮换，只有浏览器在换 PSIDTS、插件跟着推；
v1.6.41 起 initialize() 末尾无条件起 _auto_refresh_loop。浏览器和服务端共用同一个谷歌会话、各自调
RotateCookies，后一方拿着被对方换掉的旧 PSIDTS 去换就 401、被踢下线 —— 用户看到的是「经常掉线
要重登」。线上：服务端独自轮换 3 天零失败，浏览器一回来（10-24 晚）就开始 401。

要钉死的：
- 唯一闸口在 _rotate_cookies() 开头：browser 模式零网络请求、返回 STILL_VALID；server 模式与
  改动前逐字节一致。刷新循环 / reload 兜底 / 启动重试都自动遵守。
- 模式按 client **当前** PSID 查；单账号（.env）模式同样适用。
- PUT cookies / POST reload-cookies 只在 reload 成功后、按请求来源写模式，写在**新** PSID 名下：
  X-Gemini2API-Keepalive 头 → browser；Origin chrome-extension:// → browser；其余 → server。
- /admin/status 每个账号带 keepalive_mode。
"""

import asyncio
import hashlib
import json
import logging

import pytest

from app.core import account_pool as ap
from app.core import gemini_client as gc
from app.core import keepalive_modes as km
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.gemini_client import RotationResult

_AUTH = {"Authorization": "Bearer sk-test-key"}
PLUGIN_HEADER = {"X-Gemini2API-Keepalive": "gemini2api-plugin/1.3.0"}
EXTENSION_ORIGIN = {"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}
PANEL_ORIGIN = {"Origin": "http://testserver"}

ROTATE_BODY = b'[000,"-0000000000000000000"]'


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "keepalive-modes.json"
    monkeypatch.setattr(km, "MODES_PATH", path)
    return path


def _key(psid: str) -> str:
    return hashlib.sha256(psid.encode()).hexdigest()[:16]


def _recorded(store) -> dict:
    if not store.exists():
        return {}
    return {k: v["mode"] for k, v in json.loads(store.read_text(encoding="utf-8")).items()}


class _Resp:
    def __init__(self, status_code=200, cookies=None, text=""):
        self.status_code = status_code
        self.cookies = dict(cookies or {})
        self.text = text


class _Jar:
    def __init__(self):
        self.sets = []
        self.updates = 0

    def get_all(self, domain="google.com"):
        return {"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-OLD"}

    def get(self, name):
        return None

    def set(self, name, value, **kw):
        self.sets.append((name, value))

    def remove(self, name):
        return None

    def clear(self):
        return None

    def update_from_response(self, resp):
        self.updates += 1


class _Http:
    """记录每一次网络调用；post 回脚本给的响应。"""

    def __init__(self, post_resp=None, app_page=""):
        self.post_resp = post_resp or _Resp(200)
        self.app_page = app_page
        self.posts: list[tuple] = []
        self.gets: list[str] = []

    async def post(self, url, **kw):
        self.posts.append((url, kw))
        return self.post_resp

    async def get(self, url, **kw):
        self.gets.append(url)
        return _Resp(200, text=self.app_page if url == gc.GEMINI_APP_EN_URL else "")

    async def close(self):
        return None


class _Calls:
    def __init__(self):
        self.jitter = 0
        self.ensure = 0
        self.rotations: list[bool] = []

    def record_rotation(self, success):
        self.rotations.append(success)


def _rotating_client(monkeypatch, psid="PSID-1", post_resp=None):
    calls = _Calls()

    async def _jitter(*a, **kw):
        calls.jitter += 1

    async def _ensure(*a, **kw):
        calls.ensure += 1

    monkeypatch.setattr(gc, "apply_jitter", _jitter)
    monkeypatch.setattr(gc, "live_metrics", calls)
    c = gc.GeminiWebClient(psid=psid, psidts="PSIDTS-OLD")
    c._cookie_jar = _Jar()
    c._http = _Http(post_resp)
    monkeypatch.setattr(c, "_ensure_session_current", _ensure)
    monkeypatch.setattr(c, "_get_headers", lambda *a, **kw: {})
    return c, calls


# --------------------------------------------------------------------------
# client：keepalive_mode 按当前 PSID 查
# --------------------------------------------------------------------------

def test_keepalive_mode_defaults_to_server(store):
    assert gc.GeminiWebClient(psid="PSID-1", psidts="t").keepalive_mode == "server"


def test_keepalive_mode_follows_the_current_psid(store):
    km.set_mode("PSID-1", "browser")
    c = gc.GeminiWebClient(psid="PSID-1", psidts="t")
    assert c.keepalive_mode == "browser"

    c._psid = "PSID-2"  # 重新登录换了 PSID：旧记录不再命中
    assert c.keepalive_mode == "server"


def test_set_keepalive_mode_records_under_the_current_psid(store):
    c = gc.GeminiWebClient(psid="PSID-1", psidts="t")

    assert c.set_keepalive_mode("browser") is True

    assert _recorded(store) == {_key("PSID-1"): "browser"}
    assert "PSID-1" not in store.read_text(encoding="utf-8")


def test_single_account_env_mode_is_keyed_by_the_env_psid(store, monkeypatch):
    """单账号（.env GEMINI_PSID）模式：client 不带参数构造，同样按 PSID 哈希查，与 accounts.json 无关。"""
    monkeypatch.setattr(gc.settings, "gemini_psid", "PSID-FROM-ENV")
    monkeypatch.setattr(gc.settings, "gemini_psidts", "PSIDTS-FROM-ENV")
    km.set_mode("PSID-FROM-ENV", "browser")

    assert gc.GeminiWebClient().keepalive_mode == "browser"


# --------------------------------------------------------------------------
# 唯一闸口：_rotate_cookies
# --------------------------------------------------------------------------

def test_browser_mode_rotation_makes_no_network_request(store, monkeypatch):
    km.set_mode("PSID-1", "browser")
    c, calls = _rotating_client(monkeypatch, post_resp=_Resp(200, {"__Secure-1PSIDTS": "NEW"}))

    result = asyncio.run(c._rotate_cookies())

    assert result is RotationResult.STILL_VALID
    assert bool(result) is True, "调用方的 `if rotated:` 照旧往下走去取 token"
    assert c._http.posts == [], "browser 模式下绝不能调 RotateCookies"
    assert calls.jitter == 0 and calls.ensure == 0, "连轮换抖动 / 换 session 都不该做"
    assert calls.rotations == [], "既不算成功也不算失败"
    assert c._cookie_jar.sets == [] and c._psidts == "PSIDTS-OLD"


@pytest.mark.parametrize("recorded", [None, "server"], ids=["no-record", "explicit-server"])
@pytest.mark.parametrize(
    "resp,expected,psidts,metrics",
    [
        (_Resp(200, {"__Secure-1PSIDTS": "PSIDTS-NEW"}), RotationResult.RENEWED, "PSIDTS-NEW", [True]),
        (_Resp(200, {}), RotationResult.STILL_VALID, "PSIDTS-OLD", []),
        (_Resp(401), RotationResult.FAILED, "PSIDTS-OLD", [False]),
    ],
    ids=["renewed", "still-valid", "http-401"],
)
def test_server_mode_rotation_is_byte_for_byte_unchanged(store, monkeypatch, recorded, resp, expected,
                                                         psidts, metrics):
    if recorded:
        km.set_mode("PSID-1", recorded)
    c, calls = _rotating_client(monkeypatch, post_resp=resp)

    result = asyncio.run(c._rotate_cookies())

    assert result is expected
    assert c._psidts == psidts
    assert calls.rotations == metrics
    assert calls.jitter == 1
    assert c._http.posts == [(
        gc.ROTATE_COOKIES_URL,
        {
            "data": ROTATE_BODY,
            "cookies": {"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-OLD"},
            "headers": {"Content-Type": "application/json", "Origin": "https://accounts.google.com"},
        },
    )]


def test_the_gate_follows_a_mode_change_without_a_restart(store, monkeypatch):
    c, _calls = _rotating_client(monkeypatch, post_resp=_Resp(200))

    asyncio.run(c._rotate_cookies())
    km.set_mode("PSID-1", "browser")
    asyncio.run(c._rotate_cookies())
    km.set_mode("PSID-1", "server")
    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == 2


def test_refresh_loop_never_rotates_a_browser_kept_account(store, monkeypatch):
    km.set_mode("PSID-1", "browser")
    c, _calls = _rotating_client(monkeypatch)
    c._http.app_page = '"SNlM0e":"TOKEN" feeds/x' + "y" * 2000
    c._healthy = True

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(gc.settings, "refresh_interval", 30)
    monkeypatch.setattr(gc, "random_delay_factor", lambda: 1.0)
    slept = []

    async def _sleep(sec, *a, **kw):
        slept.append(sec)
        if len(slept) > 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(gc.asyncio, "sleep", _sleep)

    async def _drive():
        try:
            await c._auto_refresh_loop()
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())

    assert c._http.posts == [], "三轮刷新一次 RotateCookies 都不该发"
    assert c._http.gets.count(gc.GEMINI_APP_EN_URL) == 3, "token 探测照旧"
    assert c.is_healthy is True


def test_reload_fallback_does_not_rotate_a_browser_kept_account(store, monkeypatch):
    """reload_cookies 第一次取不到 token 时的 RotateCookies 兜底也经过同一个闸口。"""
    km.set_mode("PSID-1", "browser")
    c, _calls = _rotating_client(monkeypatch)
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    attempts = []

    async def _obtain():
        attempts.append(True)
        c._session_token = "TOKEN" if len(attempts) > 1 else ""

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_obtain_session_token", _obtain)
    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)

    result = asyncio.run(c.reload_cookies())

    assert result == {"success": True}
    assert c._http.posts == []
    assert len(attempts) == 2, "STILL_VALID 是真值：照旧再取一次 token"


def test_startup_retry_does_not_rotate_a_browser_kept_account(store, monkeypatch, caplog):
    km.set_mode("PSID-1", "browser")
    c, _calls = _rotating_client(monkeypatch)
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    jar = c._cookie_jar
    monkeypatch.setattr(gc, "PersistentCookieJar", lambda psid: jar)
    attempts = []

    async def _obtain():
        attempts.append(True)
        c._session_token = "TOKEN" if len(attempts) > 1 else ""

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_obtain_session_token", _obtain)
    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    caplog.set_level(logging.INFO, logger=gc.logger.name)

    asyncio.run(c.initialize())

    assert c._http.posts == []
    assert len(attempts) == 2
    assert c.is_healthy is True
    assert any("browser" in r.getMessage() and "RotateCookies" in r.getMessage()
               for r in caplog.records), "启动日志要点明这个账号由浏览器保活、服务端不轮换"


def test_startup_log_is_silent_about_keepalive_for_server_accounts(store, monkeypatch, caplog):
    c, _calls = _rotating_client(monkeypatch)
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    jar = c._cookie_jar
    monkeypatch.setattr(gc, "PersistentCookieJar", lambda psid: jar)

    async def _obtain():
        c._session_token = "TOKEN"

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_obtain_session_token", _obtain)
    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    caplog.set_level(logging.INFO, logger=gc.logger.name)

    asyncio.run(c.initialize())

    assert not any("browser" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------
# admin 接口：判定来源，只在 reload 成功后写，写在新 PSID 名下
# --------------------------------------------------------------------------

class _DummySession:
    def __init__(self, *a, **kw):
        pass

    async def close(self):
        return None


def _real_client(monkeypatch, *, psid="PSID-OLD", reload_ok=True):
    """真的 GeminiWebClient（真的 reload_cookies / set_keepalive_mode），网络全摘掉。"""
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    c = gc.GeminiWebClient(psid=psid, psidts="PSIDTS-OLD")
    c._cookie_jar = _Jar()
    c._http = _DummySession()

    async def _obtain():
        if reload_ok:
            c._session_token = "TOKEN"
        else:
            c._session_token = ""
            c._last_reload_error = "Cookie expired - redirected to Google login page"

    async def _rotate():
        return RotationResult.FAILED

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_obtain_session_token", _obtain)
    monkeypatch.setattr(c, "_rotate_cookies", _rotate)
    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    return c


@pytest.fixture
def pool_with(monkeypatch, tmp_path):
    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))

    def _install(account_id, client, psid="PSID-OLD"):
        acc = Account(id=account_id, psid=psid, psidts="PSIDTS-OLD", label=account_id,
                      status=AccountStatus.EXPIRED, consecutive_failures=3, client=client)
        monkeypatch.setattr(ap.account_pool, "_accounts", [acc])
        return acc

    return _install


@pytest.mark.parametrize(
    "headers,expected",
    [
        (PLUGIN_HEADER, "browser"),
        (EXTENSION_ORIGIN, "browser"),
        (PANEL_ORIGIN, "server"),
        ({}, "server"),
    ],
    ids=["plugin-header", "extension-origin", "panel", "script"],
)
def test_put_cookies_records_the_source_under_the_new_psid(gem_client, store, monkeypatch, pool_with,
                                                           headers, expected):
    pool_with("account-1", _real_client(monkeypatch))

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-NEW", "psidts": "PSIDTS-NEW"}, headers={**_AUTH, **headers})

    assert r.status_code == 200
    assert _recorded(store) == {_key("PSID-NEW"): expected}, "写在新 PSID 名下，旧 PSID 不动"


def test_put_cookies_records_the_psid_as_the_client_cleaned_it(gem_client, store, monkeypatch, pool_with):
    """面板粘贴来的值常带引号 / 分号：哈希必须按 client 实际换上的那个值算，否则闸口查不到。"""
    c = _real_client(monkeypatch)
    pool_with("account-1", c)

    raw = ' "PSID-NEW" '
    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": raw, "psidts": "PSIDTS-NEW"},
                       headers={**_AUTH, **PLUGIN_HEADER})

    assert r.status_code == 200
    assert c._psid == "PSID-NEW"
    assert _recorded(store) == {_key("PSID-NEW"): "browser"}
    assert _key(raw) not in _recorded(store)
    assert c.keepalive_mode == "browser"


def test_panel_update_hands_a_browser_kept_account_back_to_the_server(gem_client, store, monkeypatch,
                                                                       pool_with):
    """用户改用无痕窗口取的 cookie（窗口一关就没人轮换了）：面板手动更新 → 交回服务端轮换。"""
    km.set_mode("PSID-SAME", "browser")
    pool_with("account-1", _real_client(monkeypatch, psid="PSID-SAME"), psid="PSID-SAME")

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-SAME", "psidts": "PSIDTS-FROM-INCOGNITO"},
                       headers={**_AUTH, **PANEL_ORIGIN})

    assert r.status_code == 200
    assert _recorded(store) == {_key("PSID-SAME"): "server"}


@pytest.mark.parametrize("headers", [PLUGIN_HEADER, EXTENSION_ORIGIN], ids=["plugin-header", "origin"])
def test_put_cookies_failure_records_nothing(gem_client, store, monkeypatch, pool_with, headers):
    pool_with("account-1", _real_client(monkeypatch, reload_ok=False))

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-BAD", "psidts": "PSIDTS-BAD"}, headers={**_AUTH, **headers})

    assert r.status_code == 503
    assert _recorded(store) == {}


def test_post_reload_cookies_records_the_source(gem_client, store, monkeypatch, pool_with):
    pool_with("account-0", _real_client(monkeypatch))

    r = gem_client.post("/admin/reload-cookies", json={"psid": "PSID-NEW", "psidts": "PSIDTS-NEW"},
                        headers={**_AUTH, **PLUGIN_HEADER})

    assert r.status_code == 200
    assert _recorded(store) == {_key("PSID-NEW"): "browser"}


def test_post_reload_cookies_with_only_psidts_keeps_the_current_psid(gem_client, store, monkeypatch,
                                                                     pool_with):
    pool_with("account-0", _real_client(monkeypatch, psid="PSID-OLD"))

    r = gem_client.post("/admin/reload-cookies", json={"psidts": "PSIDTS-NEW"},
                        headers={**_AUTH, **EXTENSION_ORIGIN})

    assert r.status_code == 200
    assert _recorded(store) == {_key("PSID-OLD"): "browser"}


def test_post_reload_cookies_from_env_uses_the_env_psid(gem_client, store, monkeypatch, pool_with):
    """单账号（.env）模式：按 .env 里的 PSID 记，与是否有 accounts.json 无关。"""
    monkeypatch.setenv("GEMINI_PSID", "PSID-FROM-ENV")
    monkeypatch.setenv("GEMINI_PSIDTS", "PSIDTS-FROM-ENV")
    pool_with("account-0", _real_client(monkeypatch))

    r = gem_client.post("/admin/reload-cookies", headers={**_AUTH, **PANEL_ORIGIN})

    assert r.status_code == 200
    assert _recorded(store) == {_key("PSID-FROM-ENV"): "server"}


def test_post_reload_cookies_failure_records_nothing(gem_client, store, monkeypatch, pool_with):
    pool_with("account-0", _real_client(monkeypatch, reload_ok=False))

    r = gem_client.post("/admin/reload-cookies", json={"psid": "PSID-BAD", "psidts": "PSIDTS-BAD"},
                        headers={**_AUTH, **PLUGIN_HEADER})

    assert r.status_code == 503
    assert _recorded(store) == {}


def test_a_failed_mode_write_does_not_fail_the_cookie_push(gem_client, store, monkeypatch, pool_with):
    """cookie 已经换上了：记不下保活方式只记日志，绝不能把这次推送报成失败（插件会反复重推）。"""
    acc = pool_with("account-1", _real_client(monkeypatch))

    def _disk_full(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(km, "atomic_write_json", _disk_full)

    r = gem_client.put("/admin/accounts/account-1/cookies",
                       json={"psid": "PSID-NEW", "psidts": "PSIDTS-NEW"}, headers={**_AUTH, **PLUGIN_HEADER})

    assert r.status_code == 200
    assert acc.status is AccountStatus.ACTIVE


# --------------------------------------------------------------------------
# /admin/status 带 keepalive_mode
# --------------------------------------------------------------------------

class _BareClient:
    def __init__(self, psid):
        self._psid = psid

    @property
    def is_healthy(self):
        return True


def _pool(*accounts):
    pool = AccountPool.__new__(AccountPool)
    pool._accounts = list(accounts)
    pool._cond = asyncio.Condition()
    pool._strategy = type("S", (), {"value": "round-robin"})()
    pool._max_concurrent = 3
    return pool


def test_status_exports_keepalive_mode_per_account(store):
    km.set_mode("PSID-B", "browser")
    browser = Account(id="a-b", psid="PSID-B", psidts="t",
                      client=gc.GeminiWebClient(psid="PSID-B", psidts="t"))
    server = Account(id="a-s", psid="PSID-S", psidts="t",
                     client=gc.GeminiWebClient(psid="PSID-S", psidts="t"))

    info = {a["id"]: a for a in _pool(browser, server).get_status()["accounts"]}

    assert info["a-b"]["keepalive_mode"] == "browser"
    assert info["a-s"]["keepalive_mode"] == "server"


def test_status_follows_the_clients_current_psid(store):
    """reload 换了 PSID 之后 Account.psid 未必跟着变（POST /reload-cookies 不回写）：以 client 为准。"""
    km.set_mode("PSID-NEW", "browser")
    acc = Account(id="a", psid="PSID-OLD", psidts="t",
                  client=gc.GeminiWebClient(psid="PSID-NEW", psidts="t"))

    assert _pool(acc).get_status()["accounts"][0]["keepalive_mode"] == "browser"


def test_status_falls_back_to_the_account_psid(store):
    km.set_mode("PSID-X", "browser")
    no_client = Account(id="a", psid="PSID-X", psidts="t", client=None)
    bare = Account(id="b", psid="PSID-X", psidts="t", client=_BareClient("PSID-X"))

    rows = _pool(no_client, bare).get_status()["accounts"]

    assert [r["keepalive_mode"] for r in rows] == ["browser", "browser"]


def test_admin_status_endpoint_carries_keepalive_mode(gem_client, store, monkeypatch):
    km.set_mode("PSID-B", "browser")
    acc = Account(id="account-1", psid="PSID-B", psidts="t",
                  client=gc.GeminiWebClient(psid="PSID-B", psidts="t"))
    monkeypatch.setattr(ap.account_pool, "_accounts", [acc])

    body = gem_client.get("/admin/status", headers=_AUTH).json()

    assert body["accounts"][0]["keepalive_mode"] == "browser"

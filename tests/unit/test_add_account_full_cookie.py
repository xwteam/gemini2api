"""「添加账号」直接粘贴整段 Cookie（v1.6.55 规格 C1 / B1，思路来自外部 PR #14）。

v1.6.53 起谷歌要整套 Cookie（含 gemini.google.com 的 host-only OSID）才认登录态；面板「更新 Cookie」与
PUT /admin/accounts/{id}/cookies 早已能收整套，POST /admin/accounts 却只收 psid / psidts —— 新加的账号
第一次初始化（第一次 GET /app）就落在谷歌登录页、被判过期，要等插件推送或再点一次「更新 Cookie」。

要钉死的：
- 带 cookies（插件格式列表）或 cookie_header（整段 Cookie 头）：psid / psidts 可以不填（取整套里 .google.com
  的 __Secure-1PSID/1PSIDTS），填了必须一致（400 invalid_cookies）；整套在第一次 GET /app **之前**装进罐。
- 都不带：psid 必填（400 invalid_request_error），其余与 v1.6.54 一致。
- 池里已有这个 PSID → 409 duplicate_account，不新建。
- 装罐、落盘、配置快照与 PUT 同口径：模拟重启后罐里的 OSID 还在。
- 日志与响应绝不出现 Cookie 值。
"""

import asyncio
import json
import logging

import pytest

from app.core import account_pool as ap
from app.core import gemini_client as gc
from app.core import keepalive_modes as km
from app.core.account_pool import Account, AccountPool, AccountStatus, DuplicateAccountError
from app.core.fingerprint import cookie_jar as cj_mod

pytest.importorskip("curl_cffi.requests.cookies", reason="curl_cffi not installed (runtime dep)")

AUTH = {"Authorization": "Bearer sk-test-key"}
PANEL_ORIGIN = {"Origin": "http://testserver"}

SECRETS = {
    "__Secure-1PSID": "add-psid-SECRET-1111",
    "__Secure-1PSIDTS": "add-psidts-SECRET-2222",
    "SID": "add-sid-SECRET-3333",
    "HSID": "add-hsid-SECRET-4444",
    "SAPISID": "add-sapisid-SECRET-5555",
    "OSID": "add-osid-SECRET-7777",
    "__Secure-OSID": "add-sosid-SECRET-8888",
}
PSID = SECRETS["__Secure-1PSID"]
PSIDTS = SECRETS["__Secure-1PSIDTS"]


def _header(**override) -> str:
    values = {k: v for k, v in {**SECRETS, **override}.items() if v is not None}
    return "Cookie: " + "; ".join(f"{k}={v}" for k, v in values.items())


def _chrome_list(**override) -> list[dict]:
    out = []
    for name, value in {**SECRETS, **override}.items():
        if value is None:
            continue
        host_only = name in ("OSID", "__Secure-OSID")
        out.append({
            "name": name, "value": value,
            "domain": "gemini.google.com" if host_only else ".google.com",
            "hostOnly": host_only, "path": "/", "secure": True, "httpOnly": True,
            "sameSite": "no_restriction", "storeId": "0", "expirationDate": 4102444800,
        })
    return out


class _DummySession:
    def __init__(self, *a, **k):
        pass

    async def close(self):
        return None


async def _noop(*a, **kw):
    return None


@pytest.fixture
def pool(monkeypatch, tmp_path):
    """真的 AccountPool.add_account → 真的 GeminiWebClient.initialize()（真罐子，磁盘在 tmp），网络全摘掉。

    first_app_cookies：每个 client 第一次取 token（= 第一次 GET /app）那一刻罐里要发给 /app 的 Cookie。
    """
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))
    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    monkeypatch.setattr(ap.account_pool, "_next_id_seq", 0)
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)

    first_app_cookies: list[dict] = []

    async def _obtain(self):
        first_app_cookies.append(self._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL))
        self._session_token = "TOKEN"

    monkeypatch.setattr(gc.GeminiWebClient, "_obtain_session_token", _obtain)
    monkeypatch.setattr(gc.GeminiWebClient, "_send_heartbeat", _noop)
    monkeypatch.setattr(gc.GeminiWebClient, "_ensure_refresh_task", lambda self: None)

    class _Pool:
        accounts_file = tmp_path / "accounts.json"
        sent_on_first_app = first_app_cookies

        @staticmethod
        def saved() -> list[dict]:
            if not _Pool.accounts_file.exists():
                return []
            return json.loads(_Pool.accounts_file.read_text(encoding="utf-8"))["accounts"]

        @staticmethod
        def restart(psid, psidts) -> gc.GeminiWebClient:
            """按 accounts.json 里的 psid / psidts 再跑一次 initialize()（= 下一次启动）。"""
            client = gc.GeminiWebClient(psid=psid, psidts=psidts)
            asyncio.run(client.initialize())
            return client

    return _Pool


def _post(gem_client, body, headers=None):
    return gem_client.post("/admin/accounts", json=body, headers={**AUTH, **PANEL_ORIGIN, **(headers or {})})


def _assert_no_secret(text: str, extra=()):
    for v in list(SECRETS.values()) + list(extra):
        assert v not in text, "响应 / 日志里出现了 Cookie 值"


# ---------------------------------------------------------------------------
# 四种情形
# ---------------------------------------------------------------------------

def test_cookie_header_alone_adds_an_account_with_the_full_set_installed_before_the_first_app(
        gem_client, pool):
    r = _post(gem_client, {"cookie_header": _header(), "label": "work"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["full_cookie_set"] is True
    assert body["account"] == {"id": "account-0", "label": "work", "status": "active"}
    (first,) = pool.sent_on_first_app
    assert first["OSID"] == SECRETS["OSID"], "第一次 GET /app 就得带上 OSID，否则第一次初始化就被判过期"
    assert first["__Secure-OSID"] == SECRETS["__Secure-OSID"]
    assert first["SID"] == SECRETS["SID"] and first["__Secure-1PSID"] == PSID
    # accounts.json 照旧只存 psid / psidts（从整套里取）
    assert pool.saved() == [{"id": "account-0", "psid": PSID, "psidts": PSIDTS, "label": "work"}]


def test_cookie_list_from_the_plugin_works_the_same(gem_client, pool):
    r = _post(gem_client, {"cookies": _chrome_list() + [{"name": "YSC", "value": "yt", "domain": ".youtube.com"}]})

    assert r.status_code == 200, r.text
    assert r.json()["full_cookie_set"] is True
    (first,) = pool.sent_on_first_app
    assert first["OSID"] == SECRETS["OSID"] and "YSC" not in first
    assert pool.saved()[0]["psid"] == PSID and pool.saved()[0]["psidts"] == PSIDTS


def test_psid_and_psidts_only_behave_like_v1654(gem_client, pool):
    r = _post(gem_client, {"psid": ' "PSID-LEGACY" ', "psidts": "TS-LEGACY;", "label": "old"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_cookie_set"] is False
    assert body["account"]["label"] == "old"
    (first,) = pool.sent_on_first_app
    assert first == {"__Secure-1PSID": "PSID-LEGACY", "__Secure-1PSIDTS": "TS-LEGACY"}
    assert pool.saved() == [{"id": "account-0", "psid": "PSID-LEGACY", "psidts": "TS-LEGACY", "label": "old"}]


def test_legacy_add_calls_the_pool_exactly_like_v1654(gem_client, monkeypatch, tmp_path):
    """不带整套：_init_account_client 的调用与 v1.6.54 逐字一致（不多传任何关键字，旧替身照样能用）。"""
    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))
    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    calls = []

    async def _init(self, account):
        calls.append(account.psid)
        account.status = AccountStatus.ACTIVE

    monkeypatch.setattr(AccountPool, "_init_account_client", _init)

    r = _post(gem_client, {"psid": "PSID-X", "psidts": "t"})

    assert r.status_code == 200, r.text
    assert calls == ["PSID-X"]


@pytest.mark.parametrize("body", [
    {},
    {"label": "x"},
    {"psid": "", "psidts": "t"},
    {"psid": "   ", "psidts": "t"},
    {"psidts": "t"},
    {"cookie_header": "   "},
], ids=["empty", "label-only", "empty-psid", "blank-psid", "psidts-only", "blank-header"])
def test_without_psid_and_without_a_cookie_set_is_400(gem_client, pool, body):
    r = _post(gem_client, body)

    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert pool.saved() == [] and ap.account_pool.accounts == []
    assert pool.sent_on_first_app == []


# ---------------------------------------------------------------------------
# 整套与 psid / psidts 不一致、整套本身不合法
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("override", [
    {"psid": "psid-OTHER-9999"},
    {"psidts": "psidts-OTHER-9999"},
    {"psid": PSID, "psidts": "psidts-OTHER-9999"},
], ids=["psid", "psidts", "psid-ok-psidts-bad"])
def test_a_set_that_disagrees_with_the_given_psid_is_400_and_echoes_nothing(gem_client, pool, override):
    r = _post(gem_client, {"cookie_header": _header(), **override})

    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_cookies"
    _assert_no_secret(r.text, override.values())
    assert pool.saved() == [] and ap.account_pool.accounts == [] and pool.sent_on_first_app == []


def test_given_psid_and_psidts_that_match_the_set_are_accepted(gem_client, pool):
    r = _post(gem_client, {"psid": f' "{PSID}" ', "psidts": PSIDTS + ";", "cookies": _chrome_list()})

    assert r.status_code == 200, r.text
    assert r.json()["full_cookie_set"] is True
    assert pool.saved()[0]["psid"] == PSID


@pytest.mark.parametrize("body", [
    {"cookies": _chrome_list(), "cookie_header": _header()},
    {"cookie_header": _header(**{"__Secure-1PSID": None})},
    {"cookies": [{"name": "YSC", "value": "yt", "domain": ".youtube.com"}]},
], ids=["both", "no-psid-in-set", "no-google-cookies"])
def test_invalid_cookie_sets_are_400_invalid_cookies(gem_client, pool, body):
    r = _post(gem_client, body)

    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_cookies"
    _assert_no_secret(r.text)
    assert pool.saved() == [] and pool.sent_on_first_app == []


# ---------------------------------------------------------------------------
# 重复账号 → 409
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("second", [
    {"psid": PSID, "psidts": "anything"},
    {"psid": f' "{PSID}"; ', "psidts": "anything"},
    {"cookie_header": _header(**{"__Secure-1PSIDTS": "add-psidts-NEWER-0000"})},
], ids=["legacy", "legacy-quoted", "full-set"])
def test_adding_a_psid_that_is_already_in_the_pool_is_409(gem_client, pool, second):
    assert _post(gem_client, {"cookie_header": _header(), "label": "first"}).status_code == 200

    r = _post(gem_client, second)

    assert r.status_code == 409, r.text
    err = r.json()["error"]
    assert err["type"] == "duplicate_account"
    assert "account-0" in err["message"]
    _assert_no_secret(r.text, ["add-psidts-NEWER-0000"])
    assert [a.id for a in ap.account_pool.accounts] == ["account-0"]
    assert len(pool.saved()) == 1
    assert len(pool.sent_on_first_app) == 1, "重复的账号不能再初始化一次（不联网）"


def test_a_psid_the_account_switched_to_counts_as_taken(gem_client, pool):
    """POST /admin/reload-cookies 换上新 PSID 不回写 Account.psid：按 client 当前用的 PSID 也要认出来。"""
    assert _post(gem_client, {"psid": "PSID-CONFIG", "psidts": "t"}).status_code == 200
    (acc,) = ap.account_pool.accounts
    acc.client._psid = PSID

    r = _post(gem_client, {"cookie_header": _header()})

    assert r.status_code == 409
    assert len(ap.account_pool.accounts) == 1


ONE = {"__Secure-1PSIDTS": "add-psidts-ONE-SECRET-1212", "OSID": "add-osid-ONE-SECRET-3434"}
TWO = {"__Secure-1PSIDTS": "add-psidts-TWO-SECRET-5656", "OSID": "add-osid-TWO-SECRET-7878"}


@pytest.mark.parametrize("first,second", [(ONE, TWO), (ONE, ONE)], ids=["different-sets", "double-click"])
def test_concurrent_adds_of_the_same_psid_build_only_one_client(app_main, gem_client, pool, monkeypatch,
                                                                first, second):
    """同一个 PSID 并发添加两次（面板和插件同时加、或双击）：罐文件按 PSID 的哈希命名，两个 client 会写
    同一个 data/cookies/<hash>.json。落选的那个不能先建 client 再被 409 —— 它的初始化会联网（多一次 GET /app），
    还会把自己的整套、配置快照、响应里捕获的 Cookie 写进胜出账号的罐，下次启动就对不上、整罐被清空。

    用真的 GeminiWebClient.initialize：第一次 GET /app 要等一会儿（联网），慢的那次后写盘。"""
    import httpx

    delays = {ONE["__Secure-1PSIDTS"]: 0.01, TWO["__Secure-1PSIDTS"]: 0.05}

    async def _slow_first_app(self):
        await asyncio.sleep(delays[self._psidts])
        pool.sent_on_first_app.append(self._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL))
        # /app 响应里捕获的 Cookie 照样落盘（update_from_response）
        self._cookie_jar.set("NID", "nid-" + self._psidts)
        self._session_token = "TOKEN"

    monkeypatch.setattr(gc.GeminiWebClient, "_obtain_session_token", _slow_first_app)

    async def _both():
        transport = httpx.ASGITransport(app=app_main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            return await asyncio.gather(*(
                c.post("/admin/accounts", json={"cookie_header": _header(**body)},
                       headers={**AUTH, **PANEL_ORIGIN})
                for body in (first, second)))

    responses = asyncio.run(_both())

    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    (ok,) = [r for r in responses if r.status_code == 200]
    (dup,) = [r for r in responses if r.status_code == 409]
    winner_id = ok.json()["account"]["id"]
    assert dup.json()["error"]["type"] == "duplicate_account"
    assert winner_id in dup.json()["error"]["message"]
    _assert_no_secret(dup.text + ok.text, [*ONE.values(), *TWO.values()])
    assert [a.id for a in ap.account_pool.accounts] == [winner_id]
    assert len(pool.sent_on_first_app) == 1, "落选的那次不能再建 client、再 GET /app 一次"
    assert ap.account_pool._adding == {}, "占位用完要释放"

    # 模拟重启：accounts.json 里的 psidts 与罐里的整套要对得上，胜出那份的 OSID / SID 都还在
    (saved,) = pool.saved()
    won = first if saved["psidts"] == first["__Secure-1PSIDTS"] else second
    again = pool.restart(saved["psid"], saved["psidts"])
    sent = again._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL)
    assert sent.get("OSID") == won["OSID"], "胜出账号的整套被落选的那次覆盖或清空了"
    assert sent.get("SID") == SECRETS["SID"]


def test_a_psid_switched_in_while_initializing_still_keeps_one(monkeypatch, tmp_path):
    """兜底：初始化（联网）期间，池里别的账号经 PUT / reload-cookies 换成了同一个 PSID —— 进池前再查一次，
    新建的 client 关掉、409，占位照样释放。"""
    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))
    pool = AccountPool()
    shut = []

    class _Client:
        is_healthy = True

        def __init__(self, psid):
            self._psid = psid

        def owns_cookie_set(self, psid):
            return psid == self._psid

        async def shutdown(self):
            shut.append(self)

    other = Account(id="account-7", psid="PSID-OTHER", psidts="t", label="other")
    other.client = _Client("PSID-OTHER")
    pool._accounts = [other]

    async def _init(self, account):
        other.client._psid = "PSID-SAME"   # 换 Cookie 恰好发生在这次初始化联网期间
        account.client = _Client(account.psid)
        account.status = AccountStatus.ACTIVE

    monkeypatch.setattr(AccountPool, "_init_account_client", _init)

    with pytest.raises(DuplicateAccountError) as e:
        asyncio.run(pool.add_account("PSID-SAME", "t1", "a"))

    assert e.value.account_id == "account-7"
    assert [a.id for a in pool.accounts] == ["account-7"]
    assert len(shut) == 1, "落选的那个 client 要关掉"
    assert pool._adding == {}


def test_a_failed_initialization_releases_the_psid(monkeypatch, tmp_path):
    """初始化抛错（网络断了之类）：占位要释放，同一个 PSID 再加一次不能被当成「正在添加」挡掉。"""
    monkeypatch.setattr(ap.settings, "accounts_file", str(tmp_path / "accounts.json"))
    pool = AccountPool()
    calls = []

    class _Client:
        is_healthy = True

    async def _init(self, account):
        calls.append(account.id)
        if len(calls) == 1:
            raise RuntimeError("network down")
        account.client = _Client()
        account.status = AccountStatus.ACTIVE

    monkeypatch.setattr(AccountPool, "_init_account_client", _init)

    with pytest.raises(RuntimeError):
        asyncio.run(pool.add_account("PSID-SAME", "t1", "a"))
    assert pool._adding == {}

    added = asyncio.run(pool.add_account("PSID-SAME", "t1", "a"))

    assert [a.id for a in pool.accounts] == [added.id]


# ---------------------------------------------------------------------------
# 与 PUT 同口径：落盘、配置快照、保活方式；不泄露 Cookie 值
# ---------------------------------------------------------------------------

def test_the_full_set_survives_a_restart(gem_client, pool):
    """装罐、罐文件、配置快照与 accounts.json 要对得上：下次启动既不能找不到罐，也不能判成「配置变了」清空整罐。"""
    assert _post(gem_client, {"cookie_header": _header()}).status_code == 200
    saved = pool.saved()[0]

    again = pool.restart(saved["psid"], saved["psidts"])

    sent = again._cookie_jar.cookies_for_url(gc.GEMINI_APP_URL)
    assert sent["OSID"] == SECRETS["OSID"] and sent["SID"] == SECRETS["SID"]
    assert again._psidts == PSIDTS


def test_re_adding_a_previously_removed_login_replaces_the_stale_jar(gem_client, pool):
    """删掉的账号罐文件还留在 data/cookies：同一个 PSID 带新整套再加回来，第一次 GET /app 用的是新的整套。"""
    assert _post(gem_client, {"cookie_header": _header(OSID="add-osid-OLD-0000")}).status_code == 200
    assert gem_client.delete("/admin/accounts/account-0", headers=AUTH).status_code == 200

    r = _post(gem_client, {"cookie_header": _header()})

    assert r.status_code == 200, r.text
    assert pool.sent_on_first_app[-1]["OSID"] == SECRETS["OSID"]


@pytest.mark.parametrize("headers,expected", [
    ({}, "server"),
    ({"X-Gemini2API-Keepalive": "gemini2api-plugin/1.4.0"}, "browser"),
], ids=["panel", "plugin"])
def test_the_keepalive_mode_is_recorded_as_before(gem_client, pool, headers, expected):
    km.set_mode(PSID, "browser" if expected == "server" else "server")

    r = _post(gem_client, {"cookie_header": _header()}, headers=headers)

    assert r.status_code == 200, r.text
    assert km.get_mode(PSID) == expected
    assert ap.account_pool.accounts[0].client.keepalive_mode == expected


def test_adding_with_a_full_set_never_logs_or_returns_cookie_values(gem_client, pool, caplog):
    # app.main 把 "app" 这棵 logger 设成了 LOG_LEVEL（测试里是 warning）：要看到 DEBUG 得对它单独开
    with caplog.at_level(logging.DEBUG, logger="app"):
        ok = _post(gem_client, {"cookie_header": _header()})
        dup = _post(gem_client, {"cookies": _chrome_list()})
        bad = _post(gem_client, {"cookie_header": _header(), "psidts": "psidts-OTHER-9999"})

    assert (ok.status_code, dup.status_code, bad.status_code) == (200, 409, 400)
    _assert_no_secret(caplog.text + ok.text + dup.text + bad.text, ["psidts-OTHER-9999"])
    assert "OSID present" in caplog.text


def test_an_unexpected_failure_does_not_echo_cookie_values(gem_client, pool, monkeypatch):
    async def _boom(self, account, **kw):
        raise RuntimeError(f"upstream said no to {account.psid} / {SECRETS['OSID']}")

    monkeypatch.setattr(AccountPool, "_init_account_client", _boom)

    r = _post(gem_client, {"cookie_header": _header()})

    assert r.status_code == 500
    assert r.json()["error"]["type"] == "add_account_error"
    assert "upstream said no" in r.json()["error"]["message"]
    _assert_no_secret(r.text)

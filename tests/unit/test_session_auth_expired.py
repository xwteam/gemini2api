"""会话被谷歌打回登录页 = auth_expired（v1.6.44 保活修复的 A 部分，client 侧）。

线上（v1.6.43，新加坡）：两个账号的会话 10-24 晚死掉，日志是
`RotateCookies returned 401` → `Cookie expired - redirected to Google login page` →
`Auto-refresh: token fetch failed Nx, client unhealthy`，之后 37 小时每 10 分钟照样去敲一次
RotateCookies（220+ 次 401），而 /admin/status 一直报 `"status": "active"` —— 浏览器保活插件
只认 `expired`，于是一次都没去救。

client 侧要钉死的语义：
- 只在**产生**「打回登录页」判定的地方置位（_obtain_session_token、check_account 读同一个页面）；
- 成功拿到 SNlM0e、reload_cookies 成功时清掉；
- RotateCookies 回 401 本身**不**置位，以随后的 token 获取结果为准；
- 置位、且谷歌已对**这同一份** cookie 的 RotateCookies 明确回过 401 之后，才不再轮换（刷新循环、
  自愈、reload 兜底都经过 _rotate_cookies 的同一个闸口；死会话换了也是 401）。只是被打回登录页、
  谷歌还没拒绝过的会话照旧轮换 —— PSIDTS 过期、靠一次轮换就能救回的会话不能被晾死（复审复现的
  死锁：auth_expired 一置位就永久停轮换，启动那一次轮换碰上网络抖动就再也救不回来）；
- token 探测照旧，瞬时故障（或别处换上了好 cookie）能自己恢复。
"""

import asyncio

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import RotationResult

LOGIN_PAGE = (
    "<html>" + "x" * 2000
    + '<a href="https://accounts.google.com/ServiceLogin?continue=https://gemini.google.com/app">'
    "Sign in</a></html>"
)
TOKEN_PAGE = "<html>" + "y" * 2000 + '"SNlM0e":"TOKEN-FRESH" feeds/abc123 </html>'
NO_TOKEN_PAGE = "<html>" + "z" * 2000 + "</html>"
SHORT_PAGE = "<html>oops</html>"


class _Resp:
    def __init__(self, status_code=200, text="", cookies=None):
        self.status_code = status_code
        self.text = text
        self.cookies = dict(cookies or {})


class _Jar:
    def get_all(self, domain="google.com"):
        return {}

    def get(self, name):
        return None

    def set(self, name, value, **kw):
        return None

    def update_from_response(self, resp):
        return None


class _Http:
    """GEMINI_APP_EN_URL 按脚本依次回（用完就一直回最后一个）；其余导航 GET 一律 200 空页。"""

    def __init__(self, app_pages, rotate_status=401):
        self.app_pages = list(app_pages)
        self.app_gets = 0
        self.posts: list[str] = []
        self.rotate_status = rotate_status

    async def get(self, url, **kw):
        if url != gc.GEMINI_APP_EN_URL:
            return _Resp(200, "")
        self.app_gets += 1
        page = self.app_pages.pop(0) if len(self.app_pages) > 1 else self.app_pages[0]
        if isinstance(page, BaseException):
            raise page
        if isinstance(page, _Resp):
            return page
        return _Resp(200, page)

    async def post(self, url, **kw):
        self.posts.append(url)
        return _Resp(self.rotate_status)

    async def close(self):
        return None


class _Metrics:
    def record_rotation(self, success):
        return None


def _client(monkeypatch, app_pages, *, healthy=True, auth_expired=False, rotate_status=401):
    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(gc, "apply_jitter", _noop)
    monkeypatch.setattr(gc, "live_metrics", _Metrics())

    c = gc.GeminiWebClient(psid="PSID-1", psidts="PSIDTS-1")
    c._cookie_jar = _Jar()
    c._http = _Http(app_pages, rotate_status=rotate_status)
    c._healthy = healthy
    c._session_token = "OLD-TOKEN" if healthy else ""
    if auth_expired:
        c._auth_expired = True
    monkeypatch.setattr(c, "_ensure_session_current", _noop)
    monkeypatch.setattr(c, "_get_headers", lambda *a, **kw: {})

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    return c


# --------------------------------------------------------------------------
# 置位 / 清除
# --------------------------------------------------------------------------

def test_a_fresh_client_is_not_auth_expired():
    assert gc.GeminiWebClient(psid="p", psidts="t").auth_expired is False


def test_auth_expired_is_read_only():
    c = gc.GeminiWebClient(psid="p", psidts="t")
    with pytest.raises(AttributeError):
        c.auth_expired = True


def test_login_redirect_sets_auth_expired(monkeypatch):
    c = _client(monkeypatch, [LOGIN_PAGE])

    asyncio.run(c._obtain_session_token())

    assert c.auth_expired is True
    assert c._session_token == ""
    assert c._last_reload_error == "Cookie expired - redirected to Google login page", \
        "既有的报错文案（日志 / reload 的 error）不能变"


def test_acquiring_a_token_clears_auth_expired(monkeypatch):
    c = _client(monkeypatch, [TOKEN_PAGE], healthy=False, auth_expired=True)

    asyncio.run(c._obtain_session_token())

    assert c.auth_expired is False
    assert c._session_token == "TOKEN-FRESH"


@pytest.mark.parametrize(
    "page,expected_error",
    [
        (_Resp(500, "boom"), "Gemini returned HTTP 500"),
        (NO_TOKEN_PAGE, "SNlM0e token not found (cookie may be invalid or expired)"),
        (SHORT_PAGE, f"Invalid response (body too short: {len(SHORT_PAGE)} bytes)"),
        (ConnectionError("reset by peer"), "Token extraction failed: reset by peer"),
    ],
    ids=["http-500", "no-token-page", "short-body", "network-error"],
)
@pytest.mark.parametrize("initially", [False, True], ids=["was-ok", "was-expired"])
def test_other_token_failures_leave_auth_expired_alone(monkeypatch, page, expected_error, initially):
    """网络抖动 / 5xx / 页面异常说明不了会话死没死：既不置位也不清除。"""
    c = _client(monkeypatch, [page], auth_expired=initially)

    asyncio.run(c._obtain_session_token())

    assert c.auth_expired is initially
    assert c._last_reload_error == expected_error


def test_a_401_from_rotate_cookies_alone_does_not_set_auth_expired(monkeypatch):
    """401 只记日志；判定以随后的 token 获取结果为准。"""
    c = _client(monkeypatch, [TOKEN_PAGE], rotate_status=401)

    result = asyncio.run(c._rotate_cookies())

    assert result is RotationResult.FAILED
    assert c.auth_expired is False


def test_check_account_seeing_the_login_page_sets_auth_expired(monkeypatch):
    """check_account 读的是同一个 /app 页面：同类判定、同样置位（健康检查循环与 /check 都走这里）。"""
    c = _client(monkeypatch, [LOGIN_PAGE])

    result = asyncio.run(c.check_account())

    assert result["valid"] is False
    assert c.auth_expired is True
    assert c.is_healthy is True, "一次检测失败不降级（降级仍由健康检查循环的 3 连败负责）"


def test_check_account_getting_a_token_clears_auth_expired(monkeypatch):
    c = _client(monkeypatch, [TOKEN_PAGE], healthy=False, auth_expired=True)

    result = asyncio.run(c.check_account())

    assert result["valid"] is True
    assert c.auth_expired is False
    assert c.is_healthy is True


def test_check_account_other_failures_leave_auth_expired_alone(monkeypatch):
    c = _client(monkeypatch, [NO_TOKEN_PAGE], auth_expired=True)

    result = asyncio.run(c.check_account())

    assert result["valid"] is False
    assert c.auth_expired is True


# --------------------------------------------------------------------------
# reload_cookies
# --------------------------------------------------------------------------

def _reload_client(monkeypatch, *, healthy, auth_expired, tokens, rotation=RotationResult.FAILED,
                   login_redirect_on_miss=True):
    """reload_cookies 的外部 I/O 全摘掉：_obtain_session_token 按 tokens 依次给结果。"""
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: _Http([TOKEN_PAGE]))
    c = gc.GeminiWebClient(psid="PSID-OLD", psidts="PSIDTS-OLD")
    c._cookie_jar = _Jar()
    c._http = _Http([TOKEN_PAGE])
    c._healthy = healthy
    c._session_token = "GOOD-TOKEN" if healthy else ""
    if auth_expired:
        c._auth_expired = True

    pending = list(tokens)

    async def _obtain():
        token = pending.pop(0) if pending else ""
        c._session_token = token
        if not token:
            c._last_reload_error = "Cookie expired - redirected to Google login page"
            if login_redirect_on_miss:
                c._auth_expired = True  # 与真实实现一致：打回登录页时置位

    async def _rotate():
        return rotation

    async def _heartbeat():
        return True

    monkeypatch.setattr(c, "_obtain_session_token", _obtain)
    monkeypatch.setattr(c, "_rotate_cookies", _rotate)
    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    return c


def test_successful_reload_clears_auth_expired(monkeypatch):
    """不能只指望 _obtain_session_token 顺手清掉：reload 成功本身就是「会话换好了」。"""
    c = _reload_client(monkeypatch, healthy=False, auth_expired=True, tokens=["NEW-TOKEN"])

    result = asyncio.run(c.reload_cookies(psid="PSID-NEW", psidts="PSIDTS-NEW"))

    assert result == {"success": True}
    assert c.auth_expired is False
    assert c.is_healthy is True


def test_reload_that_succeeds_after_rotation_clears_auth_expired(monkeypatch):
    c = _reload_client(monkeypatch, healthy=False, auth_expired=True, tokens=["", "NEW-TOKEN"],
                       rotation=RotationResult.RENEWED, login_redirect_on_miss=False)

    result = asyncio.run(c.reload_cookies(psid="PSID-NEW", psidts="PSIDTS-NEW"))

    assert result == {"success": True}
    assert c.auth_expired is False


@pytest.mark.parametrize("was_expired", [False, True])
def test_failed_reload_of_a_healthy_client_restores_the_previous_verdict(monkeypatch, was_expired):
    """面板误填了一份死 cookie：健康的会话整组回滚 —— auth_expired 也要回到调用前的值，
    否则一个好好的会话会被当成「已失效」，刷新循环从此不再给它轮换。"""
    c = _reload_client(monkeypatch, healthy=True, auth_expired=was_expired, tokens=["", ""])

    result = asyncio.run(c.reload_cookies(psid="PSID-BAD", psidts="PSIDTS-BAD"))

    assert result["success"] is False
    assert c.is_healthy is True
    assert c._psid == "PSID-OLD"
    assert c.auth_expired is was_expired


def test_failed_reload_of_a_dead_client_keeps_the_new_verdict(monkeypatch):
    c = _reload_client(monkeypatch, healthy=False, auth_expired=False, tokens=["", ""])

    result = asyncio.run(c.reload_cookies(psid="PSID-BAD", psidts="PSIDTS-BAD"))

    assert result["success"] is False
    assert c.auth_expired is True


# --------------------------------------------------------------------------
# 刷新循环：死会话不再白敲 RotateCookies，但照旧探测 token
# --------------------------------------------------------------------------

def _run_loop(monkeypatch, c, *, iterations, rotation=RotationResult.FAILED, real_rotate=False):
    """跑 iterations 轮 _auto_refresh_loop，返回每轮是否调过 RotateCookies / 探测过 token。"""
    monkeypatch.setattr(gc.settings, "refresh_interval", 30)
    monkeypatch.setattr(gc, "random_delay_factor", lambda: 1.0)

    slept = []

    async def _sleep(sec, *a, **kw):
        slept.append(sec)
        if len(slept) > iterations:
            raise asyncio.CancelledError()

    monkeypatch.setattr(gc.asyncio, "sleep", _sleep)

    rotations = []
    probes = []
    real_obtain = c._obtain_session_token

    async def _rotate():
        rotations.append(len(slept))
        return rotation

    async def _obtain():
        probes.append(len(slept))
        await real_obtain()

    if not real_rotate:
        monkeypatch.setattr(c, "_rotate_cookies", _rotate)
    monkeypatch.setattr(c, "_obtain_session_token", _obtain)

    async def _drive():
        try:
            await c._auto_refresh_loop()
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())
    return rotations, probes


def _rejected_by_google(c):
    """让谷歌对 client 当前这份 cookie 的 RotateCookies 回一次 401（走真实的 _rotate_cookies）。"""
    c._http.rotate_status = 401
    assert asyncio.run(c._rotate_cookies()) is RotationResult.FAILED


def test_loop_skips_rotate_cookies_once_google_rejected_these_cookies(monkeypatch):
    """会话被打回登录页、且谷歌已对这同一份 cookie 回过 401：死会话换了也是 401，不再白敲，只探测。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, auth_expired=True)
    _rejected_by_google(c)

    rotations, probes = _run_loop(monkeypatch, c, iterations=3)

    assert rotations == [], "谷歌已经拒绝过这份 cookie：再敲也是 401（线上一个死账号 37 小时敲了 220+ 次）"
    assert probes == [1, 2, 3], "token 探测必须照旧，否则瞬时故障永远好不了"
    assert c.auth_expired is True


def test_loop_still_rotates_a_login_redirected_session_google_has_not_rejected(monkeypatch):
    """只是被打回登录页（健康检查先发现的，或启动那一次就地轮换碰上了网络抖动），谷歌还没对这份
    cookie 说过 401：照旧每轮轮换。PSIDTS 过期的会话往往就靠这一次轮换救回来（issue #11 的自愈）。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, auth_expired=True)

    rotations, probes = _run_loop(monkeypatch, c, iterations=3)

    assert rotations == [1, 2, 3], "auth_expired 一置位就永久停轮换 = 可恢复的会话再也救不回来"
    assert probes == [1, 2, 3]


def test_loop_resumes_rotation_once_a_probe_succeeds(monkeypatch):
    """瞬时故障：下一次探测拿到了 token → 清掉判定 → 再下一轮恢复轮换。"""
    c = _client(monkeypatch, [TOKEN_PAGE], healthy=False, auth_expired=True)
    _rejected_by_google(c)

    rotations, probes = _run_loop(monkeypatch, c, iterations=2, rotation=RotationResult.RENEWED)

    assert probes == [1, 2]
    assert rotations == [2], "第 1 轮跳过轮换，探测成功后第 2 轮恢复"
    assert c.auth_expired is False
    assert c.is_healthy is True


def test_loop_reproduces_the_production_sequence(monkeypatch):
    """线上顺序：RotateCookies 401 → token 打回登录页（置位）→ 之后只探测、不再轮换。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=True, rotate_status=401)

    rotations, probes = _run_loop(monkeypatch, c, iterations=4, real_rotate=True)

    assert c._http.posts == [gc.ROTATE_COOKIES_URL], "只有第一轮（还没判定失效时）敲过一次 RotateCookies"
    assert probes == [1, 2, 3, 4]
    assert c.auth_expired is True
    assert c.is_healthy is False, "3 连败照旧降级"


def test_loop_still_rotates_every_round_when_the_session_is_fine(monkeypatch):
    """零回归：会话正常时每一轮照旧先轮换再探测。"""
    c = _client(monkeypatch, [TOKEN_PAGE], healthy=True)

    rotations, probes = _run_loop(monkeypatch, c, iterations=3, rotation=RotationResult.RENEWED)

    assert rotations == [1, 2, 3]
    assert probes == [1, 2, 3]
    assert c.auth_expired is False


def test_the_production_sequence_with_the_health_check_first(monkeypatch):
    """默认配置下健康检查（5 分钟）往往比刷新循环（10～30 分钟）先看到登录页、先置位：刷新循环照旧
    试一次 RotateCookies，谷歌回 401 之后才停 —— 不能因为 auth_expired 已经置位就一次都不试。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=True, rotate_status=401)
    asyncio.run(c.check_account())
    assert c.auth_expired is True and c._http.posts == []

    _rotations, probes = _run_loop(monkeypatch, c, iterations=4, real_rotate=True)

    assert c._http.posts == [gc.ROTATE_COOKIES_URL], "试一次；谷歌明确拒绝之后不再敲"
    assert probes == [1, 2, 3, 4]
    assert c.auth_expired is True


class _StatefulJar(_Jar):
    """取值是真的：轮换换来的新 PSIDTS 会写进来，get_all 反映当前要发出去的 cookie。"""

    def __init__(self, psid="PSID-1", psidts="PSIDTS-1"):
        self.cookies = {"__Secure-1PSID": psid, "__Secure-1PSIDTS": psidts}

    def get_all(self, domain="google.com"):
        return dict(self.cookies)

    def get(self, name):
        return self.cookies.get(name)

    def set(self, name, value, **kw):
        self.cookies[name] = value


class _RecoverableHttp(_Http):
    """PSIDTS 过期、但还能靠一次轮换救回的会话：/app 一直打回登录页，直到某次 RotateCookies 回 200
    并下发了新 PSIDTS。RotateCookies 按脚本依次回（异常就抛，用完就一直回最后一个）。"""

    def __init__(self, rotate_script):
        super().__init__([LOGIN_PAGE])
        self.rotate_script = list(rotate_script)
        self.renewed = False

    async def get(self, url, **kw):
        if url == gc.GEMINI_APP_EN_URL and self.renewed:
            self.app_gets += 1
            return _Resp(200, TOKEN_PAGE)
        return await super().get(url, **kw)

    async def post(self, url, **kw):
        self.posts.append(url)
        step = self.rotate_script.pop(0) if len(self.rotate_script) > 1 else self.rotate_script[0]
        if isinstance(step, BaseException):
            raise step
        if step.status_code == 200 and step.cookies.get("__Secure-1PSIDTS"):
            self.renewed = True
        return step


def test_a_rotatable_session_recovers_after_a_transient_rotation_failure(monkeypatch):
    """复审复现的死锁：启动（或健康检查）看到登录页 → 置位；就地那一次轮换碰上瞬时网络错误；
    网络恢复后刷新循环必须接着轮换、一轮就救回来 —— 而不是从此只探测、永远救不回来。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False)
    c._cookie_jar = _StatefulJar()
    c._http = _RecoverableHttp([
        ConnectionError("connection reset by peer"),
        _Resp(200, cookies={"__Secure-1PSIDTS": "PSIDTS-2"}),
    ])

    asyncio.run(c._obtain_session_token())
    assert c.auth_expired is True
    assert asyncio.run(c._rotate_cookies()) is RotationResult.FAILED

    _rotations, probes = _run_loop(monkeypatch, c, iterations=6, real_rotate=True)

    assert len(c._http.posts) >= 2, "网络恢复后必须再试 RotateCookies"
    assert c.auth_expired is False
    assert c.is_healthy is True
    assert c._session_token == "TOKEN-FRESH"
    assert c._psidts == "PSIDTS-2"


def test_a_rejection_only_covers_the_exact_cookies_google_rejected(monkeypatch):
    """记下的是「谷歌拒绝过哪一份 cookie」：PSIDTS 变了（比如某个响应 Set-Cookie 下发了新值）就再给一次机会。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, rotate_status=401)
    c._cookie_jar = jar = _StatefulJar(psidts="PSIDTS-1")
    asyncio.run(c._obtain_session_token())

    asyncio.run(c._rotate_cookies())
    second = asyncio.run(c._rotate_cookies())

    assert c._http.posts == [gc.ROTATE_COOKIES_URL], "同一份 cookie 谷歌已经拒绝过，不再发"
    assert second is RotationResult.FAILED, "没轮换成：调用方不该接着当成「cookie 仍有效」去重取 token"

    jar.set("__Secure-1PSIDTS", "PSIDTS-2")
    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == 2


def test_a_401_alone_does_not_stop_rotation_while_the_session_is_alive(monkeypatch):
    """401 只记日志、不置位：会话没被打回登录页（token 还拿得到）时，下一次照旧轮换。"""
    c = _client(monkeypatch, [TOKEN_PAGE], healthy=True, rotate_status=401)

    asyncio.run(c._rotate_cookies())
    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == 2
    assert c.auth_expired is False


def test_a_new_dead_episode_gets_a_fresh_rotation_attempt(monkeypatch):
    """会话活过来（拿到了 token）就清掉上一次的拒绝记录：下一次再被打回登录页，照旧先试一次轮换。"""
    c = _client(monkeypatch, [LOGIN_PAGE, TOKEN_PAGE, LOGIN_PAGE], healthy=False, rotate_status=401)
    asyncio.run(c._obtain_session_token())     # 打回登录页
    asyncio.run(c._rotate_cookies())           # 谷歌 401
    asyncio.run(c._obtain_session_token())     # 又拿到了 token：会话活过来了
    assert c.auth_expired is False
    asyncio.run(c._obtain_session_token())     # 再次被打回登录页

    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == 2


# --------------------------------------------------------------------------
# 自愈路径（池的 _try_heal_unhealthy、generate 开头的自愈）走 reload_cookies()，经过同一个闸口
# --------------------------------------------------------------------------

def _dead_rejected_client(monkeypatch):
    """会话已被打回登录页、且谷歌已对这份 cookie 回过 401 的 client（reload_cookies 复用同一个 _Http）。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, rotate_status=401)
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    asyncio.run(c._obtain_session_token())
    asyncio.run(c._rotate_cookies())
    assert c.auth_expired is True and len(c._http.posts) == 1
    return c


def test_self_heal_reload_does_not_knock_on_cookies_google_rejected(monkeypatch):
    """generate() 开头的自愈和池自愈都是 reload_cookies() 不带新 cookie：取 token 失败后的兜底轮换
    同样不再白敲（复审：只闸了刷新循环时，有流量就每 60 秒一次 401）。"""
    c = _dead_rejected_client(monkeypatch)

    for _ in range(3):
        assert asyncio.run(c.reload_cookies())["success"] is False

    assert len(c._http.posts) == 1, "谷歌已经拒绝过这份 cookie：自愈不该每次都再敲一次 RotateCookies"
    assert c._http.app_gets == 4, "自愈照旧重新探测会话（每次一个 /app）"
    assert c.auth_expired is True


def test_pool_self_heal_does_not_knock_on_cookies_google_rejected(monkeypatch):
    """复审场景：池里没有健康账号、有请求进来，acquire 挑中这个账号去自愈。"""
    from app.core.account_pool import Account, AccountPool

    c = _dead_rejected_client(monkeypatch)
    acc = Account(id="account-0", psid="PSID-1", psidts="PSIDTS-1", label="a0", client=c)
    pool = AccountPool.__new__(AccountPool)
    pool._accounts = [acc]
    pool._cond = asyncio.Condition()

    assert asyncio.run(pool._try_heal_unhealthy(acc)) is False
    assert len(c._http.posts) == 1


def test_self_heal_reload_still_rotates_a_session_google_has_not_rejected(monkeypatch):
    """零回归：只是被打回登录页、谷歌还没拒绝过的会话，自愈的兜底轮换照旧发（救 PSIDTS 过期的会话）。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, auth_expired=True, rotate_status=401)
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)

    asyncio.run(c.reload_cookies())

    assert c._http.posts == [gc.ROTATE_COOKIES_URL]


def test_new_cookies_are_not_covered_by_an_old_rejection(monkeypatch):
    """换上一份新 cookie（面板 / 脚本推来、服务端轮换）：旧 cookie 的拒绝记录管不到它，兜底轮换照旧。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, rotate_status=401)
    c._cookie_jar = _StatefulJar(psid="PSID-1", psidts="PSIDTS-1")
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    asyncio.run(c._obtain_session_token())
    asyncio.run(c._rotate_cookies())

    asyncio.run(c.reload_cookies(psid="PSID-2", psidts="PSIDTS-2"))

    assert len(c._http.posts) == 2


def test_a_5xx_or_network_error_is_not_a_rejection(monkeypatch):
    """只有 401 算「谷歌拒绝了这份 cookie」：5xx / 网络错误是瞬时故障，下一次照旧轮换。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, rotate_status=503)
    asyncio.run(c._obtain_session_token())

    asyncio.run(c._rotate_cookies())
    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == 2


def test_a_successful_rotation_clears_an_earlier_rejection(monkeypatch):
    """谷歌回过 401、后来又对同一份 cookie 回了 200：拒绝记录作废，之后再被打回登录页照旧先试一次。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=True, rotate_status=401)
    asyncio.run(c._rotate_cookies())                  # 401（会话还活着，不置位）
    c._http.rotate_status = 200
    asyncio.run(c._rotate_cookies())                  # 200 无新值 = 现有 cookie 仍有效
    c._http.rotate_status = 401
    asyncio.run(c._obtain_session_token())            # 之后被打回登录页

    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == 3


def test_a_failed_reload_restores_the_rejection_record_too(monkeypatch):
    """健康的会话被面板误填一份死 cookie：整组回滚时「谷歌拒绝过旧 cookie」的记录也要回来，
    否则刷新循环会拿旧 cookie 再白敲一次 401。"""
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=True, rotate_status=401)
    c._cookie_jar = _StatefulJar(psid="PSID-1", psidts="PSIDTS-1")
    monkeypatch.setattr(gc, "AsyncSession", lambda *a, **kw: c._http)
    monkeypatch.setattr(c, "_ensure_refresh_task", lambda: None)
    asyncio.run(c.check_account())                    # 健康检查看到登录页（单次失败不降级）
    asyncio.run(c._rotate_cookies())                  # 谷歌对旧 cookie 回 401
    assert c.is_healthy is True and c.auth_expired is True

    result = asyncio.run(c.reload_cookies(psid="PSID-BAD", psidts="PSIDTS-BAD"))
    assert result["success"] is False and c._psid == "PSID-1"
    assert c._cookie_jar.get_all() == {"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-1"}
    posts = len(c._http.posts)

    asyncio.run(c._rotate_cookies())

    assert len(c._http.posts) == posts, "旧 cookie 谷歌已经拒绝过"

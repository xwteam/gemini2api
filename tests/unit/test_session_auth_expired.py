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
- 置位期间刷新循环不再调 RotateCookies（死会话换了也是 401），但照旧探测 token，
  瞬时故障（或别处换上了好 cookie）能自己恢复。
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


def test_loop_skips_rotate_cookies_while_auth_expired_but_still_probes(monkeypatch):
    c = _client(monkeypatch, [LOGIN_PAGE], healthy=False, auth_expired=True)

    rotations, probes = _run_loop(monkeypatch, c, iterations=3)

    assert rotations == [], "死会话期间不该再调 RotateCookies（换了也是 401，白敲谷歌）"
    assert probes == [1, 2, 3], "token 探测必须照旧，否则瞬时故障永远好不了"
    assert c.auth_expired is True


def test_loop_resumes_rotation_once_a_probe_succeeds(monkeypatch):
    """瞬时故障：下一次探测拿到了 token → 清掉判定 → 再下一轮恢复轮换。"""
    c = _client(monkeypatch, [TOKEN_PAGE], healthy=False, auth_expired=True)

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

"""Google 登录页自带 SNlM0e：落在登录页时不能当成有效会话。"""

import asyncio

from app.core import gemini_client as gc

LOGIN_URL = "https://accounts.google.com/v3/signin/identifier?continue=https://gemini.google.com/app"
LOGIN_BODY = (
    "<html>" + "x" * 2000
    + '"cfb2h":"boq_identityfrontendauthuiserver_20260101.00_p0" "SNlM0e":"LOGIN-PAGE-TOKEN"</html>'
)


class _Resp:
    def __init__(self, url, text):
        self.status_code = 200
        self.url = url
        self.text = text
        self.cookies = {}


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
    def __init__(self, resp):
        self.resp = resp

    async def get(self, url, **kw):
        return self.resp if url == gc.GEMINI_APP_EN_URL else _Resp(url, "")


def _client(monkeypatch, resp):
    async def _noop(*a, **kw):
        return None

    async def _heartbeat():
        return True

    monkeypatch.setattr(gc, "apply_jitter", _noop)
    c = gc.GeminiWebClient(psid="PSID-1", psidts="PSIDTS-1")
    c._cookie_jar = _Jar()
    c._http = _Http(resp)
    monkeypatch.setattr(c, "_ensure_session_current", _noop)
    monkeypatch.setattr(c, "_get_headers", lambda *a, **kw: {})
    monkeypatch.setattr(c, "_send_heartbeat", _heartbeat)
    return c


def test_obtain_token_ignores_snlm0e_on_login_page(monkeypatch):
    c = _client(monkeypatch, _Resp(LOGIN_URL, LOGIN_BODY))

    asyncio.run(c._obtain_session_token())

    assert c._session_token == ""
    assert c.auth_expired is True
    assert c._last_reload_error == "Cookie expired - redirected to Google login page"


def test_check_account_reports_login_page_as_invalid(monkeypatch):
    c = _client(monkeypatch, _Resp(LOGIN_URL, LOGIN_BODY))

    result = asyncio.run(c.check_account())

    assert result["valid"] is False
    assert result["has_token"] is False
    assert c.auth_expired is True


def test_real_gemini_page_with_token_still_accepted(monkeypatch):
    body = "<html>" + "y" * 2000 + '"SNlM0e":"TOKEN-FRESH" feeds/abc123</html>'
    c = _client(monkeypatch, _Resp("https://gemini.google.com/app?hl=en", body))

    asyncio.run(c._obtain_session_token())

    assert c._session_token == "TOKEN-FRESH"
    assert c.auth_expired is False

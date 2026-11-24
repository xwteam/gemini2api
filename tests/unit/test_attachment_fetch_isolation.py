"""附件 URL 绝不能用账号的会话去下载（v1.6.53 复审 Critical）。

request_cookies() 交给 curl 的是带域名的 Cookie（.google.com，含所有子域）。curl_cffi 0.7.4 每个响应
之后把 curl 的整份 Cookie 列表抄进 session.cookies（rsp.cookies = self.cookies），之后同一个 session
上的每个请求都按域带上它们。附件 URL（OpenAI image_url / Claude source.type=url）由调用方任填，过去
走的正是账号的 self._http：填 https://accounts.google.com/Logout 能把池里的账号登出；填
https://mail.google.com/... 或私有 Drive 地址，就带着账号的登录态把内容拉回来、传给 Gemini、再经
模型读出来。is_safe_url 只拦内网地址，谷歌的主机照样放行。

所以附件下载一律走另开的、不带任何 Cookie 的 session，与账号会话完全隔开。
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core import file_upload as fu
from app.core.fingerprint import cookie_jar as cj_mod
from app.core.fingerprint.cookie_jar import PersistentCookieJar, StoredCookie

curl_requests = pytest.importorskip("curl_cffi.requests", reason="curl_cffi not installed (runtime dep)")
from curl_cffi import CurlOpt  # noqa: E402

AsyncSession = curl_requests.AsyncSession

FID = "/contrib_service/ttl_1d/fid-1"


@pytest.fixture
def jar(tmp_path, monkeypatch):
    """账号的整套 Cookie（值是假的；secure=False 才能走回环的 http）。"""
    monkeypatch.setattr(cj_mod, "COOKIE_STORE_DIR", tmp_path / "cookies")
    j = PersistentCookieJar("acct-attach")
    j.replace_cookies([
        StoredCookie("SID", "sid-SECRET", domain=".google.com", secure=False),
        StoredCookie("__Secure-1PSID", "psid-SECRET", domain=".google.com", secure=False),
        StoredCookie("OSID", "osid-SECRET", domain="gemini.google.com", secure=False),
    ])
    return j


@pytest.fixture
def loopback():
    """只听 127.0.0.1 的回环服务；谷歌的主机名用 CURLOPT_RESOLVE 指过来，不连外网。"""
    seen: list[tuple] = []

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            host = self.headers.get("Host", "").split(":")[0]
            seen.append((host, self.path, self.headers.get("Cookie")))
            body = b"attachment-bytes"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1], seen
    finally:
        srv.shutdown()
        srv.server_close()


async def _fake_upload(*a, **kw):
    return FID


def test_attachment_url_on_a_google_host_gets_no_account_cookie(loopback, jar, monkeypatch):
    """复审的回环复现：账号会话先发过一次 gemini 请求（curl 把 .google.com 的 Cookie 记进了 session），
    之后附件 URL 指向 drive.google.com —— 那个请求一条 Cookie 都不能带。"""
    port, seen = loopback
    resolve = [f"{h}:{port}:127.0.0.1" for h in ("gemini.google.com", "drive.google.com")]
    monkeypatch.setattr(fu, "is_safe_url", lambda url: True)  # 回环地址本来会被 SSRF 防护拦下
    monkeypatch.setattr(fu, "upload_file", _fake_upload)       # 上传本身不出网
    # 附件下载另开的 session 也得指到回环（改之前没有这个工厂，raising=False）
    monkeypatch.setattr(fu, "_new_remote_session",
                        lambda *a, **k: AsyncSession(curl_options={CurlOpt.RESOLVE: resolve}),
                        raising=False)

    async def run():
        account_http = AsyncSession(curl_options={CurlOpt.RESOLVE: resolve})
        try:
            app_url = f"http://gemini.google.com:{port}/app"
            await account_http.get(app_url, cookies=jar.request_cookies(app_url))
            return await fu.upload_files(account_http, {}, {}, "push", [
                {"url": f"http://drive.google.com:{port}/private", "filename": "a.png", "mime": "image/png"},
            ])
        finally:
            await account_http.close()

    assert asyncio.run(run()) == [(FID, "a.png")]
    gemini = [s for s in seen if s[0] == "gemini.google.com"]
    assert gemini and "SID=" in (gemini[0][2] or ""), "前提：账号会话确实带过 .google.com 的 Cookie"
    drive = [s for s in seen if s[0] == "drive.google.com"]
    assert drive, "附件确实下载了"
    assert drive[0][2] is None, "附件 URL 收到了账号的 Cookie"


class _AccountSession:
    """账号会话的替身：附件下载碰它一下就算失败；上传（POST）照常记下来。"""

    def __init__(self):
        self.gets: list[str] = []
        self.cookies = {"SID": "sid-SECRET"}

    async def get(self, url, **kw):
        self.gets.append(url)
        raise AssertionError("附件 URL 走了账号的会话")


class _Resp:
    def __init__(self, status=200, content=b"img", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {"content-type": "image/png"}


class _RemoteSession:
    instances: list = []

    def __init__(self, *a, **kw):
        self.kwargs = kw
        self.gets: list[tuple] = []
        self.closed = False
        _RemoteSession.instances.append(self)

    async def get(self, url, **kw):
        self.gets.append((url, kw))
        return _Resp()

    async def close(self):
        self.closed = True


@pytest.fixture
def remote(monkeypatch):
    _RemoteSession.instances = []
    monkeypatch.setattr(fu, "is_safe_url", lambda url: True)
    monkeypatch.setattr(fu, "upload_file", _fake_upload)
    monkeypatch.setattr(fu, "_new_remote_session", _RemoteSession, raising=False)
    return _RemoteSession


def test_attachment_download_never_touches_the_account_session(remote):
    account = _AccountSession()

    out = asyncio.run(fu.upload_files(account, {}, {}, "push", [
        {"url": "https://accounts.google.com/Logout", "filename": "a.png", "mime": "image/png"},
        {"url": "https://mail.google.com/mail/feed/atom", "filename": "b.png", "mime": "image/png"},
    ]))

    assert account.gets == []
    assert [fid for fid, _ in out] == [FID, FID]
    fetched = [url for s in remote.instances for url, _ in s.gets]
    assert sorted(fetched) == ["https://accounts.google.com/Logout", "https://mail.google.com/mail/feed/atom"]
    for s in remote.instances:
        assert all("cookies" not in kw for _, kw in s.gets), "附件下载不传任何 Cookie"
        assert s.closed, "另开的 session 用完要关掉"


def test_each_attachment_gets_its_own_cookieless_session(remote):
    """同一批里的两个附件也不共用 session：前一个 URL 下发的 Cookie 带不到后一个 URL。"""
    asyncio.run(fu.upload_files(_AccountSession(), {}, {}, "push", [
        {"url": "https://a.example.com/1.png"},
        {"url": "https://b.example.com/2.png"},
    ]))
    assert len(remote.instances) == 2
    assert all(len(s.gets) == 1 for s in remote.instances)


def test_redirect_hops_stay_on_the_cookieless_session(monkeypatch, remote):
    """手动跟随的每一跳（SSRF 校验之后）同样在那个不带 Cookie 的 session 上发。"""

    class _Redirecting(_RemoteSession):
        async def get(self, url, **kw):
            self.gets.append((url, kw))
            if url.endswith("/start"):
                return _Resp(302, b"", {"location": "https://drive.google.com/private"})
            return _Resp()

    monkeypatch.setattr(fu, "_new_remote_session", _Redirecting)
    account = _AccountSession()

    asyncio.run(fu.upload_files(account, {}, {}, "push", [{"url": "https://evil.example.com/start"}]))

    assert account.gets == []
    (s,) = _RemoteSession.instances
    assert [u for u, _ in s.gets] == ["https://evil.example.com/start", "https://drive.google.com/private"]


def test_inline_data_attachments_open_no_extra_session(remote):
    out = asyncio.run(fu.upload_files(_AccountSession(), {}, {}, "push", [
        {"data": b"x", "filename": "a.png", "mime": "image/png"},
    ]))
    assert out == [(FID, "a.png")]
    assert remote.instances == []


def test_the_cookieless_session_uses_the_accounts_tls_fingerprint(remote):
    """另开的 session 与账号会话同一个 impersonate 目标（只是不带 Cookie）。"""
    asyncio.run(fu.upload_files(_AccountSession(), {}, {}, "push", [{"url": "https://x.example.com/a.png"}],
                                impersonate="chrome120"))
    (s,) = remote.instances
    assert s.kwargs.get("impersonate") == "chrome120"


def test_the_real_factory_builds_a_session_without_cookies():
    s = fu._new_remote_session(impersonate="chrome120")
    try:
        assert len(s.cookies) == 0
    finally:
        asyncio.run(s.close())

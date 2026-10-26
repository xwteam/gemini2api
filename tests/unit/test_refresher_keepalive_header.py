"""仓库自带的 Playwright 续期边车（refresher/refresher.py）推 cookie 时要表明自己是浏览器保活。

refresher 本身就是一个真浏览器：定时打开 gemini.google.com，由 Google 前端 JS 续期 PSIDTS，再
PUT /admin/accounts/{id}/cookies 推给主服务（账号不在池里时退回 POST /admin/reload-cookies）。
它过去既不带 X-Gemini2API-Keepalive 头、也没有 chrome-extension:// 的 Origin，主服务按来源判成
server，照样每 10 分钟轮换 —— 与 refresher 的浏览器形成同一种双方轮换，而且每推一次都把这个
PSID 的记录重写成 server（复审 Minor）。
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from app.core import keepalive_modes as km

REFRESHER = Path(__file__).resolve().parents[2] / "refresher" / "refresher.py"


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def refresher(monkeypatch):
    """按路径加载 refresher.py：playwright（测试环境没装）与 requests 换成替身，绝不联网。"""
    calls = []
    fake_requests = types.ModuleType("requests")
    fake_requests.put_status = 200

    def _put(url, json=None, headers=None, timeout=None):
        calls.append(("PUT", url, dict(headers or {})))
        return _Resp(fake_requests.put_status)

    def _post(url, json=None, headers=None, timeout=None):
        calls.append(("POST", url, dict(headers or {})))
        return _Resp(200)

    fake_requests.put = _put
    fake_requests.post = _post
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: None
    playwright.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setenv("ADMIN_API_KEY", "sk-admin-test")
    # 别在 refresher/ 下留 __pycache__（那是边车镜像的构建目录）
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    spec = importlib.util.spec_from_file_location("g2a_refresher_under_test", REFRESHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls, fake_requests


def test_the_put_tells_the_server_a_browser_keeps_these_cookies_alive(refresher):
    module, calls, _fake = refresher

    assert module.notify_gemini2api("account-0", "PSID", "PSIDTS") is True

    ((method, url, headers),) = calls
    assert method == "PUT" and url.endswith("/admin/accounts/account-0/cookies")
    assert km.KEEPALIVE_HEADER in headers
    assert km.mode_from_headers(headers) == km.MODE_BROWSER, "主服务必须把它判成浏览器保活、不再自己轮换"
    assert headers["Authorization"] == "Bearer sk-admin-test", "鉴权头不能丢"


def test_the_fallback_post_carries_the_header_too(refresher):
    """账号不在池里（PUT 回 404）时退回 POST /admin/reload-cookies：同样要带。"""
    module, calls, fake = refresher
    fake.put_status = 404

    assert module.notify_gemini2api("account-9", "PSID", "PSIDTS") is True

    assert [method for method, _url, _headers in calls] == ["PUT", "POST"]
    assert calls[1][1].endswith("/admin/reload-cookies")
    assert all(km.mode_from_headers(headers) == km.MODE_BROWSER for _m, _u, headers in calls)

"""熔断状态的展示（v1.6.46 规格 C.7，按 I.7 / I.14）。

  - /admin/status 与 /admin/accounts 共用 admin._masked_status()，两个都带 model_breakers（账号页的
    loadAccounts 读的是 /admin/accounts，只加在 /admin/status 上横幅永远出不来）；
  - 面板账号页顶部：任一族 open / half_open 且熔断开关开着时显示一行提示；open 显示绝对时间，
    half_open 单独一句；开关关闭时不显示；last_reason 转义；
  - 五个语言块（zh-CN、en-US、ja-JP、ko-KR、zh-TW）新键齐全（显式名单）。

⚠️ app.js 含 NUL 字节，必须用 read_text 读，不能 shell 出去 grep。
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

import app.core.account_pool as ap
from app.core.model_breaker import model_breaker

_ROOT = Path(__file__).resolve().parents[2]
_APP_JS = _ROOT / "static" / "app" / "app.js"
_UTILS_JS = _ROOT / "static" / "app" / "utils.js"
_I18N_JS = _ROOT / "static" / "app" / "i18n.js"
_SECTION = _ROOT / "static" / "components" / "section-accounts.html"
_LANGS = ("zh-CN", "en-US", "ja-JP", "ko-KR", "zh-TW")
_AUTH = {"Authorization": "Bearer sk-test-key"}

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")

_NEW_KEYS = ("accounts.breakerOpen", "accounts.breakerHalfOpen", "accounts.breakerProbing",
             "accounts.breakerLastReason")


def _open_flash():
    model_breaker.record_failure("flash", started_at=model_breaker.now(), fingerprint="a",
                                 reason="GenerationTimedOut")
    model_breaker.record_failure("flash", started_at=model_breaker.now(), fingerprint="b",
                                 reason="GeminiFailureReply (HTTP 502)")


# ---------------------------------------------------------------------------
# 后端
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/admin/status", "/admin/accounts"])
def test_both_admin_endpoints_carry_model_breakers(gem_client, monkeypatch, path):
    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    _open_flash()
    body = gem_client.get(path, headers=_AUTH).json()

    flash = body["model_breakers"]["flash"]
    assert flash["state"] == "open"
    assert flash["enabled"] is True
    assert flash["consecutive_failures"] == 2
    assert 0 < flash["open_remaining_seconds"] <= 60
    assert flash["cooldown_seconds"] == 60
    assert flash["last_reason"] == "GeminiFailureReply (HTTP 502)"
    assert flash["last_failure_at"].endswith("+00:00"), "与其它状态字段一样是 UTC isoformat"
    assert flash["retry_at"].endswith("+00:00")
    assert flash["probe_in_flight"] is False


@pytest.mark.parametrize("path", ["/admin/status", "/admin/accounts"])
def test_absurd_cooldowns_cannot_take_the_status_endpoints_down(gem_client, monkeypatch, path):
    """MODEL_BREAKER_COOLDOWN / MAX_COOLDOWN=1e12 过去照样被接受：熔断一打开，retry_at 的日期运算越界，
    两个端点整个开放期都回 500（面板账号页打不开）。"""
    from app.config import settings

    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    monkeypatch.setattr(settings, "model_breaker_cooldown", 1e12)
    monkeypatch.setattr(settings, "model_breaker_max_cooldown", 1e12)
    _open_flash()
    r = gem_client.get(path, headers=_AUTH)

    assert r.status_code == 200, r.text
    assert r.json()["model_breakers"]["flash"]["state"] == "open"


def test_model_breakers_is_empty_when_nothing_happened(gem_client, monkeypatch):
    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    body = gem_client.get("/admin/status", headers=_AUTH).json()
    assert body["model_breakers"] == {}


# ---------------------------------------------------------------------------
# i18n / 页面骨架
# ---------------------------------------------------------------------------

def _i18n_blocks() -> dict:
    blocks, current = {}, None
    for line in _I18N_JS.read_text(encoding="utf-8").splitlines():
        lang = re.match(r"^ {4}'([A-Za-z-]+)': \{$", line)
        if lang:
            current = lang.group(1)
            blocks[current] = {}
            continue
        if current is None:
            continue
        m = re.match(r"^ +'(accounts\.[^']+)': '(.*)',?$", line)
        if m:
            blocks[current][m.group(1)] = m.group(2)
    assert set(_LANGS) <= set(blocks), f"i18n.js 语言块解析异常: {sorted(blocks)}"
    return blocks


def test_new_breaker_keys_exist_in_every_language():
    """显式名单：五个语言块一起漏掉某个键时，集合比较照样相等，面板会把键名原样显示给用户。"""
    blocks = _i18n_blocks()
    missing = {lang: [k for k in _NEW_KEYS if k not in blocks[lang]] for lang in _LANGS}
    assert not any(missing.values()), missing


def test_breaker_texts_keep_their_placeholders_in_every_language():
    blocks = _i18n_blocks()
    for lang in _LANGS:
        assert "{family}" in blocks[lang]["accounts.breakerOpen"], lang
        assert "{time}" in blocks[lang]["accounts.breakerOpen"], lang
        assert "{family}" in blocks[lang]["accounts.breakerHalfOpen"], lang


def test_the_accounts_section_has_a_banner_slot_above_the_cards():
    html = _SECTION.read_text(encoding="utf-8")
    assert 'id="modelBreakerBanner"' in html
    assert html.index('id="modelBreakerBanner"') < html.index('id="accountsList"')


# ---------------------------------------------------------------------------
# 面板渲染：把 app.js 里真正在跑的函数切出来丢给 node
# ---------------------------------------------------------------------------

def _extract_function(source: str, name: str) -> str:
    head = source.index(f"function {name}(")
    if source[max(0, head - 6):head] == "async ":
        head -= 6
    depth = 0
    i = source.index("{", head)
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[head:i + 1]
        i += 1
    raise AssertionError(f"{name} 的大括号没配对，源码格式可能变了")


_APP_FUNCS = ("escapeHtml", "_accountKeepaliveTag", "_accountHealthNote", "_accountEmptyNote",
              "_accountHealthRow", "_accountEmptyRow", "_accountLastErrorText",
              "_modelBreakerBanner", "loadAccounts")


def _harness() -> str:
    src = _APP_JS.read_text(encoding="utf-8")
    utils = _UTILS_JS.read_text(encoding="utf-8")
    pieces = [_extract_function(src, name) for name in _APP_FUNCS]
    pieces.append(_extract_function(utils, "formatDate"))
    threshold = re.search(r"^const EMPTY_STREAK_THRESHOLD = (\d+);$", src, re.M)
    assert threshold
    return (
        textwrap.dedent("""
        const _ARGV = JSON.parse(process.argv[2]);
        const _I18N = _ARGV.i18n || {};
        function t(k) { return Object.prototype.hasOwnProperty.call(_I18N, k) ? _I18N[k] : k; }
        function makeEl(tag) {
            return {
                tag, _text: '', _html: null,
                set textContent(v) { this._text = v == null ? '' : String(v); this._html = null; },
                get textContent() { return this._text; },
                set innerHTML(v) { this._html = String(v); },
                get innerHTML() {
                    if (this._html !== null) return this._html;
                    return this._text
                        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                },
                querySelectorAll() { return []; },
            };
        }
        const _byId = {};
        const document = {
            createElement: makeEl,
            getElementById(id) { return _byId[id] || null; },
        };
        const _consoleErrors = [];
        const console = { error: (...a) => _consoleErrors.push(a.map(String).join(' ')) };
        function getCurrentLanguage() { return 'en-US'; }
        function formatNumber(n) { return String(n); }
        function getStatusBadge(s) { return '<BADGE:' + s + '>'; }
        function maskString(s) { return '<MASK>'; }
        function escapeAttr(s) { return '<ATTR:' + String(s == null ? '' : s) + '>'; }
        const _apiCalls = [];
        async function apiCall(method, path) { _apiCalls.push(method + ' ' + path); return _ARGV.response; }
        """)
        + f"const EMPTY_STREAK_THRESHOLD = {threshold.group(1)};\n"
        + "\n".join(pieces)
        + textwrap.dedent("""
        async function main() {
            _byId['accountsList'] = makeEl('div');
            _byId['modelBreakerBanner'] = makeEl('div');
            await loadAccounts();
            return {
                banner: _byId['modelBreakerBanner'].innerHTML,
                apiCalls: _apiCalls,
                consoleErrors: _consoleErrors,
            };
        }
        main().then(r => process.stdout.write(JSON.stringify(r)));
        """)
    )


_I18N = {
    "accounts.breakerOpen": "Gemini {family} DOWN; fallback until {time}",
    "accounts.breakerHalfOpen": "Gemini {family} DOWN; probing with the next request",
    "accounts.breakerProbing": "probe in flight",
    "accounts.breakerLastReason": "Last failure",
}


def _render(response: dict, tmp_path: Path) -> dict:
    script = tmp_path / "banner.mjs"
    script.write_text(_harness(), encoding="utf-8")
    proc = subprocess.run([_NODE, str(script), json.dumps({"response": response, "i18n": _I18N})],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["consoleErrors"] == [], out["consoleErrors"]
    return out


def _breaker(**kw) -> dict:
    base = {"state": "open", "enabled": True, "consecutive_failures": 2,
            "open_remaining_seconds": 42.0, "retry_at": "2026-10-26T09:58:30+00:00",
            "cooldown_seconds": 60, "probe_in_flight": False,
            "last_reason": "GeminiFailureReply (HTTP 502)",
            "last_failure_at": "2026-10-26T09:57:30+00:00"}
    base.update(kw)
    return base


@_needs_node
def test_the_banner_is_fed_by_the_endpoint_load_accounts_really_calls(gem_client, monkeypatch, tmp_path):
    """I.7：横幅的输入是 loadAccounts 实际请求的那个端点（/admin/accounts）的真实返回值。"""
    monkeypatch.setattr(ap.account_pool, "_accounts", [])
    _open_flash()
    response = gem_client.get("/admin/accounts", headers=_AUTH).json()
    out = _render(response, tmp_path)

    assert out["apiCalls"] == ["GET /admin/accounts"]
    assert "Gemini flash DOWN; fallback until " in out["banner"]
    assert "{time}" not in out["banner"] and "{family}" not in out["banner"]
    assert "GeminiFailureReply (HTTP 502)" in out["banner"]
    assert "Last failure" in out["banner"]


@_needs_node
def test_open_shows_an_absolute_time_not_a_countdown(tmp_path):
    out = _render({"accounts": [], "model_breakers": {"flash": _breaker()}}, tmp_path)
    assert "Gemini flash DOWN; fallback until " in out["banner"]
    assert "2026" in out["banner"], f"open 要显示几点几分再试谷歌: {out['banner']!r}"
    assert "42" not in out["banner"], "不是打开页面那一刻的倒计时快照"


@_needs_node
def test_half_open_has_its_own_sentence(tmp_path):
    out = _render({"accounts": [], "model_breakers": {
        "pro": _breaker(state="half_open", open_remaining_seconds=0, retry_at=None, probe_in_flight=True),
    }}, tmp_path)
    assert "Gemini pro DOWN; probing with the next request" in out["banner"]
    assert "probe in flight" in out["banner"]
    assert "fallback until" not in out["banner"]


@_needs_node
@pytest.mark.parametrize("breakers", [
    {},
    {"flash": _breaker(state="closed", open_remaining_seconds=0, retry_at=None)},
    {"flash": _breaker(enabled=False)},                   # 开关关着：不绕开谷歌，不显示「绕开」横幅
    {"flash": _breaker(state="half_open", enabled=False, retry_at=None)},
], ids=["none", "closed", "disabled-open", "disabled-half-open"])
def test_no_banner_when_nothing_is_bypassed(tmp_path, breakers):
    out = _render({"accounts": [], "model_breakers": breakers}, tmp_path)
    assert out["banner"] == ""


@_needs_node
def test_an_old_backend_without_the_field_shows_no_banner(tmp_path):
    out = _render({"accounts": []}, tmp_path)
    assert out["banner"] == ""


@_needs_node
def test_backend_strings_are_escaped(tmp_path):
    out = _render({"accounts": [], "model_breakers": {
        "flash": _breaker(last_reason='<img src=x onerror="alert(1)">'),
        "<b>evil</b>": _breaker(),
    }}, tmp_path)
    assert "<img" not in out["banner"] and "&lt;img" in out["banner"]
    assert "<b>evil</b>" not in out["banner"] and "&lt;b&gt;evil" in out["banner"]


@_needs_node
def test_several_families_get_one_line_each(tmp_path):
    out = _render({"accounts": [], "model_breakers": {
        "flash": _breaker(),
        "pro": _breaker(state="half_open", retry_at=None, open_remaining_seconds=0),
        "flash-lite": _breaker(state="closed", retry_at=None, open_remaining_seconds=0),
    }}, tmp_path)
    assert "Gemini flash DOWN" in out["banner"]
    assert "Gemini pro DOWN" in out["banner"]
    assert "flash-lite" not in out["banner"]

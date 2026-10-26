"""账号卡片必须真的把健康信息渲染出来（issue #11 的"接线"那一半）。

上一轮只测了两个纯函数 `_accountHealthNote` / `_accountEmptyNote`，它们的返回值怎么落到
面板 DOM 完全没有断言 —— 于是把 `_accountHealthRow` 的 `if (!note) return '';` 改成
`if (note) return '';`（有提示时反而返回空串，面板永远不显示"active 但 is_healthy=false"
的红字告警）可以让整批改动的用户可见价值归零，而全量单测照样全绿。
同理 `_accountHealthRow` / `_accountEmptyRow` / `loadAccounts` 里的 escapeHtml 也可以被
删掉而不变红。

这里把 app.js / utils.js 里**真正在跑的那几个函数原样切出来**丢给 node 执行
（连 `renderAccountStatusGrid` 和 `loadAccounts` 这两个真实调用点也一起切出来跑），
配一套极小的假 DOM——假 DOM 只复刻浏览器 "textContent 写入 → innerHTML 读出会转义"
这一条语义，所以跑的是 app.js 里真正的 escapeHtml，不是替身。

⚠️ app.js 含 NUL 字节，必须用 read_text 读，不能 shell 出去 grep。
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_APP_JS = _ROOT / "static" / "app" / "app.js"
_UTILS_JS = _ROOT / "static" / "app" / "utils.js"

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")


def _extract_function(source: str, name: str) -> str:
    """按大括号配对切出 `[async ]function name(...) { ... }` 全文。"""
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


_APP_FUNCS = (
    "escapeHtml",
    "_accountKeepaliveTag",
    "_accountHealthNote",
    "_accountEmptyNote",
    "_accountHealthRow",
    "_accountEmptyRow",
    "_accountLastErrorText",
    "renderAccountStatusGrid",
    "loadAccounts",
)


def _harness() -> str:
    src = _APP_JS.read_text(encoding="utf-8")
    utils = _UTILS_JS.read_text(encoding="utf-8")

    pieces = []
    for name in _APP_FUNCS:
        fn = _extract_function(src, name)
        assert f"function {name}(" in fn.split("{", 1)[0], f"切出的 {name} 不对: {fn[:80]!r}"
        pieces.append(fn)
    pieces.append(_extract_function(utils, "formatDate"))

    threshold = re.search(r"^const EMPTY_STREAK_THRESHOLD = (\d+);$", src, re.M)
    assert threshold, "没找到前端 EMPTY_STREAK_THRESHOLD 常量，app.js 格式可能变了"

    return (
        textwrap.dedent("""
        const _ARGV = JSON.parse(process.argv[2]);
        const _I18N = _ARGV.i18n || {};
        function t(k) { return Object.prototype.hasOwnProperty.call(_I18N, k) ? _I18N[k] : k; }

        // 假 DOM：只复刻浏览器 "textContent 写入 → innerHTML 读出会被转义" 这一条语义，
        // 好让 app.js 里真正的 escapeHtml 原样跑起来（它就是靠这条语义实现的）。
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

        // 与这批改动无关的周边帮手，保持最朴素的可辨认输出
        function getCurrentLanguage() { return 'en-US'; }
        function formatNumber(n) { return String(n); }
        function getStatusBadge(s) { return '<BADGE:' + s + '>'; }
        function maskString(s) { return '<MASK>'; }
        function escapeAttr(s) { return '<ATTR:' + String(s == null ? '' : s) + '>'; }
        async function apiCall() { return { accounts: _ARGV.accounts }; }
        """)
        + f"const EMPTY_STREAK_THRESHOLD = {threshold.group(1)};\n"
        + "\n".join(pieces)
        + textwrap.dedent("""

        async function main() {
            const out = {
                healthRow: _ARGV.accounts.map(_accountHealthRow),
                emptyRow: _ARGV.accounts.map(_accountEmptyRow),
                lastErrorText: _ARGV.accounts.map(_accountLastErrorText),
            };

            // 真实调用点 1：仪表盘的账号状态格
            _byId['accountStatusGrid'] = makeEl('div');
            renderAccountStatusGrid(_ARGV.accounts);
            out.grid = _byId['accountStatusGrid'].innerHTML;

            // 真实调用点 2：账号管理页
            _byId['accountsList'] = makeEl('div');
            await loadAccounts();
            out.list = _byId['accountsList'].innerHTML;

            out.consoleErrors = _consoleErrors;
            return out;
        }
        main().then(r => process.stdout.write(JSON.stringify(r)));
        """)
    )


def _render(accounts, tmp_path: Path, i18n=None) -> dict:
    script = tmp_path / "cards.mjs"
    script.write_text(_harness(), encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(script), json.dumps({"accounts": accounts, "i18n": i18n or {}})],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["consoleErrors"] == [], f"渲染过程中抛错了: {out['consoleErrors']}"
    return out


def _acc(**kw) -> dict:
    base = {
        "id": "acc-1", "label": "L", "status": "active", "psid": "p",
        "request_count": 4, "error_count": 0, "active_requests": 0, "models_count": 4,
        "is_healthy": True, "consecutive_failures": 0, "consecutive_empty": 0,
        "empty_count": 0, "last_success_at": None, "last_error": None, "last_error_at": None,
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 健康行：note 到底有没有落进 DOM
# --------------------------------------------------------------------------

@_needs_node
def test_active_but_unhealthy_account_renders_a_red_row_on_both_pages(tmp_path):
    """issue #11 的核心场景：绿着 ACTIVE 但会话已死，两个面板都必须出红字。"""
    out = _render([_acc(is_healthy=False)], tmp_path)

    row = out["healthRow"][0]
    assert row != "", "有健康告警时 _accountHealthRow 绝不能返回空串"
    assert "text-danger" in row
    assert "accounts.healthMismatch" in row
    # 两个真实调用点都得把这一行摆出来，否则用户根本看不到
    assert "accounts.healthMismatch" in out["grid"], "仪表盘账号格没渲染健康行"
    assert "accounts.healthMismatch" in out["list"], "账号管理页没渲染健康行"


@_needs_node
def test_consecutive_failures_render_a_warning_row(tmp_path):
    out = _render([_acc(consecutive_failures=2)], tmp_path)

    assert "text-warning" in out["healthRow"][0]
    assert "accounts.consecutiveFailures: 2" in out["healthRow"][0]
    assert "accounts.consecutiveFailures: 2" in out["grid"]
    assert "accounts.consecutiveFailures: 2" in out["list"]


@_needs_node
def test_healthy_account_adds_no_health_row_anywhere(tmp_path):
    """健康账号不加噪音 —— 但这不能靠"永远返回空串"来实现（见上面的用例）。"""
    out = _render([_acc()], tmp_path)

    assert out["healthRow"][0] == ""
    assert "accounts.health" not in out["grid"]
    assert "accounts.health" not in out["list"]


# --------------------------------------------------------------------------
# 空响应行
# --------------------------------------------------------------------------

@_needs_node
def test_empty_responses_render_with_total_and_streak(tmp_path):
    out = _render([_acc(empty_count=7, consecutive_empty=2)], tmp_path)

    row = out["emptyRow"][0]
    assert row != ""
    assert "text-warning" in row
    assert "7 (accounts.consecutiveNow 2)" in row
    assert "accounts.emptyResponses" in out["grid"], "仪表盘账号格没渲染空响应行"
    assert "accounts.emptyResponses" in out["list"], "账号管理页没渲染空响应行"


@_needs_node
def test_empty_streak_at_threshold_renders_red(tmp_path):
    out = _render([_acc(empty_count=3, consecutive_empty=3)], tmp_path)
    assert "text-danger" in out["emptyRow"][0]


@_needs_node
def test_account_that_never_returned_empty_adds_no_row(tmp_path):
    out = _render([_acc()], tmp_path)

    assert out["emptyRow"][0] == ""
    assert "accounts.emptyResponses" not in out["grid"]
    assert "accounts.emptyResponses" not in out["list"]


# --------------------------------------------------------------------------
# 最近错误：文本 + 发生时间
# --------------------------------------------------------------------------

@_needs_node
def test_last_error_is_rendered_together_with_its_timestamp(tmp_path):
    """没有时间戳的 last_error 就是一句没有鉴别力的话：三周前的 503 会一直挂在卡片上。

    release(success=True) 只清 consecutive_failures / consecutive_empty，从不清 last_error。
    """
    out = _render([_acc(
        last_error="HTTPStatusError (HTTP 503)",
        last_error_at="2026-09-12T01:37:47.538915+00:00",
    )], tmp_path)

    text = out["lastErrorText"][0]
    assert "HTTPStatusError (HTTP 503)" in text
    assert "2026" in text, f"错误文本里没有发生时间: {text!r}"
    assert "2026" in out["list"], "账号管理页没把 last_error_at 渲染出来"


@_needs_node
def test_last_error_without_timestamp_still_renders(tmp_path):
    """老版本后端没有 last_error_at，不得渲染成 '... (-)' 之类的噪音。"""
    out = _render([_acc(last_error="ValueError")], tmp_path)

    assert out["lastErrorText"][0] == "ValueError"
    assert "ValueError" in out["list"]


# --------------------------------------------------------------------------
# 转义：纯防御层也要有人守着
# --------------------------------------------------------------------------

@_needs_node
def test_health_and_empty_rows_escape_their_value_text(tmp_path):
    """note.text 今天只拼 i18n 常量和数字，但 escapeHtml 一旦被删就没人拦得住下一个人。"""
    out = _render(
        [_acc(consecutive_failures=2, empty_count=1, consecutive_empty=1)],
        tmp_path,
        i18n={
            "accounts.consecutiveFailures": "Fail<s>",
            "accounts.consecutiveNow": "now<x>",
        },
    )

    assert "Fail&lt;s&gt;: 2" in out["healthRow"][0]
    assert "Fail<s>" not in out["healthRow"][0], "_accountHealthRow 的 escapeHtml 被绕过了"
    assert "now&lt;x&gt;" in out["emptyRow"][0]
    assert "now<x>" not in out["emptyRow"][0], "_accountEmptyRow 的 escapeHtml 被绕过了"


@_needs_node
def test_last_error_text_is_escaped(tmp_path):
    """last_error 是后端写入的字符串，进卡片前必须转义（面板存储型 XSS 的入口）。"""
    payload = "<img src=x onerror=alert(1)>"
    out = _render([_acc(last_error=payload)], tmp_path)

    assert "&lt;img src=x onerror=alert(1)&gt;" in out["lastErrorText"][0]
    assert "<img" not in out["lastErrorText"][0]
    assert "<img" not in out["list"], "账号管理页把 last_error 原样当 HTML 插进去了"


# --------------------------------------------------------------------------
# 「浏览器保活」小标签（v1.6.44）：插件推送 cookie 的账号服务端不再轮换，面板要看得出来
# --------------------------------------------------------------------------

@_needs_node
def test_browser_kept_account_shows_the_tag_on_both_pages(tmp_path):
    out = _render([_acc(keepalive_mode="browser")], tmp_path)

    for page in ("grid", "list"):
        html = out[page]
        assert "accounts.keepaliveBrowser" in html, f"{page} 没渲染「浏览器保活」标签"
        # title 提示：cookie 由插件推送、服务端不主动轮换
        assert 'title="<ATTR:accounts.keepaliveBrowserHint>"' in html, f"{page} 的标签没带 title 提示"


@_needs_node
def test_server_mode_and_old_backends_show_no_tag(tmp_path):
    """服务端轮换（默认）不加噪音；老后端没有这个字段也不能误显示。"""
    old_backend = _acc()
    old_backend.pop("keepalive_mode", None)
    out = _render([_acc(keepalive_mode="server"), old_backend], tmp_path)

    assert "accounts.keepaliveBrowser" not in out["grid"]
    assert "accounts.keepaliveBrowser" not in out["list"]


@_needs_node
def test_keepalive_tag_text_is_escaped(tmp_path):
    out = _render([_acc(keepalive_mode="browser")], tmp_path,
                  i18n={"accounts.keepaliveBrowser": "Br<b>owser"})

    assert "Br&lt;b&gt;owser" in out["list"]
    assert "Br<b>owser" not in out["list"], "标签文字没走 escapeHtml"
    assert "Br<b>owser" not in out["grid"]


@_needs_node
def test_session_expired_account_reads_consistently(tmp_path):
    """会话被打回登录页的账号现在对外报 expired：徽章、健康行、最近错误要说同一件事，
    不能再出现「标着可用、但会话已失效」那行红字（那是给 active+不健康 准备的）。"""
    out = _render([_acc(status="expired", is_healthy=False,
                        last_error="Google session expired (login redirect)")], tmp_path)

    assert "<BADGE:expired>" in out["grid"] and "<BADGE:expired>" in out["list"]
    assert "accounts.sessionUnhealthy" in out["list"]
    assert "accounts.healthMismatch" not in out["list"]
    assert "text-danger" not in out["healthRow"][0]
    assert "Google session expired (login redirect)" in out["list"]

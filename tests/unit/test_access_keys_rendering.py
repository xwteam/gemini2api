"""访问密钥列表的**真实渲染产物**行为测试（照 test_account_card_rendering.py 的路子）。

为什么不是静态断言：只测纯函数、不断言返回值怎么落进 DOM 的话，把 statusBadge() 改成
恒返回「有效」、或者把名称的 escapeHtml 去掉，用户可见的价值/安全性直接归零，而全量
单测照样全绿。所以这里用 node 把 access-keys.js 里真正的函数跑起来，断言 innerHTML。

只复刻浏览器「textContent 写入 → innerHTML 读出会转义」这一条语义，让 utils.js 里真正的
escapeHtml 原样工作（它就是靠这条语义实现的），不给它换替身。
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "static"
_AK_JS = _STATIC / "app" / "access-keys.js"
_UTILS_JS = _STATIC / "app" / "utils.js"

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")


def _extract_function(source: str, name: str) -> str:
    """按大括号配对切出 `[async ]function name(...) { ... }` 全文（export 前缀自然被跳过）。"""
    head = source.index(f"function {name}(")
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


def _extract_const_object(source: str, name: str) -> str:
    """切出 `const NAME = { ... };`（状态 → 徽章类名/i18n 键的真实映射表）。"""
    head = source.index(f"const {name} = {{")
    i = source.index("{", head)
    depth = 0
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[head:i + 1] + ";"
        i += 1
    raise AssertionError(f"const {name} 的大括号没配对，源码格式可能变了")


_AK_FUNCS = ("escapeAttr", "statusBadge", "validityText", "usageText", "boundText", "render")


def _harness() -> str:
    src = _AK_JS.read_text(encoding="utf-8")
    utils = _UTILS_JS.read_text(encoding="utf-8")

    pieces = [_extract_const_object(src, "STATE_BADGE"), _extract_const_object(src, "STATE_I18N")]
    for name in _AK_FUNCS:
        fn = _extract_function(src, name)
        assert f"function {name}(" in fn.split("{", 1)[0], f"切出的 {name} 不对: {fn[:80]!r}"
        pieces.append(fn)
    for name in ("escapeHtml", "formatDate", "formatNumber"):
        pieces.append(_extract_function(utils, name))

    assert "akk-list-container" in src, "render 的挂载点变了，用例的假 DOM 也要跟着改"

    return (
        textwrap.dedent("""
        const _ARGV = JSON.parse(process.argv[2]);
        const _I18N = _ARGV.i18n || {};
        function t(k) { return Object.prototype.hasOwnProperty.call(_I18N, k) ? _I18N[k] : k; }
        function getCurrentLanguage() { return 'en-US'; }

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

        let keysData = [];
        """)
        + "\n".join(pieces)
        + textwrap.dedent("""

        function main() {
            keysData = _ARGV.keys;
            _byId['akk-list-container'] = makeEl('div');
            render();
            return {
                list: _byId['akk-list-container'].innerHTML,
                badges: keysData.map(statusBadge),
                validity: keysData.map(validityText),
                usage: keysData.map(usageText),
                scope: keysData.map(boundText),
                consoleErrors: _consoleErrors,
            };
        }
        process.stdout.write(JSON.stringify(main()));
        """)
    )


def _render(keys, tmp_path: Path, i18n=None) -> dict:
    script = tmp_path / "akk.mjs"
    script.write_text(_harness(), encoding="utf-8")
    proc = subprocess.run(
        [_NODE, str(script), json.dumps({"keys": keys, "i18n": i18n or {}})],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["consoleErrors"] == [], f"渲染过程中抛错了: {out['consoleErrors']}"
    return out


def _key(**kw) -> dict:
    base = {
        "id": 1, "key": "sk-" + "a" * 32, "name": "alice", "display_name": "alice",
        "enabled": True, "state": "valid", "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": None, "duration_days": None, "activated_at": "2026-01-01T00:00:00+00:00",
        "request_limit": None, "request_count": 0,
        "bound_account_ids": None, "allowed_models": None, "last_used_at": None,
    }
    base.update(kw)
    return base


@_needs_node
def test_empty_list_renders_the_empty_state(tmp_path):
    out = _render([], tmp_path, i18n={"accessKeys.empty": "No keys yet"})
    assert "No keys yet" in out["list"]
    assert "<table" not in out["list"]


@_needs_node
def test_every_key_shows_its_plaintext_and_a_copy_button(tmp_path):
    keys = [_key(id=1, key="sk-aaa"), _key(id=2, key="sk-bbb", name="bob", display_name="bob")]
    out = _render(keys, tmp_path)
    assert "sk-aaa" in out["list"] and "sk-bbb" in out["list"], "分发不出去的密钥页等于没用"
    assert out["list"].count("akk-copy-btn") == 2
    assert 'data-id="1"' in out["list"] and 'data-id="2"' in out["list"]


@_needs_node
def test_the_five_states_are_visually_distinguishable(tmp_path):
    """守住"状态列真的分得开"：有人把 statusBadge 写成恒返回 badge-success 时必须变红。"""
    states = ["valid", "pending", "disabled", "expired", "quota_exceeded"]
    i18n = {
        "accessKeys.stateValid": "Valid",
        "accessKeys.statePending": "Pending",
        "accessKeys.stateDisabled": "Disabled",
        "accessKeys.stateExpired": "Expired",
        "accessKeys.stateQuota": "Quota",
    }
    keys = [_key(id=i + 1, state=s) for i, s in enumerate(states)]
    out = _render(keys, tmp_path, i18n=i18n)

    classes = [re.search(r'class="badge (badge-[a-z]+)"', b).group(1) for b in out["badges"]]
    assert len(set(classes)) == len(states), f"状态徽章类名撞了: {classes}"
    labels = [re.search(r">([^<]*)<", b).group(1) for b in out["badges"]]
    assert sorted(labels) == sorted(i18n.values()), f"状态文案没分开: {labels}"
    for label in i18n.values():
        assert label in out["list"], f"{label} 没出现在真实渲染结果里"


@_needs_node
def test_validity_column_tells_the_three_cases_apart(tmp_path):
    keys = [
        _key(id=1),                                             # 永不过期
        _key(id=2, duration_days=7, activated_at=None),         # 惰性、未激活
        _key(id=3, expires_at="2026-03-04T05:06:07+00:00"),     # 绝对过期
    ]
    out = _render(keys, tmp_path, i18n={
        "accessKeys.never": "Never",
        "accessKeys.pendingDays": "{n} days after first use",
    })
    never, pending, absolute = out["validity"]
    assert never == "Never"
    assert pending == "7 days after first use"
    assert "2026" in absolute and absolute not in ("Never", "-")
    assert len({never, pending, absolute}) == 3


@_needs_node
def test_usage_column_shows_used_over_limit(tmp_path):
    keys = [_key(id=1, request_count=0, request_limit=None),
            _key(id=2, request_count=3, request_limit=10)]
    out = _render(keys, tmp_path, i18n={"accessKeys.unlimited": "unlimited"})
    assert out["usage"][0] == "0 / unlimited", "request_count=0 不能被当成空串吞掉"
    assert out["usage"][1] == "3 / 10"


@_needs_node
def test_scope_column_distinguishes_bound_from_unrestricted(tmp_path):
    keys = [
        _key(id=1),
        _key(id=2, bound_account_ids=["account-0", "account-1"], allowed_models=["gemini-pro"]),
    ]
    out = _render(keys, tmp_path, i18n={
        "accessKeys.allAccounts": "All accounts",
        "accessKeys.allModels": "All models",
        "accessKeys.boundAccountsN": "{n} accounts",
        "accessKeys.boundModelsN": "{n} models",
    })
    assert out["scope"][0] == "All accounts · All models"
    assert out["scope"][1] == "2 accounts · 1 models"


@_needs_node
def test_toggle_button_label_follows_enabled_state(tmp_path):
    out = _render([_key(id=1, enabled=True), _key(id=2, enabled=False)], tmp_path, i18n={
        "accessKeys.enable": "Enable", "accessKeys.disable": "Disable",
    })
    assert "Disable" in out["list"] and "Enable" in out["list"]


@_needs_node
def test_user_supplied_name_is_escaped(tmp_path):
    """名称是唯一真正的攻击面：用户可控 + 持久化 + 多人可见 = 存储型 XSS 入口。"""
    payload = '<img src=x onerror=alert(1)>'
    out = _render([_key(name=payload, display_name=payload)], tmp_path)
    assert "&lt;img" in out["list"]
    assert "<img" not in out["list"]
    assert "onerror=alert(1)>" not in out["list"]


@_needs_node
def test_i18n_values_are_escaped_too(tmp_path):
    out = _render([_key()], tmp_path, i18n={"accessKeys.name": "Name<s>"})
    assert "Name&lt;s&gt;" in out["list"]
    assert "Name<s>" not in out["list"]


@_needs_node
def test_no_inline_onclick_carries_user_data():
    """app.js 里修过的真 bug：escapeHtml 不转义单引号，用户数据拼进 inline onclick 的
    JS 字符串字面量可以直接逸出。新代码一律 data-* + addEventListener。"""
    src = _AK_JS.read_text(encoding="utf-8")
    assert not re.search(r"onclick\s*=", src), "渲染出的 HTML 里不得有 inline onclick"

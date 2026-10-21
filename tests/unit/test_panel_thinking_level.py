"""面板：模型测试页的思考档位选择（T5）+ 设置页的"默认思考档位"单选组（T3）。

把 app.js / settings.js 里真正在跑的函数原样切出来丢给 node 执行，配极小的假 DOM，
断言真正发出去的请求体 / 真正渲染出的表单。不是"断言某行源码存在"的假测试。
⚠️ app.js 含 NUL 字节：用 read_text 读，不 shell 出去 grep。
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
_SETTINGS_JS = _ROOT / "static" / "app" / "settings.js"
_PG_HTML = _ROOT / "static" / "components" / "section-playground.html"
_NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")


def _extract_function(source: str, name: str) -> str:
    head = source.index(f"function {name}(")
    if source[max(0, head - 6):head] == "async ":
        head -= 6
    depth, i = 0, source.index("{", head)
    while i < len(source):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return source[head:i + 1]
        i += 1
    raise AssertionError(f"{name} 的大括号没配对，源码格式可能变了")


def _extract_const(source: str, name: str) -> str:
    m = re.search(rf"^const {name} = (\[|\{{).*?^(\]|\}});$", source, re.M | re.S)
    assert m, f"没找到 {name}，源码格式可能变了"
    return m.group(0)


def _node(tmp_path, script: str, arg) -> dict:
    path = tmp_path / "harness.mjs"
    path.write_text(script, encoding="utf-8")
    out = subprocess.run([_NODE, str(path), json.dumps(arg)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ---------------------------------------------------------------------------
# 模型测试页：真正发出去的请求体
# ---------------------------------------------------------------------------

def _send_harness() -> str:
    src = _APP_JS.read_text(encoding="utf-8")
    pieces = [_extract_function(src, n) for n in
              ("_pgThinkingEffort", "_pgBuildChatRequest", "sendPlaygroundRequest")]
    return textwrap.dedent("""
        const _ARG = JSON.parse(process.argv[2]);
        function makeEl(extra) {
            return Object.assign({
                value: '', disabled: false, innerHTML: '', className: '', scrollTop: 0,
                scrollHeight: 0, remove() {}, appendChild() {},
                querySelector() { return makeEl(); },
            }, extra || {});
        }
        const _els = {
            'pg-send': makeEl(), 'pg-message': makeEl({ value: 'hi' }),
            'pg-model': makeEl({ value: _ARG.model }), 'pg-chat': makeEl({ querySelector: () => null }),
        };
        if (_ARG.level !== undefined) _els['pg-thinking-level'] = makeEl({ value: _ARG.level });
        const document = {
            getElementById: id => _els[id] || null,
            createElement: () => makeEl(),
        };
        const localStorage = { getItem: () => 'tok' };
        let _pgImages = [], _pgMessages = [], _pgConversationId = _ARG.conv || null;
        const _sent = [];
        async function fetch(url, init) {
            _sent.push({ url, body: JSON.parse(init.body) });
            return { ok: false, status: 500, json: async () => ({ error: { message: 'x' } }) };
        }
        function t(k) { return k; }
        function escapeHtml(s) { return String(s); }
        function showToast() {}
        function _pgMaybeImageGenerationIntent() { return false; }
        function _pgShowGeneratingWait() {}
        function _renderPgImagePreview() {}
        function _pgSetSendBusy() {}
        function _pgClearGeneratingState() {}
        function _pgFormatPlaygroundError() { return 'err'; }
        """) + "\n".join(pieces) + textwrap.dedent("""
        sendPlaygroundRequest().then(() => process.stdout.write(JSON.stringify(_sent)));
        """)


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_the_selected_level_is_sent_as_reasoning_effort(tmp_path, level):
    sent = _node(tmp_path, _send_harness(), {"model": "gemini-pro", "level": level})
    assert len(sent) == 1
    assert sent[0]["url"] == "/openai/v1/chat/completions"
    assert sent[0]["body"]["reasoning_effort"] == level
    assert sent[0]["body"]["model"] == "gemini-pro"
    assert sent[0]["body"]["stream"] is True


@pytest.mark.parametrize("level", [None, "", "garbage", "xhigh"])
def test_missing_or_unknown_level_falls_back_to_low(tmp_path, level):
    """reasoning_effort 每次都显式带上（显式请求才会回传思考，测试页才看得到思考过程）。"""
    arg = {"model": "gemini-flash"}
    if level is not None:
        arg["level"] = level
    sent = _node(tmp_path, _send_harness(), arg)
    assert sent[0]["body"]["reasoning_effort"] == "low"


def test_empty_model_falls_back_to_a_public_name(tmp_path):
    sent = _node(tmp_path, _send_harness(), {"model": "", "level": "low"})
    assert sent[0]["body"]["model"] == "gemini-flash"


def test_the_level_select_defaults_to_low_with_three_levels():
    html = _PG_HTML.read_text(encoding="utf-8")
    m = re.search(r'<select id="pg-thinking-level"[^>]*>(.*?)</select>', html, re.S)
    assert m, "模型测试页没有思考档位选择框"
    options = re.findall(r'<option value="([^"]*)"([^>]*)>', m.group(1))
    assert [v for v, _ in options] == ["low", "medium", "high"]
    assert [v for v, attrs in options if "selected" in attrs] == ["low"]
    assert 'id="pg-thinking"' not in html, "旧的思考勾选框应当被档位选择取代"


# ---------------------------------------------------------------------------
# 设置页："默认思考档位"单选组
# ---------------------------------------------------------------------------

def _settings_harness() -> str:
    src = _SETTINGS_JS.read_text(encoding="utf-8")
    pieces = [_extract_const(src, n) for n in
              ("ROTATION_OPTIONS", "THINKING_LEVEL_OPTIONS", "ENUM_OPTIONS")]
    pieces.append(_extract_function(src, "createFieldInput"))
    return textwrap.dedent("""
        const _ARG = JSON.parse(process.argv[2]);
        function t(k) { return k; }
        function isFloatField() { return false; }
        """) + "\n".join(pieces) + textwrap.dedent("""
        const out = {};
        for (const [key, value] of _ARG) {
            const html = createFieldInput(key, value);
            out[key] = [...html.matchAll(/<input type="radio" name="([^"]*)" data-key="([^"]*)" value="([^"]*)"\\s*(checked)?>/g)]
                .map(m => ({ name: m[1], key: m[2], value: m[3], checked: !!m[4] }));
        }
        process.stdout.write(JSON.stringify(out));
        """)


def test_thinking_level_renders_as_its_own_radio_group(tmp_path):
    """radio 的 name 若照抄写死成 rotation_strategy，两组会被浏览器当成同一组互斥：
    选中思考档位会把轮换策略的选中状态清掉，保存时也少提交一个字段。"""
    out = _node(tmp_path, _settings_harness(), [
        ["thinking.default_thinking_level", "medium"],
        ["account_management.rotation_strategy", "failover"],
    ])
    thinking = out["thinking.default_thinking_level"]
    rotation = out["account_management.rotation_strategy"]

    assert [r["value"] for r in thinking] == ["off", "low", "medium", "high"]
    assert [r["value"] for r in thinking if r["checked"]] == ["medium"]
    assert {r["name"] for r in thinking} == {"default_thinking_level"}
    assert {r["name"] for r in rotation} == {"rotation_strategy"}
    assert [r["value"] for r in rotation if r["checked"]] == ["failover"]


def test_every_thinking_option_value_is_accepted_by_the_backend(tmp_path):
    from app.core.settings_overrides import THINKING_DEFAULT_LEVELS

    out = _node(tmp_path, _settings_harness(), [["thinking.default_thinking_level", "low"]])
    assert {r["value"] for r in out["thinking.default_thinking_level"]} == THINKING_DEFAULT_LEVELS


def test_thinking_option_labels_exist_in_every_language():
    """选项数组里的 labelKey 不在 test_settings_panel_labels 的解析范围里，单独守。"""
    i18n = (_ROOT / "static" / "app" / "i18n.js").read_text(encoding="utf-8")
    keys = re.findall(r"labelKey: '(settings\.thinkingLevel\.[a-z]+)'",
                      _SETTINGS_JS.read_text(encoding="utf-8"))
    assert len(keys) == 4
    blocks = re.split(r"^ {4}'[A-Za-z-]+': \{$", i18n, flags=re.M)[1:]
    assert len(blocks) == 5
    for block in blocks:
        for key in keys + ["playground.thinkingLevel.low", "playground.thinkingLevel.medium",
                           "playground.thinkingLevel.high"]:
            assert f"'{key}':" in block, key

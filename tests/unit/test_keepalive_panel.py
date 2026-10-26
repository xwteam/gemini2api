"""面板上的保活相关文案（v1.6.44）。

- 「浏览器保活」小标签与它的 title 提示：五个语言块都得有，t() 对未知键会回退成键名本身，
  漏一个就把 'accounts.keepaliveBrowser' 这种字面量直接显示给用户。
- 会话被打回登录页的账号现在对外报 expired（过去只有连挂 3 次才会出现）。状态徽章此前
  不认识 expired，在中文界面里直接显示英文原词、还是灰色（像「已禁用」）：要本地化、要醒目。
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "static" / "app"
_I18N = _STATIC / "i18n.js"
_UTILS = _STATIC / "utils.js"
_LANGS = ("zh-CN", "en-US", "ja-JP", "ko-KR", "zh-TW")

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")

NEW_KEYS = ("accounts.keepaliveBrowser", "accounts.keepaliveBrowserHint", "status.expired")


def _values_by_lang() -> dict:
    blocks: dict = {}
    current = None
    for line in _I18N.read_text(encoding="utf-8").splitlines():
        lang = re.match(r"^ {4}'([A-Za-z-]+)': \{$", line)
        if lang:
            current = lang.group(1)
            blocks[current] = {}
            continue
        if current is None:
            continue
        kv = re.match(r"^ +'([^']+)': '(.*)',?$", line)
        if kv:
            blocks[current][kv.group(1)] = kv.group(2)
    assert set(_LANGS) <= set(blocks), f"i18n.js 语言块解析异常: {sorted(blocks)}"
    return blocks


def test_new_keys_exist_in_every_language():
    blocks = _values_by_lang()
    missing = {lang: [k for k in NEW_KEYS if k not in blocks[lang]] for lang in _LANGS}
    missing = {lang: keys for lang, keys in missing.items() if keys}
    assert not missing, f"这些语言块缺少保活相关的 i18n 键: {missing}"


def test_new_values_are_real_translations():
    blocks = _values_by_lang()
    for lang in _LANGS:
        for key in NEW_KEYS:
            value = blocks[lang][key]
            assert value.strip() and value != key, f"{lang} 的 {key} 是空的或直接写了键名"
    # 中文简繁之外，各语言不该原样照抄简体中文
    for lang in ("en-US", "ja-JP", "ko-KR"):
        for key in NEW_KEYS:
            assert blocks[lang][key] != blocks["zh-CN"][key], f"{lang} 的 {key} 没翻译"


def test_keepalive_hint_says_the_server_does_not_rotate():
    hint = _values_by_lang()["zh-CN"]["accounts.keepaliveBrowserHint"]
    assert "插件" in hint and "轮换" in hint


def test_status_keys_are_identical_in_every_language():
    blocks = _values_by_lang()
    keys = {lang: {k for k in blocks[lang] if k.startswith("status.")} for lang in _LANGS}
    drift = {lang: sorted(keys[lang] ^ keys["zh-CN"]) for lang in _LANGS if keys[lang] != keys["zh-CN"]}
    assert not drift, f"status.* 键在各语言块之间漂移了: {drift}"


def _extract_function(source: str, name: str) -> str:
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
    raise AssertionError(f"{name} 的大括号没配对")


def _badges(statuses, tmp_path: Path) -> list:
    """把 utils.js 里真正的 getStatusBadge 切出来跑。"""
    fn = _extract_function(_UTILS.read_text(encoding="utf-8"), "getStatusBadge")
    script = tmp_path / "badge.mjs"
    script.write_text(textwrap.dedent("""
        function t(k) { return '<T:' + k + '>'; }
        function escapeHtml(s) { return String(s); }
        """) + fn + textwrap.dedent("""
        process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(getStatusBadge)));
        """), encoding="utf-8")
    proc = subprocess.run([_NODE, str(script), json.dumps(statuses)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@_needs_node
def test_expired_badge_is_localized_and_red(tmp_path):
    (badge,) = _badges(["expired"], tmp_path)
    assert "<T:status.expired>" in badge, "expired 必须走 i18n，不能把英文原词直接摆进中文界面"
    assert "badge-danger" in badge


@_needs_node
def test_existing_badges_are_unchanged(tmp_path):
    active, disabled, error, unknown = _badges(["active", "disabled", "error", "weird"], tmp_path)
    assert "<T:status.active>" in active and "badge-success" in active
    assert "<T:status.disabled>" in disabled and "badge-secondary" in disabled
    assert "<T:status.error>" in error and "badge-danger" in error
    assert ">weird<" in unknown and "badge-secondary" in unknown


@_needs_node
@pytest.mark.parametrize("name", ["app.js", "i18n.js", "utils.js"])
def test_panel_scripts_still_parse(name):
    proc = subprocess.run([_NODE, "--check", str(_STATIC / name)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

"""访问密钥页的 i18n 守卫。

仓里既有的 test_settings_panel_labels.py 只覆盖 `settings.*` 前缀，accessKeys.* 漏键
不会让它变红 —— 所以这里补一条同形状的守卫。t() 对未知键会回退成返回键名本身，
漏一个键的后果是面板上直接把 "accessKeys.usage" 这种字符串显示给用户。
"""

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"
_I18N = _STATIC / "app" / "i18n.js"
_JS = _STATIC / "app" / "access-keys.js"
_HTML = _STATIC / "components" / "section-access-keys.html"
_SIDEBAR = _STATIC / "components" / "sidebar.html"

_LANGS = ("zh-CN", "en-US", "ja-JP", "ko-KR", "zh-TW")


def _keys_by_lang(prefix: str) -> dict:
    blocks: dict = {}
    current = None
    for line in _I18N.read_text(encoding="utf-8").splitlines():
        lang = re.match(r"^ {4}'([A-Za-z-]+)': \{$", line)
        if lang:
            current = lang.group(1)
            blocks[current] = set()
            continue
        if current is None:
            continue
        key = re.match(rf"^ +'({re.escape(prefix)}[^']*)':", line)
        if key:
            blocks[current].add(key.group(1))
    assert set(_LANGS) <= set(blocks), f"i18n.js 语言块解析异常: {sorted(blocks)}"
    return blocks


def _referenced_keys() -> set:
    js = _JS.read_text(encoding="utf-8")
    # 直接 t('accessKeys.x')，以及经 STATE_I18N 这类映射表间接用到的裸字面量
    refs = set(re.findall(r"'(accessKeys\.[^']+)'", js))
    html = _HTML.read_text(encoding="utf-8")
    refs |= set(re.findall(r'data-i18n(?:-placeholder|-title)?="(accessKeys\.[^"]+)"', html))
    return refs


def test_access_keys_keys_are_identical_in_every_language():
    blocks = _keys_by_lang("accessKeys.")
    baseline = blocks["zh-CN"]
    assert baseline, "zh-CN 块里没有任何 accessKeys.* 键，解析格式可能变了"
    drift = {
        lang: {"missing": sorted(baseline - blocks[lang]), "extra": sorted(blocks[lang] - baseline)}
        for lang in _LANGS if blocks[lang] != baseline
    }
    assert not drift, f"5 个语言块的 accessKeys.* 键集合不一致: {drift}"


def test_every_referenced_key_exists_in_every_language():
    refs = _referenced_keys()
    assert refs, "access-keys.js / section-access-keys.html 里没解析到任何 accessKeys.* 引用"
    blocks = _keys_by_lang("accessKeys.")
    missing = {lang: sorted(refs - blocks[lang]) for lang in _LANGS if refs - blocks[lang]}
    assert not missing, f"这些语言块缺少已被引用的 i18n 键: {missing}"


def test_nav_entry_is_translated_in_every_language():
    blocks = _keys_by_lang("nav.accessKeys")
    missing = [lang for lang in _LANGS if "nav.accessKeys" not in blocks[lang]]
    assert not missing, f"侧边栏入口缺少翻译: {missing}"
    assert 'data-i18n="nav.accessKeys"' in _SIDEBAR.read_text(encoding="utf-8")


def test_sidebar_entry_points_at_the_section_id():
    """侧边栏的 data-section 必须与 section 的 id 字面相等，否则点了切不过去。"""
    sidebar = _SIDEBAR.read_text(encoding="utf-8")
    assert 'data-section="access-keys"' in sidebar
    assert 'href="#access-keys"' in sidebar
    assert 'id="access-keys"' in _HTML.read_text(encoding="utf-8")


def test_section_is_registered_in_the_component_loader():
    """片段不在 component-loader 的清单里就永远不会被插进 DOM，页签是空的。"""
    loader = (_STATIC / "app" / "component-loader.js").read_text(encoding="utf-8")
    assert "section-access-keys.html" in loader


def test_app_js_wires_the_section():
    """app.js 必须 import 并在 loadSectionData 里分派 —— 片段里的 <script> 标签
    是用 insertAdjacentHTML 插进去的，按 HTML 规范永不执行，靠它加载不了模块。"""
    app_js = (_STATIC / "app" / "app.js").read_text(encoding="utf-8")
    assert "./access-keys.js" in app_js
    assert "initAccessKeys()" in app_js
    assert "loadAccessKeys()" in app_js

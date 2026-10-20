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


def _values_by_lang(prefix: str) -> dict:
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
        kv = re.match(rf"^ +'({re.escape(prefix)}[^']*)': '(.*?)',?$", line)
        if kv:
            blocks[current][kv.group(1)] = kv.group(2)
    return blocks


def test_pending_state_is_never_confusable_with_the_enable_action():
    """「未激活」说的是"计时还没开始"，不能说成"没启用"。

    zh-TW 之前写的是 未啟用，而停用态是 已停用、操作按钮是 啟用：管理员看到 未啟用
    会以为密钥被关着，去点 啟用 —— 点了什么也不会变（它本来就是启用状态，只是还没被
    用过）。纯"五个标签互不相同"的断言看不见这种撞词。
    """
    blocks = _values_by_lang("accessKeys.")
    problems = {}
    for lang in _LANGS:
        labels = blocks.get(lang, {})
        pending = labels.get("accessKeys.statePending")
        enable = labels.get("accessKeys.enable")
        assert pending and enable, f"{lang} 缺少 statePending/enable"
        states = [labels.get(f"accessKeys.state{s}") for s in ("Valid", "Pending", "Disabled", "Expired", "Quota")]
        if len(set(states)) != len(states):
            problems[lang] = f"状态文案撞了: {states}"
        elif enable in pending:
            problems[lang] = f"statePending={pending!r} 里套着启用操作 {enable!r}"
    assert not problems, problems


def test_app_js_dispatches_the_exact_sidebar_section_id():
    """侧边栏的 data-section 与 loadSectionData 的 case 标签必须字面一致。

    只断言 "loadAccessKeys()" 这个字面量出现过是假守卫：把 case 写成 'access-key'
    （少个 s）照样全绿，而浏览器里页签会永远停在转圈的 loading 占位上。
    """
    app_js = (_STATIC / "app" / "app.js").read_text(encoding="utf-8")
    sidebar = _SIDEBAR.read_text(encoding="utf-8")
    sections = set(re.findall(r'data-section="([a-z-]+)"', sidebar))
    cases = set(re.findall(r"case '([a-z-]+)':", app_js))

    assert "access-keys" in sections
    assert "access-keys" in cases, f"loadSectionData 里没有 access-keys 分支: {sorted(cases)}"
    unknown = sorted(cases - sections)
    assert not unknown, f"这些 case 标签在侧边栏里没有对应的 data-section（拼错了）: {unknown}"

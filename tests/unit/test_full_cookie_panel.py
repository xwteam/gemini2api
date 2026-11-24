"""面板「更新 Cookie」能粘贴整段 Cookie（v1.6.53 规格 A2）的静态守卫。

谷歌 11-20 改版后只有 PSID / PSIDTS 只能以访客身份打开 Gemini：弹窗要能收整段 `Cookie:` 请求头，
以 cookie_header 字段交给 PUT /admin/accounts/{id}/cookies，文案五种语言都要有。t() 对未知键回退
成键名本身，漏一个键面板上就直接显示 "accounts.fullCookieHint" 这种字符串。
"""

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"
_I18N = _STATIC / "app" / "i18n.js"
_APP = _STATIC / "app" / "app.js"
_HTML = _STATIC / "components" / "section-accounts.html"

_LANGS = ("zh-CN", "en-US", "ja-JP", "ko-KR", "zh-TW")
_NEW_KEYS = {
    "accounts.fullCookieLabel",
    "accounts.fullCookiePlaceholder",
    "accounts.fullCookieHint",
    "accounts.singleValueHint",
    "accounts.fullCookieNoPsid",
    "accounts.needPsid",
}


def _keys_by_lang() -> dict:
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
        kv = re.match(r"^ +'(accounts\.[^']*)': '(.*)',$", line)
        if kv:
            blocks[current][kv.group(1)] = kv.group(2)
    assert set(_LANGS) <= set(blocks), f"i18n.js 语言块解析异常: {sorted(blocks)}"
    return blocks


def _app_js() -> str:
    # app.js 里有几个 NUL 字节（图片占位标记），按字节读再解码
    return _APP.read_bytes().decode("utf-8")


def test_new_keys_exist_in_every_language():
    blocks = _keys_by_lang()
    missing = {lang: sorted(_NEW_KEYS - set(blocks[lang])) for lang in _LANGS if _NEW_KEYS - set(blocks[lang])}
    assert not missing, f"缺少翻译: {missing}"


def test_every_referenced_accounts_key_exists():
    refs = set(re.findall(r"t\('(accounts\.[^']+)'\)", _app_js()))
    refs |= set(re.findall(r'data-i18n(?:-placeholder|-title)?="(accounts\.[^"]+)"',
                           _HTML.read_text(encoding="utf-8")))
    assert _NEW_KEYS <= refs, f"新键没被引用: {sorted(_NEW_KEYS - refs)}"
    blocks = _keys_by_lang()
    missing = {lang: sorted(refs - set(blocks[lang])) for lang in _LANGS if refs - set(blocks[lang])}
    assert not missing, f"这些语言块缺少已被引用的 i18n 键: {missing}"


def test_hint_mentions_osid_and_plugin_version_in_every_language():
    blocks = _keys_by_lang()
    for lang in _LANGS:
        hint = blocks[lang]["accounts.fullCookieHint"]
        assert "OSID" in hint and "1.4.0" in hint, lang


def test_modal_has_the_full_cookie_textarea_and_psid_is_no_longer_mandatory():
    html = _HTML.read_text(encoding="utf-8")
    assert 'id="update-cookie-header"' in html
    update = html[html.index('id="updateCookieModal"'):]
    psid_input = re.search(r'<input[^>]*id="update-psid"[^>]*>', update).group(0)
    assert "required" not in psid_input, "粘贴整段 Cookie 时 PSID 输入框可以留空"


def test_submit_sends_the_pasted_header_as_cookie_header():
    js = _app_js()
    body = js[js.index("async function submitUpdateCookie"):]
    body = body[:body.index("\n}\n")]
    assert "update-cookie-header" in body
    assert "extra.cookie_header = header" in body
    assert "{ psid, psidts, ...extra }" in body
    assert "_cookieFromHeader(header, '__Secure-1PSID')" in body

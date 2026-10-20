"""编辑面板的真实往返行为（openPanel → submitPanel），用 node 跑真正的模块代码。

这里守的是两条只在"编辑已经用过的密钥"时才暴露的坑：
1. 有效天数的密钥首次使用后，后端会把算出来的 expires_at 也填上。两个框都回填的话，
   submitPanel 的互斥校验会把**每一次**保存都拦掉——改名、改额度、改绑定全做不了，
   而且报错还怪管理员填了两个框（那两个框是面板自己填的）。
2. <input type="datetime-local"> 的值是本地墙上时间。把后端的 UTC 瞬间直接截 16 个
   字符塞进去，再用 new Date(...).toISOString() 读回来，一次"什么都没改"的保存就能
   把有效期挪掉一个时区偏移，而且每保存一次挪一次。
"""

import json
import re
import shutil
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "static"
_AK_JS = _STATIC / "app" / "access-keys.js"
_UTILS_JS = _STATIC / "app" / "utils.js"

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")

_FUNCS = (
    "escapeAttr", "findKey", "renderChecklist", "checklistValues",
    "toLocalInputValue", "numberInputValue", "openPanel", "closePanel",
    "readNumber", "readExpiresAt", "submitPanel",
)

_INPUT_IDS = (
    "akk-name", "akk-count", "akk-request-limit", "akk-duration-days", "akk-expires-at",
)


def _extract_function(source: str, name: str) -> str:
    head = source.index(f"function {name}(")
    # 把 `async ` 前缀一起带上
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


def _harness() -> str:
    src = _AK_JS.read_text(encoding="utf-8")
    utils = _UTILS_JS.read_text(encoding="utf-8")
    pieces = [_extract_function(src, name) for name in _FUNCS]
    pieces.append(_extract_function(utils, "escapeHtml"))
    assert "akk-add-panel" in src, "编辑面板的挂载点变了，用例的假 DOM 也要跟着改"

    return (
        textwrap.dedent("""
        const _ARGV = JSON.parse(process.argv[2]);
        function t(k) { return k; }

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

        function makeInput() { return { value: '', disabled: false }; }
        function makePanel() { return { style: { display: 'none' } }; }

        function makeChecklist() {
            return {
                _html: '', _boxes: [],
                set innerHTML(v) {
                    this._html = String(v);
                    // 从真实渲染产物反推勾选状态，顺带守住"编辑时已绑定的项要回勾"
                    this._boxes = [...this._html.matchAll(
                        /<input type="checkbox" value="([^"]*)"( checked)?>/g)]
                        .map(m => ({ value: m[1].replace(/&quot;/g, '"'), checked: !!m[2] }));
                },
                get innerHTML() { return this._html; },
                querySelectorAll() { return this._boxes; },
            };
        }

        const _byId = {};
        for (const id of _ARGV.inputIds) _byId[id] = makeInput();
        _byId['akk-accounts-list'] = makeChecklist();
        _byId['akk-models-list'] = makeChecklist();
        _byId['akk-add-panel'] = makePanel();

        const document = {
            createElement: makeEl,
            getElementById(id) { return _byId[id] || null; },
        };

        const _requests = [];
        const _toasts = [];
        async function apiCall(method, path, body) {
            _requests.push({ method, path, body: body === undefined ? null : body });
            return { keys: [], accounts: [], models: [] };
        }
        function showToast(msg, kind) { _toasts.push({ msg, kind }); }
        async function loadAccessKeys() { return null; }

        let keysData = _ARGV.keys || [];
        let optionsData = _ARGV.options || { accounts: [], models: [] };
        let editingId = null;
        """)
        + "\n".join(pieces)
        + textwrap.dedent("""

        async function main() {
            const target = _ARGV.editId === null ? null : findKey(_ARGV.editId);
            openPanel(target);
            const prefill = {};
            for (const id of _ARGV.inputIds) prefill[id] = _byId[id].value;
            const checked = {
                accounts: checklistValues('akk-accounts-list'),
                models: checklistValues('akk-models-list'),
            };
            for (const [id, value] of Object.entries(_ARGV.overrides || {})) {
                _byId[id].value = value;
            }
            if (_ARGV.submit) await submitPanel();
            return {
                prefill, checked, requests: _requests, toasts: _toasts,
                panelDisplay: _byId['akk-add-panel'].style.display,
            };
        }
        main().then(out => process.stdout.write(JSON.stringify(out)));
        """)
    )


def _run(tmp_path: Path, *, keys, edit_id, submit=True, overrides=None, options=None, tz=None):
    script = tmp_path / "akk-panel.mjs"
    script.write_text(_harness(), encoding="utf-8")
    payload = {
        "keys": keys, "editId": edit_id, "submit": submit,
        "overrides": overrides or {}, "inputIds": list(_INPUT_IDS),
        "options": options or {"accounts": [], "models": []},
    }
    env = None
    if tz:
        import os
        env = dict(os.environ, TZ=tz)
    proc = subprocess.run(
        [_NODE, str(script), json.dumps(payload)],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _key(**kw) -> dict:
    base = {
        "id": 1, "key": "sk-" + "a" * 32, "name": "alice", "display_name": "alice",
        "enabled": True, "state": "valid", "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": None, "duration_days": None, "activated_at": None,
        "request_limit": None, "request_count": 0,
        "bound_account_ids": None, "allowed_models": None, "last_used_at": None,
    }
    base.update(kw)
    return base


@_needs_node
def test_an_activated_duration_key_can_still_be_edited(tmp_path):
    """首次使用之后 duration_days 与 expires_at 同时有值 —— 这是后端的正常状态，
    不能让它把密钥变成"只能停用/删除"的死状态。"""
    key = _key(id=2, name="bob", duration_days=7,
               activated_at="2026-10-20T13:09:28+00:00",
               expires_at="2026-10-27T13:09:28+00:00")
    out = _run(tmp_path, keys=[key], edit_id=2, tz="Asia/Shanghai")

    assert [x["kind"] for x in out["toasts"]] == ["success"], f"保存被拦掉了: {out['toasts']}"
    patches = [r for r in out["requests"] if r["method"] == "PATCH"]
    assert len(patches) == 1, f"一次 PATCH 都没发出去: {out['requests']}"
    assert patches[0]["path"] == "/admin/access-keys/2"
    assert patches[0]["body"]["duration_days"] == 7
    assert "expires_at" in patches[0]["body"]["clear"], (
        "有效天数的密钥保存时应让后端按 activated_at 重算绝对过期时间"
    )
    assert out["panelDisplay"] == "none", "保存成功后面板应当关掉"


@_needs_node
def test_duration_days_is_prefilled_as_a_plain_integer(tmp_path):
    key = _key(id=2, duration_days=7.0, expires_at="2026-10-27T13:09:28+00:00")
    out = _run(tmp_path, keys=[key], edit_id=2, submit=False)
    assert out["prefill"]["akk-duration-days"] == "7"
    assert out["prefill"]["akk-expires-at"] == "", "两个框都填 = 保存永远被互斥校验拦掉"


@_needs_node
@pytest.mark.parametrize("tz", ["Asia/Shanghai", "America/New_York", "UTC"])
def test_absolute_expiry_survives_a_no_op_save(tmp_path, tz):
    """只改名字的一次保存，绝不能把有效期挪走（每保存一次挪一次，还会累积）。"""
    stored = "2026-10-19T13:09:28+00:00"
    key = _key(id=4, expires_at=stored)
    out = _run(tmp_path, keys=[key], edit_id=4, tz=tz)

    patches = [r for r in out["requests"] if r["method"] == "PATCH"]
    assert len(patches) == 1, out["requests"]
    sent = patches[0]["body"]["expires_at"]
    drift = (datetime.fromisoformat(sent.replace("Z", "+00:00"))
             - datetime.fromisoformat(stored)).total_seconds()
    assert abs(drift) <= 60, f"TZ={tz} 下一次空保存把有效期挪了 {drift / 3600:.2f} 小时"
    # 回填进 datetime-local 的那串必须是本地墙上时间（不是 UTC 的钟面）
    shown = out["prefill"]["akk-expires-at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", shown), shown
    local = datetime.fromisoformat(stored).astimezone()
    if tz == "UTC":
        assert shown == "2026-10-19T13:09"
    assert len(shown) == 16 and local is not None


@_needs_node
def test_filling_both_validity_fields_by_hand_is_still_rejected(tmp_path):
    """互斥校验本身不能被拆掉：管理员手填两个框时仍要拦住、且一个请求都不发。"""
    key = _key(id=4, expires_at="2026-10-19T13:09:28+00:00")
    out = _run(tmp_path, keys=[key], edit_id=4,
               overrides={"akk-duration-days": "3"}, tz="UTC")
    assert out["requests"] == []
    assert [tz["kind"] for tz in out["toasts"]] == ["error"]
    assert out["toasts"][0]["msg"] == "accessKeys.validityConflict"


@_needs_node
def test_creating_a_key_sends_the_form_values(tmp_path):
    """零回归：新建路径（editingId=null）原样把表单值发出去。"""
    out = _run(tmp_path, keys=[], edit_id=None,
               overrides={"akk-name": "carol", "akk-count": "3",
                          "akk-request-limit": "100", "akk-duration-days": "7"},
               tz="UTC")
    posts = [r for r in out["requests"] if r["method"] == "POST"]
    assert len(posts) == 1, out["requests"]
    body = posts[0]["body"]
    assert (body["name"], body["count"], body["request_limit"], body["duration_days"]) \
        == ("carol", 3, 100, 7)
    assert body["expires_at"] is None


@_needs_node
def test_editing_prefills_the_bound_accounts_and_models(tmp_path):
    """绑定项必须回勾，否则一次"只改名字"的保存会把绑定悄悄清空。"""
    key = _key(id=2, bound_account_ids=["account-1"], allowed_models=["gemini-flash"])
    out = _run(tmp_path, keys=[key], edit_id=2, submit=True,
               options={"accounts": [{"id": "account-0", "label": "a0"},
                                     {"id": "account-1", "label": "a1"}],
                        "models": ["gemini-pro", "gemini-flash"]})
    assert out["checked"] == {"accounts": ["account-1"], "models": ["gemini-flash"]}
    body = [r for r in out["requests"] if r["method"] == "PATCH"][0]["body"]
    assert body["bound_account_ids"] == ["account-1"]
    assert body["allowed_models"] == ["gemini-flash"]

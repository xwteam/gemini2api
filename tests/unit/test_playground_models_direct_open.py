"""直接打开 / 刷新「模型测试」页（#playground）时模型下拉框要能加载出来（v1.6.57）。

v1.6.56 及以前模型列表只在仪表盘 loadDashboard 里填，直接落在 #playground 的人看到的是
一直「加载中...」的下拉框。现在切到 playground 时若下拉框还没有真实选项就拉一次；
已经有列表时不再重拉，仪表盘刷新列表时也保住当前选中的模型。

做法同 test_playground_error_frame_render.py：把 app.js 里的函数原样切出来丢给 node，配极小的假 DOM。
"""
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "static" / "app" / "app.js"
_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node 不可用，跳过前端行为测试")


def _src() -> str:
    return _APP.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    head = re.search(rf"(async\s+)?function {name}\(", source).start()
    depth, i = 0, source.index("{", head)
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[head:i + 1]
        i += 1
    raise AssertionError(f"{name} 的大括号没配对")


def test_switching_to_playground_loads_models():
    src = _src()
    loader = _extract_function(src, "loadSectionData")
    assert re.search(r"case 'playground':\s*\n\s*await ensurePlaygroundModels\(\);", loader)


_HARNESS = textwrap.dedent("""
    const calls = [];
    let status = %(status)s;
    function t(k) { return k; }
    function escapeAttr(s) { return String(s); }
    function escapeHtml(s) { return String(s); }
    async function apiCall(method, path) { calls.push(method + ' ' + path); if (status === 'FAIL') throw new Error('boom'); return status; }
    function makeSelect(options, value) {
      const sel = { _opts: options.map(([v, txt]) => ({ value: v, textContent: txt })), value };
      Object.defineProperty(sel, 'innerHTML', {
        set(html) {
          sel._opts = [...html.matchAll(/<option value="([^"]*)">([^<]*)<\\/option>/g)].map(m => ({ value: m[1], textContent: m[2] }));
          sel.value = sel._opts.length ? sel._opts[0].value : '';
        }
      });
      sel.querySelector = q => (q === 'option[value]:not([value=""])' ? (sel._opts.find(o => o.value !== '') || null) : null);
      return sel;
    }
    const select = makeSelect(%(options)s, %(value)s);
    const document = { getElementById: id => (id === 'pg-model' ? select : null) };
    %(fns)s
    (async () => {
      %(body)s
      console.log(JSON.stringify({ calls, options: select._opts.map(o => o.value), value: select.value }));
    })();
""")


def _run(options, value, body, status=None):
    src = _src()
    fns = "\n".join(_extract_function(src, n) for n in ("updatePlaygroundModels", "ensurePlaygroundModels"))
    status = status if status is not None else {"models": ["gemini-auto", "gemini-4-hydrogen", "gemini-4-neon"], "accounts": []}
    code = _HARNESS % {"status": json.dumps(status), "options": json.dumps(options),
                       "value": json.dumps(value), "fns": fns, "body": body}
    out = subprocess.run([_NODE, "-e", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@_needs_node
def test_direct_open_fills_the_placeholder_select():
    r = _run([["", "加载中..."]], "", "await ensurePlaygroundModels();")
    assert r["calls"] == ["GET /admin/status"]
    assert r["options"] == ["gemini-auto", "gemini-4-hydrogen", "gemini-4-neon"]


@_needs_node
def test_already_loaded_select_is_left_alone():
    r = _run([["gemini-auto", "gemini-auto"], ["gemini-4-neon", "gemini-4-neon"]], "gemini-4-neon",
             "await ensurePlaygroundModels();")
    assert r["calls"] == []
    assert r["value"] == "gemini-4-neon"


@_needs_node
def test_dashboard_refresh_keeps_the_chosen_model():
    r = _run([["gemini-auto", "gemini-auto"], ["gemini-4-neon", "gemini-4-neon"]], "gemini-4-neon",
             "updatePlaygroundModels(new Set(['gemini-auto', 'gemini-4-hydrogen', 'gemini-4-neon']));")
    assert r["value"] == "gemini-4-neon"


@_needs_node
def test_chosen_model_gone_falls_back_to_first():
    r = _run([["gemini-4-carbon", "gemini-4-carbon"]], "gemini-4-carbon",
             "updatePlaygroundModels(new Set(['gemini-auto', 'gemini-4-hydrogen']));")
    assert r["value"] == "gemini-auto"


@_needs_node
def test_old_backend_without_pool_models_uses_account_union():
    status = {"accounts": [{"models": ["gemini-auto"]}, {"models": ["gemini-auto", "gemini-4-neon"]}]}
    r = _run([["", "加载中..."]], "", "await ensurePlaygroundModels();", status=status)
    assert r["options"] == ["gemini-auto", "gemini-4-neon"]


@_needs_node
def test_fetch_failure_replaces_the_loading_placeholder():
    r = _run([["", "加载中..."]], "", "try { await ensurePlaygroundModels(); } catch (e) { calls.push('threw'); }",
             status="FAIL")
    assert r["calls"] == ["GET /admin/status", "threw"]
    assert r["options"] == [""]           # 只剩「无可用模型」占位（value=""），下次进页面会再拉

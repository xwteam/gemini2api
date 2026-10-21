"""v1.6.43 对外模型阵容：gemini-pro / gemini-flash / gemini-flash-lite / gemini-argon。

用户原话：「gemini-argon 保留，gemini-flash-lite，gemini-flash 和 gemini-pro 再对应网页的
模型自动做映射就可以了，thinking 的模型就不需要了」。这里钉三件事：
  1. 真实账号形态（心跳给出 3.1 Pro / 3.8 Flash / 3.5 Flash-Lite / 4 Argon）下，四个列表
     端点和面板模型测试页的下拉框都**恰好**列这 4 个，各自映射到心跳发现的网页模型；
  2. gemini-flash-thinking 及其旧别名、内部名**不在任何列表里**，但**照样能调通**
     （隐藏别名 → gemini-flash），绝不能让现有客户端突然 400；
  3. 心跳铸名的保留词里仍有 "thinking"，不会铸出一个"看着像官方思考模型"的新名字。
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import GEMINI_MODELS, MODEL_HEADER_KEY, PUBLIC_MODELS

_AUTH = {"Authorization": "Bearer sk-test-key"}
_ROOT = Path(__file__).resolve().parents[2]
_NODE = shutil.which("node")

EXPECTED = ["gemini-pro", "gemini-flash", "gemini-flash-lite", "gemini-argon"]
HIDDEN = [
    "gemini-flash-thinking", "gemini-2.5-flash-thinking", "gemini-2.0-flash-thinking",
    "gemini-3-flash-thinking", "gemini-3-flash-thinking-plus", "gemini-3-flash-thinking-advanced",
]

# 真机心跳里的 id（cap 2 账号）
PRO_ID, FLASH_ID, LITE_ID, ARGON_ID = (
    "e6fa609c3fa255c0", "56fdd199312815e2", "8c46e95b1a07cecc", "95a4c0abcba24364")


def _entry(model_id, display, number, category=None):
    e = [None] * 20
    e[0], e[11], e[17] = model_id, display, number
    if category:
        e[1] = e[10] = category
    return e


def _status_raw(*entries):
    body = [None] * 16
    body[15] = list(entries)
    return "[[" + json.dumps(["wrb.fr", "otAQ7b", json.dumps(body)])[1:-1] + "]]"


def _real_account_client(*extra):
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    c._family_model = {}
    c._available_models = []
    c._discovered_models = {}
    c._healthy = True
    c._parse_models_from_status(_status_raw(
        _entry(PRO_ID, "3.1 Pro", 3),
        _entry(FLASH_ID, "3.8 Flash", 1),
        _entry(LITE_ID, "3.5 Flash-Lite", 6),
        _entry(ARGON_ID, "4 Argon", 8, category="Argon"),
        *extra,
    ))
    return c


@pytest.fixture
def real_pool(monkeypatch):
    """把全局账号池换成"一个真实形态账号"，各列表端点走真实的 AccountPool.models。"""
    from app.core import account_pool as ap

    acct = ap.Account(id="acc1", psid="p", psidts="t")
    acct.client = _real_account_client()
    monkeypatch.setattr(ap.account_pool, "_accounts", [acct])
    return acct


# ---------------------------------------------------------------------------
# 1. 恰好 4 个，各自映射到心跳发现的网页模型
# ---------------------------------------------------------------------------

def test_the_pool_lists_exactly_the_four_models(real_pool):
    from app.core.account_pool import account_pool

    assert account_pool.models == EXPECTED


@pytest.mark.parametrize("public,model_id", [
    ("gemini-pro", PRO_ID),
    ("gemini-flash", FLASH_ID),
    ("gemini-flash-lite", LITE_ID),
    ("gemini-argon", ARGON_ID),
])
def test_each_public_name_maps_to_the_web_model_the_heartbeat_reported(public, model_id):
    """映射必须落到发给 Google 的模型头里（id 就是心跳给的那个），不是只进了某个字典。"""
    c = _real_account_client()
    resolved = gc._resolve_model(public, c._family_model)
    assert resolved in c._model_table()
    header = json.loads(gc._build_model_header(resolved, c._model_table())[MODEL_HEADER_KEY])
    assert header[4] == model_id


def _gemini_names(names):
    return [n for n in names if n.startswith("gemini-")]


def test_v1_models_lists_exactly_the_four(gem_client, real_pool):
    ids = [m["id"] for m in gem_client.get("/v1/models", headers=_AUTH).json()["data"]]
    assert _gemini_names(ids) == EXPECTED


def test_claude_models_lists_exactly_the_four(gem_client, real_pool):
    ids = [m["id"] for m in gem_client.get("/claude/v1/models", headers=_AUTH).json()["data"]]
    assert _gemini_names(ids) == EXPECTED


def test_v1beta_models_lists_exactly_the_four(gem_client, real_pool):
    names = [m["name"] for m in gem_client.get("/v1beta/models", headers=_AUTH).json()["models"]]
    assert names == [f"models/{m}" for m in EXPECTED]


def test_admin_status_feeds_exactly_the_four_to_the_panel(gem_client, real_pool):
    """面板模型测试页的下拉框只读 /admin/status 的 accounts[].models。"""
    status = gem_client.get("/admin/status", headers=_AUTH).json()
    assert status["accounts"][0]["models"] == EXPECTED
    assert status["accounts"][0]["models_count"] == 4


def _extract_function(source: str, name: str) -> str:
    head = source.index(f"function {name}(")
    depth, i = 0, source.index("{", head)
    while i < len(source):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return source[head:i + 1]
        i += 1
    raise AssertionError(f"{name} 的大括号没配对")


@pytest.mark.skipif(_NODE is None, reason="node 不可用")
def test_playground_dropdown_shows_exactly_the_four(gem_client, real_pool, tmp_path):
    """把 app.js 里真正在跑的 updatePlaygroundModels 切出来，喂 /admin/status 的真实输出。"""
    status = gem_client.get("/admin/status", headers=_AUTH).json()
    models = sorted({m for a in status["accounts"] for m in a["models"]})
    src = (_ROOT / "static" / "app" / "app.js").read_text(encoding="utf-8")
    script = tmp_path / "pg-models.mjs"
    script.write_text(textwrap.dedent("""
        const _el = { innerHTML: '' };
        const document = { getElementById: () => _el };
        const escapeAttr = s => String(s), escapeHtml = s => String(s), t = k => k;
        """) + _extract_function(src, "updatePlaygroundModels") + textwrap.dedent("""
        updatePlaygroundModels(new Set(JSON.parse(process.argv[2])));
        const vals = [..._el.innerHTML.matchAll(/<option value="([^"]*)">/g)].map(m => m[1]);
        process.stdout.write(JSON.stringify(vals));
        """), encoding="utf-8")
    out = subprocess.run([_NODE, str(script), json.dumps(models)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert sorted(json.loads(out.stdout)) == sorted(EXPECTED)
    assert not any("thinking" in v for v in json.loads(out.stdout))


# ---------------------------------------------------------------------------
# 2. flash-thinking：不列出，但照样能调通
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", HIDDEN)
def test_hidden_alias_resolves_to_this_accounts_flash(name):
    c = _real_account_client()
    resolved = gc._resolve_model(name, c._family_model)
    assert resolved == c._family_model["flash"] == "gemini-3-flash-advanced"
    # 过得了账号的路由闸门（generate/_send_request 的 `resolved not in _model_table()`）
    assert resolved in c._model_table()


@pytest.mark.parametrize("name", HIDDEN)
def test_hidden_alias_is_in_no_list(gem_client, real_pool, name):
    from app.core.account_pool import account_pool

    assert name not in account_pool.models
    assert name not in json.dumps(gem_client.get("/v1/models", headers=_AUTH).json())
    assert name not in json.dumps(gem_client.get("/claude/v1/models", headers=_AUTH).json())
    assert name not in json.dumps(gem_client.get("/v1beta/models", headers=_AUTH).json())


def test_flash_thinking_is_no_longer_a_family():
    assert "gemini-flash-thinking" not in PUBLIC_MODELS
    assert "flash-thinking" not in gc._BASE_FAMILIES
    assert "flash-thinking" not in gc._FAMILY_DEFAULT
    assert not any(info["family"] == "flash-thinking" for info in GEMINI_MODELS.values())
    # 同档回填不再补出 flash-thinking
    assert "flash-thinking" not in _real_account_client()._family_model


def _fake_generate(captured):
    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                  account_id=None, extended_thinking=False):
        captured.append(model)
        return {"text": "ok", "images": [], "conversation_id": "", "thoughts": ""}
    return gen


@pytest.mark.parametrize("name", HIDDEN)
def test_hidden_alias_still_succeeds_on_chat_completions(gem_client, real_pool, monkeypatch, name):
    """openai/responses 有一道"不是 Gemini 模型就当第三方"的闸门：别名漏掉的话这里是 400。"""
    import app.routers.openai as oai
    captured = []
    monkeypatch.setattr(oai.gemini_client, "generate", _fake_generate(captured))
    r = gem_client.post("/v1/chat/completions", json={
        "model": name, "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "ok"
    assert captured == [name]


@pytest.mark.parametrize("name", HIDDEN)
def test_hidden_alias_still_succeeds_on_responses(gem_client, real_pool, monkeypatch, name):
    import app.routers.responses as rp
    captured = []
    monkeypatch.setattr(rp.gemini_client, "generate", _fake_generate(captured))
    r = gem_client.post("/v1/responses", json={"model": name, "input": "hi"}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert captured == [name]


def test_hidden_alias_still_succeeds_on_messages_and_native(gem_client, real_pool, monkeypatch):
    import app.routers.claude as cl
    import app.routers.gemini as ge
    captured = []
    monkeypatch.setattr(cl.gemini_client, "generate", _fake_generate(captured))
    monkeypatch.setattr(ge.gemini_client, "generate", _fake_generate(captured))
    r1 = gem_client.post("/v1/messages", json={
        "model": "gemini-flash-thinking", "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
    r2 = gem_client.post("/v1beta/models/gemini-flash-thinking:generateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}]}, headers=_AUTH)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text


def test_historical_usage_under_the_old_name_is_priced_as_flash():
    from app.core.token_pricing import DEFAULT_TOKEN_PRICES, price_table_name

    assert "gemini-flash-thinking" not in DEFAULT_TOKEN_PRICES
    for name in HIDDEN:
        assert price_table_name(name) == "gemini-flash"


# ---------------------------------------------------------------------------
# 3. "thinking" 仍是铸名保留词
# ---------------------------------------------------------------------------

def test_thinking_stays_a_reserved_word():
    assert "thinking" in gc._DISCOVER_RESERVED_WORDS


@pytest.mark.parametrize("category,display", [
    ("Nova", "Thinking 5"),          # 铸名 gemini-thinking-5
    ("Flash Thinking", "9 Turbo"),   # family flash-thinking（已下线的旧 family）
    ("Deep Thinking", "Deep 2"),     # family 含保留词
])
def test_heartbeat_cannot_mint_a_thinking_model(category, display):
    c = _real_account_client(_entry("0123456789abcdef", display, 9, category=category))
    assert set(c._family_model) == {"pro", "flash", "flash-lite", "argon"}
    assert not any("thinking" in n for n in c._public_model_names())

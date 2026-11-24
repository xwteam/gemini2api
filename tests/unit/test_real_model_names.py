"""v1.6.54：模型列表用网页上的真实名字，跟着网站自动更新；按账号实时（规格 SPEC2 R1–R7）。

用户原话：「不如直接用真实模型名字，让大家看到是什么模型，就是要想办法怎么让模型随网站更新。」
追加：「最好根据账号实时获取，有的不是 pro 账号，可能模型不一样。」

fixture 照 §0 的线上实测（北京 2026-11-24 东京，三个账号完全一致）：otAQ7b body[15] 的 4 条，
字段下标是条目内的。旧形状（11-24 前网页叫 "4 Argon"，名字在 [11]）也要继续能解析。
"""

import asyncio
import json
import logging

import pytest

from app.core import gemini_client as gc
from app.core import model_names
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.gemini_client import GEMINI_MODELS, MODEL_HEADER_KEY, PUBLIC_MODELS

_AUTH = {"Authorization": "Bearer sk-test-key"}

AUTO_ID, HYDROGEN_ID, NEON_ID, CARBON_ID = (
    "8c46e95b1a07cecc", "56fdd199312815e2", "e6fa609c3fa255c0", "95a4c0abcba24364")
# 免费账号（基础版）的 id：都在写死表的 capacity 1 行上
FREE_LITE_ID, FREE_FLASH_ID, FREE_PRO_ID = (
    "cf41b0e0dd7d53e5", "fbb127bbb056c959", "9d8ca3786ebdfbea")

LIVE_NAMES = ["gemini-auto", "gemini-4-hydrogen", "gemini-4-neon", "gemini-4-carbon"]


def live_entry(model_id, category, positioning, name, number, *, f12=None) -> list:
    """§0 的条目形状：[0] id，[1]/[10] 类别，[11] 定位说明，[12]（通常 = [19]）/ [19] 真实名字，[17] 编号。"""
    e = [None] * 20
    e[0] = model_id
    e[1] = e[10] = category
    e[11] = positioning
    e[12] = name if f12 is None else f12
    e[19] = name
    e[17] = number
    return e


def AUTO():
    return live_entry(AUTO_ID, "Auto", "Auto", "Auto", 6, f12="Adapts to your needs")


def HYDROGEN():
    return live_entry(HYDROGEN_ID, "4 Hydrogen", "Everyday help", "4 Hydrogen", 1)


def NEON(name="4 Neon"):
    e = live_entry(NEON_ID, "Neon", "Deeper analysis", name, 3)
    e[6] = ["9d8ca3786ebdfbea", "95a4c0abcba24364", "797f3d0293f288ad"]
    e[8] = e[16] = "Neon4p0"
    return e


def CARBON():
    return live_entry(CARBON_ID, "Carbon", "Code & complex work", "4 Carbon", 8)


def OLD_ARGON():
    """11-24 前的形状：名字在 [11]（[19] 也是），类别 "Argon"，[2]/[12] 是一句描述。"""
    return [
        CARBON_ID, "Argon", "Complex tasks", [1, 2, 3], 2, None, None, True,
        "Argon4p0", 4, "Argon", "4 Argon", "Complex tasks", None, None, True,
        "Argon4p0", 8, ["https://example.invalid/icon.png", True], "4 Argon",
    ]


def free_entry(model_id, name, number):
    e = [None] * 20
    e[0], e[19], e[17] = model_id, name, number
    return e


def FREE_ENTRIES():
    """一个免费账号：同 family 不同 id、不同名字（Auto 同名不同 id）。"""
    return [free_entry(FREE_LITE_ID, "Auto", 6), free_entry(FREE_FLASH_ID, "Fast", 1),
            free_entry(FREE_PRO_ID, "3 Pro", 3)]


def status_raw(*entries) -> str:
    body = [None] * 16
    body[15] = list(entries)
    return "[[" + json.dumps(["wrb.fr", "otAQ7b", json.dumps(body)])[1:-1] + "]]"


def client_with(*entries) -> gc.GeminiWebClient:
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    c._family_model = {}
    c._available_models = []
    c._discovered_models = {}
    c._healthy = True
    c._heal_lock = asyncio.Lock()
    if entries:
        c._parse_models_from_status(status_raw(*entries))
    return c


def live_client():
    return client_with(AUTO(), HYDROGEN(), NEON(), CARBON())


def free_client():
    return client_with(*FREE_ENTRIES())


def sent_id(client, model):
    """这个账号会把 model 以哪个 model id 发给谷歌（None = 这个账号没有，会抛 ModelUnavailable）。"""
    resolved = client._route_model(model)
    if resolved is None:
        return None
    table = client._model_table()
    header = json.loads(gc._build_model_header(resolved, table)[MODEL_HEADER_KEY])
    return header[4]


def make_pool(*clients, statuses=None) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"p{i}", psidts="", label=f"a{i}",
                status=(statuses or {}).get(i, AccountStatus.ACTIVE), client=c)
        for i, c in enumerate(clients)]
    pool._max_concurrent = 8
    pool._acquire_timeout = 1.0
    pool._robin_index = len(clients) - 1        # 第一个选中 account-0
    return pool


# ---------------------------------------------------------------------------
# R1 列出的名字 = 网页真实名字
# ---------------------------------------------------------------------------

def test_the_live_heartbeat_lists_the_real_web_names_in_heartbeat_order():
    c = live_client()

    assert c._available_models == LIVE_NAMES
    assert c._public_model_names() == LIVE_NAMES
    # 基础 family 的识别仍按 id 表（不变）
    assert c._family_model["pro"] == "gemini-3-pro-advanced"
    assert c._family_model["flash"] == "gemini-3-flash-advanced"
    assert c._family_model["flash-lite"] == "gemini-3-flash-lite-advanced"
    # 非基础 family 用版本无关的类别名
    assert c._family_model["carbon"] == "gemini-4-carbon"
    assert c._discovered_models["gemini-4-carbon"]["id"] == CARBON_ID


def test_the_name_comes_from_field_19_not_the_positioning_text_in_11():
    """§0 的事故：先读 [11] 时 Carbon 被铸成 gemini-code-complex-work。"""
    c = live_client()

    assert "gemini-code-complex-work" not in c._available_models
    assert "gemini-everyday-help" not in c._available_models
    assert gc._entry_real_name(CARBON()) == "4 Carbon"
    assert gc._entry_real_name(AUTO()) == "Auto"


@pytest.mark.parametrize("fields,expected", [
    ({19: "4 Neon", 12: "Neon X", 11: "Deeper analysis", 1: "Neon"}, "4 Neon"),
    # [19] 缺：退 [12]
    ({12: "4 Neon", 11: "Deeper analysis", 1: "Neon"}, "4 Neon"),
    # [12] 是说明句：跳过，退 [11]
    ({12: "Adapts to your needs", 11: "Auto", 1: "Auto"}, "Auto"),
    # [12]、[11] 都是说明句：退 [1]
    ({12: "Code & complex work", 11: "Everyday help", 1: "Carbon"}, "Carbon"),
    # 旧形状：名字只在 [11]
    ({11: "4 Argon"}, "4 Argon"),
    ({11: "3.5 Flash-Lite"}, "3.5 Flash-Lite"),
    ({}, None),
    ({19: "   "}, None),
])
def test_real_name_fallback_chain(fields, expected):
    e = [None] * 20
    e[0] = "0123456789abcdef"
    for idx, value in fields.items():
        e[idx] = value
    assert gc._entry_real_name(e) == expected


@pytest.mark.parametrize("name,model_id", list(zip(LIVE_NAMES, [AUTO_ID, HYDROGEN_ID, NEON_ID, CARBON_ID])))
def test_each_real_name_is_sent_with_its_own_model_id(name, model_id):
    assert sent_id(live_client(), name) == model_id


def test_no_heartbeat_yet_lists_the_contract_names():
    c = client_with()
    assert c._public_model_names() == PUBLIC_MODELS
    assert make_pool(c).models == PUBLIC_MODELS


def test_a_rename_replaces_the_list_on_the_next_heartbeat_without_accumulating():
    c = client_with(AUTO(), HYDROGEN(), NEON(), CARBON())
    c._parse_models_from_status(status_raw(AUTO(), HYDROGEN(), NEON("4.1 Neon"), CARBON()))

    assert c._available_models == ["gemini-auto", "gemini-4-hydrogen", "gemini-4.1-neon",
                                   "gemini-4-carbon"]
    assert "gemini-4-neon" not in c._available_models


def test_list_endpoints_and_the_panel_show_the_real_names(gem_client, monkeypatch):
    from app.core import account_pool as ap

    acct = Account(id="acc1", psid="p", psidts="t", client=live_client())
    monkeypatch.setattr(ap.account_pool, "_accounts", [acct])

    ids = [m["id"] for m in gem_client.get("/v1/models", headers=_AUTH).json()["data"]]
    assert ids == LIVE_NAMES
    ids = [m["id"] for m in gem_client.get("/claude/v1/models", headers=_AUTH).json()["data"]]
    assert ids == LIVE_NAMES
    models = gem_client.get("/v1beta/models", headers=_AUTH).json()["models"]
    assert [m["name"] for m in models] == [f"models/{n}" for n in LIVE_NAMES]
    status = gem_client.get("/admin/status", headers=_AUTH).json()
    assert status["models"] == LIVE_NAMES
    assert status["accounts"][0]["models"] == LIVE_NAMES
    assert status["accounts"][0]["models_count"] == 4
    # retrieve 与列表同口径
    assert gem_client.get("/v1/models/gemini-4-neon", headers=_AUTH).status_code == 200
    assert gem_client.get("/v1/models/gemini-pro", headers=_AUTH).status_code == 404


def test_v1beta_descriptions_use_the_heartbeats_own_positioning_text(gem_client, monkeypatch):
    """不编性能：说明里只有网页名字和心跳 [11] 的原文（Auto 的 [11] 就是名字本身，退 [12]）。"""
    from app.core import account_pool as ap

    monkeypatch.setattr(ap.account_pool, "_accounts",
                        [Account(id="acc1", psid="p", psidts="t", client=live_client())])
    models = {m["name"]: m["description"]
              for m in gem_client.get("/v1beta/models", headers=_AUTH).json()["models"]}

    assert "4 Hydrogen" in models["models/gemini-4-hydrogen"]
    assert "Everyday help" in models["models/gemini-4-hydrogen"]
    assert "Code & complex work" in models["models/gemini-4-carbon"]
    assert "Adapts to your needs" in models["models/gemini-auto"]


# ---------------------------------------------------------------------------
# R2 旧名字全部继续能调，但不再列出
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,model_id", [
    ("gemini-pro", NEON_ID),
    ("gemini-flash", HYDROGEN_ID),
    ("gemini-flash-lite", AUTO_ID),
    ("gemini-2.5-pro", NEON_ID),            # MODEL_ALIASES 的老别名照旧
    ("gemini-flash-thinking", HYDROGEN_ID),
    ("gemini-argon", CARBON_ID),
    ("gemini-4-argon", CARBON_ID),
    ("gemini-carbon", CARBON_ID),
    ("gemini-neon", NEON_ID),
    ("gemini-hydrogen", HYDROGEN_ID),
])
def test_old_names_and_unversioned_aliases_still_route(name, model_id):
    c = live_client()
    assert sent_id(c, name) == model_id
    assert name not in c._available_models
    assert name not in make_pool(c).models


def test_the_old_argon_shape_still_parses_into_the_carbon_family():
    c = client_with(AUTO(), HYDROGEN(), NEON(), OLD_ARGON())

    assert c._available_models[-1] == "gemini-4-argon"
    assert c._family_model["carbon"] == "gemini-4-argon"
    for name in ("gemini-argon", "gemini-carbon", "gemini-4-argon"):
        assert sent_id(c, name) == CARBON_ID
    assert make_pool(c).family_of("gemini-4-argon") == "carbon"


def test_rename_history_survives_a_restart():
    """谷歌把 4 Neon 改成 4.1 Neon（同一个 id）：客户端里配好的 gemini-4-neon 照样能调。"""
    live_client()                                   # 第一次心跳：记下 gemini-4-neon → NEON_ID
    assert model_names.history.lookup("gemini-4-neon") == {"ids": [NEON_ID], "family": "pro"}

    model_names.history.reset()                     # 进程重启：内存那份丢掉，从盘上读回来
    renamed = client_with(AUTO(), HYDROGEN(), NEON("4.1 Neon"), CARBON())

    assert "gemini-4-neon" not in renamed._available_models, "历史名只用于解析，不列出"
    assert sent_id(renamed, "gemini-4-neon") == NEON_ID
    assert make_pool(renamed).family_of("gemini-4-neon") == "pro"


def test_history_file_is_validated_and_capped(tmp_path):
    # 名字口径与心跳铸名同一条正则（model_names 不 import gemini_client，两边各写一份，这里钉住）
    assert model_names.NAME_RE.pattern == gc._DISCOVER_NAME_RE.pattern
    path = tmp_path / "names.json"
    path.write_text(json.dumps({"names": {
        "gemini-ok": {"ids": [NEON_ID], "family": "pro", "seen": 1},
        "not-a-gemini-name": {"ids": [NEON_ID], "family": "pro"},
        "gemini-bad-id": {"ids": ["XYZ"], "family": "pro"},
        "gemini-bad-family": {"ids": [NEON_ID], "family": "Pro Max!"},
        "gemini-not-a-dict": "x",
    }}), encoding="utf-8")
    hist = model_names.ModelNameHistory(path)

    assert hist.lookup("gemini-ok") == {"ids": [NEON_ID], "family": "pro"}
    for bad in ("not-a-gemini-name", "gemini-bad-id", "gemini-bad-family", "gemini-not-a-dict"):
        assert hist.lookup(bad) is None

    path.write_text("{ not json", encoding="utf-8")
    assert model_names.ModelNameHistory(path).lookup("gemini-ok") is None, "坏文件当空，不抛"

    flood = model_names.ModelNameHistory(tmp_path / "flood.json")
    flood.record([(f"gemini-x{i}", f"{i:016x}", "x") for i in range(500)], now=1000)
    flood.record([("gemini-fresh", NEON_ID, "pro")], now=999_999)
    assert len(flood.items()) == model_names.MAX_NAMES
    assert flood.lookup("gemini-fresh") is not None, "最新见过的不能被淘汰"
    reread = model_names.ModelNameHistory(tmp_path / "flood.json")
    assert len(reread.items()) == model_names.MAX_NAMES


def test_a_malformed_heartbeat_cannot_blow_up_the_history():
    flood = [live_entry(f"{i:016x}", f"Fam{i}", "x", f"{i} Fam{i}", 9) for i in range(300)]
    for _ in range(20):
        client_with(AUTO(), HYDROGEN(), NEON(), *flood)
    assert len(model_names.history.items()) <= model_names.MAX_NAMES


@pytest.mark.parametrize("bad_name", ["Pro", "Flash-Lite", "2.5 Pro", "Flash Thinking"])
def test_a_real_name_may_not_take_over_a_contract_name_or_alias(bad_name, caplog):
    """冲突时不采纳该显示名（打一次 WARNING），该 family 照旧用契约名列出。"""
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    c = client_with(AUTO(), HYDROGEN(), NEON(bad_name), CARBON())
    c._parse_models_from_status(status_raw(AUTO(), HYDROGEN(), NEON(bad_name), CARBON()))

    assert c._available_models == ["gemini-auto", "gemini-4-hydrogen", "gemini-pro",
                                   "gemini-4-carbon"]
    assert sent_id(c, "gemini-pro") == NEON_ID
    warned = [r for r in caplog.records if "conflicts" in r.getMessage()]
    assert len(warned) == 1, [r.getMessage() for r in caplog.records]
    assert model_names.history.lookup(gc._name_from_display(bad_name)) is None


def test_a_real_name_may_not_point_an_internal_name_at_another_id():
    """「3 Pro」→ gemini-3-pro 是写死表里 9d8c… 的内部名；Neon（e6fa…）不能借用它。"""
    c = client_with(AUTO(), HYDROGEN(), NEON("3 Pro"), CARBON())
    assert "gemini-3-pro" not in c._available_models
    assert "gemini-pro" in c._available_models


# ---------------------------------------------------------------------------
# R3 所有按模型名做判断的地方
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("new,old", [
    ("gemini-4-neon", "gemini-pro"),
    ("gemini-4-hydrogen", "gemini-flash"),
    ("gemini-auto", "gemini-flash-lite"),
    ("gemini-4-carbon", "gemini-argon"),
    ("gemini-4-carbon", "gemini-4-argon"),
    ("gemini-neon", "gemini-pro"),
])
def test_breaker_family_is_the_same_for_new_and_old_names(new, old):
    pool = make_pool(live_client())
    assert pool.family_of(new) == pool.family_of(old) is not None


def test_carbon_gets_the_complex_task_timeout():
    c = live_client()
    assert gc._generate_timeout("gemini-4-carbon", "写一段排序算法", c._model_table()) == 300
    assert gc.generate_timeout_for_family("carbon", "x") == 300


def test_an_old_argon_timeout_override_applies_to_carbon(monkeypatch):
    monkeypatch.setattr(gc.settings, "generate_timeouts", "argon=500")
    assert gc.generate_timeout_for_family("carbon", "x") == 500
    monkeypatch.setattr(gc.settings, "generate_timeouts", "argon=500,carbon=400")
    assert gc.generate_timeout_for_family("carbon", "x") == 400, "显式写 carbon= 的优先"


@pytest.mark.parametrize("model,expected", [
    ("gemini-4-neon", "gemini-pro"),
    ("gemini-4-hydrogen", "gemini-flash"),
    ("gemini-auto", "gemini-flash-lite"),
    ("gemini-4-carbon", "gemini-carbon"),
    ("gemini-argon", "gemini-carbon"),
    ("gemini-4-argon", "gemini-carbon"),
])
def test_new_names_are_priced_as_their_family(model, expected):
    from app.core.token_pricing import DEFAULT_TOKEN_PRICES, price_table_name

    live_client()          # 心跳记下真实名字
    assert price_table_name(model) == expected
    assert expected in DEFAULT_TOKEN_PRICES
    assert DEFAULT_TOKEN_PRICES["gemini-carbon"] == (2.00, 10.00), "carbon 用原 argon 的价"


def test_an_operator_price_under_the_old_argon_name_still_prices_carbon_usage():
    from app.core.token_pricing import estimate_cost_breakdown

    total, unpriced = estimate_cost_breakdown(
        {"gemini-carbon": {"in": 1_000_000, "out": 0}}, {"gemini-argon": (3.0, 0.0)})
    assert total == pytest.approx(3.0) and unpriced == []


@pytest.fixture
def live_pool(monkeypatch):
    from app.core import account_pool as ap

    acct = Account(id="acc1", psid="p", psidts="t", client=live_client())
    monkeypatch.setattr(ap.account_pool, "_accounts", [acct])
    captured = []

    async def send(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   extended_thinking=False):
        captured.append((model, sent_id(acct.client, model)))
        return {"text": "ok", "images": [], "conversation_id": "", "thoughts": ""}

    monkeypatch.setattr(acct.client, "_send_request", send)
    return captured


@pytest.mark.parametrize("model", ["gemini-4-neon", "gemini-4-carbon", "gemini-auto",
                                   "gemini-argon", "gemini-pro"])
def test_every_protocol_routes_new_and_old_names_to_gemini(gem_client, live_pool, model):
    r = gem_client.post("/v1/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["model"] == model, "R4：请求什么名字就回什么名字"
    r = gem_client.post("/v1/responses", json={"model": model, "input": "hi"}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["model"] == model
    r = gem_client.post("/v1/messages", json={
        "model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]},
        headers=_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["model"] == model
    r = gem_client.post(f"/v1beta/models/{model}:generateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}]}, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert [m for m, _ in live_pool] == [model] * 4
    assert len({mid for _, mid in live_pool}) == 1 and live_pool[0][1] is not None


def test_model_mapping_and_gem_base_model_accept_real_names(gem_client, live_pool, app_main):
    app_main.app.state.model_mapping.set("my-model", "gemini-4-carbon")
    app_main.app.state.gem_mapping.set("my-gem", {"gem_id": "g1", "base_model": "gemini-4-neon",
                                                  "account_id": ""})

    for model in ("my-model", "my-gem"):
        r = gem_client.post("/v1/chat/completions", json={
            "model": model, "messages": [{"role": "user", "content": "hi"}]}, headers=_AUTH)
        assert r.status_code == 200, r.text
    assert [mid for _, mid in live_pool] == [CARBON_ID, NEON_ID]


def test_model_whitelist_matches_by_family(gem_client, monkeypatch):
    from app.core import account_pool as ap

    monkeypatch.setattr(ap.account_pool, "_accounts",
                        [Account(id="acc1", psid="p", psidts="t", client=live_client())])
    monkeypatch.setattr(gc.settings, "model_whitelist", "gemini-pro,gemini-argon")

    ids = [m["id"] for m in gem_client.get("/v1/models", headers=_AUTH).json()["data"]]
    assert ids == ["gemini-4-neon", "gemini-4-carbon"]
    ids = [m["id"] for m in gem_client.get("/claude/v1/models", headers=_AUTH).json()["data"]]
    assert ids == ["gemini-4-neon", "gemini-4-carbon"]
    names = [m["name"] for m in gem_client.get("/v1beta/models", headers=_AUTH).json()["models"]]
    assert names == ["models/gemini-4-neon", "models/gemini-4-carbon"]


@pytest.mark.parametrize("allowed,request_model,listed", [
    (["gemini-pro"], "gemini-4-neon", ["gemini-4-neon"]),
    (["gemini-4-neon"], "gemini-pro", ["gemini-4-neon"]),
    (["gemini-argon"], "gemini-4-carbon", ["gemini-4-carbon"]),
    (["gemini-flash-lite"], "gemini-auto", ["gemini-auto"]),
])
def test_access_key_allowed_models_match_old_and_new_names_by_family(
        gem_client, live_pool, monkeypatch, tmp_path, allowed, request_model, listed):
    import app.core.access_key_store as store_module
    from app.core.access_key_store import AccessKeyStore

    store = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", store)
    key = store.create("k", allowed_models=allowed).key
    auth = {"Authorization": f"Bearer {key}"}

    ids = [m["id"] for m in gem_client.get("/v1/models", headers=auth).json()["data"]]
    assert ids == listed
    r = gem_client.post("/v1/chat/completions", json={
        "model": request_model, "messages": [{"role": "user", "content": "hi"}]}, headers=auth)
    assert r.status_code == 200, r.text
    # 别的 family 照旧拒
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-4-hydrogen" if "hydrogen" not in request_model else "gemini-4-neon",
        "messages": [{"role": "user", "content": "hi"}]}, headers=auth)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# R7 按账号实时
# ---------------------------------------------------------------------------

def test_the_pool_lists_the_union_of_each_accounts_own_names():
    pool = make_pool(live_client(), free_client())
    assert pool.models == LIVE_NAMES + ["gemini-fast", "gemini-3-pro"]


def test_expired_and_disabled_accounts_do_not_count():
    pool = make_pool(live_client(), free_client(),
                     statuses={0: AccountStatus.EXPIRED})
    assert pool.models == ["gemini-auto", "gemini-fast", "gemini-3-pro"]
    pool = make_pool(live_client(), free_client(), statuses={1: AccountStatus.DISABLED})
    assert pool.models == LIVE_NAMES


def test_a_bound_access_key_only_sees_its_accounts_models(gem_client, monkeypatch, tmp_path):
    import app.core.access_key_store as store_module
    from app.core import account_pool as ap
    from app.core.access_key_store import AccessKeyStore

    pool = make_pool(live_client(), free_client())
    monkeypatch.setattr(ap.account_pool, "_accounts", pool._accounts)
    store = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", store)
    key = store.create("free-only", bound_account_ids=["account-1"]).key

    ids = [m["id"] for m in gem_client.get("/v1/models",
                                           headers={"Authorization": f"Bearer {key}"}).json()["data"]]
    assert ids == ["gemini-auto", "gemini-fast", "gemini-3-pro"]
    assert pool.models_for({"account-0"}) == LIVE_NAMES


def test_each_account_answers_a_shared_name_with_its_own_model():
    pro, free = live_client(), free_client()
    # 同名不同 id：各报各的
    assert sent_id(pro, "gemini-auto") == AUTO_ID
    assert sent_id(free, "gemini-auto") == FREE_LITE_ID
    # 契约名：每个账号按自己的 family
    assert sent_id(pro, "gemini-pro") == NEON_ID
    assert sent_id(free, "gemini-pro") == FREE_PRO_ID


def test_a_name_only_goes_to_accounts_that_have_that_model_id():
    """绝不把一个账号报的名字按 family 换成另一个账号的不同 id。"""
    pro, free = live_client(), free_client()
    assert sent_id(free, "gemini-4-carbon") is None
    assert sent_id(free, "gemini-4-neon") is None, "免费账号的 pro 是另一个 id，不能顶替 Neon"
    assert sent_id(free, "gemini-4-hydrogen") is None
    assert sent_id(pro, "gemini-3-pro") is None, "Pro 账号心跳里没有 9d8c…"
    assert sent_id(pro, "gemini-fast") is None
    # family 别名按 family 解析，只发给有这个 family 的账号
    assert sent_id(free, "gemini-carbon") is None
    assert sent_id(free, "gemini-neon") == FREE_PRO_ID


def _wire(pool, captured):
    for account in pool._accounts:
        client = account.client

        async def send(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False, _a=account, _c=client):
            captured.append((_a.id, sent_id(_c, model)))
            return {"text": "ok", "images": []}

        client._send_request = send


def test_the_pool_moves_a_request_to_the_account_that_has_it_without_penalising_the_other():
    pool = make_pool(free_client(), live_client())          # 第一个选中免费账号
    captured = []
    _wire(pool, captured)

    result = asyncio.run(pool.generate("hi", "gemini-4-carbon"))

    assert result["account_id"] == "account-1"
    assert captured == [("account-1", CARBON_ID)]
    free = pool.accounts[0]
    assert (free.consecutive_failures, free.request_count, free.cooldown_until) == (0, 0, 0)


def test_nobody_has_it_is_a_400_and_a_busy_holder_is_a_529():
    pool = make_pool(free_client(), free_client())
    with pytest.raises(gc.ModelUnavailable) as ei:
        asyncio.run(pool.generate("hi", "gemini-4-carbon"))
    assert gc.classify_error(ei.value)[0] == 400

    pool = make_pool(free_client(), live_client())
    _wire(pool, [])
    pool.accounts[1].active_requests = pool._max_concurrent          # 有 Carbon 的那个满载
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(pool.generate("hi", "gemini-4-carbon"))
    assert gc.classify_error(ei.value)[0] == 529


def test_a_bound_key_to_an_account_without_the_model_gets_a_400(monkeypatch, tmp_path):
    from app.core.access_context import set_current_access_key
    from app.core.access_key_store import AccessKeyStore

    pool = make_pool(live_client(), free_client())
    _wire(pool, [])
    entry = AccessKeyStore(file_path=str(tmp_path / "k.json")).create(
        "free", bound_account_ids=["account-1"])
    set_current_access_key(entry)
    try:
        with pytest.raises(gc.ModelUnavailable):
            asyncio.run(pool.generate("hi", "gemini-4-neon"))
    finally:
        set_current_access_key(None)


def test_a_changed_account_list_replaces_the_old_one_on_the_next_heartbeat():
    c = live_client()
    pool = make_pool(c)
    assert "gemini-4-carbon" in pool.models

    c._parse_models_from_status(status_raw(AUTO(), HYDROGEN(), NEON()))   # 谷歌收回了 Carbon

    assert c._available_models == ["gemini-auto", "gemini-4-hydrogen", "gemini-4-neon"]
    assert "gemini-4-carbon" not in pool.models
    assert sent_id(c, "gemini-4-carbon") is None
    assert sent_id(c, "gemini-carbon") is None
    assert "gemini-4-carbon" not in c._model_table(), "整体替换：不留可路由的残行"


def test_the_panel_shows_each_accounts_own_list(gem_client, monkeypatch):
    from app.core import account_pool as ap

    pool = make_pool(live_client(), free_client())
    monkeypatch.setattr(ap.account_pool, "_accounts", pool._accounts)

    status = gem_client.get("/admin/status", headers=_AUTH).json()
    assert status["accounts"][0]["models"] == LIVE_NAMES
    assert status["accounts"][1]["models"] == ["gemini-auto", "gemini-fast", "gemini-3-pro"]
    assert status["models"] == LIVE_NAMES + ["gemini-fast", "gemini-3-pro"]


def test_known_ids_keep_their_hardcoded_rows():
    """免费账号的 id 都在写死表里：按 id 认 family，不走「发现」那条路。"""
    c = free_client()
    assert c._family_model == {"flash-lite": "gemini-3-flash-lite", "flash": "gemini-3-flash",
                               "pro": "gemini-3-pro"}
    assert c._discovered_models == {}
    assert GEMINI_MODELS[c._real_names["gemini-fast"]]["id"] == FREE_FLASH_ID

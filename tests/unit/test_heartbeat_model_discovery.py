"""M1：心跳驱动的模型自动发现（4 Argon 接入）。

背景：账号心跳 RPC otAQ7b 返回的模型条目是 20 字段数组，真实 Argon 条目（中转站实抓）：
  [0]="95a4c0abcba24364" [1]="Argon" [2]="Complex tasks" [4]=2 [9]=4
  [10]="Argon" [11]="4 Argon" [17]=8 [19]="4 Argon"
改动前这条目只会被打一行 WARNING 然后丢掉，于是真机上明明可用的 Argon 对外完全不存在。

这个文件钉的是三件事：
  1. 真实形态的条目被采纳，并且采纳结果真的进了发给 Google 的模型头（不是只进了某个字典）；
  2. 畸形/被污染的条目被拒绝，且**既有 4 个公开名的映射一个字都没被动过**；
  3. 心跳没跑时回落写死表，4 个老公开名逐字节不变。
"""

import json
import logging

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import (
    GEMINI_MODELS, MODEL_HEADER_KEY, PUBLIC_MODELS, _BASE_FAMILIES,
    _FAMILY_DEFAULT, _PUBLIC_FAMILY,
)

ARGON_ID = "95a4c0abcba24364"
ARGON_INTERNAL = "gemini-4-argon"
ARGON_PUBLIC = "gemini-argon"

# 真实账号的另外三个模型（id 取自真机心跳；都落在写死表的 capacity 2 变体上）
PRO_ID = "e6fa609c3fa255c0"
FLASH_ID = "56fdd199312815e2"
FLASH_LITE_ID = "8c46e95b1a07cecc"


def argon_entry(**over) -> list:
    """真机抓到的 20 字段 Argon 条目；over 用来逐格做污染测试。"""
    e = [
        ARGON_ID, "Argon", "Complex tasks", [1, 2, 3], 2, None, None, True,
        "Argon4p0", 4, "Argon", "4 Argon", "Complex tasks", None, None, True,
        "Argon4p0", 8, ["https://example.invalid/icon.png", True], "4 Argon",
    ]
    for idx, value in over.items():
        e[int(idx.lstrip("f"))] = value
    return e


def base_entry(model_id: str, display: str, number: int) -> list:
    e = [None] * 20
    e[0] = model_id
    e[11] = display
    e[17] = number
    return e


THREE_BASE = [
    base_entry(PRO_ID, "3.1 Pro", 3),
    base_entry(FLASH_ID, "3.8 Flash", 1),
    base_entry(FLASH_LITE_ID, "3.5 Flash-Lite", 6),
]


def status_raw(*entries: list) -> str:
    body = [None] * 16
    body[15] = list(entries)
    return "[[" + json.dumps(["wrb.fr", "otAQ7b", json.dumps(body)])[1:-1] + "]]"


def fresh_client() -> gc.GeminiWebClient:
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    c._family_model = {}
    c._available_models = []
    c._discovered_models = {}
    return c


def adopted(*extra_entries: list) -> gc.GeminiWebClient:
    c = fresh_client()
    c._parse_models_from_status(status_raw(*THREE_BASE, *extra_entries))
    return c


# ---------------------------------------------------------------------------
# 1. 真实条目被采纳，并真的进了模型头
# ---------------------------------------------------------------------------

def test_real_argon_entry_is_adopted_from_the_heartbeat():
    c = adopted(argon_entry())

    assert c._family_model["argon"] == ARGON_INTERNAL
    info = c._discovered_models[ARGON_INTERNAL]
    assert info["id"] == ARGON_ID
    assert info["model_number"] == 8, "model_number 必须取 [17]=8，不是 [9]=4"
    # capacity 取账号级信号（同一次心跳里已认出的模型的 capacity），不取条目级 [4]
    assert info["capacity"] == GEMINI_MODELS["gemini-3-pro-advanced"]["capacity"]
    assert info["family"] == "argon"


def test_adoption_is_logged(caplog):
    caplog.set_level(logging.INFO, logger=gc.logger.name)

    adopted(argon_entry())

    msgs = [r.getMessage() for r in caplog.records if "adopted" in r.getMessage()]
    assert len(msgs) == 1, msgs
    assert ARGON_ID in msgs[0]
    assert "4 Argon" in msgs[0]
    assert ARGON_PUBLIC in msgs[0]


def test_public_argon_name_resolves_to_the_adopted_model():
    c = adopted(argon_entry())

    assert gc._resolve_model(ARGON_PUBLIC, c._family_model) == ARGON_INTERNAL


def test_adopted_argon_lands_in_the_model_header():
    """最要紧的一条：采纳结果必须出现在发给 Google 的 jspb 头里。

    不进头的话 _build_model_header 返回 {}、调用点的 `if model_headers:` 跳过，请求
    就不带模型头发出，Google 用账号默认模型回答 —— HTTP 200、正文正常、客户端毫无感知。
    """
    c = adopted(argon_entry())
    table = c._model_table()

    arr = json.loads(gc._build_model_header(ARGON_INTERNAL, table)[MODEL_HEADER_KEY])
    assert arr[4] == ARGON_ID
    assert arr[11] == 2

    th = json.loads(
        gc._build_model_header_thinking(ARGON_INTERNAL, "SESSION", 1, table)[MODEL_HEADER_KEY]
    )
    assert th[4] == ARGON_ID
    assert th[14] == 8, "thinking 头第 15 位是 model_number，Argon 是 8"
    assert gc._model_number(ARGON_PUBLIC, table, c._family_model) == 8


def test_argon_is_listed_as_a_public_model():
    c = adopted(argon_entry())

    names = c._public_model_names()
    assert names[:4] == PUBLIC_MODELS, "4 个契约名必须恒在最前、顺序不变"
    assert ARGON_PUBLIC in names
    assert c._available_models == names


def test_account_pool_lists_argon_only_when_an_account_has_it():
    from app.core.account_pool import AccountPool

    pool = AccountPool.__new__(AccountPool)

    class _Acct:
        def __init__(self, c):
            self.client = c

    pool._accounts = [_Acct(fresh_client())]
    assert pool.models == PUBLIC_MODELS, "没有 Argon 的部署不该看到一个调不通的选项"

    pool._accounts = [_Acct(fresh_client()), _Acct(adopted(argon_entry()))]
    assert pool.models[:4] == PUBLIC_MODELS
    assert ARGON_PUBLIC in pool.models


# ---------------------------------------------------------------------------
# 2. 污染矩阵：拒绝 + 既有映射不被动
# ---------------------------------------------------------------------------

BAD_ENTRIES = {
    "id_15_hex": argon_entry(f0=ARGON_ID[:-1]),
    "id_17_hex": argon_entry(f0=ARGON_ID + "a"),
    "id_uppercase": argon_entry(f0=ARGON_ID.upper()),
    "id_not_hex": argon_entry(f0="zzzzzzzzzzzzzzzz"),
    "id_not_a_string": argon_entry(f0=12345678901234567),
    "model_number_zero": argon_entry(f17=0, f9=None),
    "model_number_negative": argon_entry(f17=-1, f9=None),
    "model_number_string": argon_entry(f17="8", f9=None),
    "model_number_true": argon_entry(f17=True, f9=None),
    "model_number_missing": argon_entry(f17=None, f9=None),
    "no_category": argon_entry(f1=None, f10=None),
    "blank_category": argon_entry(f1="   ", f10="  "),
    "no_display": argon_entry(f11=None, f19=None, f1=None),
    "category_is_a_base_family": argon_entry(f1="Pro", f10="Pro"),
    # 最凶的一条：category 顶掉 pro 这个 family，而 display 是个全新名字（不会被
    # "与写死表同名"那条规则挡下）。采纳它就等于把 gemini-pro 重新指向任意 model_id。
    "category_hijacks_a_base_family": argon_entry(
        f0="0123456789abcdef", f1="Pro", f10="Pro", f11="9 Turbo", f19="9 Turbo"),
    "category_hijacks_flash_thinking": argon_entry(
        f0="0123456789abcdee", f1="Flash Thinking", f10="Flash Thinking",
        f11="9 Turbo", f19="9 Turbo"),
    "display_impersonates_a_public_name": argon_entry(f11="Pro", f19="Pro"),
    "display_impersonates_an_old_alias": argon_entry(f11="2.5 Pro", f19="2.5 Pro"),
    "display_is_punctuation_only": argon_entry(f11="///", f19="///", f1="Argon"),
}


# model_id 不是字符串的条目在"收集"阶段就被既有代码过滤掉了（根本进不到解析循环），
# 所以它不会有 WARNING —— 这是改动前就有的行为，这里只把它留在"不许改映射"那组里。
BAD_ENTRIES_LOGGED = {k: v for k, v in BAD_ENTRIES.items() if k != "id_not_a_string"}


@pytest.mark.parametrize("label", sorted(BAD_ENTRIES_LOGGED))
def test_malformed_entries_are_rejected_and_logged(label, caplog):
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    c = adopted(BAD_ENTRIES_LOGGED[label])

    assert "argon" not in c._family_model, f"{label} 不该被采纳"
    assert c._discovered_models == {}
    assert ARGON_PUBLIC not in c._public_model_names()
    # 被丢弃的条目必须留一条带原因/字段的 WARNING（可观测性契约，S5 定下的）
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("dropped" in m for m in warnings), warnings


@pytest.mark.parametrize("label", sorted(BAD_ENTRIES))
def test_malformed_entries_never_repoint_the_four_contract_names(label):
    """污染响应最大的危害不是多出一个模型，而是顶掉 gemini-pro 的映射。"""
    c = adopted(BAD_ENTRIES[label])

    assert c._family_model["pro"] == "gemini-3-pro-advanced"
    assert c._family_model["flash"] == "gemini-3-flash-advanced"
    assert c._family_model["flash-lite"] == "gemini-3-flash-lite-advanced"
    assert c._family_model["flash-thinking"] == "gemini-3-flash-thinking-advanced"
    for name in PUBLIC_MODELS:
        assert gc._resolve_model(name, c._family_model) in GEMINI_MODELS
        assert GEMINI_MODELS[gc._resolve_model(name, c._family_model)]["family"] \
            == _PUBLIC_FAMILY[name]


def test_a_flood_of_entries_cannot_blow_up_the_table():
    """畸形/被污染的响应可能塞几百条进来，每条都要进实例态字典。"""
    flood = [argon_entry(f0=f"{i:016x}", f1=f"Fam{i}", f10=f"Fam{i}",
                         f11=f"{i} Fam{i}", f19=f"{i} Fam{i}")
             for i in range(300)]
    c = adopted(*flood)

    assert len(c._discovered_models) <= gc._DISCOVER_MAX_PER_ROUND


def test_nothing_is_adopted_when_the_account_tier_is_ambiguous():
    """账号档位不唯一 = 心跳结构和我们的理解已经对不上，这时宁可什么都不采纳。"""
    mixed = [
        base_entry("9d8ca3786ebdfbea", "3 Pro", 3),        # capacity 1
        base_entry(FLASH_ID, "3.8 Flash", 1),               # capacity 2
    ]
    c = fresh_client()
    c._parse_models_from_status(status_raw(*mixed, argon_entry()))

    assert "argon" not in c._family_model
    assert c._discovered_models == {}


# ---------------------------------------------------------------------------
# 3. 零回归：没有 Argon / 没有心跳时的行为
# ---------------------------------------------------------------------------

def test_capacity_backfill_never_invents_argon():
    """写死表里有一条 capacity=2 的 argon。同档补全若不限制在 4 个基础 family，
    任何 capacity=2 的账号（真实账号正是 cap 2）都会被自动补上 argon，然后把
    Argon 的 id 发给一个根本没有 Argon 的账号。"""
    c = adopted()   # 只有 pro/flash/flash-lite，没有 Argon 条目

    assert "argon" not in c._family_model
    assert ARGON_PUBLIC not in c._public_model_names()
    assert c._available_models == PUBLIC_MODELS
    assert c._family_model["flash-thinking"] == "gemini-3-flash-thinking-advanced", \
        "4 个基础 family 的同档补全必须照旧"


def test_an_account_without_argon_cannot_route_argon():
    """混合池红线：A 账号发现了 Argon，/v1/models 就会列出 gemini-argon（池是跨账号
    聚合的），而选号是轮转的。没发现 Argon 的账号必须**干脆拒绝**，不能退到写死那一行
    然后把 Argon 的 model id 发给 Google —— 那条路要么 4xx/空回复（还会污染账号健康
    指标），要么 Google 按账号默认模型回答：HTTP 200、正文正常、客户端看不出被换了模型。
    """
    c = fresh_client()   # 心跳一次都没跑

    # 公开名解析不到任何内部模型 → 闸门（generate/_send_request 的 `resolved not in
    # self._model_table()`）必然命中 → ValueError → 400
    assert gc._resolve_model(ARGON_PUBLIC, c._family_model) == ARGON_PUBLIC
    assert ARGON_PUBLIC not in c._model_table()
    # 写死那一行仍在模块表里（id / model_number / 超时档位的口径兜底），但它**不可路由**
    assert ARGON_INTERNAL in GEMINI_MODELS
    assert ARGON_INTERNAL not in c._model_table()


def test_argon_becomes_routable_only_after_this_account_discovered_it():
    a = adopted(argon_entry())
    b = adopted()            # 同一个池里的另一个账号，心跳里没有 Argon

    assert gc._resolve_model(ARGON_PUBLIC, a._family_model) == ARGON_INTERNAL
    assert ARGON_INTERNAL in a._model_table()
    # 调用方传的是解析后的内部名（见 _send_request），所以这里也传它
    arr = json.loads(gc._build_model_header(ARGON_INTERNAL, a._model_table())[MODEL_HEADER_KEY])
    assert arr[4] == ARGON_ID

    assert gc._resolve_model(ARGON_PUBLIC, b._family_model) == ARGON_PUBLIC
    assert ARGON_PUBLIC not in b._model_table()
    assert ARGON_INTERNAL not in b._model_table()


def test_the_four_contract_names_are_unchanged_without_a_heartbeat():
    c = fresh_client()

    assert PUBLIC_MODELS == ["gemini-pro", "gemini-flash",
                             "gemini-flash-thinking", "gemini-flash-lite"]
    assert c._public_model_names() == PUBLIC_MODELS
    assert gc._resolve_model("gemini-pro", c._family_model) == "gemini-3-pro"
    assert gc._resolve_model("gemini-flash", c._family_model) == "gemini-3-flash"
    assert gc._resolve_model("gemini-flash-thinking", c._family_model) == "gemini-3-flash-thinking"
    assert gc._resolve_model("gemini-flash-lite", c._family_model) == "gemini-3-flash-lite"


def test_family_default_holds_exactly_the_contract_families():
    """_FAMILY_DEFAULT 是"账号没有这个 family 也放行"的唯一来源。多一个键就是多一个
    "任何账号都能路由它"的 family —— 非契约 family 只有发现到它的账号才有。"""
    assert set(_FAMILY_DEFAULT) == set(_BASE_FAMILIES)
    for family, name in _FAMILY_DEFAULT.items():
        assert GEMINI_MODELS[name]["family"] == family
    # 公开名→family 允许比它多（argon 就是），反过来不行
    assert set(_FAMILY_DEFAULT) <= set(_PUBLIC_FAMILY.values())


def test_model_table_falls_back_to_the_contract_rows_only():
    c = fresh_client()
    assert c._model_table() is gc._BASE_MODELS
    # 4 个契约 family 的写死行每个账号都能路由
    for name in _FAMILY_DEFAULT.values():
        assert name in c._model_table()
    # 非契约 family 的写死行不在里面
    assert ARGON_INTERNAL not in c._model_table()
    assert all(info["family"] in _BASE_FAMILIES for info in gc._BASE_MODELS.values())


def test_discovered_models_are_per_account():
    """A 账号发现的模型绝不能喂给 B 账号（P0-5 实例隔离）。"""
    a = adopted(argon_entry())
    b = adopted()

    assert ARGON_INTERNAL in a._discovered_models
    assert b._discovered_models == {}
    assert "argon" not in b._family_model


# ---------------------------------------------------------------------------
# 4. 未知模型名绝不允许静默发成账号默认模型
# ---------------------------------------------------------------------------

def test_send_request_refuses_a_model_it_cannot_put_in_the_header():
    """_send_request 过去没有 generate() 入口那道闸门：认不出的模型名会让
    _build_model_header 返回 {}，调用点的 `if model_headers:` 跳过，请求**不带模型头**
    发出 —— Google 用账号默认模型回答，HTTP 200、正文正常、客户端完全看不出被换了模型。
    """
    import asyncio

    c = fresh_client()
    c._healthy = True
    c._session_token = "T"
    c._push_id = ""
    c._http = None

    async def _noop(*a, **kw):
        return None

    c._ensure_session_current = _noop
    c._clear_session_cookies = lambda: None
    c._get_cookies = lambda: {}
    c._get_headers = lambda *a, **kw: {}

    with pytest.raises(ValueError) as err:
        asyncio.run(c._send_request("hi", "gemini-does-not-exist"))
    assert "unavailable" in str(err.value)


def test_an_account_without_argon_refuses_the_request_instead_of_sending_argons_id():
    """混合池里 (N-1)/N 的 Argon 请求会落到没有 Argon 的账号上。那里必须抛 ValueError
    （→ 400），而不是带着 Argon 的 model id 把请求发出去。"""
    import asyncio

    c = adopted()        # 心跳里只有 3 个基础模型，没有 Argon
    c._healthy = True
    c._session_token = "T"
    c._push_id = ""
    c._http = None

    async def _noop(*a, **kw):
        return None

    c._ensure_session_current = _noop
    c._clear_session_cookies = lambda: None
    c._get_cookies = lambda: {}
    c._get_headers = lambda *a, **kw: {}

    for name in (ARGON_PUBLIC, ARGON_INTERNAL):
        with pytest.raises(ValueError) as err:
            asyncio.run(c._send_request("hi", name))
        assert "unavailable" in str(err.value)


# ---------------------------------------------------------------------------
# 5. 发现结果只增不减 / 无界增长
# ---------------------------------------------------------------------------

def test_a_family_the_heartbeat_stopped_reporting_is_dropped():
    """只增不减的话：上一轮发现了 Argon、这一轮 Google 收回，gemini-argon 仍列在
    /v1/models 里、仍解析得到内部名 —— 用户看到一个"列表里有、调起来坏"的模型。"""
    c = adopted(argon_entry())
    assert ARGON_PUBLIC in c._public_model_names()

    c._parse_models_from_status(status_raw(*THREE_BASE))   # 第二轮：没有 Argon 了

    assert "argon" not in c._family_model
    assert ARGON_PUBLIC not in c._public_model_names()
    assert c._available_models == PUBLIC_MODELS
    assert gc._resolve_model(ARGON_PUBLIC, c._family_model) == ARGON_PUBLIC
    # 4 个契约 family 一个都不许被这轮清理碰到
    assert c._family_model["pro"] == "gemini-3-pro-advanced"
    assert set(PUBLIC_MODELS) <= set(c._available_models)


def test_discovered_models_cannot_grow_without_bound(caplog):
    """每轮上限只约束单轮。心跳一轮一轮地跑，只要每轮都给新的合法条目，
    _discovered_models 和 /v1/models 就会一直长。"""
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    c = fresh_client()
    for rnd in range(40):
        entries = [argon_entry(f0=f"{rnd:02d}{idx:014d}", f11=f"R{rnd}X{idx} Zz",
                               f1=f"Zz{rnd}x{idx}", f10=f"Zz{rnd}x{idx}")
                   for idx in range(8)]
        c._parse_models_from_status(status_raw(*THREE_BASE, *entries))

    assert len(c._discovered_models) <= gc._DISCOVER_MAX_TOTAL
    assert len(c._available_models) <= len(PUBLIC_MODELS) + gc._DISCOVER_MAX_PER_ROUND
    assert any("discovery capped" in r.message for r in caplog.records)
    # 契约名仍在最前、顺序不变
    assert c._available_models[:4] == PUBLIC_MODELS


def test_the_per_round_cap_counts_validated_candidates_not_raw_entries():
    """上限切原始列表的话，Google 在 Argon 前排进 8 个我们不认识的条目（实验性模型、
    缺字段的占位条目都算）就能把 Argon 的发现彻底饿死 —— 日志里看得到它被丢，
    功能却静默失效。"""
    # 连 model_number 都拿不到的条目（[17] 和兜底的 [9] 都空）：一条都不该占名额
    junk = [argon_entry(f0=f"{idx:016d}", f1=f"Junk{idx}", f10=f"Junk{idx}",
                        f11=f"{idx} Junk", f19=f"{idx} Junk", f17=None, f9=None)
            for idx in range(8)]
    assert all(gc._describe_discovered_model(e, 2) is None for e in junk)

    c = adopted(*junk, argon_entry())

    assert c._family_model.get("argon") == ARGON_INTERNAL
    assert c._discovered_models[ARGON_INTERNAL]["id"] == ARGON_ID
    assert ARGON_PUBLIC in c._available_models


def test_the_per_round_cap_still_holds_for_valid_entries():
    """零回归：合法条目一轮最多采纳 _DISCOVER_MAX_PER_ROUND 条。"""
    many = [argon_entry(f0=f"{idx:016d}", f1=f"Zz{idx}", f10=f"Zz{idx}",
                        f11=f"{idx} Zz", f19=f"{idx} Zz")
            for idx in range(20)]

    c = adopted(*many)

    assert len(c._discovered_models) == gc._DISCOVER_MAX_PER_ROUND


# ---------------------------------------------------------------------------
# 6. 新公开名不许长得像契约名
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("display", ["Pro 4", "4 Flash", "Lite 9", "Thinking X"])
def test_a_minted_public_name_may_not_borrow_a_contract_word(display):
    """category="Argon" + display="Pro 4" 会铸出 gemini-pro-4：它不顶掉 gemini-pro，
    但会和它一起列在 /v1/models 里，看着像官方名字、其实指向心跳给的任意 id。"""
    c = adopted(argon_entry(f11=display, f19=display))

    assert c._discovered_models == {}
    assert c._available_models == PUBLIC_MODELS
    assert c._family_model["pro"] == "gemini-3-pro-advanced"


def test_a_brand_new_family_keeps_working():
    """零回归：不含契约词的新 family 照旧采纳。"""
    c = adopted(argon_entry(f1="Xenon", f10="Xenon", f11="5 Xenon", f19="5 Xenon"))

    assert c._family_model["xenon"] == "gemini-5-xenon"
    assert "gemini-5-xenon" in c._available_models


def test_the_category_falls_back_to_field_10():
    """Google 把 family 名只放在第 10 格时也要认（参考实现 geminiFirstString(fields,1,10)
    就是为这个形态存在的）。窄到只读第 1 格 = 这类新模型永远被丢掉。"""
    e = argon_entry(f1=None)
    assert gc._entry_category(e) == "Argon"

    c = adopted(e)
    assert c._family_model["argon"] == ARGON_INTERNAL


def test_v1beta_models_keeps_a_description_on_every_entry():
    """官方 /v1beta/models 的每条都带 description，有些 SDK / UI 直接显示给用户。
    全给空串等于那一栏集体变空白。"""
    from app.routers import gemini as gr

    for name in PUBLIC_MODELS + [ARGON_PUBLIC]:
        assert gr._describe(name), name
    assert gr._describe("gemini-5-xenon") == gr._DISCOVERED_DESCRIPTION


def test_the_old_1_5_aliases_are_still_callable_even_though_unlisted():
    """口径纠正：从 /v1beta/models 列表里去掉的三条里，有两条本来是**能调通的**别名。
    列表收窄是有意的（列表该反映账号池此刻真有什么），但请求路径一个字都不许改。"""
    from app.core.gemini_client import MODEL_ALIASES

    assert MODEL_ALIASES["gemini-1.5-pro"] == "gemini-pro"
    assert MODEL_ALIASES["gemini-1.5-flash"] == "gemini-flash"
    assert gc._resolve_model("gemini-1.5-pro", {"pro": "gemini-3-pro-advanced"}) \
        == "gemini-3-pro-advanced"
    # gemini-2.0-flash-exp 连别名都没有 —— 那一条才是真的调不通
    assert "gemini-2.0-flash-exp" not in MODEL_ALIASES
    assert "gemini-2.0-flash-exp" not in GEMINI_MODELS


def test_v1beta_models_lists_real_public_names(client, monkeypatch):
    """/v1beta/models 过去写死三条 1.5/2.0 时代的名字，列表里一个契约公开名都没有。"""
    from app.core import account_pool as ap

    monkeypatch.setattr(type(ap.account_pool), "models",
                        property(lambda self: PUBLIC_MODELS + [ARGON_PUBLIC]))

    body = client.get("/v1beta/models",
                       headers={"Authorization": "Bearer sk-test-key"}).json()
    names = [m["name"] for m in body["models"]]

    assert names == [f"models/{m}" for m in PUBLIC_MODELS + [ARGON_PUBLIC]]
    assert not any("1.5" in n or "2.0-flash-exp" in n for n in names)
    # 每条都必须带 description：官方那个端点的每条都有，有些 SDK / UI 直接显示给用户，
    # 全是空串等于那一栏集体变空白（改动前那三条写死的名字各自带着一句说明）。
    assert all(m["description"] for m in body["models"]), body["models"]


# ---------------------------------------------------------------------------
# 5. 发现是账号驱动的：不是"写死表里刚好也有这一行"
# ---------------------------------------------------------------------------

BASE_TIER_ONE = [
    base_entry("9d8ca3786ebdfbea", "3 Pro", 3),
    base_entry("fbb127bbb056c959", "3 Flash", 1),
]


def test_the_account_tier_drives_the_adopted_capacity():
    """写死的 argon 兜底行是 capacity 2。心跳里这个账号是 capacity 1 档时，
    采纳到的 capacity 必须是 1 —— 否则就是拿写死表当真相、把请求发错档位。"""
    c = fresh_client()
    c._parse_models_from_status(status_raw(*BASE_TIER_ONE, argon_entry()))

    assert GEMINI_MODELS[ARGON_INTERNAL]["capacity"] == 2, "写死兜底行仍是 cap 2"
    assert c._discovered_models[ARGON_INTERNAL]["capacity"] == 1

    arr = json.loads(gc._build_model_header(ARGON_INTERNAL, c._model_table())[MODEL_HEADER_KEY])
    assert arr[11] == 1, "模型头里的 capacity 必须来自实例表，不是模块级写死表"


def xenon_entry() -> list:
    """一个写死表里完全没有的 family —— 证明发现真的不依赖写死表。"""
    e = [None] * 20
    e[0] = "a1b2c3d4e5f60789"
    e[1] = "Xenon"
    e[10] = "Xenon"
    e[11] = "5 Xenon"
    e[17] = 9
    return e


def test_a_brand_new_family_is_adopted_without_any_hardcoded_row():
    c = adopted(xenon_entry())

    assert c._family_model["xenon"] == "gemini-5-xenon"
    assert "gemini-5-xenon" not in GEMINI_MODELS, "写死表里没有这一行，全靠发现"
    assert "gemini-5-xenon" in c._public_model_names()

    table = c._model_table()
    arr = json.loads(gc._build_model_header("gemini-5-xenon", table)[MODEL_HEADER_KEY])
    assert arr[4] == "a1b2c3d4e5f60789"
    assert gc._model_number("gemini-5-xenon", table) == 9

    # 不传实例表就什么都查不到 —— 这正是"必须传实例表"的证据
    assert gc._build_model_header("gemini-5-xenon") == {}
    assert gc._model_number("gemini-5-xenon") == 1

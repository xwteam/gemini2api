"""M2：每把访问密钥的 token 用量 + 美元估算统计。

用户原话：「做请求数量上限就可以了，计次限制，但是可以统计美元，像 CPR 的同步价格一样，
转换成美元估算价格统计，但是不需要用额度限制的功能」。

所以这里钉的第一件事就是**只统计、不限额**：token 与美元一个字都不参与放行判定，
额度限制仍然只有 request_limit（计次）那一条。

第二件事是**诚实**：美元是「同样的内容若走官方 API 大约要多少钱」的参考值，不是账单。
算不出来的时候返回 None（面板显示 "—"），绝不回落到某个"差不多"的价、也绝不把
"不知道"显示成 0。
"""

import pytest

from app.config import settings
from app.core.access_key_store import AccessKeyStore
from app.core.token_pricing import (
    DEFAULT_TOKEN_PRICES, current_token_prices, estimate_cost_usd, parse_token_prices,
)


@pytest.fixture
def store(tmp_path):
    s = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    s.create("k1")
    return s


def _only(store) -> int:
    return store.list_keys()[0].id


# ---------------------------------------------------------------------------
# 1. 累加
# ---------------------------------------------------------------------------

def test_token_usage_accumulates_per_key_and_per_model(store):
    kid = _only(store)

    assert store.add_token_usage(kid, "gemini-flash", 100, 200) is True
    assert store.add_token_usage(kid, "gemini-flash", 10, 20) is True
    assert store.add_token_usage(kid, "gemini-pro", 1, 2) is True

    entry = store.get(kid)
    assert entry.input_tokens == 111
    assert entry.output_tokens == 222
    assert entry.tokens_by_model == {
        "gemini-flash": {"in": 110, "out": 220},
        "gemini-pro": {"in": 1, "out": 2},
    }


def test_two_keys_do_not_share_usage(store):
    store.create("k2")
    first, second = [k.id for k in store.list_keys()]

    store.add_token_usage(first, "gemini-flash", 5, 5)

    assert store.get(second).input_tokens == 0
    assert store.get(second).tokens_by_model is None


def test_an_unknown_key_id_is_a_no_op(store):
    assert store.add_token_usage(9999, "gemini-flash", 5, 5) is False


def test_zero_and_garbage_counts_are_ignored(store):
    kid = _only(store)

    assert store.add_token_usage(kid, "gemini-flash", 0, 0) is False
    assert store.add_token_usage(kid, "gemini-flash", "x", 1) is False
    assert store.get(kid).tokens_by_model is None


def test_negative_counts_never_decrease_the_total(store):
    kid = _only(store)
    store.add_token_usage(kid, "gemini-flash", 100, 100)

    store.add_token_usage(kid, "gemini-flash", -500, -500)

    assert store.get(kid).input_tokens == 100
    assert store.get(kid).output_tokens == 100


def test_the_model_map_cannot_grow_without_bound(store):
    kid = _only(store)

    for i in range(200):
        store.add_token_usage(kid, f"model-{i}", 1, 1)

    by_model = store.get(kid).tokens_by_model
    assert len(by_model) <= 65        # 64 个模型名 + "other"
    assert by_model["other"]["in"] > 1, "超出上限的用量并进 other，不许丢"
    assert store.get(kid).input_tokens == 200, "总数一个都不许少"


# ---------------------------------------------------------------------------
# 2. 只统计、不限额（这是本功能的全部要求）
# ---------------------------------------------------------------------------

def test_token_usage_never_blocks_a_request(store):
    kid = _only(store)
    store.update(kid, request_limit=5)
    key = store.get(kid).key

    # 堆一个大得离谱的 token 量 + 一笔很贵的估算
    store.add_token_usage(kid, "gemini-pro", 10**9, 10**9)

    for _ in range(5):
        state, entry = store.validate_and_consume(key)
        assert state == "valid", "token / 美元绝不参与放行判定"
    # 第 6 次被挡下来，而且理由必须是**计次**配额，不是 token
    state, entry = store.validate_and_consume(key)
    assert state == "quota_exceeded"
    assert entry.request_count == 5


def test_request_limit_is_the_only_quota_field(store):
    """token / 美元字段不许进 _UPDATABLE：管理员 PATCH 不能改用量，也不能把它配成上限。"""
    kid = _only(store)
    for field in ("input_tokens", "output_tokens", "tokens_by_model"):
        with pytest.raises(ValueError):
            store.update(kid, **{field: 1})


def test_consume_does_not_touch_token_counters(store):
    kid = _only(store)
    key = store.get(kid).key

    store.validate_and_consume(key)

    entry = store.get(kid)
    assert entry.request_count == 1
    assert (entry.input_tokens, entry.output_tokens) == (0, 0)


# ---------------------------------------------------------------------------
# 3. 重置 / 持久化
# ---------------------------------------------------------------------------

def test_reset_usage_clears_tokens_too(store):
    """只清 request_count 的话，面板上会出现「请求数 0 / 估算 $4.21」这种自相矛盾的行。"""
    kid = _only(store)
    store.validate_and_consume(store.get(kid).key)
    store.add_token_usage(kid, "gemini-pro", 500, 500)

    store.reset_usage(kid)

    entry = store.get(kid)
    assert entry.request_count == 0
    assert entry.input_tokens == 0
    assert entry.output_tokens == 0
    assert entry.tokens_by_model is None


def test_token_usage_survives_a_reload(tmp_path):
    path = str(tmp_path / "access_keys.json")
    first = AccessKeyStore(file_path=path)
    first.create("k")
    kid = first.list_keys()[0].id
    first.add_token_usage(kid, "gemini-flash", 7, 11)
    first.flush()

    reloaded = AccessKeyStore(file_path=path)
    entry = reloaded.get(kid)

    assert (entry.input_tokens, entry.output_tokens) == (7, 11)
    assert entry.tokens_by_model == {"gemini-flash": {"in": 7, "out": 11}}


def test_a_legacy_file_without_the_new_fields_still_loads(tmp_path):
    path = tmp_path / "access_keys.json"
    path.write_text(
        '{"next_id": 2, "keys": [{"id": 1, "key": "sk-old", "name": "legacy"}]}',
        encoding="utf-8",
    )

    entry = AccessKeyStore(file_path=str(path)).get(1)

    assert entry.key == "sk-old"
    assert (entry.input_tokens, entry.output_tokens) == (0, 0)
    assert entry.tokens_by_model is None


@pytest.mark.parametrize("junk", [
    "not-a-dict", 42, None,
    {"gemini-flash": "nope"},
    {"gemini-flash": {"in": "x", "out": 1}},
    {"gemini-flash": {"in": -1, "out": 1}},
    {"": {"in": 1, "out": 1}},
    {"gemini-flash": {"in": 0, "out": 0}},
])
def test_corrupt_token_maps_are_dropped_not_crashed(tmp_path, junk):
    """这个 dict 要落盘、还要进 JSONResponse —— 混进 NaN 就是永久 500。"""
    import json as _json
    path = tmp_path / "access_keys.json"
    path.write_text(_json.dumps(
        {"next_id": 2, "keys": [{"id": 1, "key": "sk-x", "tokens_by_model": junk}]}
    ), encoding="utf-8")

    entry = AccessKeyStore(file_path=str(path)).get(1)

    assert entry is not None
    assert entry.tokens_by_model is None


# ---------------------------------------------------------------------------
# 4. 价格表与美元估算
# ---------------------------------------------------------------------------

def test_prices_parse_and_bad_entries_are_ignored_without_raising():
    out = parse_token_prices(
        "gemini-pro=2.0/12.0, junk, nocolon, x=1, y=a/b, z=-1/2, ,gemini-flash=0.75/3.75"
    )

    assert out == {"gemini-pro": (2.0, 12.0), "gemini-flash": (0.75, 3.75)}


@pytest.mark.parametrize("raw", ["", None, "总之全是垃圾", "=/", "a=/", "a=1/"])
def test_a_broken_price_table_never_crashes(raw):
    assert parse_token_prices(raw) == {}


def test_an_unparsable_table_falls_back_to_the_builtin_defaults(monkeypatch):
    monkeypatch.setattr(settings, "token_prices", "全是垃圾")

    assert current_token_prices() == DEFAULT_TOKEN_PRICES


def test_a_configured_table_replaces_the_defaults_wholesale(monkeypatch):
    """运维显式写了一张表就完全按那张表算，否则"我把 pro 的价删了"会悄悄回落到内置价。"""
    monkeypatch.setattr(settings, "token_prices", "gemini-flash=1.0/2.0")

    prices = current_token_prices()
    assert prices == {"gemini-flash": (1.0, 2.0)}
    assert "gemini-pro" not in prices


def test_cost_is_computed_per_model_at_per_million_rates():
    cost = estimate_cost_usd(
        {"gemini-flash": {"in": 1_000_000, "out": 2_000_000}},
        {"gemini-flash": (0.75, 3.75)},
    )

    assert cost == pytest.approx(0.75 + 7.5)


def test_several_models_are_summed():
    cost = estimate_cost_usd(
        {"a": {"in": 1_000_000, "out": 0}, "b": {"in": 0, "out": 1_000_000}},
        {"a": (1.0, 0.0), "b": (0.0, 2.0)},
    )

    assert cost == pytest.approx(3.0)


@pytest.mark.parametrize("by_model", [None, {}, "x", {"unknown-model": {"in": 5, "out": 5}}])
def test_cost_is_none_when_nothing_can_be_priced(by_model):
    """返回 None 而不是 0.0 是故意的：「没花钱」和「不知道多少钱」是两件事。"""
    assert estimate_cost_usd(by_model, {"gemini-flash": (1.0, 1.0)}) is None


def test_a_priced_model_still_counts_when_another_one_is_unpriced():
    cost = estimate_cost_usd(
        {"gemini-flash": {"in": 1_000_000, "out": 0}, "mystery": {"in": 10**9, "out": 10**9}},
        {"gemini-flash": (2.0, 0.0)},
    )

    assert cost == pytest.approx(2.0)


def test_the_builtin_defaults_cover_every_public_model():
    """新加公开模型名（如 M1 的 gemini-argon）必须同步补内置价，不然面板上恒是 "—"。"""
    from app.core.gemini_client import PUBLIC_MODELS, _PUBLIC_FAMILY

    for name in list(PUBLIC_MODELS) + list(_PUBLIC_FAMILY):
        assert name in DEFAULT_TOKEN_PRICES, name
        assert DEFAULT_TOKEN_PRICES[name][0] > 0 and DEFAULT_TOKEN_PRICES[name][1] > 0

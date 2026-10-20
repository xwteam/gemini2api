"""非流式超时的分层（S7）与思考档位的映射（S8）。

S7：全族共用 60s 的 POST 超时会让"模型越强越容易被我们自己掐断"（同一道难题 pro /
    flash-thinking 实测 87 秒），掐断后还被通用重试放大成 60→等1s→60→等2s→60 =
    用户等 183 秒才看到失败。
S8：reasoning_effort 被布尔化后下游一律写死最高档，Codex / Cursor 这类默认带
    "low" / "minimal" 的客户端全部跑成最慢的档位。
"""

import asyncio
import json

import pytest
from curl_cffi.requests import RequestsError

from app.core import gemini_client as gc
from app.core.gemini_client import (MODEL_HEADER_KEY, THINKING_LEVEL_DEFAULT,
                                    THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW,
                                    THINKING_LEVEL_MEDIUM, _build_model_header_thinking,
                                    parse_thinking_level, thinking_level_of)

_AUTH = {"Authorization": "Bearer sk-test-key"}


# ---------------------------------------------------------------------------
# S7：按模型族分层
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini-3-pro", 300),
        ("gemini-3-flash", 120),
        ("gemini-3-flash-thinking", 120),
        ("gemini-3-flash-lite", 60),
        ("gemini-3-pro-advanced", 300),
        ("totally-unknown-model", 60),  # 认不出的族回落到兜底值
    ],
)
def test_timeout_is_tiered_by_family(model, expected):
    assert gc._generate_timeout(model, "写一段排序算法") == expected


def test_pro_gets_more_time_than_flash_lite():
    """核心不变量：越强的族给的时间必须越多（别让分层退化成一个常数）。"""
    pro = gc._generate_timeout("gemini-3-pro", "难题")
    lite = gc._generate_timeout("gemini-3-flash-lite", "难题")
    assert pro > lite


def test_image_intent_has_its_own_tier(monkeypatch):
    assert gc._generate_timeout("gemini-3-flash-lite", "画一张猫的图片") == 180
    monkeypatch.setattr(gc.settings, "generate_timeout_image", 240.0, raising=False)
    assert gc._generate_timeout("gemini-3-flash-lite", "画一张猫的图片") == 240


def test_config_overrides_a_family(monkeypatch):
    monkeypatch.setattr(gc.settings, "generate_timeouts", "pro=450,flash=90", raising=False)
    assert gc._generate_timeout("gemini-3-pro", "x") == 450
    assert gc._generate_timeout("gemini-3-flash", "x") == 90
    # 没被覆盖的族仍用内置分层
    assert gc._generate_timeout("gemini-3-flash-lite", "x") == 60


def test_broken_timeout_config_is_ignored(monkeypatch):
    monkeypatch.setattr(gc.settings, "generate_timeouts", "pro=abc,flash=,=7,pro", raising=False)
    assert gc._generate_timeout("gemini-3-pro", "x") == 300


# ---------------------------------------------------------------------------
# S7：必然超时的请求不许被重试三遍
# ---------------------------------------------------------------------------

def _client_with_failing_send(monkeypatch, exc):
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._healthy = True
    client._family_model = {}
    calls = []

    async def _send(*a, **kw):
        calls.append(True)
        raise exc

    monkeypatch.setattr(client, "_send_request", _send)

    async def _sleep(*a, **kw):
        return None

    monkeypatch.setattr(gc.asyncio, "sleep", _sleep)
    return client, calls


def test_curl_timeout_is_not_retried(monkeypatch):
    """curl 超时（code 28）= 我们自己掐断了一个还在生成的回答，再发两遍只会让用户多等。"""
    exc = RequestsError("Operation timed out", gc._CURL_TIMEDOUT)
    client, calls = _client_with_failing_send(monkeypatch, exc)

    with pytest.raises(RequestsError):
        asyncio.run(client.generate("hi", "gemini-flash"))

    assert len(calls) == 1, f"超时只能发一次，实际发了 {len(calls)} 次"


def test_asyncio_timeout_is_not_retried(monkeypatch):
    client, calls = _client_with_failing_send(monkeypatch, asyncio.TimeoutError())

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(client.generate("hi", "gemini-flash"))

    assert len(calls) == 1


def test_other_curl_errors_still_retry(monkeypatch):
    """零回归：非超时的失败（如连接重置）仍按 max_retries 重试。"""
    exc = RequestsError("Connection reset", 56)
    client, calls = _client_with_failing_send(monkeypatch, exc)

    with pytest.raises(Exception):
        asyncio.run(client.generate("hi", "gemini-flash"))

    assert len(calls) == gc.settings.max_retries == 3


def test_timeout_detector():
    assert gc._is_timeout_error(RequestsError("t", gc._CURL_TIMEDOUT)) is True
    assert gc._is_timeout_error(asyncio.TimeoutError()) is True
    assert gc._is_timeout_error(RequestsError("other", 56)) is False
    assert gc._is_timeout_error(RuntimeError("timed out")) is False


# ---------------------------------------------------------------------------
# S8：档位映射
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "effort,level",
    [
        ("low", 1),
        ("medium", 4),
        ("high", 2),
        # 客户端常带的别名，夹到合法档位
        ("none", 1),
        ("minimal", 1),
        ("xhigh", 2),
        (" XHigh ", 2),
        ("LOW", 1),
        # 空值 / 认不出的值 → 默认档（= 改动前写死的那个档），绝不抛错
        ("", THINKING_LEVEL_DEFAULT),
        (None, THINKING_LEVEL_DEFAULT),
        ("deep_think", THINKING_LEVEL_DEFAULT),
        ("3", THINKING_LEVEL_DEFAULT),
    ],
)
def test_parse_thinking_level(effort, level):
    assert parse_thinking_level(effort) == level


def test_level_constants_match_the_reference_mapping():
    """映射取自参考实现的断言（low→1 / medium→4 / high→2）；真机复验后改这三个常量即可。"""
    assert (THINKING_LEVEL_LOW, THINKING_LEVEL_MEDIUM, THINKING_LEVEL_HIGH) == (1, 4, 2)


@pytest.mark.parametrize(
    "value,level",
    [(True, THINKING_LEVEL_DEFAULT), (1, 1), (2, 2), (4, 4),
     ("nonsense", THINKING_LEVEL_DEFAULT), (None, THINKING_LEVEL_DEFAULT)],
)
def test_thinking_level_of(value, level):
    assert thinking_level_of(value) == level


def _inner(level=None):
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    c._session_uuid = "S"
    encoded, uuid_val = c._encode_payload_thinking("hello", "gemini-flash", "", None, None, level)
    return json.loads(json.loads(encoded)[1]), encoded, uuid_val


@pytest.mark.parametrize("level", [1, 2, 4])
def test_level_lands_in_payload_and_header(level):
    inner, _, _ = _inner(level)
    assert inner[80] == level
    arr = json.loads(_build_model_header_thinking("gemini-flash", "S", level)[MODEL_HEADER_KEY])
    assert arr[15] == level
    assert len(arr) == 17


_DEFAULT_PAYLOAD = (
    '[null, "[[\\"hello\\", 0, null, null, null, null, 0], [\\"en\\"], '
    '[\\"\\", \\"\\", \\"\\", null, null, null, null, null, null, \\"\\"], null, null, null, '
    '[1], 1, null, null, 1, 0, null, null, null, null, null, [[0]], 0, null, null, null, '
    'null, null, null, null, null, 1, null, null, [4], null, null, null, null, null, null, '
    'null, null, null, null, [1], null, null, null, null, null, null, null, null, null, '
    'null, null, 0, null, null, null, null, null, \\"UUID\\", null, [], null, null, null, '
    'null, null, null, 1, null, null, null, null, null, null, null, null, null, null, 1, 2]"]'
)


def test_default_path_is_byte_for_byte_unchanged():
    """最重要的一条：不传档位时的 payload 必须与改动前逐字节一致（只有随机 uuid 归一化）。"""
    _, encoded, uuid_val = _inner(None)
    assert encoded.replace(uuid_val, "UUID") == _DEFAULT_PAYLOAD
    arr = json.loads(_build_model_header_thinking("gemini-flash", "S")[MODEL_HEADER_KEY])
    assert arr[15] == 2


# ---------------------------------------------------------------------------
# S8：端到端（路由 → client 看到的档位）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "effort,expected",
    [("low", 1), ("medium", 4), ("high", 2), ("minimal", 1), ("xhigh", 2), ("weird", 2)],
)
def test_chat_completions_forwards_the_level(gem_client, monkeypatch, effort, expected):
    import app.routers.openai as oai

    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": effort,
    }, headers=_AUTH)

    assert r.status_code == 200
    assert captured["ext"] == expected


def test_chat_completions_without_effort_stays_off(gem_client, monkeypatch):
    """零回归：不传 reasoning_effort 时 extended_thinking 仍是 False（而不是某个档位）。"""
    import app.routers.openai as oai

    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)

    assert r.status_code == 200
    assert captured["ext"] is False


@pytest.mark.parametrize("effort,expected", [("low", 1), ("medium", 4), ("high", 2)])
def test_responses_forwards_the_level(gem_client, monkeypatch, effort, expected):
    import app.routers.responses as rp

    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        captured["ext"] = extended_thinking
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}

    monkeypatch.setattr(rp.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-flash", "input": "hi", "reasoning": {"effort": effort},
    }, headers=_AUTH)

    assert r.status_code == 200
    assert captured["ext"] == expected

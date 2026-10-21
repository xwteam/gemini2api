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
        # Argon 的心跳描述是 "Complex tasks"、和 pro 同级：给兜底的 60s 等于一道复杂题
        # 还在生成就被我们自己掐断。
        ("gemini-4-argon", 300),
        ("totally-unknown-model", 60),  # 认不出的族回落到兜底值
    ],
)
def test_timeout_is_tiered_by_family(model, expected):
    assert gc._generate_timeout(model, "写一段排序算法") == expected


def test_timeout_sees_heartbeat_discovered_models():
    """心跳发现来的模型在写死表里**没有行**。只读模块表的话它一律退到 60s 兜底，
    于是 M1 要自动接上的那种"Complex tasks"新模型会在还在生成时被我们自己掐断。"""
    discovered = {"gemini-5-xenon": {"id": "a" * 16, "capacity": 2, "pro_only": True,
                                     "family": "pro", "model_number": 9}}

    assert gc._generate_timeout("gemini-5-xenon", "难题") == 60, "只读写死表时退兜底"
    assert gc._generate_timeout("gemini-5-xenon", "难题", discovered) == 300, \
        "传了账号实例表就该按发现到的 family 分层"


def test_pro_gets_more_time_than_flash_lite():
    """核心不变量：越强的族给的时间必须越多（别让分层退化成一个常数）。"""
    pro = gc._generate_timeout("gemini-3-pro", "难题")
    lite = gc._generate_timeout("gemini-3-flash-lite", "难题")
    assert pro > lite


def test_image_intent_has_its_own_tier(monkeypatch):
    assert gc._generate_timeout("gemini-3-flash-lite", "画一张猫的图片") == 180
    monkeypatch.setattr(gc.settings, "generate_timeout_image", 240.0, raising=False)
    assert gc._generate_timeout("gemini-3-flash-lite", "画一张猫的图片") == 240


def test_image_tier_raises_the_budget_and_never_lowers_it(monkeypatch):
    """生图档是"取大"不是"覆盖"：pro 生一张图不能比 pro 答一道文字难题还短。

    生图是整个产品里最慢的操作（注释自己写着"生图 pro 常 >60s"），而 pro 的文字档是
    300s —— 覆盖式实现会把它压回 180s，正好把最慢的场景给了最短的预算，与 S7 的立意相反。
    """
    pro_text = gc._generate_timeout("gemini-3-pro", "证明一下这个定理")
    pro_image = gc._generate_timeout("gemini-3-pro", "画一张赛博朋克城市的图")
    assert pro_text == 300
    assert pro_image == 300, "pro 生图不能比 pro 纯文本更短"

    # 低档族仍然被生图档抬上去
    assert gc._generate_timeout("gemini-3-flash-lite", "画一张猫的图") == 180
    assert gc._generate_timeout("gemini-3-flash", "画一张猫的图") == 180


def test_loose_image_keywords_never_shorten_a_strong_family():
    """宽松判定的输入是拍平后的整段 prompt（含 system 与全部历史），误判面很大。
    既然它只会"加时"，一句含图像关键词的多轮难题就不会把 pro 从 300s 砍到 180s。"""
    from app.utils.tools import maybe_image_generation_intent

    text = "想做个图像识别的方案，先帮我证明这个复杂度下界"
    assert maybe_image_generation_intent(text) is True, "判定前提：这句确实会被误判成生图"
    assert gc._generate_timeout("gemini-3-pro", text) == 300


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


def test_generation_timeout_is_not_retried(monkeypatch):
    """生成期超时 = 我们自己掐断了一个还在生成的回答，再发两遍只会让用户多等。"""
    exc = gc.GenerationTimedOut(120.0, 121.0, RequestsError("Operation timed out",
                                                            gc._CURL_TIMEDOUT))
    client, calls = _client_with_failing_send(monkeypatch, exc)

    with pytest.raises(gc.GenerationTimedOut):
        asyncio.run(client.generate("hi", "gemini-flash"))

    assert len(calls) == 1, f"生成期超时只能发一次，实际发了 {len(calls)} 次"


def test_connect_phase_timeout_is_still_retried(monkeypatch):
    """连接期的超时同样是 curl code 28，但它该重试 —— 原样再发一次大概率就通了。

    过去这两种超时混在一条 `_is_timeout_error` 判断里：一次短暂的建连超时既不重试、
    也不是 5xx（account_pool 不会换号），用户直接拿到 500 硬失败。
    """
    exc = RequestsError("Operation timed out", gc._CURL_TIMEDOUT)
    client, calls = _client_with_failing_send(monkeypatch, exc)

    with pytest.raises(Exception):
        asyncio.run(client.generate("hi", "gemini-flash"))

    assert len(calls) == gc.settings.max_retries == 3


def test_asyncio_timeout_is_retried_like_any_other_failure(monkeypatch):
    """裸 asyncio.TimeoutError 不再被当成生成期超时（它不带耗时信息，分不出是哪一段）。"""
    client, calls = _client_with_failing_send(monkeypatch, asyncio.TimeoutError())

    with pytest.raises(Exception):
        asyncio.run(client.generate("hi", "gemini-flash"))

    assert len(calls) == gc.settings.max_retries == 3


# ---------------------------------------------------------------------------
# S7：生成期超时 vs 连接期超时的判定（按耗时，不按 curl code）
# ---------------------------------------------------------------------------

def _send_request_client(monkeypatch, *, budget: float, delay: float, exc):
    """让 _send_request 的 POST 等 delay 秒后抛 exc，整体预算是 budget 秒。"""
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._session_token = "TOKEN"
    client._session_uuid = "SESSION-UUID"
    client._family_model = {}
    client._push_id = ""

    class _Jar:
        def update_from_response(self, resp):
            return None

    client._cookie_jar = _Jar()

    class _Http:
        async def post(self, *a, **kw):
            await asyncio.sleep(delay)
            raise exc

    client._http = _Http()

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(gc, "apply_jitter", _noop)
    monkeypatch.setattr(gc, "_generate_timeout", lambda *a, **kw: budget)
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_clear_session_cookies", lambda: None)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    return client


def test_a_timeout_that_ate_the_whole_budget_is_a_generation_timeout(monkeypatch):
    client = _send_request_client(
        monkeypatch, budget=0.05, delay=0.06,
        exc=RequestsError("Operation timed out", gc._CURL_TIMEDOUT),
    )

    with pytest.raises(gc.GenerationTimedOut) as ei:
        asyncio.run(client._send_request("hi", "gemini-flash"))

    assert ei.value.budget == 0.05
    assert ei.value.elapsed >= 0.05


def test_a_fast_timeout_stays_a_plain_connection_error(monkeypatch):
    """几毫秒就回来的 code 28 = 建连阶段的瞬断，不许被当成生成期超时。"""
    client = _send_request_client(
        monkeypatch, budget=5.0, delay=0.0,
        exc=RequestsError("Operation timed out", gc._CURL_TIMEDOUT),
    )

    with pytest.raises(RequestsError) as ei:
        asyncio.run(client._send_request("hi", "gemini-flash"))

    assert not isinstance(ei.value, gc.GenerationTimedOut)


def test_non_timeout_failures_are_untouched(monkeypatch):
    """零回归：非超时的错误原样抛出，不被包装。"""
    client = _send_request_client(
        monkeypatch, budget=0.05, delay=0.06,
        exc=RequestsError("Connection reset", 56),
    )

    with pytest.raises(RequestsError) as ei:
        asyncio.run(client._send_request("hi", "gemini-flash"))

    assert not isinstance(ei.value, gc.GenerationTimedOut)
    assert ei.value.code == 56


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
    # `True == 1` 在 Python 里成立：不排掉 True，"把整条改动还原成 bool(_eff)" 这个变异
    # 在 low / minimal 两档上活得下来，这两条用例等于没有守卫。
    assert captured["ext"] is not True


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
    assert captured["ext"] is not True


def test_send_request_hands_the_account_table_to_the_timeout_tiering(monkeypatch):
    """call-site 回归：_send_request 必须把账号实例表传进 _generate_timeout。
    只传 (resolved, prompt) 的话，心跳发现来的模型查不到 family → 退到 60s 兜底。"""
    seen = {}

    client = _send_request_client(
        monkeypatch, budget=5.0, delay=0.0,
        exc=RequestsError("Connection reset", 56),
    )
    client._discovered_models = {
        "gemini-5-xenon": {"id": "b" * 16, "capacity": 2, "pro_only": True,
                           "family": "pro", "model_number": 9},
    }

    def _spy(resolved, prompt, models=None):
        seen["resolved"] = resolved
        seen["models"] = models
        return 5.0

    monkeypatch.setattr(gc, "_generate_timeout", _spy)

    with pytest.raises(RequestsError):
        asyncio.run(client._send_request("hi", "gemini-5-xenon"))

    assert seen["resolved"] == "gemini-5-xenon"
    assert seen["models"] is not None, "没传账号表 = 发现来的模型一律 60s"
    assert "gemini-5-xenon" in seen["models"]

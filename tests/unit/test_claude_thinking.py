"""M5：Anthropic 协议的思考链。

改动前 `grep -rn thinking app/routers/claude.py` 零命中：ClaudeRequest 没有 thinking
字段（pydantic 默认 extra="ignore"），Claude Code 发的
`thinking: {type:"enabled", budget_tokens:N}` 在校验阶段就被静默吃掉；真流式里
`{"type":"thoughts"}` 事件也被 if/elif 整个漏掉。于是 Anthropic 协议用户永远锁死在
"不思考"，而 OpenAI 协议用户可以用 reasoning_effort 选档 —— 同一个后端两种协议表现不一致。

零回归红线：**不传 thinking 时响应/帧序列逐字节不变**。这一条尤其要紧，因为底层
candidate[37] 的 thoughts 解析跟 extended_thinking 无关、是无条件跑的，所以"有
thoughts 就吐 thinking 块"会改掉所有既有请求的响应形状。
"""

import json

import pytest

from app.core.gemini_client import (
    THINKING_FOLLOW_DEFAULT, THINKING_LEVEL_DEFAULT, THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW,
    THINKING_LEVEL_MEDIUM, parse_anthropic_thinking,
)

_AUTH = {"Authorization": "Bearer sk-test-key"}


def _parse_sse(body: str):
    out = []
    for chunk in body.split("\n\n"):
        ev, data = None, None
        for line in chunk.split("\n"):
            if line.startswith(":") or not line.strip():
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if ev or data:
            out.append((ev, data))
    return out


def _result(text="答案", thoughts="我先想想"):
    return {"text": text, "conversation_id": "", "images": [], "thoughts": thoughts}


def _patch_generate(monkeypatch, result=None, captured=None):
    import app.routers.claude as cl

    async def _gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        if captured is not None:
            captured.append(extended_thinking)
        return result if result is not None else _result()

    monkeypatch.setattr(cl.gemini_client, "generate", _gen)


def _patch_stream(monkeypatch, events, captured=None):
    import app.routers.claude as cl

    async def _gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        if captured is not None:
            captured.append(extended_thinking)
        for evt in events:
            yield evt

    monkeypatch.setattr(cl.gemini_client, "generate_stream", _gen)


def _post(client, **extra):
    body = {"model": "gemini-flash", "max_tokens": 128,
            "messages": [{"role": "user", "content": "hi"}]}
    body.update(extra)
    return client.post("/v1/messages", json=body, headers=_AUTH)


# ---------------------------------------------------------------------------
# 1. 入参 → 档位
# ---------------------------------------------------------------------------

# 返回值四态（v1.6.43 起）：None = 没传（上游按"默认思考档位"、不出 thinking 块）、
# False = 明确不要、1/2/4 = 明确要了某一档、THINKING_FOLLOW_DEFAULT = 要了思考但没给档位
# （跟随默认档）。过去"没传"与"明确不要"都是 False —— 那时"没传"就等于不思考；现在用户
# 要求"没传"走默认档 low，两者必须分开。
@pytest.mark.parametrize("payload,expected", [
    (None, None),
    ({}, None),
    ("enabled", None),
    ({"type": "disabled"}, False),
    ({"type": "between_tools"}, False),
    ({"type": "something-new"}, None),
    ({"type": "adaptive"}, THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive", "display": "summarized"}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled"}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled", "budget_tokens": None}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled", "budget_tokens": "4096"}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled", "budget_tokens": 0}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled", "budget_tokens": -1}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled", "budget_tokens": True}, THINKING_FOLLOW_DEFAULT),
    ({"type": "enabled", "budget_tokens": 1}, THINKING_LEVEL_LOW),
    ({"type": "enabled", "budget_tokens": 1024}, THINKING_LEVEL_LOW),
    ({"type": "enabled", "budget_tokens": 2047}, THINKING_LEVEL_LOW),
    ({"type": "enabled", "budget_tokens": 2048}, THINKING_LEVEL_MEDIUM),
    ({"type": "enabled", "budget_tokens": 4095}, THINKING_LEVEL_MEDIUM),
    ({"type": "enabled", "budget_tokens": 4096}, THINKING_LEVEL_HIGH),
    ({"type": "enabled", "budget_tokens": 31999}, THINKING_LEVEL_HIGH),
    ({"type": "ENABLED", "budget_tokens": 4096}, THINKING_LEVEL_HIGH),
])
def test_parse_anthropic_thinking(payload, expected):
    got = parse_anthropic_thinking(payload)
    assert got == expected and type(got) is type(expected)


# output_config.effort（Claude Code 的 /effort 走这里）。Claude Code 2.1.296 抓包：每个请求都带
# thinking={"type":"adaptive","display":"omitted"} + output_config={"effort":"high"}。
# high 是 Anthropic 的默认值（官方：设成 high 与不传完全相同）→ 跟随默认档。
@pytest.mark.parametrize("thinking,output_config,expected", [
    # Claude Code 出厂请求
    ({"type": "adaptive", "display": "omitted"}, {"effort": "high"}, THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive"}, None, THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive"}, {}, THINKING_FOLLOW_DEFAULT),
    # /effort 换档
    ({"type": "adaptive"}, {"effort": "low"}, THINKING_LEVEL_LOW),
    ({"type": "adaptive"}, {"effort": "medium"}, THINKING_LEVEL_MEDIUM),
    ({"type": "adaptive"}, {"effort": "xhigh"}, THINKING_LEVEL_HIGH),
    ({"type": "adaptive"}, {"effort": "max"}, THINKING_LEVEL_HIGH),
    ({"type": "adaptive"}, {"effort": " Low "}, THINKING_LEVEL_LOW),
    ({"type": "adaptive"}, {"effort": "MAX"}, THINKING_LEVEL_HIGH),
    # 认不出 / 形态不对 → 宽容，跟随默认档，绝不报错
    ({"type": "adaptive"}, {"effort": "turbo"}, THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive"}, {"effort": 3}, THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive"}, {"effort": None}, THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive"}, "low", THINKING_FOLLOW_DEFAULT),
    ({"type": "adaptive"}, ["low"], THINKING_FOLLOW_DEFAULT),
    # enabled：合法 budget 优先于 effort；budget 缺失/无效时看 effort
    ({"type": "enabled", "budget_tokens": 1024}, {"effort": "max"}, THINKING_LEVEL_LOW),
    ({"type": "enabled", "budget_tokens": 8192}, {"effort": "low"}, THINKING_LEVEL_HIGH),
    ({"type": "enabled"}, {"effort": "low"}, THINKING_LEVEL_LOW),
    ({"type": "enabled", "budget_tokens": 0}, {"effort": "medium"}, THINKING_LEVEL_MEDIUM),
    ({"type": "enabled", "budget_tokens": "4096"}, {"effort": "high"}, THINKING_FOLLOW_DEFAULT),
    # 明确关闭 / 没开 thinking：effort 给什么都不改变
    ({"type": "disabled"}, {"effort": "max"}, False),
    ({"type": "between_tools"}, {"effort": "max"}, False),
    (None, {"effort": "max"}, None),
    ({}, {"effort": "low"}, None),
    ({"type": "something-new"}, {"effort": "max"}, None),
])
def test_output_config_effort_picks_the_level(thinking, output_config, expected):
    got = parse_anthropic_thinking(thinking, output_config)
    assert got == expected and type(got) is type(expected)


@pytest.mark.parametrize("payload", [{"type": "disabled"}, {"type": "between_tools"}])
def test_the_official_off_forms_are_not_logged_as_unrecognized(caplog, payload):
    """disabled / between_tools 是官方明确的"关思考"写法，不是"我们认不出的 type"。
    打成 unrecognized 会在排查时把人往"客户端发错了"的方向带。"""
    import logging

    from app.core import gemini_client as gc
    caplog.set_level(logging.INFO, logger=gc.logger.name)

    assert parse_anthropic_thinking(payload) is False
    assert not [r for r in caplog.records if "Unrecognized" in r.getMessage()]


def test_an_unknown_type_is_logged(caplog):
    """认不出的 type 要留一行，否则"新版客户端发了我们不认识的写法"永远查不出来。
    它按"没传"处理（None）：上游走默认档，但不凭猜测去开 thinking 块。"""
    import logging

    from app.core import gemini_client as gc
    caplog.set_level(logging.INFO, logger=gc.logger.name)

    assert parse_anthropic_thinking({"type": "something-new"}) is None
    assert any("Unrecognized" in r.getMessage() for r in caplog.records)


def test_the_level_constants_match_the_measured_mapping():
    """low→1 / medium→4 / high→2 来自参考实现的测试断言（gemini_thinking_test.go:20）。
    真机实测（gemini-pro，每档 2 次）：high(2) 思考 1256/562 字、42～65 秒，已证实是最深
    的一档；low(1) 411/707 字与 medium(4) 524/450 字两次采样区分不开，沿用参考实现。
    THINKING_LEVEL_DEFAULT 只是底层编码器拿到空档位时的静态兜底，保持改动前的 2；"要了思考
    但没给可认档位"的请求不用它，而是跟随默认思考档位（THINKING_FOLLOW_DEFAULT）。"""
    assert (THINKING_LEVEL_LOW, THINKING_LEVEL_MEDIUM, THINKING_LEVEL_HIGH) == (1, 4, 2)
    assert THINKING_LEVEL_DEFAULT == 2


def test_the_requested_level_reaches_generate(gem_client, monkeypatch):
    captured: list = []
    _patch_generate(monkeypatch, captured=captured)

    _post(gem_client, thinking={"type": "enabled", "budget_tokens": 1024})
    _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})
    _post(gem_client)

    # 第三次没传 thinking → "默认思考档位"设置（出厂 low），用户要求的新默认
    assert captured == [THINKING_LEVEL_LOW, THINKING_LEVEL_HIGH, THINKING_LEVEL_LOW]


def test_the_global_switch_still_wins(gem_client, monkeypatch):
    from app.config import settings
    captured: list = []
    _patch_generate(monkeypatch, captured=captured)
    monkeypatch.setattr(settings, "extended_thinking_enabled", False)

    _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})

    assert captured == [False]


# ---------------------------------------------------------------------------
# 2. 非流式：thinking 块
# ---------------------------------------------------------------------------

def test_nonstream_returns_a_thinking_block_before_the_text_block(gem_client, monkeypatch):
    _patch_generate(monkeypatch)

    body = _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096}).json()

    assert body["content"] == [
        {"type": "thinking", "thinking": "我先想想"},
        {"type": "text", "text": "答案", "citations": None},
    ]
    assert "signature" not in body["content"][0], "造不出合法签名就不发，发空串更坏"


def test_nonstream_counts_thinking_tokens_into_output(gem_client, monkeypatch):
    from app.utils.tools import estimate_tokens
    _patch_generate(monkeypatch)

    body = _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096}).json()

    assert body["usage"]["output_tokens"] == estimate_tokens("答案") + estimate_tokens("我先想想")


def test_nonstream_without_thinking_is_byte_for_byte_unchanged(gem_client, monkeypatch):
    """底层的 thoughts 解析是无条件的，所以这条是 M5 的核心零回归用例。"""
    from app.utils.tools import estimate_tokens
    _patch_generate(monkeypatch)

    body = _post(gem_client).json()

    assert body["content"] == [{"type": "text", "text": "答案", "citations": None}]
    assert body["usage"]["output_tokens"] == estimate_tokens("答案")


@pytest.mark.parametrize("payload", [{"type": "disabled"}, {"type": "between_tools"}])
def test_disabled_thinking_matches_not_passing_it_at_all(gem_client, monkeypatch, payload):
    _patch_generate(monkeypatch)

    with_off = _post(gem_client, thinking=payload).json()
    without = _post(gem_client).json()

    with_off.pop("id"), without.pop("id")
    assert with_off == without


def test_an_empty_thinking_chain_does_not_produce_an_empty_block(gem_client, monkeypatch):
    _patch_generate(monkeypatch, result=_result(thoughts="   "))

    body = _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096}).json()

    assert body["content"] == [{"type": "text", "text": "答案", "citations": None}]


# ---------------------------------------------------------------------------
# 3. 真流式
# ---------------------------------------------------------------------------

STREAM_EVENTS = [
    {"type": "thoughts", "text": "先想"},
    {"type": "thoughts", "text": "再想"},
    {"type": "delta", "text": "答"},
    {"type": "delta", "text": "案"},
    {"type": "final", "text": "答案", "conversation_id": "", "images": [], "thoughts": "先想再想"},
]


def _stream(client, **extra):
    body = {"model": "gemini-flash", "max_tokens": 128, "stream": True,
            "messages": [{"role": "user", "content": "hi"}]}
    body.update(extra)
    with client.stream("POST", "/v1/messages", json=body, headers=_AUTH) as r:
        return _parse_sse("".join(r.iter_text()))


def test_realstream_emits_a_thinking_block_then_the_text_block(gem_client, monkeypatch):
    _patch_stream(monkeypatch, STREAM_EVENTS)

    events = _stream(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})
    shape = [(ev, (d or {}).get("index"),
              (d or {}).get("content_block", {}).get("type")
              or (d or {}).get("delta", {}).get("type"))
             for ev, d in events]

    assert shape == [
        ("message_start", None, None),
        ("content_block_start", 0, "thinking"),
        ("content_block_delta", 0, "thinking_delta"),
        ("content_block_delta", 0, "thinking_delta"),
        ("content_block_stop", 0, None),
        ("content_block_start", 1, "text"),
        ("content_block_delta", 1, "text_delta"),
        ("content_block_delta", 1, "text_delta"),
        ("content_block_stop", 1, None),
        ("message_delta", None, None),
        ("message_stop", None, None),
    ]
    thinking = [d["delta"]["thinking"] for ev, d in events
                if ev == "content_block_delta" and d["delta"]["type"] == "thinking_delta"]
    assert thinking == ["先想", "再想"]


def test_realstream_without_thinking_is_byte_for_byte_unchanged(gem_client, monkeypatch):
    _patch_stream(monkeypatch, STREAM_EVENTS)

    events = _stream(gem_client)
    shape = [(ev, (d or {}).get("index")) for ev, d in events]

    assert shape == [
        ("message_start", None),
        ("content_block_start", 0),
        ("content_block_delta", 0),
        ("content_block_delta", 0),
        ("content_block_stop", 0),
        ("message_delta", None),
        ("message_stop", None),
    ]
    assert not any("thinking" in json.dumps(d) for _ev, d in events)


def test_realstream_thoughts_arriving_only_in_the_final_frame_still_land(gem_client, monkeypatch):
    _patch_stream(monkeypatch, [
        {"type": "final", "text": "答案", "conversation_id": "", "images": [],
         "thoughts": "收尾才给的思考"},
    ])

    events = _stream(gem_client, thinking={"type": "enabled", "budget_tokens": 2048})
    kinds = [(ev, (d or {}).get("index")) for ev, d in events]

    assert ("content_block_start", 0) in kinds
    assert events[1][1]["content_block"]["type"] == "thinking"
    assert any(d.get("delta", {}).get("thinking") == "收尾才给的思考"
               for ev, d in events if ev == "content_block_delta")


def test_realstream_late_thoughts_after_text_are_dropped_not_misordered(gem_client, monkeypatch):
    """Anthropic 规定 thinking 块排在 text 之前。文本块一开就回不去了，
    迟到的思考增量只能丢，绝不能在 text 之后插一个顺序违规的 thinking 块。"""
    _patch_stream(monkeypatch, [
        {"type": "delta", "text": "答案"},
        {"type": "thoughts", "text": "迟到的思考"},
        {"type": "final", "text": "答案", "conversation_id": "", "images": [], "thoughts": "迟到的思考"},
    ])

    events = _stream(gem_client, thinking={"type": "enabled", "budget_tokens": 2048})
    starts = [(ev, d["index"], d["content_block"]["type"])
              for ev, d in events if ev == "content_block_start"]

    assert starts == [("content_block_start", 0, "text")]
    assert "迟到的思考" not in json.dumps(events, ensure_ascii=False)


def test_realstream_counts_thinking_tokens_into_output(gem_client, monkeypatch):
    from app.utils.tools import estimate_tokens
    _patch_stream(monkeypatch, STREAM_EVENTS)

    events = _stream(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})
    delta = next(d for ev, d in events if ev == "message_delta")

    assert delta["usage"]["output_tokens"] == \
        estimate_tokens("答案") + estimate_tokens("先想再想")


# ---------------------------------------------------------------------------
# 4. buffered 流式（带 tools，Claude Code 走的就是这条）
# ---------------------------------------------------------------------------

_TOOLS = [{"name": "get_weather", "description": "d",
           "input_schema": {"type": "object", "properties": {}}}]


def test_buffered_text_block_index_shifts_by_one_when_thinking_is_on(gem_client, monkeypatch):
    """带 tools 时走 buffered（tool_calls 必须拿到完整 JSON 才能解析）。
    这里上游回的不是工具 JSON，于是回落成普通文本块 —— buffered 的文本路径。"""
    _patch_generate(monkeypatch)

    events = _stream(gem_client, tools=_TOOLS,
                     thinking={"type": "enabled", "budget_tokens": 4096})
    starts = [(d["index"], d["content_block"]["type"])
              for ev, d in events if ev == "content_block_start"]

    assert starts == [(0, "thinking"), (1, "text")]


def test_buffered_tool_blocks_shift_by_one_and_keep_tool_use(gem_client, monkeypatch):
    _patch_generate(monkeypatch, result=_result(
        text='{"tool_calls":[{"name":"get_weather","arguments":{}}]}'))

    events = _stream(gem_client, tools=_TOOLS,
                     thinking={"type": "enabled", "budget_tokens": 4096})
    starts = [(d["index"], d["content_block"]["type"])
              for ev, d in events if ev == "content_block_start"]
    delta = next(d for ev, d in events if ev == "message_delta")

    assert starts == [(0, "thinking"), (1, "tool_use")]
    assert delta["delta"]["stop_reason"] == "tool_use"


def test_buffered_tool_blocks_are_zero_based_without_thinking(gem_client, monkeypatch):
    """索引写错会让客户端把 tool_use 和 thinking 块对错号 → 工具调用直接失效。"""
    _patch_generate(monkeypatch, result=_result(
        text='{"tool_calls":[{"name":"get_weather","arguments":{}}]}'))

    events = _stream(gem_client, tools=_TOOLS)
    starts = [(d["index"], d["content_block"]["type"])
              for ev, d in events if ev == "content_block_start"]

    assert starts == [(0, "tool_use")]
    assert not any("thinking" in json.dumps(d) for _ev, d in events)


def test_buffered_without_thinking_is_byte_for_byte_unchanged(gem_client, monkeypatch):
    _patch_generate(monkeypatch)

    events = _stream(gem_client)
    starts = [(d["index"], d["content_block"]["type"])
              for ev, d in events if ev == "content_block_start"]

    assert starts == [(0, "text")]
    assert not any("thinking" in json.dumps(d) for _ev, d in events)


# ---------------------------------------------------------------------------
# 6. 非 dict 的 thinking 不许变成 FastAPI 原生 422
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", ["enabled", 5, True, [], 1.5])
def test_a_non_dict_thinking_behaves_like_not_passing_it(gem_client, monkeypatch, payload):
    """这个字段加进来之前是被 pydantic extra="ignore" 静默吞掉、请求照常 200。
    限成 `dict | None` 会把它变成 FastAPI 原生 422：既改了既有状态码，响应体
    `{"detail":[...]}` 也不是 Anthropic 的 `{"type":"error","error":{...}}` 形状，
    SDK 拿到它会报解析错误而不是一条可读的报错。parse_anthropic_thinking 本身对非 dict
    是宽容的（返回 None = 没传），放开类型正是为了让那份宽容真的生效。"""
    captured = []
    _patch_generate(monkeypatch, captured=captured)

    resp = _post(gem_client, thinking=payload)

    assert resp.status_code == 200, resp.text
    # 等价于「没传」：上游按默认档（出厂 low）思考，但绝不出 thinking 块
    assert captured == [THINKING_LEVEL_LOW], "非 dict 必须等价于「没传」"
    assert not any(b.get("type") == "thinking" for b in resp.json()["content"])


def test_a_non_dict_thinking_gives_the_same_body_as_omitting_it(gem_client, monkeypatch):
    _patch_generate(monkeypatch)

    weird = _post(gem_client, thinking="enabled").json()
    without = _post(gem_client).json()

    weird.pop("id"), without.pop("id")
    assert weird == without


# ---------------------------------------------------------------------------
# 7. 非流式：开思考失败后退回非思考重试
# ---------------------------------------------------------------------------

def _patch_generate_failing_on_thinking(monkeypatch, exc, *, fail_all=False):
    """开思考的那次调用抛 exc；退回非思考的那次按 fail_all 决定成功还是继续抛。"""
    import app.routers.claude as cl

    calls = []

    async def _gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        calls.append(extended_thinking)
        if extended_thinking or fail_all:
            raise exc
        return _result(text="退回后的答案", thoughts="这段思考不该被吐出来")

    monkeypatch.setattr(cl.gemini_client, "generate", _gen)
    return calls


def test_a_failed_thinking_request_retries_without_thinking(gem_client, monkeypatch):
    """开思考 = 走另一套 payload + header，失败率和普通路径不同。不退回重试的话，
    "勾了思考"会把整条请求搞挂（镜像 openai.py 既有做法）。"""
    calls = _patch_generate_failing_on_thinking(monkeypatch, RuntimeError("thinking boom"))

    resp = _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})

    assert resp.status_code == 200, resp.text
    assert calls == [THINKING_LEVEL_HIGH, False], "必须先按档位试一次、再退回非思考试一次"
    assert resp.json()["content"][-1]["text"] == "退回后的答案"


def test_the_retry_turn_does_not_claim_it_was_thinking(gem_client, monkeypatch):
    """退回成功时那一轮确实没有思考。底层 candidate[37] 的解析是无条件跑的，所以
    不把 extended_thinking 关掉就会给一个"证明没思考过"的回答配上 thinking 块。"""
    _patch_generate_failing_on_thinking(monkeypatch, RuntimeError("thinking boom"))

    body = _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096}).json()

    assert [b["type"] for b in body["content"]] == ["text"]
    assert "这段思考不该被吐出来" not in json.dumps(body)


def test_both_attempts_failing_still_returns_an_anthropic_error(gem_client, monkeypatch):
    """零回归：退回那次也失败时，报的是第二次的错，信封仍是 Anthropic 形状。"""
    calls = _patch_generate_failing_on_thinking(
        monkeypatch, RuntimeError("Client not ready"), fail_all=True)

    resp = _post(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})

    assert calls == [THINKING_LEVEL_HIGH, False]
    assert resp.status_code != 200
    body = resp.json()
    assert body["type"] == "error"
    assert body["error"]["type"] and "not ready" in body["error"]["message"]


def test_with_default_off_a_failure_is_not_retried(gem_client, monkeypatch):
    """零回归：默认档 off 且不传 thinking 时走不思考路径，**只调一次**，不许凭空多打一次上游。
    （v1.6.42 里"不传"就是这条路径；现在"不传"走默认档，off 才回到它。）"""
    from app.config import settings
    monkeypatch.setattr(settings, "default_thinking_level", "off")
    calls = _patch_generate_failing_on_thinking(
        monkeypatch, RuntimeError("Client not ready"), fail_all=True)

    resp = _post(gem_client)

    assert calls == [False]
    assert resp.status_code != 200


def test_a_failed_default_level_request_retries_without_thinking(gem_client, monkeypatch):
    """默认档（出厂 low）也走思考路径，失败时同样退回不思考重试一次 —— 否则默认开 low
    会比改动前多出一类硬失败。退回后的那一轮没有思考，当然也不出 thinking 块。"""
    calls = _patch_generate_failing_on_thinking(monkeypatch, RuntimeError("thinking boom"))

    resp = _post(gem_client)

    assert resp.status_code == 200, resp.text
    assert calls == [THINKING_LEVEL_LOW, False]
    assert [b["type"] for b in resp.json()["content"]] == ["text"]


# ---------------------------------------------------------------------------
# 8. 正文块开了之后迟到的思考增量：丢是规范要求的，但不许静默
# ---------------------------------------------------------------------------

_LATE_EVENTS = [
    {"type": "delta", "text": "He"},
    {"type": "thoughts", "text": "LATE"},
    {"type": "delta", "text": "llo"},
    {"type": "final", "text": "Hello", "thoughts": "LATE", "images": []},
]


def test_late_thinking_deltas_are_dropped_but_logged(gem_client, monkeypatch, caplog):
    """思考与正文交错时（上游在正文开始后还在增长 candidate[37]），后到的思考增量
    只能丢：Anthropic 的块顺序不允许在 text 之后再开/再续 thinking 块。但这是
    reasoning 通道的丢内容 —— 同一次生成在 OpenAI 协议侧是完整的 —— 所以必须有
    WARNING 说清丢了多少，而不是一行看不见的 debug。"""
    import logging

    caplog.set_level(logging.WARNING, logger="app.routers.claude")
    _patch_stream(monkeypatch, _LATE_EVENTS)

    events = _stream(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})

    # 正文完整（不是数据损坏），但一个 thinking 块都没有
    text = "".join(d["delta"]["text"] for ev, d in events
                   if ev == "content_block_delta" and d["delta"]["type"] == "text_delta")
    assert text == "Hello"
    assert not any("thinking" in json.dumps(d) for _ev, d in events)

    messages = [r.getMessage() for r in caplog.records]
    assert any("late thinking delta" in m for m in messages), messages
    assert any("short by 4 char(s)" in m for m in messages), messages


def test_thinking_that_arrives_before_the_text_is_not_logged(gem_client, monkeypatch, caplog):
    """零回归：正常顺序（思考先到）一个告警都不许打，否则日志天天在喊狼来了。"""
    import logging

    caplog.set_level(logging.WARNING, logger="app.routers.claude")
    _patch_stream(monkeypatch, [
        {"type": "thoughts", "text": "T1"},
        {"type": "delta", "text": "答"},
        {"type": "final", "text": "答", "thoughts": "T1", "images": []},
    ])

    events = _stream(gem_client, thinking={"type": "enabled", "budget_tokens": 4096})

    starts = [(d["index"], d["content_block"]["type"])
              for ev, d in events if ev == "content_block_start"]
    assert starts == [(0, "thinking"), (1, "text")]
    assert not [r for r in caplog.records if "thinking" in r.getMessage()]

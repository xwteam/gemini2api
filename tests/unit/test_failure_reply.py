"""谷歌的「失败套话」不能当正常回答交付（v1.6.46 规格 A，非流式部分 + H.6 / H.7 / H.8）。

线上（中转站三账号，北京 2026-10-26 14:18～14:4x、16:43～17:2x）：gemini-flash 谷歌侧故障时，
有一种表现是 1.2 秒就回 HTTP 200，正文恰好是一句
    I seem to be encountering an error. Can I try something else for you?
我们把它当正常回答返回给客户端，还存进了会话记录。参考实现
refs/gemini-web-to-api/internal/modules/providers/gemini_music_test.go:93 也把这句列为
「Gemini Web 报错」。

本文件钉住：
  - 判定是纯函数：整段正文规范化后**恰好等于**某条套话才算；前缀 / 包含 / 带图 / 回声都不算；
    GEMINI_FAILURE_REPLIES 可追加，内置那句始终生效；
  - 回声保护只看非 assistant 内容（H.6）：历史里 assistant 说过这句，不能让识别失效；
  - _send_request 解析完就判，命中抛 GeminiFailureReply（HTTPStatusError 子类、502）；
  - generate() 对它不做同账号 5xx 快速重试（H.7），池按 5xx 换号 + 软冷却；
  - 各端点沿用既有的非超时上游错误映射（H.8），OpenAI chat 能走兜底；
  - 套话不进会话记录，也不算空响应。
"""

import asyncio
import json
import logging

import pytest

from app.core import gemini_client as gc
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.gemini_client import GeminiWebClient, HTTPStatusError, classify_error
from app.utils.prompt import build_prompt_from_messages

PHRASE = "I seem to be encountering an error. Can I try something else for you?"
_AUTH = {"Authorization": "Bearer sk-test-key"}


# ---------------------------------------------------------------------------
# 纯函数判定
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    PHRASE,
    f"  {PHRASE}\n",
    "i SEEM to be   encountering an error.\nCan I try   something else for you?",
    PHRASE.upper(),
], ids=["exact", "outer-whitespace", "inner-whitespace-and-case", "upper"])
def test_the_builtin_phrase_is_recognised_after_normalisation(text):
    assert gc.is_generic_failure_reply(text, [], "hi") is True


@pytest.mark.parametrize("text", [
    "I seem to be encountering an error.",                     # 前缀
    PHRASE + " Here is the answer anyway: 42.",                # 以它开头、后面还有正文
    "Earlier the app said: " + PHRASE,                         # 包含
    "I seem to be encountering an error. Can I try something else for you",  # 少了问号
    "",
    "   ",
], ids=["prefix", "longer-answer", "contains", "near-miss", "empty", "blank"])
def test_anything_but_an_exact_match_is_a_normal_answer(text):
    assert gc.is_generic_failure_reply(text, [], "hi") is False


def test_a_reply_that_comes_with_generated_images_is_never_judged():
    assert gc.is_generic_failure_reply(PHRASE, [{"url": "https://lh3/x"}], "画一只猫") is False


def test_echo_guard_when_the_user_asked_for_this_very_sentence():
    prompt = f'Please repeat exactly: "{PHRASE}"'
    assert gc.is_generic_failure_reply(PHRASE, [], prompt) is False


def test_echo_guard_normalises_the_prompt_too():
    prompt = "please REPEAT:\n" + PHRASE.lower().replace(" ", "  ")
    assert gc.is_generic_failure_reply(PHRASE, [], prompt) is False


def test_echo_guard_ignores_assistant_turns_in_the_history():
    """H.6：故障期间漏过去的套话已经进了客户端自己保存的历史（第 0 节）。回声保护若把拍平后的
    整段 prompt 都算上，这批对话就永久失去识别，以后每次漏过去的套话还会自我延续。"""
    prompt = build_prompt_from_messages([
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "what is 2+2?"},
        {"role": "assistant", "content": PHRASE},
        {"role": "user", "content": "try again please"},
    ])
    assert PHRASE in prompt, "前提：历史里的 assistant 轮次确实拍进了 prompt"
    assert gc.is_generic_failure_reply(PHRASE, [], prompt) is True


def test_echo_guard_still_honours_a_user_turn_in_a_flattened_history():
    prompt = build_prompt_from_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": f"say exactly this and nothing else: {PHRASE}"},
    ])
    assert gc.is_generic_failure_reply(PHRASE, [], prompt) is False


@pytest.mark.parametrize("role", ["system", "tool"])
def test_echo_guard_counts_system_and_tool_content(role):
    messages = [{"role": "user", "content": "go"}]
    messages.insert(0 if role == "system" else 1, {"role": role, "content": f"quote: {PHRASE}"})
    if role == "tool":
        messages.append({"role": "user", "content": "what did the tool say?"})
    prompt = build_prompt_from_messages(messages)
    assert gc.is_generic_failure_reply(PHRASE, [], prompt) is False


def test_echo_guard_with_the_tool_prompt_wrapper():
    """带工具的请求在拍平历史外面又包了一层（build_tool_prompt 的 "User message: ..."）。"""
    from app.utils.tools import build_tool_prompt

    history = build_prompt_from_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": PHRASE},
        {"role": "user", "content": "again"},
    ])
    tools = [{"type": "function", "function": {"name": "f", "description": "d", "parameters": {}}}]
    assert gc.is_generic_failure_reply(PHRASE, [], build_tool_prompt(history, tools)) is True


def test_configured_phrases_are_added_and_blank_entries_ignored(monkeypatch):
    monkeypatch.setattr(gc.settings, "gemini_failure_replies",
                        " 我好像遇到了错误，换个问题试试？ ||  | Something went wrong. ", raising=False)
    assert gc.is_generic_failure_reply("我好像遇到了错误，换个问题试试？", [], "hi") is True
    assert gc.is_generic_failure_reply("something   went wrong.", [], "hi") is True
    # 内置那句始终生效
    assert gc.is_generic_failure_reply(PHRASE, [], "hi") is True
    # 空条目绝不能把空回答（或任何回答）判成套话
    assert gc.is_generic_failure_reply("", [], "hi") is False
    assert gc.is_generic_failure_reply("ok", [], "hi") is False
    # 规格 A.1「空条目忽略」：套话表里压根不能有空串（它是一切文本的前缀，流式扣住会永远扣着）
    assert gc.failure_reply_phrases() == (
        PHRASE.casefold(), "我好像遇到了错误，换个问题试试？", "something went wrong.",
    )


def test_the_exception_is_a_502_http_status_error():
    exc = gc.GeminiFailureReply(PHRASE)
    assert isinstance(exc, HTTPStatusError)
    assert exc.status_code == 502
    assert "generic failure message" in str(exc)
    assert PHRASE in str(exc)
    assert classify_error(exc) == (502, "api_error", None)
    assert not gc.is_timeout_error(exc)


# ---------------------------------------------------------------------------
# _send_request：解析完就判（非流式 / buffered / 研究 / 生图都经它）
# ---------------------------------------------------------------------------

def _payload(text, *, images=False):
    cand = ["rc_1", [text]]
    if images:
        # candidate[12][7][0] 是生图列表，每张图的 img[0][3] 是元数据（见 _extract_generated_images）
        meta = [None, 1, "a.png", "https://lh3.googleusercontent.com/x", "image/png", [1, 1, 1]]
        img = [[None, None, None, meta]]
        cand += [None] * (12 - len(cand)) + [[None] * 7 + [[[img]]]]
    return [None, ["c_1", "r_1"], None, None, [cand]]


def _raw(text, **kw) -> str:
    frame = ["wrb.fr", None, json.dumps(_payload(text, **kw)), None, None, None, "generic"]
    return ")]}'\n\n" + json.dumps([frame])


def _web_client(monkeypatch, raw_bodies):
    """真的 GeminiWebClient（_send_request / generate 全是真代码），只有 HTTP 层是替身。"""
    bodies = list(raw_bodies)
    client = GeminiWebClient.__new__(GeminiWebClient)
    client._healthy = True
    client._heal_lock = asyncio.Lock()
    client._session_token = "TOKEN"
    client._family_model = {}
    client._session_uuid = "SESSION-UUID"
    client._push_id = ""
    client.posts = 0

    class _Resp:
        status_code = 200
        cookies: dict = {}
        headers: dict = {}

        def __init__(self, text):
            self.text = text

    class _Http:
        async def post(self, url, data=None, **kw):
            client.posts += 1
            return _Resp(bodies[min(client.posts, len(bodies)) - 1])

    class _Jar:
        def update_from_response(self, resp):
            return None

    async def _noop(*a, **kw):
        return None

    async def _image_entry(img, cookies):
        return {"b64": "x", "mime": "image/png"}

    client._http = _Http()
    client._cookie_jar = _Jar()
    monkeypatch.setattr(gc, "apply_jitter", _noop)
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_clear_session_cookies", lambda: None)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    monkeypatch.setattr(client, "_build_image_entry", _image_entry)
    return client


def test_send_request_raises_on_the_failure_phrase(monkeypatch):
    client = _web_client(monkeypatch, [_raw(PHRASE)])
    with pytest.raises(gc.GeminiFailureReply) as ei:
        asyncio.run(client._send_request("只回答一个字：好", "gemini-flash"))
    assert ei.value.status_code == 502


def test_send_request_passes_normal_answers_through(monkeypatch):
    client = _web_client(monkeypatch, [_raw("好")])
    out = asyncio.run(client._send_request("只回答一个字：好", "gemini-flash"))
    assert out["text"] == "好"


def test_send_request_respects_the_echo_guard(monkeypatch):
    client = _web_client(monkeypatch, [_raw(PHRASE)])
    out = asyncio.run(client._send_request(f"Repeat after me: {PHRASE}", "gemini-flash"))
    assert out["text"] == PHRASE


def test_send_request_does_not_judge_a_reply_with_images(monkeypatch):
    client = _web_client(monkeypatch, [_raw(PHRASE, images=True)])
    out = asyncio.run(client._send_request("画一只猫", "gemini-flash"))
    assert out["text"] == PHRASE
    assert len(out["images"]) == 1


def test_send_request_judges_the_tool_wrapped_prompt_without_assistant_turns(monkeypatch):
    """buffered 带工具路径同样经 _send_request：历史里的 assistant 套话不触发回声保护。"""
    from app.utils.tools import build_tool_prompt

    history = build_prompt_from_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": PHRASE},
        {"role": "user", "content": "again"},
    ])
    prompt = build_tool_prompt(history, [{"type": "function", "function": {"name": "f"}}])
    client = _web_client(monkeypatch, [_raw(PHRASE)])
    with pytest.raises(gc.GeminiFailureReply):
        asyncio.run(client._send_request(prompt, "gemini-flash"))


# ---------------------------------------------------------------------------
# generate()：不做同账号 5xx 快速重试（H.7）
# ---------------------------------------------------------------------------

def test_generate_hands_the_failure_reply_straight_to_the_pool(monkeypatch):
    """套话不是网络抖动：同一个账号原样再发一次多半还是这句，只会让客户端多等一轮。"""
    assert gc.settings.same_account_5xx_retries >= 1, "前提：同账号 5xx 快速重试是开着的"
    client = _web_client(monkeypatch, [_raw(PHRASE)])
    with pytest.raises(gc.GeminiFailureReply):
        asyncio.run(client.generate("hi", "gemini-flash"))
    assert client.posts == 1


def test_generate_still_quick_retries_a_plain_5xx(monkeypatch):
    """零回归：普通 5xx 照旧在同账号快速重试一次。"""
    client = _web_client(monkeypatch, [_raw("x")])
    calls = []

    async def _send(*a, **kw):
        calls.append(True)
        raise HTTPStatusError(503, "busy")

    async def _no_sleep(*a, **kw):
        return None

    monkeypatch.setattr(client, "_send_request", _send)
    monkeypatch.setattr(gc.asyncio, "sleep", _no_sleep)
    with pytest.raises(HTTPStatusError):
        asyncio.run(client.generate("hi", "gemini-flash"))
    assert len(calls) == 1 + gc.settings.same_account_5xx_retries


# ---------------------------------------------------------------------------
# 账号池：5xx 口径换号 + 软冷却；不算连败、不算空响应
# ---------------------------------------------------------------------------

def _pool(clients) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"psid-{i}", psidts="", label=f"account-{i}",
                status=AccountStatus.ACTIVE, client=c)
        for i, c in enumerate(clients)
    ]
    pool._max_concurrent = 8
    pool._acquire_timeout = 2.0
    return pool


def test_pool_fails_over_and_cools_every_account_down(monkeypatch, caplog):
    clients = [_web_client(monkeypatch, [_raw(PHRASE)]) for _ in range(3)]
    pool = _pool(clients)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(gc.GeminiFailureReply):
            asyncio.run(pool.generate("只回答一个字：好", "gemini-flash"))

    assert [c.posts for c in clients] == [1, 1, 1], "每个账号恰好打一次（不在同账号快速重试）"
    for account in pool.accounts:
        assert account.status == AccountStatus.ACTIVE
        assert account.consecutive_failures == 0
        assert account.cooldown_until > 0, "套话按瞬时上游故障记账：软冷却"
        assert account.consecutive_empty == 0 and account.empty_count == 0, "它不是空响应"
        assert account.last_error == "GeminiFailureReply (HTTP 502)"
        assert account.active_requests == 0
    warnings = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    for account in pool.accounts:
        assert account.id in warnings
    assert "generic failure message" in warnings


def test_pool_moves_on_to_a_healthy_account(monkeypatch):
    bad = _web_client(monkeypatch, [_raw(PHRASE)])
    good = _web_client(monkeypatch, [_raw("好")])
    pool = _pool([bad, good])
    out = asyncio.run(pool.generate("只回答一个字：好", "gemini-flash"))
    assert out["text"] == "好"
    assert out["account_id"] == "account-1"


# ---------------------------------------------------------------------------
# 路由：沿用既有映射（H.8），OpenAI chat 可兜底，套话不进会话记录
# ---------------------------------------------------------------------------

class _Calls:
    def __init__(self):
        self.generate = []
        self.stream = []


def _patch_failure(monkeypatch, router_module) -> _Calls:
    """把路由用的账号池换成「每次都回套话」的替身（与超时测试同一个形状）。"""
    calls = _Calls()

    async def generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       account_id=None, extended_thinking=False):
        calls.generate.append({"thinking": extended_thinking, "conv": conversation_id})
        raise gc.GeminiFailureReply(PHRASE)

    async def generate_stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                              account_id=None, extended_thinking=False):
        calls.stream.append({"thinking": extended_thinking, "conv": conversation_id})
        raise gc.GeminiFailureReply(PHRASE)
        yield  # pragma: no cover - 保留 async generator 形状

    monkeypatch.setattr(router_module.gemini_client, "generate", generate)
    monkeypatch.setattr(router_module.gemini_client, "generate_stream", generate_stream)
    return calls


def _sse_events(body: str):
    out = []
    for block in body.split("\n\n"):
        ev, data = None, None
        for line in block.split("\n"):
            if not line.strip() or line.startswith(":"):
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                if raw == "[DONE]":
                    continue
                data = json.loads(raw)
        if ev or data is not None:
            out.append((ev, data))
    return out


def _stream_body(http, path, body):
    with http.stream("POST", path, json=body, headers=_AUTH) as r:
        return "".join(r.iter_text())


_TOOLS_OPENAI = [{"type": "function", "function": {
    "name": "get_weather", "description": "w",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
}}]


def test_openai_nonstream_without_fallback_is_a_502_api_error(gem_client, monkeypatch):
    import app.routers.openai as oai

    calls = _patch_failure(monkeypatch, oai)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)

    assert r.status_code == 502, r.text
    assert r.json()["error"]["type"] == "api_error"
    assert "generic failure message" in r.json()["error"]["message"]
    # 既有机制：思考路径先原样退回不思考一次
    assert [c["thinking"] for c in calls.generate][-1] is False
    assert len(calls.generate) == 2


def test_openai_nonstream_falls_back_to_a_third_party(gem_client, monkeypatch):
    import app.routers.openai as oai

    _patch_failure(monkeypatch, oai)

    async def fake_fallback(request, req, messages_raw, exclude_model=""):
        return {"id": "chatcmpl-fb", "object": "chat.completion", "created": 0, "model": "tp",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "from fallback"}}]}

    monkeypatch.setattr(oai, "_fallback_result", fake_fallback)
    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "from fallback"


def test_openai_stream_without_fallback_emits_an_api_error_frame(gem_client, monkeypatch):
    import app.routers.openai as oai

    _patch_failure(monkeypatch, oai)
    body = _stream_body(gem_client, "/v1/chat/completions", {
        "model": "gemini-flash", "stream": True, "messages": [{"role": "user", "content": "hi"}],
    })
    events = _sse_events(body)
    errors = [d["error"] for _, d in events if isinstance(d, dict) and "error" in d]
    assert [(e["type"], e["code"]) for e in errors] == [("api_error", 502)], body
    content = "".join((d["choices"][0]["delta"].get("content") or "") for _, d in events
                      if isinstance(d, dict) and d.get("choices"))
    assert PHRASE not in content, "套话绝不能当正文流出去"


def test_openai_stream_falls_back_before_any_content(gem_client, monkeypatch):
    import app.routers.openai as oai

    _patch_failure(monkeypatch, oai)

    async def fake_fallback_stream(request, req, messages_raw, exclude_model, completion_id, model_name):
        yield 'data: {"fallback": true}\n\n'

    monkeypatch.setattr(oai, "_maybe_fallback_stream", fake_fallback_stream)
    body = _stream_body(gem_client, "/v1/chat/completions", {
        "model": "gemini-flash", "stream": True, "messages": [{"role": "user", "content": "hi"}],
    })
    assert '"fallback": true' in body
    assert "api_error" not in body


def test_openai_buffered_tool_stream_emits_an_api_error_frame(gem_client, monkeypatch):
    import app.routers.openai as oai

    _patch_failure(monkeypatch, oai)
    body = _stream_body(gem_client, "/v1/chat/completions", {
        "model": "gemini-flash", "stream": True, "tools": _TOOLS_OPENAI,
        "messages": [{"role": "user", "content": "weather?"}],
    })
    errors = [d["error"] for _, d in _sse_events(body) if isinstance(d, dict) and "error" in d]
    assert [(e["type"], e["code"]) for e in errors] == [("api_error", 502)], body


def test_openai_images_is_a_502_api_error(gem_client, monkeypatch):
    import app.routers.openai as oai

    _patch_failure(monkeypatch, oai)
    r = gem_client.post("/v1/images/generations", json={"prompt": "a cat"}, headers=_AUTH)
    assert r.status_code == 502, r.text
    assert r.json()["error"]["type"] == "api_error"


def test_claude_nonstream_is_a_502_api_error(gem_client, monkeypatch):
    import app.routers.claude as cl

    _patch_failure(monkeypatch, cl)
    r = gem_client.post("/v1/messages", json={
        "model": "gemini-flash", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}],
    }, headers=_AUTH)
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["type"] == "error" and body["error"]["type"] == "api_error"


def test_claude_stream_emits_an_api_error_event(gem_client, monkeypatch):
    import app.routers.claude as cl

    _patch_failure(monkeypatch, cl)
    body = _stream_body(gem_client, "/v1/messages", {
        "model": "gemini-flash", "max_tokens": 64, "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    })
    errors = [d["error"] for ev, d in _sse_events(body) if ev == "error"]
    assert [e["type"] for e in errors] == ["api_error"], body


def test_gemini_native_nonstream_is_a_502_api_error(gem_client, monkeypatch):
    import app.routers.gemini as ge

    _patch_failure(monkeypatch, ge)
    r = gem_client.post("/v1beta/models/gemini-flash:generateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    }, headers=_AUTH)
    assert r.status_code == 502, r.text
    assert r.json()["error"]["type"] == "api_error"


def test_gemini_native_stream_emits_an_api_error_line(gem_client, monkeypatch):
    import app.routers.gemini as ge

    _patch_failure(monkeypatch, ge)
    body = _stream_body(gem_client, "/v1beta/models/gemini-flash:streamGenerateContent", {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    })
    errors = [json.loads(line)["error"] for line in body.splitlines()
              if line.strip() and "error" in json.loads(line)]
    assert [e["type"] for e in errors] == ["api_error"], body


def test_responses_nonstream_is_a_502_api_error(gem_client, monkeypatch):
    import app.routers.responses as rr

    _patch_failure(monkeypatch, rr)
    r = gem_client.post("/v1/responses", json={"model": "gemini-flash", "input": "hi"}, headers=_AUTH)
    assert r.status_code == 502, r.text
    assert r.json()["error"]["type"] == "api_error"


def test_responses_stream_fails_with_the_existing_internal_error_code(gem_client, monkeypatch):
    import app.routers.responses as rr

    _patch_failure(monkeypatch, rr)
    body = _stream_body(gem_client, "/v1/responses", {"model": "gemini-flash", "input": "hi",
                                                       "stream": True})
    failed = [d["response"] for ev, d in _sse_events(body) if ev == "response.failed"]
    assert [f["error"]["code"] for f in failed] == ["internal_error"], body


def test_research_keeps_its_generic_500(gem_client, monkeypatch):
    import app.routers.research as research

    class _Pool:
        is_healthy = True
        models = ["gemini-flash"]

        async def generate(self, *a, **k):
            raise gc.GeminiFailureReply(PHRASE)

    monkeypatch.setattr(research, "gemini_client", _Pool())
    r = gem_client.post("/gemini/v1beta/deepresearch", json={"query": "q", "model": "gemini-flash"},
                        headers=_AUTH)
    assert r.status_code == 500, r.text
    assert r.json()["detail"] == "Research failed"


def test_the_failure_phrase_never_reaches_the_conversation_store(gem_client, monkeypatch, tmp_path):
    """端到端（真池 + 真 client，只有 HTTP 层是替身）：会话记录里不能出现这句套话。"""
    import app.core.conversation_store as store_module
    import app.routers.openai as oai
    from app.core.conversation_store import ConversationStore

    monkeypatch.setattr(store_module, "DATA_DIR", tmp_path / "conversations")
    store = ConversationStore()
    monkeypatch.setattr(oai, "conversation_store", store)
    pool = _pool([_web_client(monkeypatch, [_raw(PHRASE)])])
    monkeypatch.setattr(oai, "gemini_client", pool)

    r = gem_client.post("/v1/chat/completions", json={
        "model": "gemini-flash", "conversation_id": "thread-1",
        "messages": [{"role": "user", "content": "只回答一个字：好"}],
    }, headers=_AUTH)

    assert r.status_code == 502, r.text
    conv = asyncio.run(store.get(oai.scoped_conversation_id("thread-1")))
    stored = json.dumps([m for m in (conv.messages if conv else [])], ensure_ascii=False)
    assert PHRASE not in stored
    files = list((tmp_path / "conversations").glob("*.json"))
    assert all(PHRASE not in f.read_text(encoding="utf-8") for f in files)

"""issue #10 followup F2：工具调用畸形重试要在已开的流式连接上继续保活。

parse_tool_response_with_retry 判定为畸形时会再跑一整轮上游 generate()——四个 STREAMING
router 此前都是裸 `await`，跑在已经开了的 SSE/NDJSON 流上：role/message_start/created 等
首帧早就发出去了，这次重试没有心跳，死寂窗口从一个 keepalive 间隔直接跳到一整轮上游生成，
足够激进的反代掐断连接。

覆盖：一个 SSE router（openai.py 的 buffered 流式）+ Gemini 原生 NDJSON router（帧类型不同，
NDJSON 不能用 `: ping` 注释帧，必须是裸换行）；两边都验证「首次即合法 = 零额外心跳」的零回归。
"""
import asyncio
import json

_AUTH = {"Authorization": "Bearer sk-test-key"}

TRUNCATED = (
    '```json\n{"status":"tool_use","tool_calls":[{"name":"mcp__brain__create_multi_simulation",'
    '"arguments":{"alpha_expre'
)
VALID = '{"status":"tool_use","tool_calls":[{"name":"run_shell","arguments":{"cmd":"ls"}}]}'

_OPENAI_TOOLS = [{"type": "function", "function": {
    "name": "run_shell", "description": "run a shell cmd",
    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]
_GEMINI_TOOLS = [{"function_declarations": [{
    "name": "run_shell", "description": "run a shell cmd",
    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}]}]


def _slow_retry_generate(calls, first_text, retry_text, delay=0.25):
    """首次快速返回 first_text；第二次（重试）先睡 delay 秒再返回 retry_text。"""
    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"text": first_text, "conversation_id": "", "images": [], "thoughts": ""}
        await asyncio.sleep(delay)
        return {"text": retry_text, "conversation_id": "", "images": [], "thoughts": ""}
    return gen


def _fast_generate(text):
    async def gen(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        return {"text": text, "conversation_id": "", "images": [], "thoughts": ""}
    return gen


# ---------------------------------------------------------------------------
# openai.py 的 buffered 流式路径（SSE，`: ping\n\n` 注释帧）
# ---------------------------------------------------------------------------

def test_openai_stream_tool_retry_emits_sse_keepalive(gem_client, monkeypatch):
    import app.routers.openai as oai
    from app.core import stream as stream_mod
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    calls = {"n": 0}
    monkeypatch.setattr(oai.gemini_client, "generate",
                        _slow_retry_generate(calls, TRUNCATED, VALID))

    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "list files"}],
        "tools": _OPENAI_TOOLS, "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert calls["n"] == 2, "重试必须真的发生"
    assert ": ping" in body, "重试期间的死寂窗口必须有 SSE 注释帧保活"
    assert "run_shell" in body
    # 心跳先于重试后的最终内容（否则说明重试期间根本没保活）
    assert body.index(": ping") < body.index("run_shell")


def test_openai_stream_tool_valid_first_time_emits_no_extra_keepalive(gem_client, monkeypatch):
    """零回归：首次即合法 → 不重试 → 不该多出任何心跳帧。"""
    import app.routers.openai as oai
    from app.core import stream as stream_mod
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    monkeypatch.setattr(oai.gemini_client, "generate", _fast_generate(VALID))

    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "list files"}],
        "tools": _OPENAI_TOOLS, "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert ": ping" not in body
    assert "run_shell" in body


# ---------------------------------------------------------------------------
# 原生 Gemini streamGenerateContent（NDJSON，裸换行保活，绝不能出现 SSE 注释帧）
# ---------------------------------------------------------------------------

def test_gemini_ndjson_tool_retry_emits_blankline_keepalive(gem_client, monkeypatch):
    import app.routers.gemini as gm
    from app.core import stream as stream_mod
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    calls = {"n": 0}
    monkeypatch.setattr(gm.gemini_client, "generate",
                        _slow_retry_generate(calls, TRUNCATED, VALID))

    with gem_client.stream("POST", "/v1beta/models/gemini-pro:streamGenerateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "list files"}]}],
        "tools": _GEMINI_TOOLS,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert calls["n"] == 2, "重试必须真的发生"
    assert ": ping" not in body, "NDJSON 流绝不能混入 SSE 注释帧"
    assert "\n\n" in body, "重试期间的死寂窗口必须有裸换行保活"
    assert "run_shell" in body
    assert body.index("\n\n") < body.index("run_shell")


def test_gemini_ndjson_tool_valid_first_time_emits_no_extra_keepalive(gem_client, monkeypatch):
    """零回归：首次即合法 → 不重试 → 流回的文本与修复前逐字节一致，无额外心跳。"""
    import app.routers.gemini as gm
    from app.core import stream as stream_mod
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    calls = {"n": 0}
    monkeypatch.setattr(gm.gemini_client, "generate",
                        _slow_retry_generate(calls, VALID, VALID))

    with gem_client.stream("POST", "/v1beta/models/gemini-pro:streamGenerateContent", json={
        "contents": [{"role": "user", "parts": [{"text": "list files"}]}],
        "tools": _GEMINI_TOOLS,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())

    assert calls["n"] == 1, "首次合法不得重试"
    assert ": ping" not in body
    streamed = "".join(
        p.get("text", "")
        for line in body.splitlines() if line.strip()
        for p in json.loads(line)["candidates"][0]["content"]["parts"]
    )
    assert streamed == VALID

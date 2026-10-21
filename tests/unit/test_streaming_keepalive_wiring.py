import asyncio
from pathlib import Path
from app.core import stream as stream_mod

_ROOT = Path(__file__).resolve().parent.parent.parent
_AUTH = {"Authorization": "Bearer sk-test-key"}


def test_chat_realstream_emits_keepalive_ping_during_silence(gem_client, monkeypatch):
    """真流式路径：等上游的静默期必须发 : ping；答案与 [DONE] 照常（零回归）。"""
    import app.routers.openai as oai
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        await asyncio.sleep(0.25)   # 静默 gap > interval → 多个 ping
        yield {"type": "delta", "text": "85"}
        yield {"type": "final", "text": "85", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate_stream", slow_generate_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "1+3+9*9"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert ": ping" in body        # 心跳出现
    assert "85" in body            # 答案照常
    assert "[DONE]" in body        # 正常收尾


def test_chat_realstream_no_ping_when_fast(gem_client, monkeypatch):
    """默认 10s 间隔 + 瞬时流 → 无 ping，行为与既有一致。"""
    import app.routers.openai as oai

    async def fast_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        yield {"type": "delta", "text": "hi"}
        yield {"type": "final", "text": "hi", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate_stream", fast_generate_stream)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert ": ping" not in body
    assert "hi" in body and "[DONE]" in body


def test_openai_still_has_buffered_keepalive():
    """回归：buffered 路径心跳（既有）不受影响。"""
    src = (_ROOT / "app" / "routers" / "openai.py").read_text(encoding="utf-8")
    assert "_sse_keepalive_during(gen_task)" in src


def test_responses_stream_emits_keepalive_ping_during_silence(gem_client, monkeypatch):
    """/v1/responses 流式：等上游的静默期必须发 : ping；答案照常。"""
    import app.routers.responses as rp
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        await asyncio.sleep(0.25)
        yield {"type": "delta", "text": "85"}
        yield {"type": "final", "text": "85", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(rp.gemini_client, "generate_stream", slow_generate_stream)
    with gem_client.stream("POST", "/v1/responses", json={
        "model": "gemini-pro", "input": "1+3+9*9", "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert ": ping" in body
    assert "85" in body


def test_claude_realstream_emits_keepalive_ping_during_silence(gem_client, monkeypatch):
    """/v1/messages（SSE）真流式路径：静默期必须发 : ping；答案照常（零回归）。"""
    import app.routers.claude as cl
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        await asyncio.sleep(0.25)   # 静默 gap > interval → 多个 ping
        yield {"type": "delta", "text": "85"}
        yield {"type": "final", "text": "85", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(cl.gemini_client, "generate_stream", slow_generate_stream)
    with gem_client.stream("POST", "/v1/messages", json={
        "model": "gemini-flash", "max_tokens": 100,
        "messages": [{"role": "user", "content": "1+3+9*9"}], "stream": True,
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert ": ping" in body        # 心跳出现（SSE 端点，与 openai/responses 同款帧）
    assert "85" in body            # 答案照常


def test_gemini_native_realstream_emits_blankline_keepalive_during_silence(gem_client, monkeypatch):
    """/v1beta/.../streamGenerateContent（NDJSON）真流式路径：静默期必须发空行心跳
    （不能用 ": ping" SSE 注释——那在 application/json 逐行 JSON 流里是非法内容）。"""
    import app.routers.gemini as gm
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        await asyncio.sleep(0.25)
        yield {"type": "delta", "text": "85"}
        yield {"type": "final", "text": "85", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(gm.gemini_client, "generate_stream", slow_generate_stream)
    with gem_client.stream("POST", "/v1beta/models/gemini-flash:streamGenerateContent", json={
        "contents": [{"parts": [{"text": "1+3+9*9"}]}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert "\n\n" in body           # 空行 = 心跳（正常 NDJSON 逐行输出不会有连续换行）
    assert "85" in body
    assert ": ping" not in body     # 绝不能把 SSE 注释帧混进 NDJSON 流


def test_chat_realstream_exception_before_any_delta_does_not_500(gem_client, monkeypatch):
    """FIX 3b + R1：真流式在发出任何 delta 前直接抛异常，路由必须走既有 except 分支收尾
    （_maybe_fallback_stream 探不到第三方结果时落回 _err_chunk），而不是让异常击穿到 500；
    且错误必须以标准 OpenAI error 帧（data.error）发出，不能伪装成 finish_reason="stop"
    的正常回答（R1：与 Claude 侧同类修复对齐，这是 defect ② 在 OpenAI 协议上的残留）。"""
    import app.routers.openai as oai

    async def boom_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        raise RuntimeError("boom")
        yield  # pragma: no cover — 让函数保持 async generator 形态，不会被执行到

    monkeypatch.setattr(oai.gemini_client, "generate_stream", boom_generate_stream)
    # 默认思考档（出厂 low）开着时，真流式失败会先退回不思考的非流式重试一次；
    # 上游整体故障时那一次也同样失败，这里让 generate 抛同一个错误。
    async def _same_failure(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(oai.gemini_client, "generate", _same_failure)
    with gem_client.stream("POST", "/v1/chat/completions", json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "1+3+9*9"}], "stream": True,
    }, headers=_AUTH) as r:
        assert r.status_code == 200   # 请求本身不能 500/未处理异常击穿
        body = "".join(r.iter_text())
    # 测试环境 FALLBACK_ENABLED 默认 False → _maybe_fallback_stream 探不到结果 → 落回 _err_chunk，
    # 发标准 error 帧，随后照常发 [DONE] 收尾——不再伪装成 content:"Error: ..." 的正常回答。
    assert '"error"' in body
    assert '"message": "boom"' in body
    assert "Error: boom" not in body
    assert '"finish_reason": "stop"' not in body
    assert "[DONE]" in body

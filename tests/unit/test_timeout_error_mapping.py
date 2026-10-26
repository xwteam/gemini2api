"""生成超时不能再变成纯文本 500（v1.6.45 规格 A）。

线上（新加坡中转站 v1.6.44，北京 2026-10-26 14:18～14:4x）：谷歌那边 3.8 Flash 卡住，非流式生成
按预算 120 秒掐断、抛 GenerationTimedOut（TimeoutError 的子类）。四个协议路由的非流式 / buffered
路径只接 (RuntimeError, ValueError, HTTPStatusError)，超时一路冒到 ASGI 层，客户端拿到纯文本的
「500 Internal Server Error」：OpenAI / Anthropic SDK 都解析不了、不会按超时重试，开了
FALLBACK_ENABLED 也没去兜底。

本文件钉住：
  - classify_error：生成期超时 → (504, "timeout_error", None)；
  - 四个协议的非流式与 buffered（带工具的伪流式）路径：504 + 该协议的 JSON 错误信封（流式路径是
    协议内错误事件），开兜底时先兜底；
  - 超时不触发「退回不思考再试一次」，也不触发「会话过期、用完整 prompt 重试」（预算已经花完）；
  - 真流式路径的错误事件类型是 timeout_error，不是 api_error / 500。
"""

import asyncio
import json

import pytest
from curl_cffi.requests import RequestsError

from app.core.gemini_client import GenerationTimedOut, HTTPStatusError, classify_error

_AUTH = {"Authorization": "Bearer sk-test-key"}

_TOOLS_OPENAI = [{"type": "function", "function": {
    "name": "get_weather", "description": "w",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
}}]
_TOOLS_ANTHROPIC = [{"name": "get_weather", "description": "w",
                     "input_schema": {"type": "object", "properties": {}}}]
_TOOLS_GEMINI = [{"functionDeclarations": [{"name": "get_weather", "description": "w",
                                             "parameters": {"type": "object", "properties": {}}}]}]
_TOOLS_RESPONSES = [{"type": "function", "name": "get_weather", "description": "w",
                     "parameters": {"type": "object", "properties": {}}}]


def _timed_out() -> GenerationTimedOut:
    return GenerationTimedOut(120, 120.4, RequestsError("Operation timed out", code=28))


class _Calls:
    """记录 generate / generate_stream 被调了几次、带的什么参数。"""

    def __init__(self):
        self.generate = []
        self.stream = []


def _patch_timeouts(monkeypatch, router_module) -> _Calls:
    """把路由用的 gemini_client（账号池）换成「每次都超时」的替身。"""
    calls = _Calls()

    async def generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                       account_id=None, extended_thinking=False):
        calls.generate.append({"prompt": prompt, "conv": conversation_id,
                               "thinking": extended_thinking, "account_id": account_id})
        raise _timed_out()

    async def generate_stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                              account_id=None, extended_thinking=False):
        calls.stream.append({"prompt": prompt, "conv": conversation_id,
                             "thinking": extended_thinking, "account_id": account_id})
        raise _timed_out()
        yield  # pragma: no cover - 保留 async generator 形状

    monkeypatch.setattr(router_module.gemini_client, "generate", generate)
    monkeypatch.setattr(router_module.gemini_client, "generate_stream", generate_stream)
    return calls


def _sse_events(body: str):
    """SSE 文本 → [(event, data)]；忽略注释行（: ping）与 [DONE]。"""
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


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    _timed_out(),
    TimeoutError("read timed out"),
    asyncio.TimeoutError(),
    RequestsError("Operation timed out after 180000 milliseconds", code=28),
], ids=["GenerationTimedOut", "TimeoutError", "asyncio.TimeoutError", "curl-code-28"])
def test_generation_timeouts_classify_as_504_timeout_error(exc):
    assert classify_error(exc) == (504, "timeout_error", None)


def test_other_curl_errors_keep_their_old_mapping():
    """只有超时（code 28）改成 504；别的 curl 错误照旧（落到兜底的 500 api_error）。"""
    assert classify_error(RequestsError("Could not resolve host", code=6)) == (500, "api_error", None)


@pytest.mark.parametrize("exc,expected", [
    (HTTPStatusError(429, "x"), (429, "rate_limit_error", None)),
    (HTTPStatusError(503, "x"), (503, "api_error", None)),
    (RuntimeError("No available accounts"), (529, "overloaded_error", 30)),
    (RuntimeError("Client not ready"), (500, "api_error", None)),
    (ValueError("bad model"), (400, "invalid_request_error", None)),
])
def test_non_timeout_mappings_are_unchanged(exc, expected):
    assert classify_error(exc) == expected

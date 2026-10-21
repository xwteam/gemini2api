"""第三方转发的请求体里不能带 null 字段（书生端砚 2026-10-21 线上事故）。

ChatMessage 的可选字段（name / tool_calls / tool_call_id）model_dump 后都是 null；按 OpenAI SDK
严格校验的上游（书生端砚的 deepseek / glm / kimi / minimax / qwen）收到 `"name": null` 一律 400
「15 validation errors … name: Input should be a valid string」。同一个 payload 去掉 null 键就是 200。
"""

import json

from app.core import api_forwarder as af
from app.core.api_key_store import ApiKeyEntry
from app.models.openai import ChatRequest

_ENTRY = ApiKeyEntry(id="k1", provider="custom", model="deepseek-v4-flash-0731", api_key="sk-x",
                     base_url="https://discovery-api.intern-ai.org.cn/v1", label="书生端砚-01",
                     status="active", added_at="", last_used_at=None)


def _nulls(obj, path="$"):
    if obj is None:
        return [path]
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _nulls(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in _nulls(v, f"{path}[{i}]")]
    return []


def _payload(req: ChatRequest) -> dict:
    messages = [m.model_dump() for m in req.messages]      # 与 _dispatch_thirdparty 完全同一种取法
    _, _, payload = af._build_openai_request(_ENTRY, messages, req)
    return payload


def test_the_exact_production_request_has_no_null_fields():
    req = ChatRequest(model="deepseek-v4-flash-0731", max_tokens=256,
                      messages=[{"role": "user", "content": "Reply with exactly: PONG"}])
    payload = _payload(req)
    assert _nulls(payload) == [], _nulls(payload)
    assert payload["messages"] == [{"role": "user", "content": "Reply with exactly: PONG"}]
    json.dumps(payload)                                      # 能原样发出去


def test_a_tool_round_trip_keeps_every_real_field():
    req = ChatRequest(model="deepseek-v4-flash-0731", messages=[
        {"role": "system", "content": "s"},
        {"role": "user", "content": "天气？", "name": "alice"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]},
        {"role": "tool", "content": "晴", "tool_call_id": "call_1"},
    ], tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}])
    payload = _payload(req)
    assert _nulls(payload) == [], _nulls(payload)
    user, assistant, tool = payload["messages"][1:]
    assert user == {"role": "user", "content": "天气？", "name": "alice"}
    assert assistant["tool_calls"][0]["id"] == "call_1" and "content" not in assistant
    assert tool == {"role": "tool", "content": "晴", "tool_call_id": "call_1"}
    assert payload["tools"][0]["function"]["name"] == "get_weather"


def test_message_content_is_passed_through_untouched():
    """只清消息第一层：多模态内容数组原样转发，不去碰客户端自己的结构。"""
    parts = [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "https://x/a.png"}}]
    req = ChatRequest(model="m", messages=[{"role": "user", "content": parts}])
    assert _payload(req)["messages"] == [{"role": "user", "content": parts}]

"""流式分流门禁：只有工具调用才强制 buffered（S9 / S10）。

buffered = "等全文生成完才吐第一个字"。过去 `has_tools or attachments or
maybe_image_generation_intent(prompt)` 三条里有两条不该在这儿：
- attachments：附件在 generate_stream 里本来就会先上传完再对话，挡进 buffered 只是让所有
  带图/带文件的请求都失去真流式；
- 生图意图：那是个关键词猜测，误判面很大，会把一堆普通对话一起拖进 buffered。
has_tools 这条保留 —— tool_calls 必须拿到完整 JSON 才能解析。
"""

import base64

import pytest

_AUTH = {"Authorization": "Bearer sk-test-key"}

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@pytest.fixture
def routed(monkeypatch):
    """把两条路径各自打桩，返回"这次请求实际走了哪条"的记录。"""
    import app.routers.openai as oai

    calls = []

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        calls.append(("buffered", attachments))
        return {"text": "answer", "images": [], "conversation_id": "c", "thoughts": ""}

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        calls.append(("stream", attachments))
        yield {"type": "delta", "text": "an"}
        yield {"type": "delta", "text": "swer"}
        yield {"type": "final", "text": "answer", "conversation_id": "c",
               "images": [], "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate", fake_generate)
    monkeypatch.setattr(oai.gemini_client, "generate_stream", fake_generate_stream)
    return calls


def _post(client, body):
    return client.post("/v1/chat/completions", json=body, headers=_AUTH)


def _image_message(text: str):
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}},
    ]}]


_TOOLS = [{"type": "function", "function": {"name": "f", "description": "d",
                                            "parameters": {"type": "object", "properties": {}}}}]


def test_attachments_now_stream(gem_client, routed):
    """带附件的流式请求必须走真流式，且附件照常传下去。"""
    r = _post(gem_client, {"model": "gemini-flash", "stream": True,
                           "messages": _image_message("这张图里是什么")})

    assert r.status_code == 200
    assert [c[0] for c in routed] == ["stream"]
    assert routed[0][1], "附件必须照常交给 generate_stream，不能被丢掉"
    assert len(routed[0][1]) == 1


def test_image_intent_now_streams(gem_client, routed):
    """生图意图不再强制 buffered（它现在只决定 POST 超时）。"""
    r = _post(gem_client, {"model": "gemini-flash", "stream": True,
                           "messages": [{"role": "user", "content": "画一张猫的图片"}]})

    assert r.status_code == 200
    assert [c[0] for c in routed] == ["stream"]


def test_tools_still_buffered(gem_client, routed):
    """保留的那条门禁：tool_calls 要完整 JSON 才能解析，必须 buffered。"""
    r = _post(gem_client, {"model": "gemini-flash", "stream": True, "tools": _TOOLS,
                           "messages": [{"role": "user", "content": "查一下天气"}]})

    assert r.status_code == 200
    assert [c[0] for c in routed] == ["buffered"]


def test_tools_with_attachments_still_buffered(gem_client, routed):
    r = _post(gem_client, {"model": "gemini-flash", "stream": True, "tools": _TOOLS,
                           "messages": _image_message("看图并调用工具")})

    assert r.status_code == 200
    assert [c[0] for c in routed] == ["buffered"]


def test_plain_text_still_streams(gem_client, routed):
    """零回归：普通文本流式请求本来就走真流式。"""
    r = _post(gem_client, {"model": "gemini-flash", "stream": True,
                           "messages": [{"role": "user", "content": "你好"}]})

    assert r.status_code == 200
    assert [c[0] for c in routed] == ["stream"]
    # 真流式：两个 delta 分两帧到达（buffered 会把全文一次切片发完）
    assert '"content": "an"' in r.text and '"content": "swer"' in r.text


def test_image_intent_only_affects_the_timeout():
    """生图意图的作用域只剩超时：同一个模型，生图意图拿到更长的 POST 超时。"""
    from app.core import gemini_client as gc

    assert gc._generate_timeout("gemini-3-flash", "画一张猫的图片") == 180
    assert gc._generate_timeout("gemini-3-flash", "你好") == 120

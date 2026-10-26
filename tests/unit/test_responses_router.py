import json

_AUTH = {"Authorization": "Bearer sk-test-key"}


def test_responses_non_stream_text_reply(gem_client, monkeypatch):
    import app.routers.responses as rr

    async def fake_generate(prompt, model, conversation_id="", attachments=None,
                            gem_id=None, account_id=None, extended_thinking=False):
        assert model == "gemini-pro"
        return {"text": "Hello human", "conversation_id": "", "images": []}

    monkeypatch.setattr(rr.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={"model": "gemini-pro", "input": "hi"}, headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["content"][0]["text"] == "Hello human"


def test_responses_requires_auth(client):
    r = client.post("/v1/responses", json={"model": "gemini-pro", "input": "hi"})
    assert r.status_code in (401, 403)


def test_responses_previous_response_id_rejected(client, monkeypatch):
    import app.routers.responses as rr

    async def fake_generate(*a, **k):
        return {"text": "x", "conversation_id": "", "images": []}
    monkeypatch.setattr(rr.gemini_client, "generate", fake_generate)

    r = client.post("/v1/responses",
                    json={"model": "gemini-pro", "input": "hi", "previous_response_id": "resp_dead"},
                    headers=_AUTH)
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_responses_missing_input_is_400(client):
    r = client.post("/v1/responses", json={"model": "gemini-pro"}, headers=_AUTH)
    assert r.status_code == 400


def test_responses_with_tool_call_returns_function_call_item(gem_client, monkeypatch):
    import app.routers.responses as rr

    async def fake_generate(prompt, model, conversation_id="", attachments=None,
                            gem_id=None, account_id=None, extended_thinking=False):
        assert "run_shell" in prompt  # tool description injected into prompt
        return {"text": '{"status":"tool_use","tool_calls":[{"name":"run_shell","arguments":{"cmd":"ls"}}]}',
               "conversation_id": "", "images": []}

    monkeypatch.setattr(rr.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={
        "model": "gemini-pro", "input": "list files",
        "tools": [{"type": "function", "name": "run_shell", "description": "run a shell cmd",
                  "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}],
    }, headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    item = body["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "run_shell"
    assert json.loads(item["arguments"]) == {"cmd": "ls"}


def test_responses_stream_emits_output_text_done_event(gem_client, monkeypatch):
    import app.routers.responses as rr

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        yield {"type": "delta", "text": "Hel"}
        yield {"type": "delta", "text": "lo"}
        yield {"type": "final", "text": "Hello", "conversation_id": "", "images": []}

    monkeypatch.setattr(rr.gemini_client, "generate_stream", fake_generate_stream)
    with gem_client.stream("POST", "/v1/responses",
                       json={"model": "gemini-pro", "input": "hi", "stream": True},
                       headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert "response.output_text.done" in body
    assert "response.function_call_arguments.done" not in body  # no tools this turn
    assert "response.completed" in body
    assert "[DONE]" not in body


def test_responses_stream_embeds_generated_images_as_markdown(gem_client, monkeypatch):
    """真流式路径（无工具/附件）也不能丢图：final 事件里的 images 要嵌入 full_text 再收尾。"""
    import app.routers.responses as rr

    async def fake_generate_stream(prompt, model, conversation_id="", attachments=None,
                                   gem_id=None, account_id=None, extended_thinking=False):
        yield {"type": "delta", "text": "Here"}
        yield {"type": "final", "text": "Here", "conversation_id": "",
              "images": [{"id": "img-999"}]}

    monkeypatch.setattr(rr.gemini_client, "generate_stream", fake_generate_stream)
    with gem_client.stream("POST", "/v1/responses",
                       json={"model": "gemini-pro", "input": "draw a dog", "stream": True},
                       headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert "![generated image](" in body
    assert "img-999" in body
    assert "response.output_text.done" in body


def test_responses_routes_unknown_gemini_model_to_thirdparty(gem_client, monkeypatch):
    """端到端：模型不是 Gemini 模型时，路由把请求转给第三方分发适配层，
    并把 dispatch_thirdparty_responses 的返回值（此处为 JSONResponse）原样透传给客户端。
    用 gem_client（已装好 app.state.model_mapping/gem_mapping）而非裸 client，
    因为要真正跑到 resolved_model 判断那一段（裸 client 不跑 lifespan，state 里没有这些对象）。"""
    from fastapi.responses import JSONResponse

    async def fake_dispatch(request, resolved_model, messages_raw, tools_raw, tool_choice,
                            stream, request_params):
        assert resolved_model == "deepseek-chat"
        assert stream is False
        return JSONResponse(content={"object": "response", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}
        ]})

    monkeypatch.setattr("app.core.responses_thirdparty.dispatch_thirdparty_responses", fake_dispatch)
    r = gem_client.post("/v1/responses", json={"model": "deepseek-chat", "input": "hi"}, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["output"][0]["content"][0]["text"] == "ok"


def test_responses_non_stream_embeds_generated_images_as_markdown(gem_client, monkeypatch):
    """Gemini 生图（result.images）不能被 /v1/responses 静默丢弃：沿用 chat/completions 的
    既有做法，Markdown 图片链接嵌入文字内容（design doc §1/§4.3）。"""
    import app.routers.responses as rr

    async def fake_generate(prompt, model, conversation_id="", attachments=None,
                            gem_id=None, account_id=None, extended_thinking=False):
        return {"text": "here you go", "conversation_id": "",
               "images": [{"id": "img-123"}]}

    monkeypatch.setattr(rr.gemini_client, "generate", fake_generate)
    r = gem_client.post("/v1/responses", json={"model": "gemini-pro", "input": "draw a cat"},
                        headers=_AUTH)
    assert r.status_code == 200
    text = r.json()["output"][0]["content"][0]["text"]
    assert "![generated image](" in text
    assert "img-123" in text
    assert "here you go" in text


def test_responses_stream_with_tools_buffers_and_emits_function_call_done(gem_client, monkeypatch):
    import app.routers.responses as rr

    async def fake_generate(prompt, model, conversation_id="", attachments=None,
                            gem_id=None, account_id=None, extended_thinking=False):
        return {"text": '{"status":"tool_use","tool_calls":[{"name":"run_shell","arguments":{"cmd":"ls"}}]}',
               "conversation_id": "", "images": []}

    monkeypatch.setattr(rr.gemini_client, "generate", fake_generate)
    with gem_client.stream("POST", "/v1/responses", json={
        "model": "gemini-pro", "input": "list files", "stream": True,
        "tools": [{"type": "function", "name": "run_shell", "description": "d", "parameters": {}}],
    }, headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert "response.function_call_arguments.done" in body
    assert "response.completed" in body


def test_responses_sends_native_tool_history_to_thirdparty(gem_client, monkeypatch):
    """第三方收到的是 OpenAI 原生的 assistant.tool_calls + 带 tool_call_id 的 tool 消息（v1.6.48）。"""
    from fastapi.responses import JSONResponse
    seen = {}

    async def fake_dispatch(request, resolved_model, messages_raw, tools_raw, tool_choice,
                            stream, request_params):
        seen["messages"] = messages_raw
        return JSONResponse(content={"object": "response", "output": []})

    monkeypatch.setattr("app.core.responses_thirdparty.dispatch_thirdparty_responses", fake_dispatch)
    r = gem_client.post("/v1/responses", json={"model": "deepseek-chat", "input": [
        {"type": "message", "role": "user", "content": "列目录"},
        {"type": "function_call", "call_id": "call_1", "name": "shell", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "a.txt"},
    ]}, headers=_AUTH)
    assert r.status_code == 200
    assert seen["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert seen["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "a.txt"}


"""defect ⑧：原生 Gemini 路由此前只认 snake_case，官方 SDK 发出的 camelCase wire format
（systemInstruction/generationConfig/inlineData/functionCall/functionResponse）被 pydantic
当成未知字段静默丢弃——system prompt 消失、生成参数消失、附件消失、工具调用/工具结果消失，
但请求仍然 200，是最隐蔽的一类失败。

覆盖两层：
1. 模型层：GeminiRequest.model_validate 直接喂 camelCase JSON，断言字段真的落进了 snake_case
   属性里（而不是 None）。generation_config 目前未被路由层消费（连 snake_case 时代都没有），
   所以只在模型层钉住"解析成功"，不在端点层断言它传到了上游。
2. 端点层：systemInstruction / inlineData / functionCall / functionResponse 这几个确实会被
   路由层消费并传到 gemini_client.generate() 的字段，跑真实端点、monkeypatch generate()
   捕获 prompt/attachments，断言值真的到达了。

每个 camelCase 场景都配一个逐字等价的 snake_case 版本，断言两者产出完全一致——
populate_by_name=True 不能破坏任何既有 snake_case 调用方。
"""
import base64

from app.models.gemini import GeminiRequest, GeminiContent, GeminiPart

_AUTH = {"Authorization": "Bearer sk-test-key"}
_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def _ok_result(text="ok"):
    return {"text": text, "conversation_id": "", "images": [], "thoughts": ""}


# ---------------------------------------------------------------------------
# 1. 模型层：camelCase 字段确实落进对应属性，不再是 None
# ---------------------------------------------------------------------------

class TestModelAcceptsCamelCase:
    def test_system_instruction_camel(self):
        req = GeminiRequest.model_validate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "systemInstruction": {"parts": [{"text": "be nice"}]},
        })
        assert req.system_instruction is not None
        assert req.system_instruction.parts[0].text == "be nice"

    def test_generation_config_camel(self):
        req = GeminiRequest.model_validate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 256, "topP": 0.9, "topK": 40},
        })
        assert req.generation_config is not None
        assert req.generation_config.temperature == 0.7
        assert req.generation_config.max_output_tokens == 256
        assert req.generation_config.top_p == 0.9
        assert req.generation_config.top_k == 40

    def test_inline_data_camel(self):
        req = GeminiRequest.model_validate({
            "contents": [{"role": "user", "parts": [
                {"text": "look"},
                {"inlineData": {"mimeType": "image/png", "data": _PNG_B64}},
            ]}],
        })
        assert req.contents[0].parts[1].inline_data == {"mimeType": "image/png", "data": _PNG_B64}

    def test_tool_config_and_tools_camel(self):
        req = GeminiRequest.model_validate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "tools": [{"functionDeclarations": [
                {"name": "run", "description": "run cmd", "parameters": {"type": "object"}}]}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        })
        assert req.tools[0].function_declarations[0].name == "run"
        assert req.tool_config.function_calling_config == {"mode": "AUTO"}

    def test_snake_case_still_works_at_model_level(self):
        """populate_by_name=True 回归守卫：既有 snake_case 调用方（内部测试/其它协议转发）不受影响。"""
        req = GeminiRequest.model_validate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "system_instruction": {"parts": [{"text": "be nice"}]},
            "generation_config": {"temperature": 0.7, "max_output_tokens": 256, "top_p": 0.9, "top_k": 40},
        })
        assert req.system_instruction.parts[0].text == "be nice"
        assert req.generation_config.max_output_tokens == 256


# ---------------------------------------------------------------------------
# 2. 端点层：真正被消费的字段（system prompt / 附件 / 工具调用文本）到达上游
# ---------------------------------------------------------------------------

def test_system_instruction_camel_reaches_upstream_prompt(gem_client, monkeypatch):
    import app.routers.gemini as ge
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["prompt"] = prompt
        return _ok_result()

    monkeypatch.setattr(ge.gemini_client, "generate", fake_generate)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "systemInstruction": {"parts": [{"text": "be nice"}]},
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    assert "be nice" in captured["prompt"]
    assert captured["prompt"].startswith("System: be nice")


def test_system_instruction_snake_case_regression_identical(gem_client, monkeypatch):
    import app.routers.gemini as ge
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["prompt"] = prompt
        return _ok_result()

    monkeypatch.setattr(ge.gemini_client, "generate", fake_generate)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "system_instruction": {"parts": [{"text": "be nice"}]},
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    assert captured["prompt"] == "System: be nice\n\nHuman: hi"


def test_inline_data_camel_reaches_attachments(gem_client, monkeypatch):
    import app.routers.gemini as ge
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["attachments"] = attachments
        return _ok_result()

    monkeypatch.setattr(ge.gemini_client, "generate", fake_generate)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={
            "contents": [{"role": "user", "parts": [
                {"text": "look"},
                {"inlineData": {"mimeType": "image/png", "data": _PNG_B64}},
            ]}],
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    atts = captured["attachments"]
    assert len(atts) == 1
    assert atts[0]["mime"] == "image/png"
    assert isinstance(atts[0]["data"], (bytes, bytearray))


def test_inline_data_snake_case_regression_identical(gem_client, monkeypatch):
    import app.routers.gemini as ge
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["attachments"] = attachments
        return _ok_result()

    monkeypatch.setattr(ge.gemini_client, "generate", fake_generate)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={
            "contents": [{"role": "user", "parts": [
                {"text": "look"},
                {"inline_data": {"mime_type": "image/png", "data": _PNG_B64}},
            ]}],
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    atts = captured["attachments"]
    assert len(atts) == 1
    assert atts[0]["mime"] == "image/png"


def test_function_call_and_response_camel_reach_prompt(gem_client, monkeypatch):
    """Gemini 原生工具循环：上一轮的 functionCall + 客户端回填的 functionResponse
    此前完全不被识别（只认 text part），现应渲染进 prompt，模型才能看到工具调用历史。"""
    import app.routers.gemini as ge
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["prompt"] = prompt
        return _ok_result()

    monkeypatch.setattr(ge.gemini_client, "generate", fake_generate)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={
            "contents": [
                {"role": "user", "parts": [{"text": "what's the weather in SF?"}]},
                {"role": "model", "parts": [
                    {"functionCall": {"name": "get_weather", "args": {"city": "SF"}}}]},
                # 官方 Gemini wire format 里 Content.role 只有 "user"/"model" 两种取值
                # （无独立的 "function"/"tool" role）——functionResponse 和普通用户消息
                # 一样挂在 role="user" 的 Content 下。
                {"role": "user", "parts": [
                    {"functionResponse": {"name": "get_weather", "response": {"content": "sunny, 72F"}}}]},
            ],
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    prompt = captured["prompt"]
    assert '[Tool call: get_weather({"city": "SF"})]' in prompt
    assert "sunny, 72F" in prompt
    assert "[Tool result:" in prompt


def test_function_call_and_response_snake_case_regression_identical(gem_client, monkeypatch):
    import app.routers.gemini as ge
    captured = {}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        captured["prompt"] = prompt
        return _ok_result()

    monkeypatch.setattr(ge.gemini_client, "generate", fake_generate)
    r = gem_client.post(
        "/v1beta/models/gemini-pro:generateContent",
        json={
            "contents": [
                {"role": "user", "parts": [{"text": "what's the weather in SF?"}]},
                {"role": "model", "parts": [
                    {"function_call": {"name": "get_weather", "args": {"city": "SF"}}}]},
                {"role": "user", "parts": [
                    {"function_response": {"name": "get_weather", "response": {"content": "sunny, 72F"}}}]},
            ],
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    prompt = captured["prompt"]
    assert '[Tool call: get_weather({"city": "SF"})]' in prompt
    assert "sunny, 72F" in prompt

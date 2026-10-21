"""回归：commit 2c6172c 让 _parse_contents 把 functionResponse part 渲染进用户消息的
TEXT（供模型看到工具调用历史），但这段渲染出的文本随后被喂进 last_user_text() 做
「生图意图」判断——工具结果正文里随便一句提到 image/picture 的话（如某个 list_files
工具返回 "... contains an image of a logo"）就会被误判成用户在要图，导致
is_image_generation_intent 命中，客户端声明的 tools/functionDeclarations 被静默丢弃。

这正是 commit efbdd1d 在 Anthropic/OpenAI router 修过的缺陷，在原生 Gemini router
因 2c6172c 引入 functionResponse 渲染又重新出现了一次。修复见
app/routers/gemini.py::_last_user_text_native ——生图意图判断必须在 req.contents
（part 类型尚未被拍平成字符串）这一层过滤，只取 role=="user" 最后一条内容里的
纯 text part，跳过 function_call/function_response。
"""

_AUTH = {"Authorization": "Bearer sk-test-key"}


def _ok_result(text="ok"):
    return {"text": text, "conversation_id": "", "images": [], "thoughts": ""}


def test_function_response_mentioning_image_does_not_drop_tools(gem_client, monkeypatch):
    """官方 SDK 形态的第二轮请求：上一轮 functionCall + 客户端回填的 functionResponse，
    工具结果 JSON 正文里带 "image" 字样。tools 必须存活——build_tool_prompt 的工具说明
    要真的到达上游 prompt，不能被生图意图判断静默吃掉。"""
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
                {"role": "user", "parts": [{"text": "List my files"}]},
                {"role": "model", "parts": [
                    {"functionCall": {"name": "list_files", "args": {}}}]},
                {"role": "user", "parts": [
                    {"functionResponse": {
                        "name": "list_files",
                        "response": {"out": "assets/ contains an image of a logo"},
                    }}]},
            ],
            "tools": [{"functionDeclarations": [
                {"name": "list_files", "description": "List files in a directory",
                 "parameters": {"type": "object"}}]}],
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    prompt = captured["prompt"]
    assert "You have access to the following tools:" in prompt, (
        f"tools 被生图意图判断误丢弃，captured prompt: {prompt!r}"
    )
    assert "list_files: List files in a directory" in prompt


def test_genuine_image_text_still_routes_to_image_path(gem_client, monkeypatch):
    """对照组：图片意图真的出现在最后一轮用户消息的 text part 里时，仍要拿到生图路径
    （不注入工具 JSON 指令），不能因为这次修复而把这条路也堵死。"""
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
                {"role": "user", "parts": [{"text": "draw me a cat"}]},
            ],
            "tools": [{"functionDeclarations": [
                {"name": "list_files", "description": "List files in a directory",
                 "parameters": {"type": "object"}}]}],
        },
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    prompt = captured["prompt"]
    assert "You have access to the following tools:" not in prompt, (
        f"生图意图没能压制工具 prompt，captured prompt: {prompt!r}"
    )

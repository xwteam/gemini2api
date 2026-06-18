"""Unit tests for ``app.utils.tools`` (pure logic, stdlib-only).

These characterize the image-intent detection and the prompt-simulated
tool-call parsing so future refactors cannot silently change behavior.
"""

import pytest

from app.utils import tools


class TestImageGenerationIntent:
    @pytest.mark.parametrize(
        "text",
        [
            "画一只猫",
            "帮我画一个 logo",
            "生成一张图",
            "做一张海报",
            "generate an image of a cat",
            "create a picture of the moon",
            "a photo of a dog",
        ],
    )
    def test_positive(self, text):
        assert tools.is_image_generation_intent(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "写一份报告",
            "create a plan",          # 收窄：无图像词，不应触发
            "tell me about cats",
            "总结一下这段文字",
        ],
    )
    def test_negative(self, text):
        assert tools.is_image_generation_intent(text) is False

    @pytest.mark.xfail(
        reason="P2 已知误判：'draw a' 子串命中 'draw a conclusion'（待词边界修复）",
        strict=False,
    )
    def test_known_false_positive_draw_a_conclusion(self):
        assert tools.is_image_generation_intent("please draw a conclusion") is False


class TestMaybeImageGenerationIntent:
    @pytest.mark.parametrize(
        "text",
        [
            "画一只猫",                 # 严格命中也应为 True
            "给我做个壁纸",             # 名词(壁纸)+动词(做/给我)
            "I want a wallpaper",       # noun(wallpaper)+verb(want)
            "搞个头像",
        ],
    )
    def test_positive(self, text):
        assert tools.maybe_image_generation_intent(text) is True

    @pytest.mark.parametrize("text", ["", "今天天气真好", "讲个笑话"])
    def test_negative(self, text):
        assert tools.maybe_image_generation_intent(text) is False

    def test_superset_of_strict(self):
        strict_positive = "generate an image of a fox"
        assert tools.is_image_generation_intent(strict_positive) is True
        assert tools.maybe_image_generation_intent(strict_positive) is True


class TestParseToolResponse:
    def test_plain_tool_call(self):
        raw = '{"status": "tool_use", "tool_calls": [{"name": "run", "arguments": {"cmd": "ls"}}]}'
        out = tools.parse_tool_response(raw)
        assert out["type"] == "tool_calls"
        assert out["tool_calls"][0]["name"] == "run"
        assert out["tool_calls"][0]["arguments"] == {"cmd": "ls"}

    def test_markdown_fenced_tool_call(self):
        raw = '```json\n{"status":"tool_use","tool_calls":[{"name":"f","arguments":{}}]}\n```'
        out = tools.parse_tool_response(raw)
        assert out["type"] == "tool_calls"
        assert out["tool_calls"][0]["name"] == "f"

    def test_text_status(self):
        out = tools.parse_tool_response('{"status": "text", "content": "hello"}')
        assert out == {"type": "text", "content": "hello"}

    def test_plain_text_passthrough(self):
        out = tools.parse_tool_response("just a normal reply")
        assert out == {"type": "text", "content": "just a normal reply"}

    def test_arguments_as_json_string_normalized(self):
        raw = '{"tool_calls": [{"name": "g", "arguments": "{\\"a\\": 1}"}]}'
        out = tools.parse_tool_response(raw)
        assert out["type"] == "tool_calls"
        assert out["tool_calls"][0]["arguments"] == {"a": 1}

    def test_malformed_tool_json_not_passed_through(self):
        # 残缺的工具调用 JSON 不应原样透传给客户端
        raw = '{"status": "tool_use", "tool_calls": [{"name": "x", "argumen'
        out = tools.parse_tool_response(raw)
        assert out["type"] == "text"
        assert "工具调用" in out["content"]

    def test_empty_returns_text(self):
        assert tools.parse_tool_response("") == {"type": "text", "content": ""}


class TestBuildToolPrompt:
    def test_no_tools_returns_prompt_unchanged(self):
        assert tools.build_tool_prompt("hi", []) == "hi"

    def test_with_tools_embeds_schema(self):
        out = tools.build_tool_prompt(
            "do it",
            [{"function": {"name": "run", "description": "run cmd", "parameters": {}}}],
        )
        assert "run" in out
        assert "tool_use" in out
        assert "User message: do it" in out

    def test_tool_choice_required(self):
        out = tools.build_tool_prompt("x", [{"function": {"name": "a"}}], tool_choice="required")
        assert "MUST use one of the available tools" in out


class TestHelpers:
    def test_estimate_tokens(self):
        assert tools.estimate_tokens("") == 0
        assert tools.estimate_tokens("abcdefgh") == 2  # len 8 // 4

    def test_extract_json_object(self):
        assert tools._extract_json_object('noise {"a": 1} tail') == '{"a": 1}'
        assert tools._extract_json_object("no json here") is None

    def test_strip_code_fence(self):
        assert tools._strip_code_fence('```json\n{"a":1}\n```') == '{"a":1}'
        assert tools._strip_code_fence("plain") == "plain"

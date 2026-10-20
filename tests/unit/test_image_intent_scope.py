"""生图意图误判 → 静默丢掉客户端 tools 的回归守卫。

两处修复：
1. 作用域：意图只看「最后一轮用户消息」，不再看整段拍平 prompt
   （后者含 system 提示词、历史轮次、tool_result 正文）。
2. 词边界：英文模式改为 \\b 锚定的正则；"draw a"/"draw an" 这类只有动词+冠词、
   自身不含图像名词的片段，还必须后随图像名词才算要图。
CJK 无词边界概念，仍按子串匹配，因此中文误判只能靠作用域修复兜住。
"""

import pytest

from app.utils import tools
from app.utils.prompt import last_user_text

_AUTH = {"Authorization": "Bearer sk-test-key"}

# 被验证过的误判样本（修复前 is_image_generation_intent 全部返回 True）
DOCKERFILE_TEXT = "FROM python:3.12\n# create an image of the app\nRUN pip install -r req.txt"
DOCKER_CMD_TEXT = "docker build -t x . # image of a container"
CJK_DOC_TEXT = "本文档绘制了系统架构"
TOOL_RESULT_TEXT = "an image of a cat is stored at /tmp"

_TOOLS_MARKER = "You have access to the following tools:"


def _ok_result(text="ok"):
    return {"text": text, "conversation_id": "", "images": [], "thoughts": ""}


# --------------------------------------------------------------------------
# 1. 匹配器层面：词边界 / 冠词片段类误判
# --------------------------------------------------------------------------
class TestMatcherFalsePositives:
    @pytest.mark.parametrize(
        "text",
        [
            "please draw a conclusion",          # 原 xfail
            "draw an outline of the plan",
            "we should draw a distinction between the two",
            "draw a line under this discussion",
            "let me draw an inference from the logs",
        ],
    )
    def test_english_idioms_are_not_image_intent(self, text):
        assert tools.is_image_generation_intent(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "draw a map of the kingdom",
            "draw a card for my friend",
            "draw a line drawing of a cat",
        ],
    )
    def test_r4_ambiguous_idioms_stay_excluded(self, text):
        """R4 一度把 map/card/line 移出习语闭集，理由是它们也是真实可画之物，但该改动
        已被回退：is_image_generation_intent 只在客户端声明了 tools 时才有效果——它
        决定的是要不要压制/丢弃这些 tools。假阳性（习语被误判成生图意图）会让 tools
        被静默丢弃、agent 的工具循环无声断掉，没有报错没有日志；假阴性（真实生图请求
        未被识别）只是这一次生图被压制成文本回复，用户看得见、能立刻换说法重试。两者
        代价不对称，所以安全方向是排除更多习语而非更少，即使这意味着牺牲
        "draw a map of the kingdom" 这类真实生图请求的召回率。见
        app/utils/tools.py 里 _DRAW_ARTICLE_IDIOM_OBJECTS 上方注释。"""
        assert tools.is_image_generation_intent(text) is False

    def test_word_boundary_required(self):
        """子串匹配会在词内命中；\\b 之后不再。"""
        assert tools.is_image_generation_intent("the metadata photo of-mode flag") is False
        assert tools.is_image_generation_intent("a photo of a dog") is True


class TestMatcherStillPositive:
    @pytest.mark.parametrize(
        "text",
        [
            "draw a picture of a cat",
            "draw a nice picture of a cat",
            "draw me a dog",
            "create an image of a sunset",
            "generate an image of a cat",
            "create a picture of the moon",
            "make a poster of the concert",
            "a photo of a dog",
            "画一只猫",
            "帮我画一个 logo",
            "生成一张图",
            "做一张海报",
            # 曾经的过度修正回归守卫：这四个是英文最常见的生图请求，"draw a/an" 后面
            # 不跟图像名词也必须命中——之前误把它们和 "draw a conclusion" 这类习语
            # 混为一谈，导致 has_tools 常年为 True、四个 router 全部注入工具 prompt、
            # 压制了 Gemini 的生图。绝不能再回归。
            "draw a cat",
            "draw an elephant",
            "draw a robot in space",
            "please draw a cat for me",
        ],
    )
    def test_genuine_requests_still_detected(self, text):
        assert tools.is_image_generation_intent(text) is True

    def test_cjk_still_substring_matched(self):
        """中文没有词边界，保持子串匹配（不能改成正则 \\b）。"""
        assert tools.is_image_generation_intent("帮我绘制一张猫的插画") is True

    def test_known_gap_unchanged_but_covered_by_loose_helper(self):
        """既有缺口（本次修复未改变）：'生成一张猫的图片' 不是关键词表里的连续串，
        严格判断本来就是 False；宽松兜底仍能命中，生图链路不受影响。"""
        assert tools.is_image_generation_intent("生成一张猫的图片") is False
        assert tools.maybe_image_generation_intent("生成一张猫的图片") is True


class TestLooseHelperNotNarrowed:
    """maybe_image_generation_intent 现在**只**决定非流式 POST 超时该不该抬一档，
    不再参与 buffered 分流（分流只看 has_tools），而且它只会"加时"不会"减时"。
    收窄它会让真·生图被我们自己掐断，所以收紧严格判断后，宽松判断的召回必须原样保留。"""

    @pytest.mark.parametrize(
        "text",
        ["draw a cat", "draw an elephant", "draw a picture of a cat", "draw me a dog"],
    )
    def test_loose_recall_preserved(self, text):
        assert tools.maybe_image_generation_intent(text) is True


# --------------------------------------------------------------------------
# 2. 作用域：last_user_text 只取最后一轮用户消息的 text 块
# --------------------------------------------------------------------------
class TestLastUserText:
    def test_plain_string_content(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert last_user_text(msgs) == "hello"

    def test_returns_last_user_turn_not_history(self):
        msgs = [
            {"role": "user", "content": "draw a picture of a cat"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "now refactor main.py"},
        ]
        assert last_user_text(msgs) == "now refactor main.py"

    def test_skips_assistant_and_system_turns(self):
        msgs = [
            {"role": "system", "content": DOCKERFILE_TEXT},
            {"role": "user", "content": "build it"},
            {"role": "assistant", "content": CJK_DOC_TEXT},
        ]
        assert last_user_text(msgs) == "build it"

    def test_tool_result_blocks_excluded(self):
        """Anthropic 协议里 tool_result 挂在 user 轮上，但它是工具输出不是用户诉求。"""
        msgs = [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": TOOL_RESULT_TEXT},
            {"type": "text", "text": "ok, continue"},
        ]}]
        assert last_user_text(msgs) == "ok, continue"
        assert tools.is_image_generation_intent(last_user_text(msgs)) is False

    def test_tool_result_only_turn_is_empty(self):
        msgs = [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": TOOL_RESULT_TEXT},
        ]}]
        assert last_user_text(msgs) == ""
        assert tools.is_image_generation_intent(last_user_text(msgs)) is False

    def test_multiple_text_blocks_joined(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "a"}, {"type": "text", "text": "b"},
        ]}]
        assert last_user_text(msgs) == "a\nb"

    def test_no_user_message_returns_empty(self):
        assert last_user_text([{"role": "assistant", "content": "hi"}]) == ""
        assert last_user_text([]) == ""

    def test_image_block_only_turn_does_not_crash(self):
        msgs = [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "data": ""}}]}]
        assert last_user_text(msgs) == ""

    def test_typeless_text_block_falls_back(self):
        """镜像 build_prompt_from_messages 里的兜底：block 带字符串 "text" 但没有
        （或带别的）type 字段时也要纳入，否则这类请求永远判不出生图意图。"""
        msgs = [{"role": "user", "content": [{"text": "draw a picture of a cat"}]}]
        assert last_user_text(msgs) == "draw a picture of a cat"
        assert tools.is_image_generation_intent(last_user_text(msgs)) is True

    def test_typeless_fallback_still_excludes_image_blocks(self):
        """image 块正常没有 "text"；万一出现，也不该被兜底当成用户正文纳入。"""
        msgs = [{"role": "user", "content": [{"type": "image", "text": TOOL_RESULT_TEXT}]}]
        assert last_user_text(msgs) == ""

    @pytest.mark.parametrize("noise", [DOCKERFILE_TEXT, DOCKER_CMD_TEXT, CJK_DOC_TEXT, TOOL_RESULT_TEXT])
    def test_noise_in_history_never_reaches_matcher(self, noise):
        """这些文本本身仍会命中关键词（中文/含图像名词的英文无法靠词边界区分），
        所以必须靠作用域挡住：它们出现在 system/历史/tool_result 里就不该被看见。"""
        msgs = [
            {"role": "system", "content": noise},
            {"role": "assistant", "content": noise},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": noise},
                                         {"type": "text", "text": "继续修 bug"}]},
        ]
        assert tools.is_image_generation_intent(last_user_text(msgs)) is False


# --------------------------------------------------------------------------
# 3. 端到端：tools 不再被静默丢弃
# --------------------------------------------------------------------------
_CLAUDE_TOOLS = [{"name": "Bash", "description": "run a shell command",
                  "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}}]


def _patch_generate(monkeypatch, module):
    seen = {}

    async def fake_generate(prompt, *args, **kwargs):
        seen["prompt"] = prompt
        return _ok_result()

    monkeypatch.setattr(module.gemini_client, "generate", fake_generate)
    return seen


class TestClaudeEndpointKeepsTools:
    def test_tool_result_mentioning_image_does_not_drop_tools(self, gem_client, monkeypatch):
        """核心回归：tool_result 正文里的 'an image of a cat is stored at /tmp'
        曾让 has_tools=False —— 客户端 tools 被静默丢弃且请求改走真流式路径。"""
        import app.routers.claude as cl
        seen = _patch_generate(monkeypatch, cl)

        r = gem_client.post("/v1/messages", json={
            "model": "gemini-pro", "max_tokens": 100, "tools": _CLAUDE_TOOLS,
            "messages": [
                {"role": "user", "content": "find the cat picture"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": TOOL_RESULT_TEXT},
                    {"type": "text", "text": "ok, now run the tests"},
                ]},
            ],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER in seen["prompt"]     # 工具指令块仍在 → tools 没被丢
        assert "Bash" in seen["prompt"]

    @pytest.mark.parametrize("system_text", [DOCKERFILE_TEXT, DOCKER_CMD_TEXT, CJK_DOC_TEXT])
    def test_system_prompt_noise_does_not_drop_tools(self, gem_client, monkeypatch, system_text):
        import app.routers.claude as cl
        seen = _patch_generate(monkeypatch, cl)

        r = gem_client.post("/v1/messages", json={
            "model": "gemini-pro", "max_tokens": 100, "tools": _CLAUDE_TOOLS,
            "system": system_text,
            "messages": [{"role": "user", "content": "run the build"}],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER in seen["prompt"]

    def test_english_idiom_in_last_turn_does_not_drop_tools(self, gem_client, monkeypatch):
        import app.routers.claude as cl
        seen = _patch_generate(monkeypatch, cl)

        r = gem_client.post("/v1/messages", json={
            "model": "gemini-pro", "max_tokens": 100, "tools": _CLAUDE_TOOLS,
            "messages": [{"role": "user", "content": "read the logs and draw a conclusion"}],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER in seen["prompt"]

    def test_review_regression_grep_line_idiom_does_not_drop_tools(self, gem_client, monkeypatch):
        """R4 回归守卫：审查实测复现的具体场景。最后一轮用户消息里含
        "draw a line under this discussion" 这个纯习语用法，且客户端声明了 tools。
        R4 曾把 line 移出闭集，导致这句话被误判成生图意图：tools 被静默丢弃、请求
        改走生图分支，agent 的工具循环无声断掉，没有报错也没有日志。回退后（line
        重新回到闭集里）必须仍然保留 tools。"""
        import app.routers.claude as cl
        seen = _patch_generate(monkeypatch, cl)

        r = gem_client.post("/v1/messages", json={
            "model": "gemini-pro", "max_tokens": 100, "tools": _CLAUDE_TOOLS,
            "messages": [{
                "role": "user",
                "content": "In the doc it says 'draw a line under this discussion'. Please grep for it.",
            }],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER in seen["prompt"]     # 工具指令块仍在 → tools 没被丢
        assert "Bash" in seen["prompt"]

    def test_genuine_image_request_still_bypasses_tools(self, gem_client, monkeypatch):
        """反向守卫：真·生图意图仍要跳过工具模拟，否则工具 prompt 会压制生图。"""
        import app.routers.claude as cl
        seen = _patch_generate(monkeypatch, cl)

        r = gem_client.post("/v1/messages", json={
            "model": "gemini-pro", "max_tokens": 100, "tools": _CLAUDE_TOOLS,
            "messages": [{"role": "user", "content": "draw a picture of a cat"}],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER not in seen["prompt"]


class TestOpenAIEndpointKeepsTools:
    _TOOLS = [{"type": "function", "function": {
        "name": "run", "description": "run cmd",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]

    def test_tool_output_mentioning_image_does_not_drop_tools(self, gem_client, monkeypatch):
        import app.routers.openai as oa
        seen = _patch_generate(monkeypatch, oa)

        r = gem_client.post("/v1/chat/completions", json={
            "model": "gemini-pro", "tools": self._TOOLS,
            "messages": [
                {"role": "system", "content": DOCKERFILE_TEXT},
                {"role": "user", "content": "list the files"},
                {"role": "assistant", "content": None,
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": "run", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": TOOL_RESULT_TEXT},
                {"role": "user", "content": "now run the tests"},
            ],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER in seen["prompt"]

    def test_genuine_image_request_still_bypasses_tools(self, gem_client, monkeypatch):
        import app.routers.openai as oa
        seen = _patch_generate(monkeypatch, oa)

        r = gem_client.post("/v1/chat/completions", json={
            "model": "gemini-pro", "tools": self._TOOLS,
            "messages": [{"role": "user", "content": "画一只猫"}],
        }, headers=_AUTH)

        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER not in seen["prompt"]


class TestGeminiEndpointKeepsTools:
    _TOOLS = [{"function_declarations": [
        {"name": "run", "description": "run cmd", "parameters": {"type": "object"}}]}]

    def _body(self, last_user: str, **extra):
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "check the repo"}]},
                {"role": "model", "parts": [{"text": CJK_DOC_TEXT}]},
                {"role": "user", "parts": [{"text": last_user}]},
            ],
            "tools": self._TOOLS,
        }
        body.update(extra)
        return body

    def test_generate_content_keeps_function_declarations(self, gem_client, monkeypatch):
        import app.routers.gemini as ge
        seen = _patch_generate(monkeypatch, ge)

        r = gem_client.post(
            "/v1beta/models/gemini-pro:generateContent",
            json=self._body("now run the tests",
                            system_instruction={"role": "user", "parts": [{"text": DOCKERFILE_TEXT}]}),
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER in seen["prompt"]

    def test_stream_generate_content_keeps_function_declarations(self, gem_client, monkeypatch):
        import app.routers.gemini as ge
        seen = _patch_generate(monkeypatch, ge)

        with gem_client.stream(
            "POST", "/v1beta/models/gemini-pro:streamGenerateContent",
            json=self._body("now run the tests",
                            system_instruction={"role": "user", "parts": [{"text": DOCKERFILE_TEXT}]}),
            headers=_AUTH,
        ) as r:
            assert r.status_code == 200
            r.read()
        assert _TOOLS_MARKER in seen["prompt"]

    def test_genuine_image_request_still_bypasses_tools(self, gem_client, monkeypatch):
        import app.routers.gemini as ge
        seen = _patch_generate(monkeypatch, ge)

        r = gem_client.post(
            "/v1beta/models/gemini-pro:generateContent",
            json=self._body("create an image of a sunset"),
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert _TOOLS_MARKER not in seen["prompt"]

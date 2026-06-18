"""Unit tests for ``app.utils.prompt`` (pure logic, stdlib-only).

Covers message flattening and multimodal attachment extraction for both the
OpenAI (``image_url``) and Claude (``image.source``) content shapes.
"""

import base64

from app.utils import prompt

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


class TestBuildPromptFromMessages:
    def test_roles_are_labeled(self):
        out = prompt.build_prompt_from_messages(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "yo"},
            ]
        )
        assert "Human: hi" in out
        assert "Assistant: yo" in out

    def test_system_param_prefixed(self):
        out = prompt.build_prompt_from_messages([{"role": "user", "content": "q"}], system="be nice")
        assert out.startswith("System: be nice")

    def test_list_content_blocks_flattened(self):
        out = prompt.build_prompt_from_messages(
            [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]
        )
        assert "Human: a\nb" in out

    def test_tool_prompt_appended(self):
        out = prompt.build_prompt_from_messages([{"role": "user", "content": "x"}], tool_prompt="TOOLS")
        assert out.rstrip().endswith("TOOLS")


class TestExtractAttachments:
    def test_text_only_returns_empty(self):
        assert prompt.extract_attachments([{"role": "user", "content": "plain text"}]) == []

    def test_openai_data_uri(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_B64}"}}
                ],
            }
        ]
        atts = prompt.extract_attachments(msgs)
        assert len(atts) == 1
        assert atts[0]["mime"] == "image/png"
        assert atts[0]["filename"].endswith(".png")
        assert isinstance(atts[0]["data"], (bytes, bytearray))

    def test_openai_http_url(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "https://x/y.png"}}],
            }
        ]
        atts = prompt.extract_attachments(msgs)
        assert atts == [{"url": "https://x/y.png", "filename": "image_0", "mime": ""}]

    def test_claude_base64_source(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": _PNG_B64},
                    }
                ],
            }
        ]
        atts = prompt.extract_attachments(msgs)
        assert len(atts) == 1
        assert atts[0]["mime"] == "image/jpeg"
        assert atts[0]["filename"].endswith(".jpg")

    def test_invalid_data_uri_skipped(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,@@@notb64"}}],
            }
        ]
        # _parse_image_url 对非法 base64 返回 None → 被跳过
        assert prompt.extract_attachments(msgs) == []


class TestParseImageUrl:
    def test_http(self):
        assert prompt._parse_image_url("http://a/b", 0) == {
            "url": "http://a/b",
            "filename": "image_0",
            "mime": "",
        }

    def test_non_url_returns_none(self):
        assert prompt._parse_image_url("notaurl", 0) is None
        assert prompt._parse_image_url("", 0) is None

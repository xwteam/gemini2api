"""M3：Canvas 正文丢失（数据丢失）。

Gemini 网页端写较长代码/文档时会自动把内容放进 Canvas 面板，正文里只留一个
`http://googleusercontent.com/immersive_entry_chip/N` 占位链接。改动前我们既不读真实
内容、也不剥这个链接 —— 客户端拿到的"答案"就是一条打不开的 URL，正文全丢（连被
Gemini 塞进 Canvas 的工具调用 JSON 一起丢，因为 parse_tool_response 是在客户端层
返回正文之后才跑的）。

真实内容在 candidate[30]，口径同参考实现 refs/gemini-web-to-api 的 extractCanvases。
流式与非流式必须产出逐字节一致的正文，所以每条都两边都测。
"""

import asyncio
import json

from app.core import gemini_client as gc

CHIP0 = "http://googleusercontent.com/immersive_entry_chip/0"
CHIP1 = "https://googleusercontent.com/immersive_entry_chip/1"


def canvas_entry(content: str, *, is_code=True, language=None, file_name="main.py",
                 title="Demo", cid="c-1") -> list:
    """candidate[30] 的一条：[id,_,title,_,content,…,fileName(9),kind(10),…,details(14),…]"""
    e = [None] * 18
    e[0] = cid
    e[2] = title
    e[4] = content
    e[9] = file_name
    e[10] = 2 if is_code else 1
    if language is not None:
        e[14] = [None, language]
    return e


def candidate(text: str, *, canvases=None, thoughts=None) -> list:
    c = [None] * 38
    c[1] = [text]
    if canvases is not None:
        c[30] = list(canvases)
    if thoughts is not None:
        c[37] = [[thoughts]]
    return c


def wrb_line(cand: list, conv="cid-1") -> str:
    payload = [None, conv, None, None, [cand]]
    return json.dumps([["wrb.fr", "rpc", json.dumps(payload)]])


def parse(*candidates: list) -> dict:
    """一个 candidate 一帧（真机就是这样：帧是累积式的，每帧一个 candidate）。"""
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    return client._parse_output("\n".join(wrb_line(c) for c in candidates))


def finalize(text: str, canvases=None, thoughts="", images=None) -> dict:
    """流式收尾。canvases 传的是**解析后**的条目（流式循环里 _canvases_from_wrb 的产物）。"""
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    parsed = gc._extract_canvases(candidate("x", canvases=canvases)) if canvases else []
    return asyncio.run(
        client._finalize_stream(text, "cid-1", images or [], thoughts, parsed)
    )


def stream_canvases(cand: list) -> list:
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    elem = json.loads(wrb_line(cand))[0]
    return client._canvases_from_wrb(elem)


CODE = "def hello():\n    return 1"


# ---------------------------------------------------------------------------
# 1. 占位链 → 真实内容
# ---------------------------------------------------------------------------

def test_nonstream_restores_canvas_code_into_the_body():
    out = parse(candidate(f"给你写好了：\n\n{CHIP0}\n\n改完告诉我",
                          canvases=[canvas_entry(CODE, language="python")]))

    assert "immersive_entry_chip" not in out["text"], "死链绝不能当答案交付"
    assert out["text"] == "给你写好了：\n\n```python\ndef hello():\n    return 1\n```\n\n改完告诉我"


def test_stream_restores_the_same_body_byte_for_byte():
    text = f"给你写好了：\n\n{CHIP0}\n\n改完告诉我"
    canvases = [canvas_entry(CODE, language="python")]

    assert finalize(text, canvases)["text"] == parse(
        candidate(text, canvases=canvases))["text"]


def test_document_canvas_is_inlined_without_a_fence():
    out = parse(candidate(CHIP0, canvases=[
        canvas_entry("# 标题\n\n正文", is_code=False, file_name="doc.md")]))

    assert out["text"] == "# 标题\n\n正文"
    assert "```" not in out["text"]


def test_code_canvas_that_already_has_a_fence_is_not_double_wrapped():
    out = parse(candidate(CHIP0, canvases=[
        canvas_entry("```js\nlet a = 1;\n```", language="js")]))

    assert out["text"] == "```js\nlet a = 1;\n```"


def test_language_falls_back_to_the_file_extension():
    out = parse(candidate(CHIP0, canvases=[
        canvas_entry("SELECT 1;", language=None, file_name="q.sql")]))

    assert out["text"].startswith("```sql\n")


def test_language_is_read_from_details_index_4_too():
    entry = canvas_entry("x = 1", language=None, file_name="noext")
    entry[14] = [None, None, None, None, "python"]
    out = parse(candidate(CHIP0, canvases=[entry]))

    assert out["text"].startswith("```python\n")


def test_several_chips_map_to_their_own_canvases():
    out = parse(candidate(f"{CHIP0}\n---\n{CHIP1}", canvases=[
        canvas_entry("first", language="txt"),
        canvas_entry("second", language="txt"),
    ]))

    assert out["text"] == "```txt\nfirst\n```\n---\n```txt\nsecond\n```"


def test_canvas_from_an_earlier_frame_still_wins():
    """参考实现注释明说 Canvas 只出现在部分帧、最后一帧常常只有文本。
    每帧覆盖（含空值覆盖）的话，收尾时 canvases 会是空的 → 正文仍然丢。"""
    out = parse(
        candidate("稍等", canvases=[canvas_entry(CODE, language="python")]),
        candidate(f"写好了：{CHIP0}"),
    )

    assert "```python" in out["text"]
    assert "immersive_entry_chip" not in out["text"]


def test_canvases_are_read_from_a_stream_frame():
    found = stream_canvases(candidate("x", canvases=[canvas_entry(CODE, language="python")]))

    assert len(found) == 1
    assert found[0]["content"] == CODE
    assert found[0]["is_code"] is True


# ---------------------------------------------------------------------------
# 2. 取不到真实内容：剥死链 + 可读说明，且正文绝不变空
# ---------------------------------------------------------------------------

def test_a_chip_without_any_canvas_becomes_a_readable_note():
    out = parse(candidate(f"代码见：{CHIP0}"))

    assert "immersive_entry_chip" not in out["text"]
    assert gc._CANVAS_MISSING_NOTE in out["text"]


def test_an_out_of_range_chip_index_does_not_grab_another_canvas():
    """错配比丢内容更糟：把 A 的内容贴到 B 的位置，客户端完全看不出来。"""
    out = parse(candidate(f"{CHIP1}", canvases=[canvas_entry("only one", language="txt")]))

    assert "only one" not in out["text"]
    assert out["text"] == gc._CANVAS_MISSING_NOTE


def test_a_chip_only_answer_never_becomes_empty():
    """正文变空会被 fallback.is_empty_result / _is_empty_generation 判成空响应，
    累加空响应计数器甚至触发换号。"""
    from app.core.fallback import is_empty_result

    out = parse(candidate(CHIP0))

    assert out["text"].strip()
    assert not is_empty_result(out)
    assert finalize(CHIP0)["text"] == out["text"]


def test_canvas_entry_without_content_is_skipped():
    out = parse(candidate(CHIP0, canvases=[canvas_entry("", language="txt")]))

    assert out["text"] == gc._CANVAS_MISSING_NOTE


def test_malformed_canvas_structures_never_raise():
    for junk in (None, "not-a-list", [], [None], [["too", "short"]], [{"a": 1}], 42):
        cand = [None] * 38
        cand[1] = ["hi"]
        cand[30] = junk
        assert gc._extract_canvases(cand) == []
        assert parse(cand)["text"] == "hi"


# ---------------------------------------------------------------------------
# 3. 零回归
# ---------------------------------------------------------------------------

def test_an_answer_without_any_chip_is_byte_for_byte_unchanged():
    body = "普通回答。顺便提一句 ``` 和 http://example.com/x 都不该被动。"
    out = parse(candidate(body))

    assert out["text"] == body
    assert finalize(body)["text"] == body


def test_canvas_content_does_not_leak_into_thoughts():
    out = parse(candidate(f"见 {CHIP0}",
                          canvases=[canvas_entry(CODE, language="python")],
                          thoughts="我先想想"))

    assert out["thoughts"] == "我先想想"

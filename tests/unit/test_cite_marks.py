"""谷歌的引用标记 `[cite_start]` / `[cite: 1]` 不进正文（v1.6.51）。

北京 2026-10-27 中转站实测：带一张红色图片问颜色，回答是「红色[cite: 1]」。网页里这些标记渲染成
引用小标，API 客户端拿到的就是一串噪音。非流式与流式同一个口径；流式要扣住只到了一半的标记，
而且流出去的始终是最终正文的前缀（append-only）。
"""
import pytest

from app.core import gemini_client as gc


def _final(raw: str, images=()) -> str:
    """收尾口径（_finalize_stream / _parse_output）：还原正文 → 剥占位链接 → 剥引用标记。"""
    return gc._strip_image_placeholders(gc._restore_body(raw, [], "")[0], list(images))


@pytest.mark.parametrize("raw,clean", [
    ("红色[cite: 1]", "红色"),
    ("[cite_start]天空是蓝的[cite: 1, 2]。", "天空是蓝的。"),
    ("见第[cite: 3-5]页", "见第页"),
], ids=["tail", "start-and-multi", "range"])
def test_cite_marks_are_removed(raw, clean):
    assert _final(raw) == clean
    assert gc._stable_placeholder_prefix(raw) == clean


@pytest.mark.parametrize("raw", [
    "数组 a[1] 和 b[2]",
    "参见 [cite: 附录 B]",
    "[citation needed]",
    "[cite]",
    "data[cite:5]",
], ids=["index", "non-numeric", "citation-needed", "bare-cite", "code-without-space"])
def test_lookalikes_are_left_alone(raw):
    assert _final(raw) == raw
    assert gc._stable_placeholder_prefix(raw) == raw


def test_a_placeholder_right_before_a_cite_mark_does_not_swallow_the_text_after_it():
    """先剥占位、再剥引用标记：反过来的话占位链接和后面的中文挨在一起，被占位正则的 \\w* 吞掉。"""
    raw = "见下图 http://googleusercontent.com/image_retrieval/12[cite: 1]这是说明"
    assert _final(raw, images=[{"x": 1}]) == "见下图 这是说明"
    assert gc._stable_placeholder_prefix(raw) == "见下图 这是说明"


def test_a_half_cite_before_a_held_code_marker_does_not_leak():
    """扣住半截标记要看截断后的文本：被 code_event 扣住的尾巴里那个 [cite 不能漏出去。"""
    safe = gc._stable_placeholder_prefix("答案[cite: 1?code_reference&code_event_index=")
    assert "[" not in safe, safe


def _stream(frames):
    """模拟真流式：每帧是累积正文，按 _stable_placeholder_prefix 算增量（与 generate_stream 同口径）。"""
    emitted = ""
    for text in frames:
        safe = gc._stable_placeholder_prefix(text)
        assert safe.startswith(emitted), (emitted, safe)
        emitted = safe
    return emitted


def test_stream_never_leaks_a_half_marker_and_ends_as_the_final_text():
    frames = ["红色", "红色[", "红色[ci", "红色[cite: ", "红色[cite: 1", "红色[cite: 1]", "红色[cite: 1]。好"]
    leaked = [gc._stable_placeholder_prefix(f) for f in frames]
    assert not any("[" in s for s in leaked), leaked
    assert _stream(frames) == _final(frames[-1]) == "红色。好"


def test_stream_releases_a_bracket_that_turns_out_not_to_be_a_marker():
    frames = ["数组 a", "数组 a[", "数组 a[1", "数组 a[1]", "数组 a[1] 完"]
    assert gc._stable_placeholder_prefix("数组 a[") == "数组 a", "可能是标记的开头：先扣住"
    assert _stream(frames) == "数组 a[1] 完"


def test_cite_start_halves_are_held_too():
    assert gc._stable_placeholder_prefix("[cite_sta") == ""
    assert gc._stable_placeholder_prefix("[cite_start]蓝") == "蓝"

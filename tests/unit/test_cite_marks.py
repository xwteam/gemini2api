"""谷歌的引用标记 `[cite_start]` / `[cite: 1]` 不进正文（v1.6.51）。

北京 2026-10-27 中转站实测：带一张红色图片问颜色，回答是「红色[cite: 1]」。网页里这些标记渲染成
引用小标，API 客户端拿到的就是一串噪音。非流式与流式同一个口径；流式要扣住只到了一半的标记，
而且流出去的始终是最终正文的前缀（append-only）。
"""
import pytest

from app.core import gemini_client as gc


@pytest.mark.parametrize("raw,clean", [
    ("红色[cite: 1]", "红色"),
    ("[cite_start]天空是蓝的[cite: 1, 2]。", "天空是蓝的。"),
    ("见第[cite: 3-5]页", "见第页"),
    ("[cite:7]结尾", "结尾"),
], ids=["tail", "start-and-multi", "range", "no-space"])
def test_cite_marks_are_removed(raw, clean):
    assert gc._clean_control_markers(raw)[0] == clean
    assert gc._restore_body(raw, [], "")[0] == clean


@pytest.mark.parametrize("raw", [
    "数组 a[1] 和 b[2]",
    "参见 [cite: 附录 B]",
    "[citation needed]",
    "[cite]",
], ids=["index", "non-numeric", "citation-needed", "bare-cite"])
def test_lookalikes_are_left_alone(raw):
    assert gc._clean_control_markers(raw)[0] == raw
    assert gc._stable_placeholder_prefix(raw) == raw


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
    assert _stream(frames) == gc._restore_body(frames[-1], [], "")[0] == "红色。好"


def test_stream_releases_a_bracket_that_turns_out_not_to_be_a_marker():
    frames = ["数组 a", "数组 a[", "数组 a[1", "数组 a[1]", "数组 a[1] 完"]
    assert gc._stable_placeholder_prefix("数组 a[") == "数组 a", "可能是标记的开头：先扣住"
    assert _stream(frames) == "数组 a[1] 完"


def test_cite_start_halves_are_held_too():
    assert gc._stable_placeholder_prefix("[cite_sta") == ""
    assert gc._stable_placeholder_prefix("[cite_start]蓝") == "蓝"

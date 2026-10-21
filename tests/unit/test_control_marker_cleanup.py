"""M4：正文里的控制标记清理（三类），以及"用户正文里恰好出现这些字样"时不许误伤。

三类（参考实现 B 的 ExtractThinkingAndText、参考实现 A 的 clean_text）：
  1. <ctrl94>thought…<ctrl95> —— 思考内容泄漏进正文。我们有 reasoning_content /
     thinking 通道，所以这段**归到思考链**，不是直接扔掉。
  2. code_reference / code_stdout 伪代码围栏的 info string。
  3. card_content 死链。

两条红线：
  - 未闭合的 <ctrl94> 一律原样保留。参考实现 B 在只有起始标记时把起始之后的全部内容
    都当思考、正文只留起始之前那段 —— 那是一条数据丢失路径，我们刻意反着做。
  - 流式侧不许泄露半截标记（`<ctrl9` 这种），也不许发出"后来会被清掉"的内容
    （那会破坏 append-only 前缀关系，补尾分支直接走不到）。
"""

import asyncio

from app.core import gemini_client as gc
from app.core.gemini_client import _clean_control_markers as clean
from app.core.gemini_client import _stable_placeholder_prefix as safe_prefix


def finalize(text: str, thoughts="") -> dict:
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    return asyncio.run(client._finalize_stream(text, "cid", [], thoughts, []))


# ---------------------------------------------------------------------------
# 1. ctrl94/ctrl95：内容进思考链
# ---------------------------------------------------------------------------

def test_a_paired_ctrl_block_goes_to_thoughts_not_to_the_bin():
    body, thought = clean("Hello! <ctrl94>thought\nThinking process...\n<ctrl95>Actual response")

    assert "ctrl94" not in body and "ctrl95" not in body
    assert body == "Hello! Actual response"
    assert thought == "Thinking process..."


def test_bare_ctrl94_without_the_thought_word_is_handled_too():
    body, thought = clean("<ctrl94>pondering<ctrl95>answer")

    assert body == "answer"
    assert thought == "pondering"


def test_several_ctrl_blocks_are_joined_in_order():
    body, thought = clean("a<ctrl94>one<ctrl95>b<ctrl94>two<ctrl95>c")

    assert body == "abc"
    assert thought == "one\n\ntwo"


def test_ctrl_thoughts_are_appended_after_the_real_thinking_chain():
    """顺序不能反：openai.py 的流式收尾只在 final_thoughts.startswith(emitted) 时
    补发差量，否则明确不重发 —— 把 ctrl 那段放前面会让整段 reasoning 被静默丢掉。"""
    emitted = "已经流出去的思考"
    final = finalize("答案<ctrl94>补充的思考<ctrl95>", thoughts=emitted)

    assert final["thoughts"].startswith(emitted)
    assert final["thoughts"] == f"{emitted}\n\n补充的思考"
    assert final["text"] == "答案"


def test_an_unterminated_ctrl94_keeps_the_whole_body():
    """参考实现 B 这里会把起始之后的全部内容都当思考、正文只留前半段。"""
    text = "前半段 <ctrl94> 后面还有很长的正文，一个字都不能丢"
    body, thought = clean(text)

    assert body == text
    assert thought == ""


def test_a_lone_ctrl95_is_left_alone():
    text = "正文里只有一个 <ctrl95> 收尾标记"

    assert clean(text) == (text, "")


# ---------------------------------------------------------------------------
# 2. code_reference / code_stdout 伪围栏
# ---------------------------------------------------------------------------

def test_the_code_event_marker_is_removed_but_the_body_is_kept():
    body, thought = clean("```python?code_reference&code_event_index=3\nprint(1)\n```")

    assert body == "```python\nprint(1)\n```"
    assert thought == ""


def test_code_stdout_marker_is_removed_too():
    body, _ = clean("```text?code_stdout&code_event_index=12\n42\n```")

    assert body == "```text\n42\n```"


def test_the_fence_body_is_never_deleted():
    """参考实现 A 连围栏正文一起 DOTALL 删掉。那个围栏里可能装着模型真写的代码或
    真实 stdout —— 删错就是又一次"正文丢失"，手上没有真机样本就不许删。"""
    body, _ = clean("```python?code_stdout&code_event_index=1\nimportant output\n```")

    assert "important output" in body


# ---------------------------------------------------------------------------
# 3. card_content 死链
# ---------------------------------------------------------------------------

def test_card_content_dead_links_are_stripped():
    body, _ = clean("看这个卡片：http://googleusercontent.com/card_content/7\n剩下的正文")

    assert "card_content" not in body
    assert body == "看这个卡片：剩下的正文"


def test_card_content_is_also_stripped_in_the_stream_prefix():
    """不剥的话它会被 host 前缀 hold 住，后面的正文白等到 final 才发。"""
    out = safe_prefix("A http://googleusercontent.com/card_content/1\nB")

    assert "card_content" not in out
    assert out == "A B"


# ---------------------------------------------------------------------------
# 4. 不许误伤用户正文里恰好出现的这些字样
# ---------------------------------------------------------------------------

UNTOUCHED = [
    "Gemini 的内部标记写作 <ctrl94>，它表示一段思考的开始。",
    "问：<ctrl95> 是什么意思？答：它是结束标记。",
    "参数名叫 code_reference，用来引用上一段代码。",
    "查询串形如 ?code_reference&code_event_index= 后面跟一个数字。",
    "card_content 是 Gemini 内部的卡片标识，不是一个真实可访问的路径。",
    "这段 markdown 里有围栏：```python\nprint('code_stdout')\n```",
    "普通回答，什么标记都没有。",
]


def test_prose_that_merely_mentions_the_markers_is_untouched():
    for text in UNTOUCHED:
        body, thought = clean(text)
        assert body == text, f"被误伤了: {text!r} -> {body!r}"
        assert thought == "", text


def test_untouched_prose_survives_both_paths():
    """流式侧允许把"看着像标记起始"的尾部 hold 住（等 final 决断），但**绝不允许改写**：
    已流出的内容必须恒是最终正文的前缀，剩下的由收尾补发。"""
    for text in UNTOUCHED:
        assert finalize(text)["text"] == text
        emitted = safe_prefix(text)
        assert text.startswith(emitted), f"流式侧被误伤了: {text!r} -> {emitted!r}"


# ---------------------------------------------------------------------------
# 5. 流式：不泄露半截标记，也不发后来会被清掉的内容
# ---------------------------------------------------------------------------

def test_a_half_arrived_ctrl_marker_is_never_emitted():
    for partial in ("<", "<c", "<ct", "<ctr", "<ctrl", "<ctrl9", "<ctrl94", "<ctrl94>"):
        out = safe_prefix(f"答案开头{partial}")
        assert out == "答案开头", f"泄露了半截标记: {out!r}"


def test_a_complete_ctrl_block_is_stripped_so_the_tail_keeps_flowing():
    out = safe_prefix("前<ctrl94>思考<ctrl95>后")

    assert out == "前后", "成对标记要整段剥掉并放行后文，否则后文白等到 final"


def test_the_stream_prefix_stays_a_prefix_of_the_final_body():
    """四个路由都靠 final_text.startswith(已流出的内容) 补尾，不成立就静默不发 delta
    = 客户端丢内容。"""
    cases = [
        "普通回答，没有任何标记",
        "答案<ctrl94>思考<ctrl95>继续",
        "开头 <ctrl94> 未闭合，后面还有正文",
        "卡片 http://googleusercontent.com/card_content/3 之后还有话",
        "```python?code_reference&code_event_index=2\nx=1\n```",
    ]
    for text in cases:
        emitted = safe_prefix(text)
        final = finalize(text)["text"]
        assert final.startswith(emitted), f"{text!r}: {final!r} 不以 {emitted!r} 开头"


def test_a_half_arrived_code_event_marker_is_never_emitted():
    for partial in ("?", "?code", "?code_ref", "?code_reference",
                    "?code_reference&code_event_index=",
                    "?code_stdout&code_event_index="):
        out = safe_prefix(f"```python{partial}")
        assert out == "```python", f"泄露了半截标记: {out!r}"


def test_text_after_a_complete_code_event_marker_keeps_flowing():
    """标记完整到达后必须当场剥掉，后面的正文照常流出去。
    只靠"遇到 `?` 就 hold"的话，整段围栏正文都要等到 final 才一次性补出来。"""
    out = safe_prefix("```python?code_reference&code_event_index=2\nx=1")

    assert out == "```python\nx=1"

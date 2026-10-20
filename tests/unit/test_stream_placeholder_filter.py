"""真流式收尾必须和非流式一样无条件剥掉 googleusercontent 占位 URL。

「疑似生图」的请求现在走真流式（S10），而 Gemini 对模糊措辞（"来张猫的图"）常走
**图片检索**而不是生成：正文里有 `http://googleusercontent.com/image_retrieval/...`，
images 却是空的。那条链接客户端访问必定失败。

过去 _finalize_stream 的占位过滤被关在 `if images:` 里面，于是：
- 流式途中 _stable_placeholder_prefix 会把占位串 hold 住（不泄露半截网址）；
- 但收尾的 final.text 仍带着整条死链，路由的「补发缺失尾部」把它当正常尾巴发出去。
改动前同一个请求走 buffered，_parse_output 是无条件剥掉的（剥空还会给一句友好提示）。
"""

import asyncio

import pytest

from app.core import gemini_client as gc

_RETRIEVAL = "http://googleusercontent.com/image_retrieval/12345"


def _client():
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    return c


def _finalize(text, images=None, conv="cid"):
    client = _client()
    return asyncio.run(client._finalize_stream(text, conv, images or [], ""))


def test_retrieval_placeholder_is_stripped_without_real_images():
    final = _finalize(f"这是你要的猫图：{_RETRIEVAL}")

    assert "googleusercontent" not in final["text"], "死链绝不能流给客户端"
    assert final["text"] == "这是你要的猫图："
    assert final["images"] == []


def test_placeholder_only_answer_gets_the_friendly_hint():
    """剥空且没有真图：与 _parse_output 一样给引导提示，而不是返回空。"""
    final = _finalize(_RETRIEVAL)

    assert final["text"] == gc._IMAGE_RETRIEVAL_HINT


def test_stream_and_nonstream_agree_on_the_same_body():
    """同一段正文，两条路径的收尾结果必须逐字一致。"""
    text = f"图片如下：{_RETRIEVAL} 还有别的吗"
    streamed = _finalize(text)["text"]
    nonstream = gc._strip_image_placeholders(text, [])

    assert streamed == nonstream
    assert "googleusercontent" not in streamed


def test_text_without_placeholders_is_untouched():
    """零回归：不含占位串的正文一个字都不能改（含首尾空白）。"""
    final = _finalize("  普通回答，末尾有空格  ")

    assert final["text"] == "  普通回答，末尾有空格  "


def test_collection_placeholder_is_also_stripped():
    final = _finalize("看这些：http://googleusercontent.com/image_collection/7")

    assert "googleusercontent" not in final["text"]


@pytest.mark.parametrize("marker", ["image_retrieval/1", "image_generation_content/2"])
def test_all_placeholder_flavours(marker):
    final = _finalize(f"a https://googleusercontent.com/{marker} b")

    assert "googleusercontent" not in final["text"]


def test_real_images_path_still_strips_and_downloads(monkeypatch):
    """零回归：真的有图时照旧下载并剥占位串（这条路径本来就是对的）。"""
    client = _client()

    async def _entry(img, cookies):
        return {"b64": "x", "mime": "image/png"}

    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_build_image_entry", _entry)

    final = asyncio.run(client._finalize_stream(
        f"给你画好了 {_RETRIEVAL}", "cid", [{"url": "u"}], "",
    ))

    assert final["text"] == "给你画好了"
    assert len(final["images"]) == 1


def test_real_images_with_empty_text_do_not_get_the_hint(monkeypatch):
    """有真图时剥空了也不许加那句"没有生成图片"的提示。"""
    client = _client()

    async def _entry(img, cookies):
        return {"b64": "x", "mime": "image/png"}

    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_build_image_entry", _entry)

    final = asyncio.run(client._finalize_stream(_RETRIEVAL, "cid", [{"url": "u"}], ""))

    assert final["text"] == ""
    assert len(final["images"]) == 1


# ---------------------------------------------------------------------------
# 端到端：真流式整条链路（喂原始响应流，看实际产出的事件）
# ---------------------------------------------------------------------------

def _raw_stream(text: str) -> str:
    import json as _json

    payload = _json.dumps([None, ["c_1"], None, None, [[None, [text]]]])
    return ")]}'\n\n" + _json.dumps([["wrb.fr", None, payload, None, None, None, "generic"]])


def _stream_client(monkeypatch, raw: str, *, chunk_size: int = 23):
    data = raw.encode()
    chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

    class _Resp:
        status_code = 200
        cookies: dict = {}
        headers: dict = {}

        def aiter_content(self):
            async def gen():
                for c in chunks:
                    yield c

            return gen()

        async def atext(self):
            return raw

    class _CM:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Session:
        def __init__(self, *a, **kw):
            pass

        def stream(self, *a, **kw):
            return _CM()

        async def close(self):
            return None

    monkeypatch.setattr(gc, "AsyncSession", _Session)

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(gc, "apply_jitter", _noop)

    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._healthy = True
    client._session_token = "TOKEN"
    client._current_target = "chrome120"
    client._family_model = {}
    client._session_uuid = "SESSION-UUID"
    client._push_id = ""

    class _Jar:
        def update_from_response(self, resp):
            return None

    client._cookie_jar = _Jar()
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    return client


def _drain(client):
    async def run():
        return [evt async for evt in client.generate_stream("来张猫的图", "gemini-flash")]

    return asyncio.run(run())


def test_no_event_of_a_real_stream_carries_the_dead_link(monkeypatch):
    client = _stream_client(monkeypatch, _raw_stream(f"这是你要的猫图：{_RETRIEVAL}"))

    events = _drain(client)
    emitted = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    final = [e for e in events if e["type"] == "final"][-1]

    assert "googleusercontent" not in emitted, f"流式增量里泄露了死链: {emitted!r}"
    assert "googleusercontent" not in final["text"], f"final 里泄露了死链: {final['text']!r}"
    # 补发缺失尾部的那条逻辑要求 final.text 以已发内容为前缀，否则尾巴发不出去
    assert final["text"].startswith(emitted)
    assert final["text"] == "这是你要的猫图："

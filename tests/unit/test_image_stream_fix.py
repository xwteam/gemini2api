"""Regression guards for seq=12 image-gen network-error fix (SSE keepalive + download tuning).

Static source checks — no runtime deps required.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_buffered_stream_emits_immediate_sse_and_keepalive():
    """seq=12/s1: buffered path must not block with zero SSE bytes during generate()."""
    src = (_REPO_ROOT / "app" / "routers" / "openai.py").read_text(encoding="utf-8")
    assert "_sse_keepalive_during" in src
    assert 'yield ": ping\\n\\n"' in src  # literal ping frame still emitted by _sse_stream_chunks
    # First role frame before awaiting generate result
    assert "async def _stream_response_buffered" in src
    idx_fn = src.index("async def _stream_response_buffered")
    body = src[idx_fn : idx_fn + 2500]
    assert "StreamDelta(role=\"assistant\")" in body
    assert "_sse_keepalive_during(gen_task)" in body


def test_image_download_uses_s2048_and_short_timeout():
    """seq=12/s2: =s0 full-res replaced; per-GET timeout converged to ~25s."""
    src = (_REPO_ROOT / "app" / "core" / "gemini_client.py").read_text(encoding="utf-8")
    assert "=s2048" in src
    assert "_IMAGE_DOWNLOAD_TIMEOUT" in src
    assert "_IMAGE_DOWNLOAD_TIMEOUT" in src and "timeout=timeout" in src
    assert "=s512" in src  # fallback tier
    assert "_build_image_entry" in src
    assert '"fallback": True' in src


def test_image_generate_uses_extended_post_timeout():
    """pro 生图常 >60s：生图意图须用更长 POST 超时，避免 flash 正常而 pro 断连。

    这里断言的是**行为**（算出来的预算、以及它真的被交给了 POST），不是源码里有没有某个
    标识符 —— 后者既不守护分层也不守护传参，两个名字只要还在文件里就恒为真。
    """
    import asyncio

    from app.core import gemini_client as gc

    # 1) 生图意图确实抬高了预算（同一个族，纯文本 vs 生图）
    assert gc._generate_timeout("gemini-3-flash", "画一张猫的图片") > \
        gc._generate_timeout("gemini-3-flash", "你好")

    # 2) 算出来的预算真的被交给了 StreamGenerate 的 POST
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._session_token = "TOKEN"
    client._session_uuid = "SESSION-UUID"
    client._family_model = {}
    client._push_id = ""
    captured = {}

    class _Jar:
        def update_from_response(self, resp):
            return None

    class _Resp:
        status_code = 200
        text = ")]}'\n\n[]"
        cookies: dict = {}
        headers: dict = {}

    class _Http:
        async def post(self, url, **kw):
            captured["timeout"] = kw.get("timeout")
            return _Resp()

    client._cookie_jar = _Jar()
    client._http = _Http()

    async def _noop(*a, **kw):
        return None

    import pytest as _pytest
    mp = _pytest.MonkeyPatch()
    try:
        mp.setattr(gc, "apply_jitter", _noop)
        mp.setattr(client, "_ensure_session_current", _noop)
        mp.setattr(client, "_clear_session_cookies", lambda: None)
        mp.setattr(client, "_get_cookies", lambda: {})
        mp.setattr(client, "_get_headers", lambda *a, **kw: {})
        asyncio.run(client._send_request("画一张猫的图片", "gemini-flash"))
    finally:
        mp.undo()

    assert captured["timeout"] == gc._generate_timeout("gemini-3-flash", "画一张猫的图片")
    assert captured["timeout"] >= 180


def test_images_md_handles_download_fallback():
    """seq=12/s2: download failure must not silently drop images."""
    src = (_REPO_ROOT / "app" / "routers" / "openai.py").read_text(encoding="utf-8")
    assert 'im.get("fallback")' in src

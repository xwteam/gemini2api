"""Regression guards for seq=12 image-gen network-error fix (SSE keepalive + download tuning).

Static source checks — no runtime deps required.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_buffered_stream_emits_immediate_sse_and_keepalive():
    """seq=12/s1: buffered path must not block with zero SSE bytes during generate()."""
    src = (_REPO_ROOT / "app" / "routers" / "openai.py").read_text(encoding="utf-8")
    assert "_sse_keepalive_during" in src
    assert 'yield ": ping\\n\\n"' in src
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


def test_images_md_handles_download_fallback():
    """seq=12/s2: download failure must not silently drop images."""
    src = (_REPO_ROOT / "app" / "routers" / "openai.py").read_text(encoding="utf-8")
    assert 'im.get("fallback")' in src

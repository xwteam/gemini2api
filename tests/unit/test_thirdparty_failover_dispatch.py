"""直连第三方故障切换分发（monkeypatch 出口，不触网）。"""

import asyncio
import types
from fastapi.responses import JSONResponse, StreamingResponse

import app.routers.openai as oai
from app.core.api_key_store import ApiKeyPool
from app.models.openai import ChatRequest


def _request_with_pool(pool):
    state = types.SimpleNamespace(api_key_pool=pool)
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


def _pool_with(tmp_path, *models):
    pool = ApiKeyPool(file_path=str(tmp_path / "api-keys.json"))
    ids = [pool.add(provider="openai", model=m, api_key="sk-x", base_url="https://x/v1").id for m in models]
    return pool, ids


def _ok_json(content="hi"):
    return JSONResponse(content={"choices": [{"message": {"content": content}}]})


def _err_json(status=429):
    return JSONResponse(status_code=status, content={"error": {"message": "quota", "type": "x"}})


def _req(stream=False):
    return ChatRequest(model="deepseek", messages=[{"role": "user", "content": "hi"}], stream=stream)


def test_thirdparty_ok_judgements():
    assert oai._thirdparty_ok(_ok_json("hi")) is True
    assert oai._thirdparty_ok(_err_json(429)) is False
    assert oai._thirdparty_ok(JSONResponse(content={"choices": [{"message": {"content": ""}}]})) is False


def test_first_fails_second_used(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")
    calls = []

    async def fake_forward(entry, messages, req):
        calls.append(entry.id)
        return _err_json(429) if entry.id == ids[0] else _ok_json("ok")
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert isinstance(resp, JSONResponse) and resp.status_code == 200
    assert calls == ids                                   # 两家都试过、按序
    assert pool.get(ids[1]).last_used_at is not None      # 第二家被标记使用
    assert ids[0] in pool._cooldowns                      # 第一家被冷却


def test_all_fail_returns_last_error(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_forward(entry, messages, req):
        return _err_json(429)
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert isinstance(resp, JSONResponse) and resp.status_code == 429


def test_empty_response_triggers_switch(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_forward(entry, messages, req):
        return JSONResponse(content={"choices": [{"message": {"content": ""}}]}) if entry.id == ids[0] else _ok_json("ok")
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert resp.status_code == 200


def test_single_entry_not_starved(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek")

    async def fake_forward(entry, messages, req):
        return _err_json(500)
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    r1 = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    r2 = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert r1.status_code == 500 and r2.status_code == 500   # 第二次仍尝试了它（不饿死）


def test_no_candidates_returns_none(tmp_path):
    pool, _ = _pool_with(tmp_path, "deepseek")
    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "not-in-pool"))
    assert resp is None


def test_stream_fails_over(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")
    good = StreamingResponse(iter([b"x"]), media_type="text/event-stream")

    async def fake_open_stream(entry, messages, req):
        return (None, _err_json(429)) if entry.id == ids[0] else (good, None)
    monkeypatch.setattr(oai, "open_stream", fake_open_stream)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(stream=True), "deepseek"))
    assert resp is good
    assert ids[0] in pool._cooldowns

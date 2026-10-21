"""直连第三方故障切换分发（monkeypatch 出口，不触网）。"""

import asyncio
import types

import pytest
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


def test_all_fail_with_the_same_error_returns_it(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_forward(entry, messages, req):
        return _err_json(429)
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert isinstance(resp, JSONResponse) and resp.status_code == 429
    assert set(ids) <= set(pool._cooldowns)               # 429 是 key 自身的问题 → 冷却


def test_request_rejected_is_reported_and_does_not_cool_down_good_keys(tmp_path, monkeypatch):
    """线上真实形态（书生端砚 × 5）：前 4 个 key 都 400「参数被拒」、第 5 个 key 429 额度用完。
    过去回最后那个 429，客户端被误导成"额度不够"，还把 4 个好 key 全冷却了。"""
    pool, ids = _pool_with(tmp_path, *["deepseek"] * 5)

    async def fake_forward(entry, messages, req):
        if entry.id == ids[-1]:
            return _err_json(429)
        return JSONResponse(status_code=400, content={"error": {"message": "15 validation errors",
                                                                "type": "upstream_request_rejected"}})
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert resp.status_code == 400
    assert b"15 validation errors" in resp.body               # 上游的真实原因原样带给客户端
    assert set(pool._cooldowns) == {ids[-1]}                  # 只冷却真有问题的那个 key


def test_request_rejected_on_stream_open_is_reported_without_cooldown(tmp_path, monkeypatch):
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_open_stream(entry, messages, req):
        return None, _err_json(422)
    monkeypatch.setattr(oai, "open_stream", fake_open_stream)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(stream=True), "deepseek"))
    assert resp.status_code == 422
    assert not pool._cooldowns


@pytest.mark.parametrize("statuses,expected", [
    ((429, 400), 400),            # 请求被拒（带原因）优先于额度
    ((401, 500, 429), 500),       # 上游故障优先于额度 / key 鉴权
    ((403, 429), 429),            # 额度优先于 key 鉴权
    ((401, 403), 401),            # 同档取先失败的那个
])
def test_all_fail_reports_the_most_informative_error(tmp_path, monkeypatch, statuses, expected):
    pool, ids = _pool_with(tmp_path, *["deepseek"] * len(statuses))
    by_id = dict(zip(ids, statuses))

    async def fake_forward(entry, messages, req):
        return _err_json(by_id[entry.id])
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert resp.status_code == expected


def test_reasoning_only_answer_counts_as_success(tmp_path, monkeypatch):
    """推理模型被 max_tokens 截断：只有思考、正文为空。换下一个 key 同一个模型也一样截断，
    不能当失败把每个 key 都冷却一遍。"""
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")
    calls = []

    async def fake_forward(entry, messages, req):
        calls.append(entry.id)
        return JSONResponse(content={"choices": [{"message": {"content": "", "reasoning_content": "想…"},
                                                  "finish_reason": "length"}]})
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert resp.status_code == 200 and calls == ids[:1] and not pool._cooldowns


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


def test_no_pool_returns_none():
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    resp = asyncio.run(oai._dispatch_thirdparty(request, _req(), "deepseek"))
    assert resp is None


def test_thirdparty_ok_passthrough_non_jsonresponse():
    assert oai._thirdparty_ok(StreamingResponse(iter([b"x"]))) is True
    assert oai._thirdparty_ok("not-a-response") is True


def test_a_key_rejected_while_another_succeeds_is_moved_to_the_back(tmp_path, monkeypatch):
    """k1 配错（上游 404）、k2 正常：同一次分发里 k2 成功了，说明是 k1 自己的问题 → 冷却 k1，
    下一个请求直接先打 k2，不再每次白跑一轮。"""
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")
    calls = []

    async def fake_forward(entry, messages, req):
        calls.append(entry.id)
        return _err_json(404) if entry.id == ids[0] else _ok_json("ok")
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    for _ in range(2):
        resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
        assert resp.status_code == 200
    assert calls == [ids[0], ids[1], ids[1]]
    assert set(pool._cooldowns) == {ids[0]}


def test_an_empty_200_is_reported_as_an_upstream_failure(tmp_path, monkeypatch):
    """全败时不能回 200 空答案（SDK 不会重试）：空响应按上游故障 502 报。"""
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_forward(entry, messages, req):
        if entry.id == ids[0]:
            return JSONResponse(content={"choices": [{"message": {"content": ""}}]})
        return _err_json(429)
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert resp.status_code == 502


def test_a_gateway_config_error_never_masks_the_upstream_error(tmp_path, monkeypatch):
    """条目 base_url 没配（网关自己生成的 400）不能盖住另一个 key 真实的 429；它是条目自己的
    问题，照常冷却。"""
    from app.core import api_forwarder as af
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_forward(entry, messages, req):
        return af._bad_request("base_url is not configured") if entry.id == ids[0] else _err_json(429)
    monkeypatch.setattr(oai, "forward_to_provider", fake_forward)

    resp = asyncio.run(oai._dispatch_thirdparty(_request_with_pool(pool), _req(), "deepseek"))
    assert resp.status_code == 429
    assert set(pool._cooldowns) == set(ids)


# ---- /v1/responses 的第三方分发与 chat 共用同一套规则 ----

def _responses(pool, stream):
    from app.core import responses_thirdparty as rt
    return asyncio.run(rt.dispatch_thirdparty_responses(
        _request_with_pool(pool), "deepseek", [{"role": "user", "content": "hi"}], None, None,
        stream, {}))


def test_responses_non_stream_reports_the_rejection_not_the_last_429(tmp_path, monkeypatch):
    from app.core import responses_thirdparty as rt
    pool, ids = _pool_with(tmp_path, *["deepseek"] * 5)

    async def fake_forward(entry, messages, req):
        return _err_json(429) if entry.id == ids[-1] else _err_json(400)
    monkeypatch.setattr(rt, "forward_to_provider", fake_forward)

    resp = _responses(pool, stream=False)
    assert resp.status_code == 400
    assert set(pool._cooldowns) == {ids[-1]}


def test_responses_stream_failure_names_the_best_error_without_cooling_rejected_keys(tmp_path,
                                                                                     monkeypatch):
    from app.core import responses_thirdparty as rt
    pool, ids = _pool_with(tmp_path, "deepseek", "deepseek")

    async def fake_open_stream(entry, messages, req):
        return None, _err_json(400)
    monkeypatch.setattr(rt, "open_stream", fake_open_stream)

    resp = _responses(pool, stream=True)

    async def body():
        return "".join([c if isinstance(c, str) else c.decode() async for c in resp.body_iterator])
    text = asyncio.run(body())
    assert "response.failed" in text and "HTTP 400" in text
    assert not pool._cooldowns


def test_a_non_openai_provider_error_is_not_committed_as_a_stream():
    """gemini 存根（501）这类非 OpenAI 兼容 provider 的错误不能当成流直接提交——否则后面
    正常的 key 一次都试不到。"""
    from app.core import api_forwarder as af
    from app.core.api_key_store import ApiKeyEntry
    entry = ApiKeyEntry(id="g1", provider="gemini", model="m", api_key="k", base_url="",
                        label=None, status="active", added_at="", last_used_at=None)
    resp, err = asyncio.run(af.open_stream(entry, [{"role": "user", "content": "hi"}], _req(stream=True)))
    assert resp is None and err.status_code == 501

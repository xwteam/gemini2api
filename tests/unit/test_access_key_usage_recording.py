"""M2 的落账链路：一次真实请求之后，token 真的记到了命中的那把访问密钥上。

为什么不在中间件里收口（这是本功能唯一的设计难点）：log_capture_middleware 是
`await call_next(request)` 之后立刻记日志，而对 StreamingResponse 来说 call_next
返回时生成器**一个字节都还没迭代** —— 流式路径算出来的 token 中间件永远看不到
（仓里自己就把流式响应体标成 _STREAMING_NOT_CAPTURED）。所以落账走
access_context 的 ContextVar：它在 verify_api_key 里设一次，端点函数和
StreamingResponse 的生成器迭代都能读到。

四个协议 × 流式/非流式都要覆盖，而且必须验证**流式**那几条真的记上了（那正是中间件
方案会悄悄失效的地方）。
"""

import pytest

import app.core.access_key_store as store_module
from app.core.access_context import set_current_access_key
from app.core.access_key_store import AccessKeyStore
from app.utils.tools import estimate_tokens


@pytest.fixture(autouse=True)
def _clear_ctx():
    set_current_access_key(None)
    yield
    set_current_access_key(None)


@pytest.fixture
def issued(monkeypatch, tmp_path):
    """换一份干净的密钥库，签一把不限额的密钥，返回 (store, key_id, headers)。"""
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    entry = fresh.create("tester")
    return fresh, entry.id, {"Authorization": f"Bearer {entry.key}"}


def _result(text="answer text here", thoughts=""):
    return {"text": text, "conversation_id": "", "images": [], "thoughts": thoughts}


def _patch(monkeypatch, module_name, result=None, events=None):
    import importlib
    mod = importlib.import_module(module_name)

    async def _gen(prompt, model, conversation_id="", attachments=None, gem_id=None,
                   account_id=None, extended_thinking=False):
        return result if result is not None else _result()

    async def _stream(prompt, model, conversation_id="", attachments=None, gem_id=None,
                      account_id=None, extended_thinking=False):
        for evt in (events or []):
            yield evt

    monkeypatch.setattr(mod.gemini_client, "generate", _gen)
    monkeypatch.setattr(mod.gemini_client, "generate_stream", _stream)


TEXT = "answer text here"
FINAL = [{"type": "delta", "text": TEXT},
         {"type": "final", "text": TEXT, "conversation_id": "", "images": [], "thoughts": ""}]


# ---------------------------------------------------------------------------
# 四个协议，非流式
# ---------------------------------------------------------------------------

def test_openai_nonstream_records_usage(gem_client, monkeypatch, issued):
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.openai")

    gem_client.post("/v1/chat/completions", headers=headers, json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}]})

    entry = store.get(kid)
    assert entry.input_tokens > 0
    assert entry.output_tokens == estimate_tokens(TEXT)
    assert entry.tokens_by_model and "gemini-flash" in entry.tokens_by_model


def test_claude_nonstream_records_usage(gem_client, monkeypatch, issued):
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.claude")

    gem_client.post("/v1/messages", headers=headers, json={
        "model": "gemini-flash", "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}]})

    assert store.get(kid).output_tokens == estimate_tokens(TEXT)


def test_gemini_nonstream_records_usage(gem_client, monkeypatch, issued):
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.gemini")

    gem_client.post("/v1beta/models/gemini-flash:generateContent", headers=headers, json={
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}]})

    assert store.get(kid).output_tokens == estimate_tokens(TEXT)


def test_responses_nonstream_records_usage(gem_client, monkeypatch, issued):
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.responses")

    gem_client.post("/v1/responses", headers=headers, json={
        "model": "gemini-flash", "input": "hi"})

    assert store.get(kid).output_tokens == estimate_tokens(TEXT)


# ---------------------------------------------------------------------------
# 四个协议，流式（中间件方案在这里必然失效）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module,path,body", [
    ("app.routers.openai", "/v1/chat/completions",
     {"model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}], "stream": True}),
    ("app.routers.claude", "/v1/messages",
     {"model": "gemini-flash", "max_tokens": 64, "stream": True,
      "messages": [{"role": "user", "content": "hi"}]}),
    ("app.routers.gemini", "/v1beta/models/gemini-flash:streamGenerateContent",
     {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}),
    ("app.routers.responses", "/v1/responses",
     {"model": "gemini-flash", "input": "hi", "stream": True}),
])
def test_streaming_paths_record_usage(gem_client, monkeypatch, issued, module, path, body):
    store, kid, headers = issued
    _patch(monkeypatch, module, events=FINAL)

    with gem_client.stream("POST", path, headers=headers, json=body) as r:
        "".join(r.iter_text())

    entry = store.get(kid)
    assert entry.output_tokens == estimate_tokens(TEXT), f"{path} 没落账"
    assert entry.input_tokens > 0


def test_openai_streaming_wire_output_gains_no_usage_frame(gem_client, monkeypatch, issued):
    """OpenAI 流式过去完全没有 token 统计，这是四个协议里唯一的真空区。
    补统计时**只能内部记账** —— 往 SSE 里加 usage 帧就是线上协议的实际变更。"""
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.openai", events=FINAL)

    with gem_client.stream("POST", "/v1/chat/completions", headers=headers, json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }) as r:
        body = "".join(r.iter_text())

    assert '"usage"' not in body
    assert store.get(kid).output_tokens == estimate_tokens(TEXT)


# ---------------------------------------------------------------------------
# 幂等 / 零行为变化 / 不限额
# ---------------------------------------------------------------------------

def test_a_request_is_only_counted_once(gem_client, monkeypatch, issued):
    """工具重试 / fallback / 异常回落都会让同一个请求经过多个"终点"。"""
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.claude", result=_result(
        text='{"tool_calls":[{"name":"f","arguments":{}}]}'))

    gem_client.post("/v1/messages", headers=headers, json={
        "model": "gemini-flash", "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "f", "description": "d",
                   "input_schema": {"type": "object", "properties": {}}}]})

    by_model = store.get(kid).tokens_by_model or {}
    total = sum(v["out"] for v in by_model.values())
    assert total == store.get(kid).output_tokens
    assert len(by_model) == 1, f"一个请求只该记一次: {by_model}"


def test_env_api_key_requests_record_nothing(gem_client, monkeypatch, issued):
    """.env 的 API_KEY 直连不查密钥库、不挂上下文 —— 与 request_count 现有口径一致。"""
    store, kid, _headers = issued
    _patch(monkeypatch, "app.routers.openai")

    gem_client.post("/v1/chat/completions",
                    headers={"Authorization": "Bearer sk-test-key"},
                    json={"model": "gemini-flash",
                          "messages": [{"role": "user", "content": "hi"}]})

    entry = store.get(kid)
    assert (entry.input_tokens, entry.output_tokens) == (0, 0)
    assert entry.tokens_by_model is None


def test_huge_token_usage_never_rejects_a_request(gem_client, monkeypatch, issued):
    """用户要的是「只统计美元、不用额度限制」。"""
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.openai")
    store.add_token_usage(kid, "gemini-pro", 10**12, 10**12)

    r = gem_client.post("/v1/chat/completions", headers=headers, json={
        "model": "gemini-flash", "messages": [{"role": "user", "content": "hi"}]})

    assert r.status_code == 200


def test_old_aliases_are_folded_into_the_public_name(gem_client, monkeypatch, issued):
    """价格表按稳定公开名配；用 gemini-2.5-pro 调同一个模型不该单开一行、显示成 "—"。"""
    store, kid, headers = issued
    _patch(monkeypatch, "app.routers.openai")

    gem_client.post("/v1/chat/completions", headers=headers, json={
        "model": "gemini-2.5-pro", "messages": [{"role": "user", "content": "hi"}]})

    assert list(store.get(kid).tokens_by_model) == ["gemini-pro"]


def test_the_admin_endpoint_exposes_tokens_and_an_estimated_cost(client, monkeypatch, tmp_path):
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    entry = fresh.create("k")
    fresh.add_token_usage(entry.id, "gemini-flash", 1_000_000, 1_000_000)

    body = client.get("/admin/access-keys",
                      headers={"Authorization": "Bearer sk-test-key"}).json()
    row = body["keys"][0]

    assert row["input_tokens"] == 1_000_000
    assert row["output_tokens"] == 1_000_000
    assert row["tokens_by_model"] == {"gemini-flash": {"in": 1_000_000, "out": 1_000_000}}
    assert row["estimated_cost_usd"] == pytest.approx(0.75 + 3.75)


def test_an_unpriced_model_serializes_as_none(client, monkeypatch, tmp_path):
    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    entry = fresh.create("k")
    fresh.add_token_usage(entry.id, "some-gem-model", 1_000_000, 1_000_000)

    body = client.get("/admin/access-keys",
                      headers={"Authorization": "Bearer sk-test-key"}).json()

    assert body["keys"][0]["estimated_cost_usd"] is None


def test_record_token_usage_is_idempotent_within_one_request(monkeypatch, tmp_path):
    """同一个请求里多次落账只算一次，换一个请求（另一份上下文）照常记。

    一个请求会经过好几个「终点」：工具 JSON 畸形重试、思考失败退回非思考、会话过期
    用完整 prompt 重试、第三方兜底。每条分支的终点都直接调 record_token_usage，靠这道
    幂等守卫兜住重复，而不是靠逐点推演"这一条到底会不会和那一条同时跑"。
    """
    import contextvars

    from app.core.access_context import record_token_usage

    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)
    created = fresh.create("k")
    _state, snapshot = fresh.validate_and_consume(created.key)

    def _one_request():
        set_current_access_key(snapshot)
        record_token_usage("gemini-flash", 100, 200)
        record_token_usage("gemini-flash", 100, 200)
        record_token_usage("gemini-pro", 7, 7)

    contextvars.copy_context().run(_one_request)
    assert fresh.get(created.id).input_tokens == 100
    assert fresh.get(created.id).output_tokens == 200
    assert list(fresh.get(created.id).tokens_by_model) == ["gemini-flash"]

    contextvars.copy_context().run(_one_request)
    assert fresh.get(created.id).input_tokens == 200
    assert fresh.get(created.id).output_tokens == 400

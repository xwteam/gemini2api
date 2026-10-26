"""对标补齐（v1.6.50）：混合账号池换号、附件上传重试、生成图并发下载、GET /v1/models/{model}。"""
import asyncio
import time

import pytest

from app.core import file_upload as fu
from app.core import gemini_client as gc
from app.core.account_pool import Account, AccountPool, AccountStatus

_AUTH = {"Authorization": "Bearer sk-test-key"}


# ---------------------------------------------------------------------------
# 混合账号池：账号没有这个模型 → 不计失败、不冷却、换号
# ---------------------------------------------------------------------------

class _Client:
    def __init__(self, has_model: bool):
        self._healthy = True
        self._heal_lock = asyncio.Lock()
        self.has_model = has_model
        self.calls = 0

    @property
    def is_healthy(self):
        return self._healthy

    def _model_table(self):
        return dict(gc._BASE_MODELS)

    async def generate(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False):
        self.calls += 1
        if not self.has_model:
            raise gc.ModelUnavailable(f"Model '{model}' unavailable. Options: gemini-pro")
        return {"text": "ok", "images": []}

    async def generate_stream(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                              extended_thinking=False):
        self.calls += 1
        if not self.has_model:
            raise gc.ModelUnavailable(f"Model '{model}' unavailable. Options: gemini-pro")
        yield {"type": "delta", "text": "ok"}
        yield {"type": "final", "text": "ok"}


def _pool(*clients) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [Account(id=f"account-{i}", psid=f"p{i}", psidts="", label=f"a{i}",
                              status=AccountStatus.ACTIVE, client=c) for i, c in enumerate(clients)]
    pool._max_concurrent = 8
    pool._acquire_timeout = 2.0
    pool._robin_index = len(clients) - 1        # 第一个选中 account-0
    return pool


def test_a_request_moves_on_to_an_account_that_has_the_model():
    lacking, having = _Client(False), _Client(True)
    pool = _pool(lacking, having)
    result = asyncio.run(pool.generate("hi", "gemini-argon"))
    assert result["text"] == "ok" and result["account_id"] == "account-1"
    first = pool.accounts[0]
    assert (first.consecutive_failures, first.cooldown_until, first.status) == (0, 0, AccountStatus.ACTIVE)
    assert first.active_requests == 0


def test_the_stream_moves_on_too():
    pool = _pool(_Client(False), _Client(True))

    async def run():
        return [e async for e in pool.generate_stream("hi", "gemini-argon")]

    events = asyncio.run(run())
    assert events[-1]["type"] == "final" and events[-1]["account_id"] == "account-1"
    assert pool.accounts[0].consecutive_failures == 0


def test_no_account_has_it_is_still_the_400_error():
    pool = _pool(_Client(False), _Client(False))
    with pytest.raises(gc.ModelUnavailable):
        asyncio.run(pool.generate("hi", "gemini-argon"))
    assert all(a.consecutive_failures == 0 and a.status == AccountStatus.ACTIVE for a in pool.accounts)
    assert gc.classify_error(gc.ModelUnavailable("x"))[0] == 400


# ---------------------------------------------------------------------------
# 附件上传：网络错误 / 5xx 重试一次，4xx 不重试
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def _http(script):
    class _H:
        posts = 0

        async def post(self, *a, **kw):
            _H.posts += 1
            item = script[min(_H.posts, len(script)) - 1]
            if isinstance(item, Exception):
                raise item
            return item

    return _H()


@pytest.mark.parametrize("script,expected,posts", [
    ([ConnectionError("reset"), _Resp(200, "/contrib/file-1")], "/contrib/file-1", 2),
    ([_Resp(503, "busy"), _Resp(200, "/contrib/file-2")], "/contrib/file-2", 2),
    ([_Resp(400, "bad type")], None, 1),
    ([_Resp(502, "x"), _Resp(502, "x")], None, 2),
], ids=["network-then-ok", "5xx-then-ok", "4xx-no-retry", "5xx-twice-gives-up"])
def test_upload_retries_transient_failures_once(monkeypatch, script, expected, posts):
    monkeypatch.setattr(fu, "UPLOAD_RETRY_DELAY", 0)
    http = _http(script)
    fid = asyncio.run(fu.upload_file(http, {}, {}, "push", b"data", "a.png", "image/png"))
    assert fid == expected and http.posts == posts


# ---------------------------------------------------------------------------
# 生成图并发下载：顺序不变、失败项去掉、总耗时不是逐张相加
# ---------------------------------------------------------------------------

def test_generated_images_download_concurrently_and_keep_their_order(monkeypatch):
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)

    async def slow_entry(img, cookies):
        await asyncio.sleep(0.2)
        return None if img["n"] == 2 else {"n": img["n"]}

    monkeypatch.setattr(client, "_build_image_entry", slow_entry)
    t0 = time.monotonic()
    entries = asyncio.run(client._build_image_entries([{"n": i} for i in range(4)], {}))
    elapsed = time.monotonic() - t0
    assert [e["n"] for e in entries] == [0, 1, 3]
    assert elapsed < 0.6, f"4 张图逐张下载要 0.8 秒，并发应在 0.2 秒左右（实际 {elapsed:.2f}s）"


# ---------------------------------------------------------------------------
# GET /v1/models/{model}
# ---------------------------------------------------------------------------

def test_retrieve_a_listed_model(gem_client):
    listed = gem_client.get("/v1/models", headers=_AUTH).json()["data"]
    some = listed[0]["id"]
    r = gem_client.get(f"/v1/models/{some}", headers=_AUTH)
    assert r.status_code == 200 and r.json()["id"] == some and r.json()["object"] == "model"


def test_retrieve_an_unknown_model_is_an_openai_style_404(gem_client):
    r = gem_client.get("/v1/models/no-such-model", headers=_AUTH)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"

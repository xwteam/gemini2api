"""生成超时不能把账号推向 EXPIRED（v1.6.45 规格 A.5）。

超时是谷歌那边卡住（线上 2026-10-26：3.8 Flash 收到几十字节后就没数据了），不是 cookie 失效。
过去它在账号池里走的是 release(success=False) 那条「连败 3 次即 EXPIRED」的通道 —— 谷歌卡
一阵子，单账号池连着 3 个超时就被踢出轮换，之后的请求全部 503，直到有人去面板上恢复。

现在照池里现有的瞬时故障口径（5xx 限流那一条）记账：记一次错误、短暂冷却，不累计连败、不标
EXPIRED；也不换号重试（预算已经花完，再试会让客户端再等一整轮，见规格 A.3）。
"""

import asyncio

import pytest
from curl_cffi.requests import RequestsError

from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.gemini_client import GenerationTimedOut


def _generation_timeout():
    return GenerationTimedOut(120, 120.4, RequestsError("Operation timed out", code=28))


class _Client:
    """最小 GeminiWebClient 替身：generate / generate_stream 按配置失败。"""

    def __init__(self, exc_factory=None, stream_prefix=()):
        self._healthy = True
        self._heal_lock = asyncio.Lock()
        self._exc_factory = exc_factory
        self._stream_prefix = list(stream_prefix)
        self.generate_calls = 0
        self.stream_calls = 0

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def generate(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False):
        self.generate_calls += 1
        if self._exc_factory is not None:
            raise self._exc_factory()
        return {"text": "ok", "images": [], "conversation_id": ""}

    async def generate_stream(self, prompt, model, conversation_id="", attachments=None,
                              gem_id=None, extended_thinking=False):
        self.stream_calls += 1
        for evt in self._stream_prefix:
            yield evt
        if self._exc_factory is not None:
            raise self._exc_factory()
        yield {"type": "final", "text": "ok", "images": [], "conversation_id": ""}


def _pool(clients) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"psid-{i}", psidts="", label=f"account-{i}",
                status=AccountStatus.ACTIVE, client=c)
        for i, c in enumerate(clients)
    ]
    pool._max_concurrent = 8
    pool._acquire_timeout = 2.0
    return pool


async def _drain(agen):
    return [evt async for evt in agen]


def _assert_still_in_rotation(account: Account):
    assert account.status == AccountStatus.ACTIVE, "超时把账号推成了 EXPIRED"
    assert account.consecutive_failures == 0, "超时被算进了「连败 3 次即 EXPIRED」的计数"
    assert account.active_requests == 0, "槽位没还"


def test_repeated_nonstream_timeouts_never_expire_the_account():
    client = _Client(_generation_timeout)
    pool = _pool([client])

    async def run():
        for _ in range(5):
            with pytest.raises(GenerationTimedOut):
                await pool.generate("p", "gemini-flash")

    asyncio.run(run())

    account = pool.accounts[0]
    _assert_still_in_rotation(account)
    # 照 5xx 的瞬时故障口径：记错误、进短冷却（面板上看得到），但不降级
    assert account.error_count == 5
    assert account.last_error == "GenerationTimedOut"
    assert account.cooldown_until > 0
    assert client.generate_calls == 5


def test_nonstream_timeout_is_not_retried_on_another_account():
    """超时不换号重试：整轮预算已经花完，再试会让客户端再等一整轮（规格 A.3）。"""
    a, b = _Client(_generation_timeout), _Client(_generation_timeout)
    pool = _pool([a, b])

    async def run():
        with pytest.raises(GenerationTimedOut):
            await pool.generate("p", "gemini-flash")

    asyncio.run(run())
    assert a.generate_calls + b.generate_calls == 1


@pytest.mark.parametrize("exc_factory", [
    lambda: TimeoutError(),                                   # wait_for 等不到下一个 chunk
    lambda: RequestsError("Operation timed out", code=28),    # 流式 session 的总超时
], ids=["chunk-wait-timeout", "curl-code-28"])
@pytest.mark.parametrize("prefix", [(), ({"type": "delta", "text": "partial"},)],
                         ids=["before-first-chunk", "after-partial-output"])
def test_stream_timeouts_never_expire_the_account(exc_factory, prefix):
    client = _Client(exc_factory, stream_prefix=prefix)
    pool = _pool([client])

    async def run():
        for _ in range(4):
            with pytest.raises((TimeoutError, RequestsError)):
                await _drain(pool.generate_stream("p", "gemini-flash"))

    asyncio.run(run())
    account = pool.accounts[0]
    _assert_still_in_rotation(account)
    assert account.error_count == 4
    assert client.stream_calls == 4


def test_stream_timeout_is_not_retried_on_another_account():
    a, b = _Client(lambda: TimeoutError()), _Client(lambda: TimeoutError())
    pool = _pool([a, b])

    async def run():
        with pytest.raises(TimeoutError):
            await _drain(pool.generate_stream("p", "gemini-flash"))

    asyncio.run(run())
    assert a.stream_calls + b.stream_calls == 1


def test_non_timeout_hard_failures_still_count_towards_expired():
    """零回归：只有超时改口径。别的不可重试失败照旧累计连败、满 3 次标 EXPIRED。"""
    client = _Client(lambda: RuntimeError("Exhausted 3 retries: boom"))
    pool = _pool([client])

    async def run():
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await pool.generate("p", "gemini-flash")

    asyncio.run(run())
    assert pool.accounts[0].status == AccountStatus.EXPIRED

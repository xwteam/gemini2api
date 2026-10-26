"""熔断的记录点在账号池（v1.6.46 规格 C.2 / C.5，按 I.1 / I.3 / I.4 / I.6 / I.9 细化）。

为什么在池层：池手里有 model、prompt、conversation_id 与每个账号的 client，一次上游尝试的结果
（成功 / 换号 / 不换号的失败）都在这里落地；client 层的同号快速重试不单独记（I.3）。

  - 按「一个账号一次尝试」记：池换号两次 → 记两次尝试，但同一请求只 +1（指纹相同）；
  - 只计「疑似故障」（I.4）：失败套话；非流式生成超时只在几乎没收到数据（< 1KB）时；流式无进展
    超时只在这次尝试一次进展都没有时。别的失败一律不计；
  - 每次尝试只记一个结果，以第一个决定性信号为准（I.6）：流式在第一个正文增量发出时记成功（只有
    思考不算），之后再失败不计；
  - 族由「路由传给池的同一个 model 参数」精确查表得出（I.9），绝不做子串匹配。
"""

import asyncio

import pytest
from curl_cffi.requests import RequestsError

from app.core import gemini_client as gc
from app.core.account_pool import Account, AccountPool, AccountStatus
from app.core.model_breaker import model_breaker, request_fingerprint, same_request_as

PHRASE = "I seem to be encountering an error. Can I try something else for you?"


def _failure():
    return gc.GeminiFailureReply(PHRASE)


def _timed_out(received: str | None):
    msg = "Failed to perform, curl: (28) Operation timed out after 120001 milliseconds"
    if received is not None:
        msg += f" with {received} received"
    return gc.GenerationTimedOut(120, 120.2, RequestsError(msg + ".", code=28))


class _Client:
    """最小 client 替身：按脚本逐次产出结果 / 抛错。"""

    def __init__(self, results=(), stream_scripts=(), table=None):
        self._healthy = True
        self._heal_lock = asyncio.Lock()
        self._results = list(results)
        self._streams = list(stream_scripts)
        self._table = table
        self.calls = 0

    @property
    def is_healthy(self):
        return self._healthy

    def _model_table(self):
        return dict(gc._BASE_MODELS, **(self._table or {}))

    async def generate(self, prompt, model, conversation_id="", attachments=None, gem_id=None,
                       extended_thinking=False):
        self.calls += 1
        item = self._results.pop(0) if self._results else {"text": "ok", "images": []}
        if isinstance(item, BaseException):
            raise item
        return item

    async def generate_stream(self, prompt, model, conversation_id="", attachments=None,
                              gem_id=None, extended_thinking=False):
        self.calls += 1
        script = self._streams.pop(0) if self._streams else [{"type": "final", "text": "ok"}]
        for item in script:
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                await item()
                continue
            yield item


def _pool(*clients) -> AccountPool:
    pool = AccountPool()
    pool._accounts = [
        Account(id=f"account-{i}", psid=f"psid-{i}", psidts="", label=f"account-{i}",
                status=AccountStatus.ACTIVE, client=c)
        for i, c in enumerate(clients)
    ]
    pool._max_concurrent = 8
    pool._acquire_timeout = 2.0
    pool._robin_index = len(clients) - 1          # 第一个选中 account-0
    return pool


@pytest.fixture
def spy(monkeypatch):
    """记下池调熔断器的每一次记录（仍然调用真的熔断器）。"""
    calls = []
    real_failure, real_success = model_breaker.record_failure, model_breaker.record_success

    def failure(family, *, started_at, fingerprint, reason):
        calls.append(("failure", family, fingerprint, reason))
        real_failure(family, started_at=started_at, fingerprint=fingerprint, reason=reason)

    def success(family, *, started_at):
        calls.append(("success", family))
        real_success(family, started_at=started_at)

    monkeypatch.setattr(model_breaker, "record_failure", failure)
    monkeypatch.setattr(model_breaker, "record_success", success)
    return calls


def _gen(pool, prompt="p", model="gemini-flash", **kw):
    return asyncio.run(pool.generate(prompt, model, **kw))


def _gen_err(pool, prompt="p", model="gemini-flash", **kw):
    try:
        _gen(pool, prompt, model, **kw)
    except Exception as e:  # noqa: BLE001
        return e
    raise AssertionError("expected a failure")


def _stream(pool, prompt="p", model="gemini-flash", **kw):
    async def run():
        events = []
        try:
            async for evt in pool.generate_stream(prompt, model, **kw):
                events.append(evt)
        except Exception as e:  # noqa: BLE001
            return events, e
        return events, None

    return asyncio.run(run())


def _state(family="flash"):
    return model_breaker.snapshot().get(family, {}).get("state")


# ---------------------------------------------------------------------------
# 族解析（I.9）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,family", [
    ("gemini-flash", "flash"),
    ("gemini-2.5-flash", "flash"),            # 别名
    ("gemini-flash-thinking", "flash"),       # 已下线的隐藏别名
    ("gemini-3-flash-plus", "flash"),         # 内部名
    ("gemini-flash-lite", "flash-lite"),      # 绝不能被归到 flash
    ("gemini-2.0-flash-lite", "flash-lite"),
    ("gemini-3-flash-lite-advanced", "flash-lite"),
    ("gemini-pro", "pro"),
    ("gemini-argon", "argon"),
    ("gemini-4-argon", "argon"),
    ("gemini-5-nova", "nova"),                # 心跳发现的族：只在某个账号的 _model_table() 里
    ("gemini-flash-lite-preview-x", None),    # 不做子串匹配
    ("my-gemini-flash", None),
    ("gpt-4o", None),
    ("", None),
])
def test_family_of(model, family):
    nova = {"gemini-5-nova": {"id": "a" * 16, "capacity": 2, "pro_only": True, "family": "nova",
                              "model_number": 9}}
    pool = _pool(_Client(), _Client(table=nova))
    assert pool.family_of(model) == family


def test_family_of_tolerates_clients_without_a_model_table():
    class _Bare:
        is_healthy = True

    pool = _pool(_Bare())
    assert pool.family_of("gemini-5-nova") is None
    assert pool.family_of("gemini-flash") == "flash"


# ---------------------------------------------------------------------------
# 非流式
# ---------------------------------------------------------------------------

def test_one_request_failing_over_twice_records_two_attempts_but_counts_once(spy):
    pool = _pool(_Client([_failure()]), _Client([_failure()]))
    err = _gen_err(pool, "只回答一个字：好")

    assert isinstance(err, gc.GeminiFailureReply)
    failures = [c for c in spy if c[0] == "failure"]
    assert len(failures) == 2, "每个账号的每次尝试各记一次"
    assert failures[0][1] == "flash" and failures[0][2] == failures[1][2], "同一请求同一指纹"
    assert failures[0][2] == request_fingerprint("只回答一个字：好", "")
    snap = model_breaker.snapshot()["flash"]
    assert snap["consecutive_failures"] == 1 and snap["state"] == "closed"


def test_the_same_prompt_failing_repeatedly_never_opens(spy):
    pool = _pool(_Client([_failure()] * 5))
    for _ in range(5):
        _gen_err(pool, "同一个毒请求")
    assert _state() == "closed"


def test_two_different_prompts_failing_once_each_open_the_family(spy):
    pool = _pool(_Client([_failure(), _failure()]))
    _gen_err(pool, "问题一")
    _gen_err(pool, "问题二")
    assert _state() == "open"
    assert model_breaker.should_bypass("flash", probe_timeout=200).bypass is True
    # 只有这个族：同账号的 flash-lite / pro 不受牵连
    assert _state("pro") is None and _state("flash-lite") is None


def test_the_conversation_id_is_part_of_the_fingerprint(spy):
    pool = _pool(_Client([_failure(), _failure()]))
    _gen_err(pool, "继续", conversation_id='["c_1", "r_1", null]')
    _gen_err(pool, "继续", conversation_id='["c_2", "r_2", null]')
    assert _state() == "open"


def test_a_rewritten_retry_of_the_same_request_keeps_the_first_fingerprint(spy):
    """路由对同一个客户端请求的改写重试（续接失败 → 改发完整历史）在 same_request_as 里发：池记的
    指纹仍是第一次尝试的，计数只 +1（I.3）。池换号照旧每次尝试各记一次。"""
    resume = '["c_1", "r_1", "rc_1"]'
    pool = _pool(_Client([_failure(), _failure(), _failure()]), _Client([_failure()]))
    _gen_err(pool, "q2", conversation_id=resume, account_id="account-0")
    with same_request_as("q2", resume):
        _gen_err(pool, "Human: q1\n\nAssistant: a1\n\nHuman: q2")

    failures = [c for c in spy if c[0] == "failure"]
    assert len(failures) == 3, "续接一次 + 完整历史换号两次，每次尝试各记一次"
    assert {f[2] for f in failures} == {request_fingerprint("q2", resume)}
    snap = model_breaker.snapshot()["flash"]
    assert (snap["state"], snap["consecutive_failures"]) == ("closed", 1)


def test_a_non_empty_answer_is_a_success_and_closes_the_breaker(spy):
    model_breaker.record_failure("flash", started_at=model_breaker.now(), fingerprint="a", reason="x")
    model_breaker.record_failure("flash", started_at=model_breaker.now(), fingerprint="b", reason="x")
    assert _state() == "open"
    pool = _pool(_Client([{"text": "好", "images": []}]))
    _gen(pool)
    assert ("success", "flash") in spy
    assert _state() == "closed"


@pytest.mark.parametrize("result", [
    {"text": "", "images": [], "thoughts": "只有思考"},
    {"text": "", "images": [{"b64": "x"}]},
])
def test_thoughts_or_images_count_as_content(spy, result):
    pool = _pool(_Client([result]))
    _gen(pool)
    assert ("success", "flash") in spy


def test_an_empty_answer_is_neither_success_nor_failure(spy):
    pool = _pool(_Client([{"text": "", "images": []}]))
    _gen(pool)
    assert spy == []


@pytest.mark.parametrize("received,counted", [
    ("39 bytes", True),                       # 实测卡住：39～184B
    ("184 bytes", True),
    ("1023 bytes", True),
    ("1024 bytes", False),
    ("50000 out of 80000 bytes", False),      # 带 Content-Length 的报错格式
    (None, True),                             # 解析不出字节数：照旧计数
], ids=["39B", "184B", "1023B", "1024B", "out-of-format", "unparseable"])
def test_a_generation_timeout_counts_only_when_almost_nothing_arrived(spy, received, counted):
    """I.4：单个长请求超时分不清是卡住还是在慢思考。两个不同的正常长回答（各自超过 300 秒）不能
    误开熔断：实测的故障形态是「几乎没收到数据」。"""
    pool = _pool(_Client([_timed_out(received)]))
    err = _gen_err(pool)
    assert isinstance(err, gc.GenerationTimedOut)
    assert any(c[0] == "failure" for c in spy) is counted


def test_generation_timed_out_parses_the_bytes_received_from_libcurl():
    assert _timed_out("39 bytes").bytes_received == 39
    assert _timed_out("50000 out of 80000 bytes").bytes_received == 50000
    assert _timed_out(None).bytes_received is None
    assert gc.GenerationTimedOut(120, 121, TimeoutError()).bytes_received is None


@pytest.mark.parametrize("exc", [
    gc.TimeoutAfterRetries("Exhausted 3 retries: Connection timed out after 10001 milliseconds"),
    gc.GeminiRejectionError([13, 1152]),
    gc.HTTPStatusError(400, "bad"),
    gc.HTTPStatusError(401, "expired"),
    gc.HTTPStatusError(503, "busy"),
    RuntimeError("Exhausted 3 retries: boom"),
    ValueError("bad model"),
    TimeoutError("plain"),
], ids=["TimeoutAfterRetries", "rejection", "400", "401", "503", "runtime", "value", "plain-timeout"])
def test_failures_that_are_not_a_model_outage_are_not_recorded(spy, exc):
    pool = _pool(_Client([exc]))
    with pytest.raises(Exception):
        _gen(pool)
    assert spy == []


def test_pool_exhaustion_and_cancellation_are_not_recorded(spy):
    pool = _pool()
    with pytest.raises(RuntimeError):
        _gen(pool)

    class _Slow(_Client):
        async def generate(self, *a, **kw):
            await asyncio.sleep(10)

    pool = _pool(_Slow())

    async def run():
        task = asyncio.ensure_future(pool.generate("p", "gemini-flash"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert spy == []


def test_records_use_the_model_parameter_the_router_passed(spy):
    pool = _pool(_Client([_failure()]))
    _gen_err(pool, model="gemini-2.5-flash")
    assert spy[0][1] == "flash"


def test_an_unknown_model_records_nothing(spy):
    pool = _pool(_Client([_failure()]))
    _gen_err(pool, model="mystery-model")
    assert model_breaker.snapshot() == {}


# ---------------------------------------------------------------------------
# 真流式
# ---------------------------------------------------------------------------

def test_stream_success_is_recorded_at_the_first_body_delta(spy):
    """I.6：第一个正文增量（已经过了 A 的扣留检查）就是决定性信号，不等整段流完。"""
    seen_before_rest = {}

    async def checkpoint():
        seen_before_rest["spy"] = list(spy)

    pool = _pool(_Client(stream_scripts=[[
        {"type": "thoughts", "text": "想"},
        {"type": "delta", "text": "第一段"},
        checkpoint,
        {"type": "delta", "text": "第二段"},
        {"type": "final", "text": "第一段第二段"},
    ]]))
    _, err = _stream(pool)
    assert err is None
    assert seen_before_rest["spy"] == [("success", "flash")]
    assert spy == [("success", "flash")], "每次尝试只记一个结果"


def test_thoughts_alone_are_not_an_early_success(spy):
    async def checkpoint():
        assert spy == [], "只有思考不算成功（A 允许思考先于套话发出）"

    pool = _pool(_Client(stream_scripts=[[
        {"type": "thoughts", "text": "想"}, checkpoint, _failure(),
    ]]))
    _, err = _stream(pool)
    assert isinstance(err, gc.GeminiFailureReply)
    assert [c[0] for c in spy] == ["failure"]


def test_thoughts_then_the_failure_phrase_counts_once_and_never_expires_the_account(spy):
    """I.1：先发思考、再出套话 → 不累计连败、不标 EXPIRED，熔断计数只 +1（失败记录挂在
    _release_failed 这条分支上）。"""
    pool = _pool(_Client(stream_scripts=[[{"type": "thoughts", "text": "想"}, _failure()]]))
    _, err = _stream(pool)
    assert isinstance(err, gc.GeminiFailureReply)
    account = pool.accounts[0]
    assert account.status == AccountStatus.ACTIVE and account.consecutive_failures == 0
    assert [c[0] for c in spy] == ["failure"]
    assert model_breaker.snapshot()["flash"]["consecutive_failures"] == 1


def test_stream_failover_branch_records_each_attempt(spy):
    pool = _pool(_Client(stream_scripts=[[_failure()]]), _Client(stream_scripts=[[_failure()]]))
    _, err = _stream(pool, "同一个问题")
    assert isinstance(err, gc.GeminiFailureReply)
    failures = [c for c in spy if c[0] == "failure"]
    assert len(failures) == 2 and failures[0][2] == failures[1][2]
    assert model_breaker.snapshot()["flash"]["consecutive_failures"] == 1


def test_a_failure_after_a_recorded_success_is_not_counted(spy):
    pool = _pool(_Client(stream_scripts=[[{"type": "delta", "text": "已经发出去的正文"}, _failure()]]))
    _, err = _stream(pool)
    assert isinstance(err, gc.GeminiFailureReply)
    assert spy == [("success", "flash")]


@pytest.mark.parametrize("progressed,counted", [(False, True), (True, False)])
def test_a_stream_stall_counts_only_without_any_progress(spy, progressed, counted):
    prefix = [{"type": "thoughts", "text": "想了一会儿"}] if progressed else []
    stall = gc.GenerationStalled(120, 120.0, 2, progressed)
    pool = _pool(_Client(stream_scripts=[prefix + [stall]]))
    _, err = _stream(pool)
    assert isinstance(err, gc.GenerationStalled)
    assert any(c[0] == "failure" for c in spy) is counted


def test_a_normal_end_with_content_is_a_success(spy):
    pool = _pool(_Client(stream_scripts=[[
        {"type": "thoughts", "text": "想"}, {"type": "final", "text": "", "thoughts": "想"},
    ]]))
    _, err = _stream(pool)
    assert err is None
    assert spy == [("success", "flash")]


def test_an_empty_stream_records_nothing(spy):
    pool = _pool(_Client(stream_scripts=[[{"type": "final", "text": "", "images": []}]]))
    _stream(pool)
    assert spy == []


def test_a_success_from_an_attempt_started_before_the_breaker_opened_does_not_close_it(spy):
    """I.6：故障开始前就在流的长回答，在熔断打开之后才发出正文 / 结束，不能把熔断关掉。"""
    async def open_meanwhile():
        model_breaker.record_failure("flash", started_at=model_breaker.now(), fingerprint="x",
                                     reason="r")
        model_breaker.record_failure("flash", started_at=model_breaker.now(), fingerprint="y",
                                     reason="r")

    pool = _pool(_Client(stream_scripts=[[
        open_meanwhile, {"type": "delta", "text": "迟到的正文"}, {"type": "final", "text": "迟到的正文"},
    ]]))
    _, err = _stream(pool)
    assert err is None
    assert ("success", "flash") in spy
    assert _state() == "open"


def test_a_client_disconnect_records_nothing(spy):
    pool = _pool(_Client(stream_scripts=[[{"type": "thoughts", "text": "想"},
                                          {"type": "delta", "text": "x"}]]))

    async def run():
        agen = pool.generate_stream("p", "gemini-flash")
        await agen.__anext__()
        await agen.aclose()

    asyncio.run(run())
    assert spy == []

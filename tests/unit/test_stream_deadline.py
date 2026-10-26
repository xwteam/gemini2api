"""真流式不再无限等待（v1.6.46 规格 B + H.1 / H.3 / H.4 / H.5 / I.15）。

线上（中转站，北京 2026-10-26）：gemini-flash 谷歌侧排队时，StreamGenerate 的字节时间线是
    +60.1s  HTTP 200 响应头才到，同时到 39B：)]}'\\n\\n[["wrb.fr",null,"[{\\"37\\":[0]}]"]
    +120.1s 33B 又一个 [{"37":[0]}] 帧（没有正文、没有思考）
    +180.1s 33B 同上
    +181.6s 正文到达
谷歌每 60 秒发一个不含任何内容的心跳帧，过去 generate_stream 的 chunk_timeout=120 是「两次收到
字节之间」的上限，被心跳一次次重置；curl_cffi 0.7.4 流式下 timeout 只是 CONNECTTIMEOUT +
LOW_SPEED，同样被心跳重置。实测一条 flash 流式请求客户端干等 239.5 秒。

而同账号 gemini-pro 不开思考做难题，时间线一模一样（+60.1s 才回响应头 + 一个心跳帧），+89.4s
正文到达、是正常回答 —— 所以期限只能是族预算，不能更短（第 0 节第 3 条）。

本文件的测试跑在**虚拟时钟**的事件循环上（select 不真的等，直接把时钟拨过去），所以可以按真实的
秒数复刻上面两条时间线；传输层替身复刻 curl_cffi 0.7.4 的语义：后台传输任务与消费者无关地一直跑，
stream 上下文的 __aexit__ 只是等它跑完、不中止，除非 session 已经 close（第二次 close 抛 TypeError）。
另有两条用真 curl_cffi 连本机回环服务（只连 127.0.0.1）的验收测试。
"""

import asyncio
import json
import selectors
import time

import pytest
from curl_cffi.requests import RequestsError

from app.core import gemini_client as gc
from app.core.gemini_client import GeminiWebClient

_FLASH, _PRO, _LITE = "gemini-flash", "gemini-pro", "gemini-flash-lite"

# ---------------------------------------------------------------------------
# 虚拟时钟事件循环
# ---------------------------------------------------------------------------


class _VirtualClockSelector(selectors.DefaultSelector):
    """select(timeout) 不真的阻塞：把虚拟时钟往前拨 timeout 秒，再立即轮询一次。"""

    def __init__(self):
        super().__init__()
        self.now = 1000.0

    def select(self, timeout=None):
        if timeout is None:
            raise RuntimeError("virtual-time loop would block forever: nothing is scheduled")
        if timeout > 0:
            self.now += timeout
        return super().select(0)


class _VirtualTimeLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        self._vsel = _VirtualClockSelector()
        super().__init__(self._vsel)

    def time(self):
        return self._vsel.now


def _run(coro_fn):
    loop = _VirtualTimeLoop()
    try:
        return loop.run_until_complete(coro_fn())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


# ---------------------------------------------------------------------------
# 响应流的帧
# ---------------------------------------------------------------------------

_HEARTBEAT = b',["wrb.fr",null,"[{\\"37\\":[0]}]"]'


def _frame(text=None, thoughts=None, images=False) -> bytes:
    cand = ["rc_1", [text] if text is not None else None]
    if images:
        meta = [None, 1, "a.png", "https://lh3.googleusercontent.com/x", "image/png", [1, 1, 1]]
        cand += [None] * (12 - len(cand)) + [[None] * 7 + [[[[[None, None, None, meta]]]]]]
    if thoughts is not None:
        cand += [None] * (37 - len(cand)) + [[[thoughts]]]
    payload = [None, ["c_1", "r_1"], None, None, [cand]]
    return b"," + json.dumps(["wrb.fr", None, json.dumps(payload)]).encode()


def _meta_frame() -> bytes:
    """只带会话元数据的帧（_extract_text_from_wrb 返回非空 conv、没有正文）。"""
    return b"," + json.dumps(["wrb.fr", None, json.dumps([None, ["c_1", "r_1"], None, None, None])]).encode()


def _prefixed(events):
    """第一段字节带上 `)]}'` 前缀和外层数组的左括号（真机首包形态）。"""
    out = list(events)
    if out:
        at, data = out[0]
        if isinstance(data, bytes):
            out[0] = (at, b")]}'\n\n[" + data[1:])
    return out


# ---------------------------------------------------------------------------
# curl_cffi 0.7.4 语义的传输层替身
# ---------------------------------------------------------------------------


class _Upstream:
    """一条假的 StreamGenerate 响应。时间从 session.stream() 被调用那一刻算（秒）。

    events: [(秒, bytes | Exception)]；end_at=None 表示上游永不结束（直到 session 被 close）。
    """

    def __init__(self, *, headers_at=0.0, events=(), end_at=None, status=200):
        self.headers_at = headers_at
        self.events = _prefixed(events) if status < 400 else list(events)
        self.end_at = end_at
        self.status = status


class _Curl074Session:
    upstream: _Upstream = None          # 每个测试设一次
    created: list = []

    def __init__(self, *a, impersonate=None, timeout=None, **kw):
        self.timeout = timeout
        self.close_calls = 0
        self.closed = asyncio.Event()
        self.transfer = None
        self.closed_at = None
        _Curl074Session.created.append(self)

    def stream(self, method, url, **kw):
        return _Curl074CM(self, _Curl074Session.upstream)

    async def close(self):
        self.close_calls += 1
        if self.close_calls > 1:
            # curl_cffi 0.7.4 实测：第二次 AsyncSession.close() 抛这个
            raise TypeError("initializer for ctype 'void *' must be a cdata pointer, not NoneType")
        self.closed_at = asyncio.get_running_loop().time()
        self.closed.set()


async def _sleep_until(session, deadline) -> bool:
    """睡到绝对时刻 deadline；中途 session 被 close 就提前返回 True。"""
    loop = asyncio.get_running_loop()
    delay = deadline - loop.time()
    if delay > 0 and not session.closed.is_set():
        closed = asyncio.ensure_future(session.closed.wait())
        sleeper = asyncio.ensure_future(asyncio.sleep(delay))
        await asyncio.wait({closed, sleeper}, return_when=asyncio.FIRST_COMPLETED)
        for t in (closed, sleeper):
            t.cancel()
    return session.closed.is_set()


async def _transfer(session, up: _Upstream, queue: asyncio.Queue, headers_evt: asyncio.Event):
    """相当于 curl 的后台 perform 任务：只有 session.close() 能让它提前停下。"""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        if await _sleep_until(session, t0 + up.headers_at):
            return
        headers_evt.set()
        last_data = loop.time()
        pending = list(up.events)
        while True:
            next_at = t0 + pending[0][0] if pending else (t0 + up.end_at if up.end_at is not None else None)
            # LOW_SPEED：连续 timeout 秒一个字节都没有，curl 以 code 28 中断（0.7.4 的流式 timeout）
            low_speed_at = last_data + session.timeout if session.timeout else None
            candidates = [t for t in (next_at, low_speed_at) if t is not None]
            if not candidates:
                await session.closed.wait()
                return
            target = min(candidates)
            if await _sleep_until(session, target):
                return
            if low_speed_at is not None and target == low_speed_at and (next_at is None or low_speed_at < next_at):
                queue.put_nowait(RequestsError(
                    f"Failed to perform, curl: (28) Operation too slow. Less than 1 bytes/sec "
                    f"transferred the last {int(session.timeout)} seconds.", code=28))
                return
            if not pending:
                return                      # end_at 到了：正常结束
            _, data = pending.pop(0)
            if isinstance(data, Exception):
                queue.put_nowait(data)
                return
            queue.put_nowait(data)
            last_data = loop.time()
    finally:
        headers_evt.set()
        queue.put_nowait(None)


class _Curl074Resp:
    cookies: dict = {}
    headers: dict = {}

    def __init__(self, queue, status):
        self.queue = queue
        self.status_code = status

    def aiter_content(self):
        async def gen():
            while True:
                item = await self.queue.get()
                if item is None:
                    return
                if isinstance(item, Exception):
                    raise item
                yield item

        return gen()

    async def atext(self):
        parts = []
        async for c in self.aiter_content():
            parts.append(c)
        return b"".join(parts).decode()


class _Curl074CM:
    def __init__(self, session, up):
        self.session = session
        self.up = up

    async def __aenter__(self):
        self.queue = asyncio.Queue()
        headers_evt = asyncio.Event()
        # 后台传输任务一开始就跑起来；等响应头被取消也不会停它（与 curl 的 perform 一样）
        self.session.transfer = asyncio.ensure_future(
            _transfer(self.session, self.up, self.queue, headers_evt))
        await headers_evt.wait()
        return _Curl074Resp(self.queue, self.up.status)

    async def __aexit__(self, *exc):
        # 0.7.4 的 Response.aclose() 只是 await astream_task：不中止，一直等到上游自己结束
        await self.session.transfer
        return False


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


def _client(monkeypatch, up: _Upstream):
    monkeypatch.setattr(gc, "AsyncSession", _Curl074Session)
    _Curl074Session.upstream = up
    _Curl074Session.created = []

    async def _noop(*a, **kw):
        return None

    async def _image_entry(img, cookies):
        return {"b64": "x", "mime": "image/png"}

    monkeypatch.setattr(gc, "apply_jitter", _noop)
    client = GeminiWebClient.__new__(GeminiWebClient)
    client._healthy = True
    client._session_token = "TOKEN"
    client._current_target = "chrome120"
    client._family_model = {}
    client._session_uuid = "SESSION-UUID"
    client._push_id = ""
    client._http = object()                 # 只有附件上传会用到它（测试里 upload_files 是替身）

    class _Jar:
        def update_from_response(self, resp):
            return None

    client._cookie_jar = _Jar()
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    monkeypatch.setattr(client, "_build_image_entry", _image_entry)
    return client


class _Outcome:
    def __init__(self):
        self.events = []
        self.error = None
        self.t_start = None
        self.t_end = None

    @property
    def elapsed(self):
        return self.t_end - self.t_start

    @property
    def deltas(self):
        return [e["text"] for e in self.events if e["type"] == "delta"]


def _drive(client, prompt="hi", model=_FLASH, **kw) -> _Outcome:
    out = _Outcome()

    async def run():
        loop = asyncio.get_running_loop()
        out.t_start = loop.time()
        try:
            async for evt in client.generate_stream(prompt, model, **kw):
                out.events.append(evt)
        except Exception as e:  # noqa: BLE001
            out.error = e
        out.t_end = loop.time()
        session = _Curl074Session.created[-1] if _Curl074Session.created else None
        out.transfer_done = None
        if session is not None and session.transfer is not None:
            # 传输任务必须已经停了（session 关了它就该在同一刻结束），绝不能留在后台跑。
            # 给它几轮调度去收尾，但虚拟时钟不许往前走（sleep(0) 不排定时器）。
            for _ in range(5):
                await asyncio.sleep(0)
            out.transfer_done = session.transfer.done()
        return out

    return _run(run)


def _heartbeats(start, stop, every):
    t, out = start, []
    while t < stop:
        out.append((t, _HEARTBEAT))
        t += every
    return out


# ---------------------------------------------------------------------------
# 第 0 节的两条真机时间线
# ---------------------------------------------------------------------------

def test_flash_stuck_in_googles_queue_now_times_out_at_its_budget(monkeypatch):
    up = _Upstream(headers_at=60.1, events=[
        (60.1, _HEARTBEAT), (120.1, _HEARTBEAT), (180.1, _HEARTBEAT), (181.6, _frame("好")),
    ], end_at=182.0)
    out = _drive(_client(monkeypatch, up), "只回答一个字：好", _FLASH)

    assert isinstance(out.error, gc.GenerationStalled), out.error
    assert isinstance(out.error, TimeoutError)
    assert gc.is_timeout_error(out.error)
    assert gc.classify_error(out.error) == (504, "timeout_error", None)
    assert 119.9 <= out.elapsed < 121.0, f"flash 预算 120 秒，实际 {out.elapsed:.1f}s"
    assert out.deltas == []
    assert out.error.budget == 120
    assert out.error.keepalive_frames == 1, "只有 +60.1s 那一个心跳在期限之前到"
    assert out.error.progressed is False
    msg = str(out.error)
    assert "stream" in msg and "120s" in msg and "1 keepalive frame" in msg, msg
    assert out.transfer_done, "到期之后传输必须真的停了"


def test_pro_thinking_silently_for_89s_is_still_a_normal_answer(monkeypatch):
    """第 0 节第 3 条的反例：时间线与卡住一模一样，只是 +89.4s 正文到了。绝不能提前掐断。"""
    up = _Upstream(headers_at=60.1, events=[(60.1, _HEARTBEAT), (89.4, _frame("答案是 42"))],
                   end_at=89.6)
    out = _drive(_client(monkeypatch, up), "一道难题", _PRO)

    assert out.error is None, out.error
    assert out.deltas == ["答案是 42"]
    assert out.events[-1]["type"] == "final"


# ---------------------------------------------------------------------------
# 期限的口径
# ---------------------------------------------------------------------------

def test_heartbeats_never_extend_the_deadline(monkeypatch):
    up = _Upstream(events=_heartbeats(0.0, 1000.0, 10.0), end_at=1000.0)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.GenerationStalled)
    assert 119.9 <= out.elapsed < 121.0
    assert out.error.keepalive_frames >= 11


def test_after_progress_the_deadline_rolls_by_a_full_budget(monkeypatch):
    events = [(i * 100.0 + 1, _frame("好" * (i + 1))) for i in range(10)]   # 每 100 秒长一截，共 900+ 秒
    up = _Upstream(events=events, end_at=1000.0)
    out = _drive(_client(monkeypatch, up))

    assert out.error is None, out.error
    assert "".join(out.deltas) == "好" * 10


def test_a_stall_after_progress_times_out_one_budget_after_the_last_progress(monkeypatch):
    up = _Upstream(events=[(5.0, _frame("开头"))] + _heartbeats(15.0, 1000.0, 10.0), end_at=1000.0)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.GenerationStalled)
    assert 124.9 <= out.elapsed < 126.0, out.elapsed
    assert out.error.progressed is True
    assert 119.9 <= out.error.waited < 121.0
    assert out.deltas == ["开头"], "已经流出的正文不收回"


def test_the_gap_limit_is_the_family_budget_not_120s(monkeypatch):
    """H.3：间隔上限 = budget，取代原来固定的 chunk_timeout=120（不能两者取 min）。
    pro 预算 300：两次进展之间隔 249 秒、290 秒都是正常的慢思考。"""
    up = _Upstream(events=[(1.0, _frame("第一段")), (250.0, _frame("第一段，第二段")),
                           (540.0, _frame("第一段，第二段，第三段"))], end_at=541.0)
    out = _drive(_client(monkeypatch, up), "一道难题", _PRO)

    assert out.error is None, out.error
    assert "".join(out.deltas) == "第一段，第二段，第三段"


def test_waiting_for_response_headers_counts_against_the_deadline(monkeypatch):
    up = _Upstream(headers_at=500.0, events=[(500.0, _frame("迟到的回答"))], end_at=501.0)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.GenerationStalled)
    assert 119.9 <= out.elapsed < 121.0, out.elapsed
    assert out.error.progressed is False
    assert out.transfer_done, "等响应头超时后，后台传输也必须被收掉"


def test_generate_timeouts_override_applies_to_streaming(monkeypatch):
    monkeypatch.setattr(gc.settings, "generate_timeouts", "flash=30", raising=False)
    up = _Upstream(events=_heartbeats(0.0, 1000.0, 10.0), end_at=1000.0)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.GenerationStalled)
    assert 29.9 <= out.elapsed < 31.0
    assert out.error.budget == 30


def test_image_intent_raises_the_streaming_budget_too(monkeypatch):
    """生图意图取大（与非流式同一个 _generate_timeout）：flash-lite 生图 60 → 180 秒。"""
    events = [(1.0, _frame("好的，正在画")), (150.0, _frame("好的，正在画", images=True))]

    out = _drive(_client(monkeypatch, _Upstream(events=events, end_at=151.0)), "画一张猫的图片", _LITE)
    assert out.error is None, out.error
    assert len(out.events[-1]["images"]) == 1

    out = _drive(_client(monkeypatch, _Upstream(events=events, end_at=151.0)), "讲个笑话", _LITE)
    assert isinstance(out.error, gc.GenerationStalled)
    assert 60.9 <= out.elapsed < 62.0, out.elapsed


def test_uploading_attachments_does_not_eat_the_budget(monkeypatch):
    """H.4：期限从紧挨着 StreamGenerate POST 之前开始计时，与非流式 _send_request 的 started 同口径。"""
    import app.core.file_upload as fu

    async def slow_upload(*a, **kw):
        await asyncio.sleep(200.0)            # 上传 200 秒，超过 flash 的整个预算
        return [("fid-1", "a.png")]

    monkeypatch.setattr(fu, "upload_files", slow_upload)
    up = _Upstream(events=[(5.0, _frame("看到了图"))], end_at=6.0)
    out = _drive(_client(monkeypatch, up), "看图", _FLASH,
                 attachments=[{"data": b"x", "filename": "a.png", "mime": "image/png"}])

    assert out.error is None, out.error
    assert out.deltas == ["看到了图"]


def test_progress_is_judged_on_parsed_values_even_while_the_body_is_held(monkeypatch):
    """H.5：A 的扣住期间到达的真实内容照样算进展（与有没有 yield 无关）。"""
    up = _Upstream(events=[
        (1.0, _frame("I")), (100.0, _frame("I seem")), (200.0, _frame("I seem to be")),
        (300.0, _frame("I seem to be encountering")),
        (400.0, _frame("I seem to be encountering a bug in your code.")),
    ], end_at=401.0)
    out = _drive(_client(monkeypatch, up))

    assert out.error is None, out.error
    assert out.deltas == ["I seem to be encountering a bug in your code."]


def test_repeated_and_metadata_only_frames_are_not_progress(monkeypatch):
    events = [(1.0, _frame("同一段"))]
    for i in range(1, 30):
        events.append((1.0 + i * 15.0, _frame("同一段") if i % 2 else _meta_frame()))
    out = _drive(_client(monkeypatch, _Upstream(events=events, end_at=1000.0)))

    assert isinstance(out.error, gc.GenerationStalled)
    assert 120.9 <= out.elapsed < 122.0, out.elapsed


def test_growing_thoughts_are_progress(monkeypatch):
    events = [(i * 60.0 + 7.0, _frame(None, thoughts="想" * (i + 1))) for i in range(5)]
    events.append((310.0, _frame("结论", thoughts="想" * 5)))
    out = _drive(_client(monkeypatch, _Upstream(events=events, end_at=311.0)),
                 extended_thinking=1)

    assert out.error is None, out.error
    assert out.deltas == ["结论"]


# ---------------------------------------------------------------------------
# 真的中止传输（H.1）
# ---------------------------------------------------------------------------

def test_the_timeout_reaches_the_caller_within_a_second_while_heartbeats_continue(monkeypatch):
    """验收：服务端持续发心跳时，TimeoutError 子类在期限后 1 秒内到达调用方。

    0.7.4 的 stream 上下文退出时只会等后台传输自己结束；不先关 session，这里要等到第 3600 秒。"""
    up = _Upstream(events=_heartbeats(0.0, 3600.0, 5.0), end_at=3600.0)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.GenerationStalled)
    assert out.elapsed < 120.0 + 1.0, f"异常 {out.elapsed:.1f}s 才到调用方"
    session = _Curl074Session.created[-1]
    assert session.close_calls == 1, "session 只关一次（0.7.4 第二次 close 会抛 TypeError）"
    assert out.transfer_done


def test_a_4xx_whose_error_body_never_ends_is_bounded_by_the_deadline(monkeypatch):
    up = _Upstream(status=400, events=[(0.5, b"bad request, and the body never ends")], end_at=None)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.HTTPStatusError), out.error
    assert out.error.status_code == 400
    assert out.elapsed < 121.0
    assert out.transfer_done


def test_curl_code_28_inside_the_stream_becomes_a_stream_stall(monkeypatch):
    up = _Upstream(events=[(2.0, _frame("开头")),
                           (50.0, RequestsError("Operation too slow", code=28))], end_at=None)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, gc.GenerationStalled), out.error
    assert out.error.progressed is True
    assert 47.9 <= out.error.waited < 49.0, out.error.waited
    assert isinstance(out.error.__cause__, RequestsError)


def test_other_curl_errors_inside_the_stream_pass_through(monkeypatch):
    up = _Upstream(events=[(2.0, _frame("开头")),
                           (50.0, RequestsError("Connection reset by peer", code=56))], end_at=None)
    out = _drive(_client(monkeypatch, up))

    assert isinstance(out.error, RequestsError) and out.error.code == 56
    assert not isinstance(out.error, gc.GenerationStalled)


def test_the_stream_session_timeout_is_at_least_budget_plus_margin(monkeypatch):
    """I.15：0.7.4 流式的 timeout 实际是 LOW_SPEED（连续 N 秒没字节就 code 28）。过去写死 180，
    会先于 pro 的 300 秒期限把一个还在慢思考的请求打断。"""
    up = _Upstream(events=[], end_at=None)          # pro：响应头之后 300 秒一个字节都没有
    out = _drive(_client(monkeypatch, up), "一道难题", _PRO)

    session = _Curl074Session.created[-1]
    assert session.timeout >= 300 + 30, session.timeout
    assert isinstance(out.error, gc.GenerationStalled)
    assert 299.9 <= out.elapsed < 301.0, f"180 秒没数据就被打断了：{out.elapsed:.1f}s"


def test_a_client_disconnect_aborts_the_transfer_at_once(monkeypatch):
    """客户端断连（生成器被 aclose）时同样先中止传输，账号槽位不必占到谷歌自己返回。"""
    up = _Upstream(events=[(1.0, _frame("开头"))] + _heartbeats(5.0, 3600.0, 5.0), end_at=3600.0)
    client = _client(monkeypatch, up)

    async def run():
        loop = asyncio.get_running_loop()
        agen = client.generate_stream("hi", _FLASH)
        first = await agen.__anext__()
        t0 = loop.time()
        await agen.aclose()
        session = _Curl074Session.created[-1]
        for _ in range(5):
            await asyncio.sleep(0)
        return first, loop.time() - t0, session.transfer.done()

    first, took, transfer_done = _run(run)
    assert first == {"type": "delta", "text": "开头"}
    assert took < 1.0, took
    assert transfer_done


# ---------------------------------------------------------------------------
# 用真 curl_cffi 连本机回环服务（只连 127.0.0.1）
# ---------------------------------------------------------------------------

def _loopback_client(monkeypatch, port: int):
    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(gc, "GENERATE_URL", f"http://127.0.0.1:{port}/StreamGenerate")
    monkeypatch.setattr(gc, "apply_jitter", _noop)
    monkeypatch.setattr(gc.settings, "generate_timeouts", "flash=1.5", raising=False)
    client = GeminiWebClient.__new__(GeminiWebClient)
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


def _loopback(handler_delay_headers: float, heartbeat_every: float, total: float):
    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            await asyncio.sleep(handler_delay_headers)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         b"Transfer-Encoding: chunked\r\n\r\n")

            def chunk(b):
                return b"%x\r\n" % len(b) + b + b"\r\n"

            writer.write(chunk(b")]}'\n\n[" + _HEARTBEAT[1:]))
            await writer.drain()
            loop = asyncio.get_running_loop()
            stop = loop.time() + total
            while loop.time() < stop:
                await asyncio.sleep(heartbeat_every)
                writer.write(chunk(_HEARTBEAT))
                await writer.drain()
            writer.write(chunk(b"]") + b"0\r\n\r\n")
            await writer.drain()
        except Exception:  # noqa: BLE001 - 客户端走了，写失败是预期的
            pass
        finally:
            writer.close()

    return handle


def _run_loopback(monkeypatch, *, delay_headers, heartbeat_every, total):
    async def run():
        server = await asyncio.start_server(
            _loopback(delay_headers, heartbeat_every, total), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = _loopback_client(monkeypatch, port)
        t0 = time.monotonic()
        err = None
        try:
            async for _ in client.generate_stream("hi", _FLASH):
                pass
        except Exception as e:  # noqa: BLE001
            err = e
        took = time.monotonic() - t0
        server.close()
        return err, took

    return asyncio.run(run())


def test_real_curl_cffi_stream_with_heartbeats_aborts_within_a_second(monkeypatch):
    err, took = _run_loopback(monkeypatch, delay_headers=0.0, heartbeat_every=0.2, total=8.0)
    assert isinstance(err, gc.GenerationStalled), err
    assert took < 1.5 + 1.0, f"异常 {took:.2f}s 才到调用方（期限 1.5s，服务器 8s 后才结束）"


def test_real_curl_cffi_header_wait_is_bounded(monkeypatch):
    err, took = _run_loopback(monkeypatch, delay_headers=6.0, heartbeat_every=0.2, total=1.0)
    assert isinstance(err, gc.GenerationStalled), err
    assert took < 1.5 + 1.0, f"等响应头 {took:.2f}s（期限 1.5s，服务器 6s 后才回头）"

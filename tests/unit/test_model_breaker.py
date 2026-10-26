"""模型级熔断的状态机（v1.6.46 规格 C.1～C.4、C.7 的状态字段，及 I.2 / I.3 / I.5 / I.6 / I.12 / I.14）。

谷歌某个模型族整体故障时（第 0 节：flash 至少两段、三个账号都中招），带第三方兜底的请求不该每次
先白等一个预算。熔断器按族记「疑似故障」的失败，够数就打开一段时间：这期间开了兜底的
/v1/chat/completions 请求直接走兜底；到期后放一个真实请求去试探谷歌。

这里的熔断器都显式注入时钟与配置（I.13），不读全局 settings、不碰全局实例。
"""

import inspect
import logging
from datetime import datetime, timezone

import pytest

from app.core import model_breaker as mb
from app.core.model_breaker import BreakerConfig, ModelBreaker, request_fingerprint

FAM = "flash"
WALL0 = datetime(2026, 10, 26, 9, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _breaker(**overrides):
    cfg = dict(enabled=True, threshold=2, window=300.0, cooldown=60.0, max_cooldown=300.0)
    cfg.update(overrides)
    clock = _Clock()
    holder = {"cfg": BreakerConfig(**cfg)}
    b = ModelBreaker(clock=clock,
                     wall_clock=lambda: WALL0.replace(microsecond=0) + _delta(clock.t - 1000.0),
                     config=lambda: holder["cfg"])
    return b, clock, holder


def _delta(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def _fail(b, clock, fp, *, started=None, reason="GeminiFailureReply (HTTP 502)", family=FAM):
    b.record_failure(family, started_at=clock.t if started is None else started,
                     fingerprint=fp, reason=reason)


def _state(b, family=FAM):
    return b.snapshot()[family]["state"]


def _open(b, clock, family=FAM):
    _fail(b, clock, "req-a", family=family)
    _fail(b, clock, "req-b", family=family)
    assert _state(b, family) == "open"


# ---------------------------------------------------------------------------
# closed：阈值、窗口、按不同请求计数
# ---------------------------------------------------------------------------

def test_threshold_distinct_requests_open_the_breaker():
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a")
    assert _state(b) == "closed"
    assert b.should_bypass(FAM, probe_timeout=200).bypass is False
    _fail(b, clock, "req-b")
    assert _state(b) == "open"
    assert b.should_bypass(FAM, probe_timeout=200).bypass is True


def test_the_same_request_failing_again_counts_once():
    """I.3：同一请求的换号、思考重试、客户端 / SDK 重发都只 +1 —— 一个「毒请求」不能熔断整个族。"""
    b, clock, _ = _breaker()
    for _ in range(6):
        _fail(b, clock, "req-a")
        clock.t += 5
    snap = b.snapshot()[FAM]
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 1


def test_last_reason_is_updated_for_every_attempt_even_when_not_counted():
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a", reason="GenerationTimedOut")
    _fail(b, clock, "req-a", reason="GenerationStalled")
    assert b.snapshot()[FAM]["last_reason"] == "GenerationStalled"


def test_window_expiry_restarts_the_count():
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a")                       # 计入于 t=1000
    clock.t += 301
    _fail(b, clock, "req-b")                       # 本次尝试开始于 1301，距上次计入 301 秒 > 300
    snap = b.snapshot()[FAM]
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 1


def test_window_is_judged_by_when_the_failing_attempt_started():
    """I.2：失败是在尝试开始后满一个预算才记下的。两个顺序的 300 秒 pro 超时（第二个在第一个失败之后
    才开始）间隔必然 > 300 秒 —— 按「记下时刻」判窗口，pro / argon 在顺序流量下永远不熔断。"""
    b, clock, _ = _breaker()
    clock.t = 1300.0
    _fail(b, clock, "req-a", started=1000.0, family="pro")      # 300 秒超时，记于 1300
    clock.t = 1602.0
    _fail(b, clock, "req-b", started=1302.0, family="pro")      # 失败之后才开始，又等满 300 秒
    assert _state(b, "pro") == "open"


def test_a_failure_whose_attempt_started_long_after_still_resets():
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a")
    clock.t += 1000
    _fail(b, clock, "req-b", started=clock.t - 10)
    assert _state(b) == "closed"


def test_threshold_one_opens_on_the_first_failure():
    b, clock, _ = _breaker(threshold=1)
    _fail(b, clock, "req-a")
    assert _state(b) == "open"


# ---------------------------------------------------------------------------
# open → half_open → 探测
# ---------------------------------------------------------------------------

def test_open_bypasses_until_the_cooldown_ends_then_lets_exactly_one_probe_through():
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 59
    assert b.should_bypass(FAM, probe_timeout=200).bypass is True
    clock.t += 2
    first = b.should_bypass(FAM, probe_timeout=200)
    second = b.should_bypass(FAM, probe_timeout=200)
    assert (first.bypass, first.is_probe) == (False, True), "第一个调用者占住探测位、去试谷歌"
    assert (second.bypass, second.is_probe) == (True, False), "其它调用者照样绕开"
    assert b.snapshot()[FAM]["state"] == "half_open"
    assert b.snapshot()[FAM]["probe_in_flight"] is True


def test_a_successful_probe_closes_and_resets_the_cooldown():
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 61
    probe = b.should_bypass(FAM, probe_timeout=200)
    started = clock.t
    _fail(b, clock, "req-c", started=started)          # 探测失败 → 重开、120 秒
    assert b.snapshot()[FAM]["cooldown_seconds"] == 120
    clock.t += 121
    probe = b.should_bypass(FAM, probe_timeout=200)
    assert probe.is_probe
    b.record_success(FAM, started_at=clock.t)
    b.release(probe)
    snap = b.snapshot()[FAM]
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 0
    assert snap["cooldown_seconds"] == 60, "关闭后开放期复位为初始值"
    assert b.should_bypass(FAM, probe_timeout=200).bypass is False


def test_failed_probes_double_the_cooldown_up_to_the_cap():
    b, clock, _ = _breaker(cooldown=60, max_cooldown=200)
    _open(b, clock)
    seen = []
    for _ in range(4):
        clock.t += b.snapshot()[FAM]["open_remaining_seconds"] + 0.5
        probe = b.should_bypass(FAM, probe_timeout=500)
        assert probe.is_probe
        _fail(b, clock, f"probe-{len(seen)}")
        seen.append(b.snapshot()[FAM]["cooldown_seconds"])
    assert seen == [120, 200, 200, 200]


def test_a_probe_with_an_uncounted_outcome_hands_the_slot_to_the_next_request():
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 61
    probe = b.should_bypass(FAM, probe_timeout=200)
    assert b.should_bypass(FAM, probe_timeout=200).bypass is True
    b.release(probe)                                   # 4xx / 池满 / 被取消：不计入、释放
    assert _state(b) == "half_open"
    nxt = b.should_bypass(FAM, probe_timeout=200)
    assert nxt.is_probe and not nxt.bypass


def test_an_abandoned_probe_slot_is_reclaimed_after_its_timeout():
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 61
    b.should_bypass(FAM, probe_timeout=150)            # 占住后再也没有释放（泄漏）
    clock.t += 149
    assert b.should_bypass(FAM, probe_timeout=150).bypass is True
    clock.t += 2
    again = b.should_bypass(FAM, probe_timeout=150)
    assert again.is_probe, "探测位占用超过调用方给的时限视为已放弃，自动释放"


def test_a_stale_ticket_never_releases_someone_elses_probe():
    """I.5：票据 + epoch。慢探测在新一轮里 release，不能把新一轮的探测位放掉（否则两个探测并发）。"""
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 61
    old = b.should_bypass(FAM, probe_timeout=10)
    clock.t += 11                                       # old 被判为已放弃
    new = b.should_bypass(FAM, probe_timeout=200)
    assert new.is_probe
    b.release(old)                                      # 迟到的 release
    assert b.should_bypass(FAM, probe_timeout=200).bypass is True, "new 的探测位还被占着"

    # 跨 epoch：探测失败重开 → 再到 half_open，上一轮的票据同样无效
    _fail(b, clock, "req-x")
    clock.t += 121
    newest = b.should_bypass(FAM, probe_timeout=200)
    assert newest.is_probe
    b.release(new)
    assert b.should_bypass(FAM, probe_timeout=200).bypass is True


def test_every_transition_bumps_the_epoch_and_tickets_carry_it():
    """I.5：每次状态转换 epoch+1 并清空探测位，票据带着发放时的 epoch。

    （探测票据另带一个全局唯一的 token，迟到的 release 单靠它也放不掉别人的探测位；epoch 按规格
    保留，这里钉住它确实随每次转换前进。）"""
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a")
    closed = b.should_bypass(FAM, probe_timeout=200)
    _fail(b, clock, "req-b")                                        # closed → open
    opened = b.should_bypass(FAM, probe_timeout=200)
    assert opened.bypass and opened.epoch == closed.epoch + 1
    clock.t += 61
    probe = b.should_bypass(FAM, probe_timeout=200)                 # open → half_open（惰性）
    assert probe.is_probe and probe.epoch == opened.epoch + 1
    _fail(b, clock, "req-c")                                        # half_open → open（翻倍）
    reopened = b.should_bypass(FAM, probe_timeout=200)
    assert reopened.bypass and reopened.epoch == probe.epoch + 1
    clock.t += 121
    probe2 = b.should_bypass(FAM, probe_timeout=200)                # open → half_open
    assert probe2.epoch == reopened.epoch + 1
    b.record_success(FAM, started_at=clock.t)                       # half_open → closed
    after = b.should_bypass(FAM, probe_timeout=200)
    assert not after.bypass and after.epoch == probe2.epoch + 1
    assert b.snapshot()[FAM]["probe_in_flight"] is False


def test_releasing_a_non_probe_ticket_is_a_no_op():
    b, clock, _ = _breaker()
    _open(b, clock)
    ticket = b.should_bypass(FAM, probe_timeout=200)
    b.release(ticket)
    b.release(None)
    assert _state(b) == "open"


# ---------------------------------------------------------------------------
# 任何（不过期的）成功关闭熔断；过期结果不算（I.6）
# ---------------------------------------------------------------------------

def test_any_fresh_success_closes_even_while_open():
    """别的协议（不走绕开逻辑）的请求带回来的成功同样关闭熔断。"""
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 5
    b.record_success(FAM, started_at=clock.t - 1)
    assert _state(b) == "closed"


def test_a_success_from_an_attempt_started_before_the_breaker_opened_is_ignored():
    b, clock, _ = _breaker()
    long_running_started = clock.t - 50                # 故障前就在流的长回答
    _open(b, clock)
    clock.t += 5
    b.record_success(FAM, started_at=long_running_started)
    assert _state(b) == "open"
    clock.t += 61
    probe = b.should_bypass(FAM, probe_timeout=200)
    b.record_success(FAM, started_at=long_running_started)
    assert _state(b) == "half_open"
    b.release(probe)


def test_a_failure_from_an_attempt_started_before_the_last_open_is_ignored_in_half_open():
    b, clock, _ = _breaker()
    old_started = clock.t - 10
    _open(b, clock)
    clock.t += 61
    b.should_bypass(FAM, probe_timeout=200)
    _fail(b, clock, "req-old", started=old_started)
    snap = b.snapshot()[FAM]
    assert snap["state"] == "half_open"
    assert snap["cooldown_seconds"] == 60


def test_in_closed_only_a_success_started_after_the_last_counted_failure_resets_the_count():
    b, clock, _ = _breaker(threshold=3)
    before = clock.t - 1
    _fail(b, clock, "req-a")
    b.record_success(FAM, started_at=before)
    assert b.snapshot()[FAM]["consecutive_failures"] == 1, "过期成功不清零"
    clock.t += 1
    b.record_success(FAM, started_at=clock.t)
    assert b.snapshot()[FAM]["consecutive_failures"] == 0


def test_failures_while_open_only_update_the_reason():
    b, clock, _ = _breaker()
    _open(b, clock)
    before = b.snapshot()[FAM]
    clock.t += 30
    _fail(b, clock, "req-c", reason="GenerationStalled")
    after = b.snapshot()[FAM]
    assert after["state"] == "open"
    assert after["cooldown_seconds"] == before["cooldown_seconds"] == 60, "不翻倍"
    assert after["open_remaining_seconds"] == pytest.approx(30), "不续期"
    assert after["last_reason"] == "GenerationStalled"


def test_only_the_first_counted_failure_of_a_half_open_epoch_reopens_and_doubles():
    b, clock, _ = _breaker()
    _open(b, clock)
    clock.t += 61
    b.should_bypass(FAM, probe_timeout=200)
    _fail(b, clock, "req-c")
    _fail(b, clock, "req-d")                            # 同一轮里第二个失败：已经 open，不再翻倍
    snap = b.snapshot()[FAM]
    assert snap["state"] == "open"
    assert snap["cooldown_seconds"] == 120


def test_a_success_on_an_unknown_family_does_not_create_state():
    b, clock, _ = _breaker()
    b.record_success("pro", started_at=clock.t)
    assert b.snapshot() == {}


def test_no_family_means_no_breaker():
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a", family=None)
    _fail(b, clock, "req-b", family=None)
    assert b.should_bypass(None, probe_timeout=200).bypass is False
    assert b.snapshot() == {}


# ---------------------------------------------------------------------------
# 开关、配置、状态
# ---------------------------------------------------------------------------

def test_disabled_breaker_never_bypasses(caplog):
    b, clock, holder = _breaker(enabled=False)
    with caplog.at_level(logging.WARNING):
        _fail(b, clock, "req-a")
        _fail(b, clock, "req-b")
    assert b.should_bypass(FAM, probe_timeout=200).bypass is False
    clock.t += 61
    ticket = b.should_bypass(FAM, probe_timeout=200)
    assert (ticket.bypass, ticket.is_probe) == (False, False)
    assert b.snapshot()[FAM]["enabled"] is False
    # 关掉时的日志不能声称「开了兜底的请求直接走兜底」
    assert not any("直接走兜底" in r.getMessage() for r in caplog.records)


def test_the_config_is_read_on_every_call():
    b, clock, holder = _breaker(threshold=3)
    _fail(b, clock, "req-a")
    _fail(b, clock, "req-b")
    assert _state(b) == "closed"
    holder["cfg"] = holder["cfg"]._replace(threshold=2)
    _fail(b, clock, "req-c")
    assert _state(b) == "open"


def test_snapshot_fields():
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a", reason="GenerationTimedOut")
    clock.t += 3
    _fail(b, clock, "req-b", reason="GeminiFailureReply (HTTP 502)")
    clock.t += 20
    snap = b.snapshot()[FAM]
    assert snap == {
        "state": "open",
        "enabled": True,
        "consecutive_failures": 2,
        "open_remaining_seconds": pytest.approx(40),
        "retry_at": "2026-10-26T09:01:03+00:00",       # 绝对时间（墙钟 UTC），不是倒计时
        "cooldown_seconds": 60,
        "probe_in_flight": False,
        "last_reason": "GeminiFailureReply (HTTP 502)",
        "last_failure_at": "2026-10-26T09:00:03+00:00",
    }
    clock.t += 41
    snap = b.snapshot()[FAM]
    assert snap["state"] == "half_open", "snapshot 同样先做 open→half_open 的惰性转换"
    assert snap["open_remaining_seconds"] == 0 and snap["retry_at"] is None
    assert snap["probe_in_flight"] is False


def test_snapshot_does_not_show_a_count_whose_window_has_passed():
    """consecutive_failures 是「当前窗口里」疑似故障地失败过的不同请求个数（API.md）。计数只在下一次
    失败 / 成功时才真正清空，窗口过了还显示 1，看起来像「再来一次就熔断」—— 其实下一次会从 1 重新计。"""
    b, clock, _ = _breaker()
    _fail(b, clock, "req-a")                       # 计入于 t=1000，WINDOW=300
    clock.t = 1300.0
    assert b.snapshot()[FAM]["consecutive_failures"] == 1, "窗口边界上照旧算（与 record_failure 同口径）"
    clock.t = 4600.0
    snap = b.snapshot()[FAM]
    assert (snap["state"], snap["consecutive_failures"]) == ("closed", 0)
    assert snap["last_reason"], "最近一次失败的原因照旧展示"
    # 只是展示：snapshot 不改状态，下一次失败照旧从 1 重新计
    _fail(b, clock, "req-b")
    assert b.snapshot()[FAM]["consecutive_failures"] == 1


def test_the_breaker_api_is_fully_synchronous():
    """I.5：检查和占位之间不能有 await —— 整个接口同步，没有任何协程。"""
    for name in ("should_bypass", "release", "record_failure", "record_success", "snapshot", "reset"):
        assert not inspect.iscoroutinefunction(getattr(ModelBreaker, name)), name


def test_reset_clears_everything():
    b, clock, _ = _breaker()
    _open(b, clock)
    b.reset()
    assert b.snapshot() == {}
    assert b.should_bypass(FAM, probe_timeout=200).bypass is False


def test_request_fingerprint():
    a = request_fingerprint("hello", "")
    assert a == request_fingerprint("hello", "")
    assert a != request_fingerprint("hello", '["c_1", null, null]')
    assert a != request_fingerprint("hello!", "")
    assert len(a) == 16 and int(a, 16) >= 0
    # 只在内存里用：绝不含原文
    assert "hello" not in a
    # 孤立代理码（JSON 里的 \ud800 之类）不能让它炸
    assert request_fingerprint("\ud800", "") != request_fingerprint("\ud801", "")


def test_same_request_as_pins_the_fingerprint_of_the_first_attempt():
    """路由对同一个客户端请求的改写重试（续接失败 → 改发完整历史）prompt 与 conversation_id 都变了，
    在 same_request_as 里发就沿用第一次尝试的指纹（I.3：一个客户端请求只 +1）。"""
    assert mb.attempt_fingerprint("full history", "") == request_fingerprint("full history", "")
    with mb.same_request_as("q2", '["c_1", "r_1", "rc_1"]'):
        assert mb.attempt_fingerprint("full history", "") == request_fingerprint("q2", '["c_1", "r_1", "rc_1"]')
    assert mb.attempt_fingerprint("full history", "") == request_fingerprint("full history", "")


def test_a_task_created_inside_same_request_as_keeps_the_pinned_fingerprint():
    """路由的重试都包成 task 跑（保活）：task 建在块里就继承它，块结束之后照样有效；块外不受影响。"""
    import asyncio

    async def main():
        async def attempt():
            await asyncio.sleep(0)
            return mb.attempt_fingerprint("full history", "")

        with mb.same_request_as("q2", "c1"):
            task = asyncio.create_task(attempt())
        outside = mb.attempt_fingerprint("full history", "")
        return await task, outside

    inside, outside = asyncio.run(main())
    assert inside == request_fingerprint("q2", "c1")
    assert outside == request_fingerprint("full history", "")


# ---------------------------------------------------------------------------
# 配置：非法值回退默认并 WARNING，服务照样起得来（C.4 / I.12）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,raw,expected", [
    ("model_breaker_enabled", "maybe", True),
    ("model_breaker_enabled", "false", False),
    ("model_breaker_enabled", "OFF", False),
    ("model_breaker_threshold", "abc", 2),
    ("model_breaker_threshold", "0", 2),
    ("model_breaker_threshold", "-3", 2),
    ("model_breaker_threshold", "3", 3),
    ("model_breaker_window", "soon", 300.0),
    ("model_breaker_window", "0", 300.0),
    ("model_breaker_window", "nan", 300.0),
    ("model_breaker_cooldown", "-5", 60.0),
    ("model_breaker_cooldown", "90", 90.0),
    ("model_breaker_max_cooldown", "x", 300.0),
])
def test_invalid_settings_fall_back_to_the_defaults(field, raw, expected, caplog):
    from app.config import Settings

    with caplog.at_level(logging.WARNING, logger="app.config"):
        s = Settings(_env_file=None, **{field: raw})
    assert getattr(s, field) == expected
    valid = raw in ("false", "OFF", "3", "90")
    assert any(field.upper() in r.getMessage() for r in caplog.records) is (not valid)


def test_max_cooldown_is_never_below_the_cooldown(caplog):
    from app.config import Settings

    with caplog.at_level(logging.WARNING, logger="app.config"):
        s = Settings(_env_file=None, model_breaker_cooldown="400", model_breaker_max_cooldown="100")
    assert s.model_breaker_cooldown == 400
    assert s.model_breaker_max_cooldown == 400
    assert any("MODEL_BREAKER_MAX_COOLDOWN" in r.getMessage() for r in caplog.records)


def test_the_global_breaker_reads_runtime_settings(monkeypatch):
    """I.12：全局实例每次调用现读 settings（运行时覆盖与测试 monkeypatch 生效），非法值同样兜住。"""
    from app.config import settings

    b = mb.ModelBreaker(clock=_Clock())
    monkeypatch.setattr(settings, "model_breaker_threshold", 1)
    b.record_failure(FAM, started_at=1000.0, fingerprint="req-a", reason="x")
    assert b.snapshot()[FAM]["state"] == "open"
    monkeypatch.setattr(settings, "model_breaker_enabled", False)
    assert b.should_bypass(FAM, probe_timeout=200).bypass is False
    monkeypatch.setattr(settings, "model_breaker_enabled", True)
    monkeypatch.setattr(settings, "model_breaker_cooldown", 0)          # 运行时塞进来的非法值
    b.reset()
    b.record_failure(FAM, started_at=1000.0, fingerprint="req-a", reason="x")
    assert b.snapshot()[FAM]["cooldown_seconds"] == 60


def test_the_global_instance_starts_empty_in_every_test():
    """I.13：conftest 的 autouse fixture 每个测试前复位全局熔断器。"""
    assert mb.model_breaker.snapshot() == {}
    mb.model_breaker.record_failure(FAM, started_at=0.0, fingerprint="a", reason="x")
    assert mb.model_breaker.snapshot() != {}

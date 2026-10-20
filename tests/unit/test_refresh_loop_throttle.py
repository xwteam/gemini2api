"""轮换循环「启动就常驻」之后必须加的两道闸：间隔下限、降级阈值。

S1 把 `_ensure_refresh_task()` 改成无条件启动，于是 `_auto_refresh_loop` 从一条
「几乎不执行」的旁路变成了常驻后台流量，两条潜伏路径随之变成每个账号的默认行为：

1. **频率**：每一轮是 5 个上游请求（RotateCookies + `_obtain_session_token` 的 3 个 GET +
   心跳）。配置默认 5 分钟时 = 每账号每天 1440 次定时请求，而参考实现默认 1440 **分钟**、
   并把下限硬夹在 10 分钟（注释原文：更频繁会显得像自动化、容易被标记或封禁）。
   更糟的是 `REFRESH_INTERVAL=0` 一直是合法值（面板上"填 0 表示关掉"是很自然的直觉），
   `asyncio.sleep(0)` 不产生任何延迟 —— 循环退化成以网络 RTT 为唯一节流的热循环。
2. **降级**：取不到 token 一次就 `self._healthy = False`，而 `_obtain_session_token()`
   会把任何异常（网络抖动/超时/Google 瞬时 5xx）吞掉并清空 token。改动前这条路径碰不到
   健康账号；现在每 N 分钟一次的探活只要抖一下，一个完全正常的账号就被踢出选号池、
   还触发一次毫无必要的 reload_cookies 自愈。
"""

import asyncio
import logging

import pytest

from app.core import gemini_client as gc


def _loop_client(monkeypatch, *, token_results, rotation=True, interval=30):
    """跑 len(token_results) 轮 _auto_refresh_loop，返回 (client, 每轮 sleep 的秒数)。"""
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._healthy = True
    client._session_token = "GOOD-TOKEN"

    monkeypatch.setattr(gc.settings, "refresh_interval", interval)
    monkeypatch.setattr(gc, "random_delay_factor", lambda: 1.0)

    slept: list[float] = []

    async def _sleep(sec, *a, **kw):
        slept.append(sec)
        if len(slept) > len(token_results):
            raise asyncio.CancelledError()

    monkeypatch.setattr(gc.asyncio, "sleep", _sleep)

    pending = list(token_results)

    async def _rotate():
        return gc.RotationResult.RENEWED if rotation else gc.RotationResult.FAILED

    async def _obtain():
        # 真实实现在任何失败路径上都会把 token 清空
        client._session_token = pending.pop(0) if pending else ""

    async def _heartbeat():
        return None

    monkeypatch.setattr(client, "_rotate_cookies", _rotate)
    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)

    async def _drive():
        # 循环体顶部的 sleep 在 try 之外（真实运行时靠 Task.cancel 终止），
        # 所以这里的 CancelledError 就是"跑够轮数了"的信号。
        try:
            await client._auto_refresh_loop()
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())
    return client, slept


# ---------------------------------------------------------------------------
# 1. 间隔下限
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "configured,expected_seconds",
    [
        (0, gc.MIN_REFRESH_INTERVAL_MINUTES * 60),    # 热循环：必须被夹住
        (1, gc.MIN_REFRESH_INTERVAL_MINUTES * 60),
        (5, gc.MIN_REFRESH_INTERVAL_MINUTES * 60),    # 旧默认值也低于下限
        (30, 30 * 60),                                # 新默认值原样生效
        (120, 120 * 60),                              # 调大不受影响
    ],
)
def test_interval_is_clamped_to_a_floor(monkeypatch, configured, expected_seconds):
    _client, slept = _loop_client(
        monkeypatch, token_results=["T"], interval=configured,
    )
    assert slept, "循环必须先 sleep 再干活"
    assert set(slept) == {expected_seconds}


def test_floor_is_at_least_ten_minutes():
    """下限不能被改小到失去意义（参考实现的硬下限同样是 10 分钟）。"""
    assert gc.MIN_REFRESH_INTERVAL_MINUTES >= 10


def test_default_interval_is_not_minutes_level_noise():
    """默认值必须远离"每 5 分钟敲 Google 5 次"那个量级。"""
    from app.config import Settings

    assert Settings().refresh_interval >= 30


# ---------------------------------------------------------------------------
# 2. 降级阈值
# ---------------------------------------------------------------------------

def test_one_failed_probe_does_not_demote_a_healthy_account(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    client, _ = _loop_client(monkeypatch, token_results=[""])

    assert client.is_healthy is True, "一次抖动不该把健康账号踢出选号池"
    assert client._session_token == "GOOD-TOKEN", "也不该把手里那个可用的 token 丢掉"


def test_two_failed_probes_still_do_not_demote(monkeypatch):
    client, _ = _loop_client(monkeypatch, token_results=["", ""])

    assert client.is_healthy is True
    assert client._session_token == "GOOD-TOKEN"


def test_three_failed_probes_demote(monkeypatch):
    """连续到阈值才真的降级（与 _health_check_loop 的 3 次口径一致）。"""
    client, _ = _loop_client(monkeypatch, token_results=["", "", ""])

    assert client.is_healthy is False
    assert client._session_token == ""


def test_demotion_streak_matches_the_health_check_threshold():
    assert gc.REFRESH_UNHEALTHY_STREAK == 3


def test_a_success_resets_the_streak(monkeypatch):
    """失败两次、成功一次、再失败两次 —— 不许凑成 3 次把账号降级。"""
    client, _ = _loop_client(monkeypatch, token_results=["", "", "T-OK", "", ""])

    assert client.is_healthy is True
    assert client._session_token == "T-OK"


def test_successful_probe_marks_healthy(monkeypatch):
    """零回归：探活成功仍然把 client 标健康并换上新 token。"""
    client, _ = _loop_client(monkeypatch, token_results=["T-NEW"])

    assert client.is_healthy is True
    assert client._session_token == "T-NEW"


# ---------------------------------------------------------------------------
# 3. 面板不许把间隔设成 0
# ---------------------------------------------------------------------------

def test_panel_rejects_zero_refresh_interval():
    from app.core.settings_overrides import check_domain

    assert check_domain("refresh_interval", 0) is not None
    assert check_domain("refresh_interval", -5) is not None
    assert check_domain("refresh_interval", 1) is None

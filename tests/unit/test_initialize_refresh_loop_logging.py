"""启动必须无条件启动 PSIDTS 轮换循环，并把这件事写进日志（issue #11 的代码级根因）。

Google 的 `__Secure-1PSIDTS` 是小时级轮换的。旧实现里 `_ensure_refresh_task()` 只在
initialize() 拿不到 token 的 else 分支、以及 reload_cookies() 里被调用 —— 也就是说
「正常启动」的网关从来不跑 `_auto_refresh_loop`：启动时拿着一份好 cookie，几小时后
整池账号一起失效，只能人工换 cookie。参考实现在 Init 末尾无条件起这个循环
（refs/gemini-web-to-api internal/modules/providers/gemini_service.go:167-170）。

这里钉死三件事：两条分支都启动轮换循环、各自恰好打一句日志（不重复）、
以及 _healthy 的结果与原先一致（只改轮换的控制流，不改健康判定）。
"""

import asyncio
import logging

import pytest

from app.core import gemini_client as gc


class _DummySession:
    def __init__(self, *a, **kw):
        pass


def _client(monkeypatch, tmp_path, *, token: str) -> tuple[gc.GeminiWebClient, list]:
    """造一个把所有外部 I/O 都摘掉的 client，只留 initialize() 的分支逻辑。"""
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    monkeypatch.setattr(gc, "PersistentCookieJar", lambda psid: _DummyJar())

    client = gc.GeminiWebClient(psid="PSID", psidts="PSIDTS")

    async def _obtain():
        client._session_token = token

    async def _heartbeat():
        return None

    ensured = []
    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)

    # 只拦住"真的创建后台任务"这一步，_ensure_refresh_task 本体照跑 —— 它自己也会打一句
    # "Auto-refresh loop started"。以前这里把整个方法 stub 掉，于是测试看不见它的日志，
    # 生产上两句一起打（重复条目）也照样全绿。
    def _fake_create_task(coro, *a, **kw):
        coro.close()  # 别让协程留下 "never awaited" 警告
        return _DummyTask()

    monkeypatch.setattr(gc.asyncio, "create_task", _fake_create_task)

    real_ensure = client._ensure_refresh_task

    def _spy():
        ensured.append(True)
        return real_ensure()

    monkeypatch.setattr(client, "_ensure_refresh_task", _spy)
    return client, ensured


class _DummyTask:
    def done(self):
        return False

    def cancel(self):
        return None


class _DummyJar:
    def get_all(self):
        return {}

    def set(self, *a, **kw):
        return None

    def clear(self):
        return None


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


@pytest.fixture
def _caplog_info(caplog):
    caplog.set_level(logging.INFO, logger=gc.logger.name)
    return caplog


def test_healthy_startup_starts_the_rotation_loop(monkeypatch, tmp_path, _caplog_info):
    """正常启动（拿到 token）也必须启动轮换循环 —— 这正是 issue #11 的根因。"""
    client, ensured = _client(monkeypatch, tmp_path, token="SNlM0e-value")
    asyncio.run(client.initialize())

    msgs = _messages(_caplog_info)
    hits = [m for m in msgs if "Auto-refresh loop" in m]
    assert len(hits) == 1, f"启动必须恰好说一次轮换循环的状态，实际: {hits}"
    assert "started" in hits[0] and "NOT started" not in hits[0]

    assert ensured == [True], "拿到 token 的分支同样要启动轮换循环"
    assert client.is_healthy is True


def test_tokenless_startup_starts_the_loop_and_says_why(monkeypatch, tmp_path, _caplog_info):
    client, ensured = _client(monkeypatch, tmp_path, token="")
    asyncio.run(client.initialize())

    msgs = _messages(_caplog_info)
    hits = [m for m in msgs if "Auto-refresh loop" in m]
    assert len(hits) == 1, f"启动必须恰好说一次轮换循环的状态（不许重复），实际: {hits}"
    assert "NOT started" not in hits[0]
    assert "started" in hits[0]
    # 原因由紧挨着的上一条 warning 说清楚
    assert any("Token not found" in m for m in msgs), "还得说清楚 token 没拿到"

    assert ensured == [True]
    assert client.is_healthy is False


def test_both_branches_start_exactly_one_loop(monkeypatch, tmp_path, _caplog_info):
    """两条分支的轮换行为必须一致：都启动、都只打一句（避免 grep 出重复条目）。"""
    ok, ok_ensured = _client(monkeypatch, tmp_path, token="SNlM0e-value")
    asyncio.run(ok.initialize())
    healthy_hits = [m for m in _messages(_caplog_info) if "Auto-refresh loop" in m]

    _caplog_info.clear()
    bad, bad_ensured = _client(monkeypatch, tmp_path, token="")
    asyncio.run(bad.initialize())
    tokenless_hits = [m for m in _messages(_caplog_info) if "Auto-refresh loop" in m]

    assert ok_ensured == bad_ensured == [True]
    assert len(healthy_hits) == len(tokenless_hits) == 1

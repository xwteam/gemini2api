"""启动时的 Cookie 取舍（S3）与 Cookie 轮换的三态语义（S2）。

S3：配置里的 cookie（.env / accounts.json）必须优先于磁盘缓存。旧实现无条件偏向
    data/cookies/<hash>.json，于是"照文档改配置再重启"这个出事时最常用的恢复手法完全
    失效 —— 旧 PSIDTS 覆盖刚换上的新值，账号重启后依旧是过期的。
S2：Google 的 RotateCookies 在现有 PSIDTS 还有效时回 HTTP 200 但不下发新 Cookie，
    这不是失败。算成失败会①让面板的轮换成功率变成装饰品；②让 reload_cookies() 跳过
    第二次取 token，把一个重试就能救回的账号判死。
"""

import asyncio

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import RotationResult


class _DummySession:
    def __init__(self, *a, **kw):
        pass

    async def close(self):
        return None


class _Jar:
    """够用的假 Cookie 罐：记录每一次 set/clear，get_all 返回预置的"磁盘内容"。"""

    def __init__(self, disk: dict | None = None):
        self.disk = dict(disk or {})
        self.sets: list[tuple[str, str]] = []
        self.cleared = 0

    def get_all(self, domain: str = "google.com") -> dict:
        return dict(self.disk)

    def set(self, name, value, **kw):
        self.sets.append((name, value))
        self.disk[name] = value

    def clear(self):
        self.cleared += 1
        self.disk.clear()

    def update_from_response(self, resp):
        return None


def _init_client(monkeypatch, *, cfg_psid, cfg_psidts, disk):
    """跑一次 initialize()，所有外部 I/O 摘掉，只留 Cookie 取舍这一段逻辑。"""
    jar = _Jar(disk)
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    monkeypatch.setattr(gc, "PersistentCookieJar", lambda psid: jar)

    client = gc.GeminiWebClient(psid=cfg_psid, psidts=cfg_psidts)

    async def _obtain():
        client._session_token = "TOKEN"

    async def _heartbeat():
        return None

    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(client, "_ensure_refresh_task", lambda: None)

    asyncio.run(client.initialize())
    return client, jar


# ---------------------------------------------------------------------------
# S3：配置值优先于磁盘缓存
# ---------------------------------------------------------------------------

def test_new_config_psidts_beats_stale_disk_cache(monkeypatch):
    """改了 .env 的 PSIDTS 再重启：用的必须是新值，陈旧缓存必须被清掉。"""
    client, jar = _init_client(
        monkeypatch,
        cfg_psid="PSID-1",
        cfg_psidts="PSIDTS-NEW",
        disk={"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-OLD",
              "NID": "stale-session-cookie"},
    )

    assert client._psidts == "PSIDTS-NEW", "配置里的新 PSIDTS 不能被磁盘旧值覆盖"
    assert client._psid == "PSID-1"
    assert jar.cleared == 1, "陈旧缓存必须整份清掉（同批的会话 Cookie 也已失效）"
    assert ("__Secure-1PSIDTS", "PSIDTS-NEW") in jar.sets
    assert ("__Secure-1PSID", "PSID-1") in jar.sets
    assert "NID" not in jar.disk, "清缓存之后不该还留着旧会话的 Cookie"


def test_changed_config_psid_also_drops_the_cache(monkeypatch):
    """PSID 本身换了（换号）：缓存里上一个账号的 Cookie 一律不要。"""
    client, jar = _init_client(
        monkeypatch,
        cfg_psid="PSID-2",
        cfg_psidts="PSIDTS-2",
        disk={"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-1"},
    )

    assert client._psid == "PSID-2"
    assert client._psidts == "PSIDTS-2"
    assert jar.cleared == 1


def test_matching_config_and_cache_changes_nothing(monkeypatch):
    """零回归：配置与缓存一致时不清缓存、照旧回放磁盘值。"""
    client, jar = _init_client(
        monkeypatch,
        cfg_psid="PSID-1",
        cfg_psidts="PSIDTS-SAME",
        disk={"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-SAME"},
    )

    assert jar.cleared == 0
    assert client._psidts == "PSIDTS-SAME"
    assert jar.sets == [], "回放磁盘值的分支本来就不写 Cookie，不能多写"


def test_cache_still_supplies_psidts_when_config_has_none(monkeypatch):
    """零回归：配置只给了 PSID（PSIDTS 留空）时，仍然用缓存里的 PSIDTS。"""
    client, jar = _init_client(
        monkeypatch,
        cfg_psid="PSID-1",
        cfg_psidts="",
        disk={"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-FROM-DISK"},
    )

    assert jar.cleared == 0
    assert client._psidts == "PSIDTS-FROM-DISK"


def test_empty_cache_persists_the_configured_cookies(monkeypatch):
    """零回归：磁盘上什么都没有时，把配置值写进缓存。"""
    client, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-1", disk={},
    )

    assert jar.cleared == 0
    assert ("__Secure-1PSID", "PSID-1") in jar.sets
    assert ("__Secure-1PSIDTS", "PSIDTS-1") in jar.sets
    assert client._psidts == "PSIDTS-1"


# ---------------------------------------------------------------------------
# S2：轮换的三态语义
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, cookies=None, text=""):
        self.status_code = status_code
        self.cookies = dict(cookies or {})
        self.text = text


class _Rotations:
    """record_rotation 的调用记录。"""

    def __init__(self):
        self.calls: list[bool] = []

    def record_rotation(self, success: bool):
        self.calls.append(success)


def _rotate_client(monkeypatch, resp):
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._psidts = "PSIDTS-OLD"
    from threading import Lock

    client._lock = Lock()
    client._cookie_jar = _Jar()

    class _Http:
        async def post(self, *a, **kw):
            return resp

    client._http = _Http()

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(gc, "apply_jitter", _noop)
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_clear_session_cookies", lambda: None)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})

    rots = _Rotations()
    monkeypatch.setattr(gc, "live_metrics", rots)
    return client, rots


def test_http200_without_new_psidts_is_not_a_failure(monkeypatch):
    """200 但没下发新 PSIDTS：现有 Cookie 还有效 → STILL_VALID、真值、不计失败。"""
    client, rots = _rotate_client(monkeypatch, _Resp(200, cookies={}, text="[]"))

    result = asyncio.run(client._rotate_cookies())

    assert result is RotationResult.STILL_VALID
    assert bool(result) is True, "调用方的 `if rotated:` 必须继续往下走"
    assert rots.calls == [], "既不算成功也不算失败，否则面板的轮换成功率是假的"
    assert client._psidts == "PSIDTS-OLD"


def test_http200_with_new_psidts_renews(monkeypatch):
    client, rots = _rotate_client(
        monkeypatch, _Resp(200, cookies={"__Secure-1PSIDTS": "PSIDTS-NEW"}),
    )

    result = asyncio.run(client._rotate_cookies())

    assert result is RotationResult.RENEWED
    assert bool(result) is True
    assert client._psidts == "PSIDTS-NEW"
    assert ("__Secure-1PSIDTS", "PSIDTS-NEW") in client._cookie_jar.sets
    assert rots.calls == [True]


def test_non_200_is_a_real_failure(monkeypatch):
    client, rots = _rotate_client(monkeypatch, _Resp(401))

    result = asyncio.run(client._rotate_cookies())

    assert result is RotationResult.FAILED
    assert bool(result) is False
    assert rots.calls == [False]


@pytest.mark.parametrize(
    "rotation,expect_success",
    [
        (RotationResult.STILL_VALID, True),
        (RotationResult.RENEWED, True),
        (RotationResult.FAILED, False),
    ],
)
def test_reload_cookies_retries_token_unless_rotation_really_failed(
    monkeypatch, rotation, expect_success
):
    """reload_cookies 的第二次取 token：只有真失败才跳过。

    「200 无新值」被算成失败时，这里会直接判死账号并进冷却 —— 而第二次取 token 本来就能
    救回它（第一次失败往往只是 session cookie 脏了，RotateCookies 已经把它洗干净）。
    """
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    client = gc.GeminiWebClient(psid="p", psidts="t")
    client._cookie_jar = _Jar()
    client._http = _DummySession()
    client._session_token = "GOOD"
    client._healthy = True

    attempts = []

    async def _obtain():
        attempts.append(True)
        # 第一次拿不到（会话脏了），第二次（轮换之后）拿到
        client._session_token = "NEW-TOKEN" if len(attempts) > 1 else ""
        if not client._session_token:
            client._last_reload_error = "SNlM0e token not found"

    async def _rotate():
        return rotation

    async def _heartbeat():
        return None

    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_rotate_cookies", _rotate)
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(client, "_ensure_refresh_task", lambda: None)

    result = asyncio.run(client.reload_cookies())

    assert result["success"] is expect_success
    assert len(attempts) == (2 if expect_success else 1)

"""启动时的 Cookie 取舍（S3）与 Cookie 轮换的三态语义（S2）。

S3：**配置真的变了**才优先于磁盘缓存。两个方向都得对：
    - 配置变新（运维照文档改 .env / accounts.json 再重启，出事时最常用的恢复手法）：
      旧实现无条件偏向 data/cookies/<hash>.json，旧 PSIDTS 覆盖刚换上的新值，白改；
    - 缓存变新（轮换循环或面板「更新 cookie」写进磁盘，二者都不回写配置）：只比较
      "配置值 != 缓存值"又会每次重启都把这份新值当"陈旧缓存"丢掉，账号重启即死。
    所以启动时把"这一次生效的配置值"也存进罐子，比的是配置值自己变没变。
    另外：启动取不到 token 时就地轮换重试一次，不再空等一个刷新周期。
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
    """够用的假 Cookie 罐：记录每一次 set/clear，get_all 返回预置的"磁盘内容"。

    get_all 必须像真罐子一样按域过滤（真实现是
    `domain in cookie.domain or cookie.domain.endswith(domain)`）：启动时存的"上一次
    生效的配置值"快照挂在一个非 google 域上，它绝不能出现在发往上游的 Cookie 里。
    """

    def __init__(self, disk: dict | None = None):
        self.disk = dict(disk or {})
        self.domains: dict[str, str] = {k: ".google.com" for k in self.disk}
        self.sets: list[tuple[str, str]] = []
        self.cleared = 0
        self.removed: list[str] = []

    def get_all(self, domain: str = "google.com") -> dict:
        return {
            k: v for k, v in self.disk.items()
            if domain in self.domains.get(k, ".google.com")
            or self.domains.get(k, ".google.com").endswith(domain)
        }

    def get(self, name):
        return self.disk.get(name)

    def set(self, name, value, **kw):
        self.sets.append((name, value))
        self.disk[name] = value
        self.domains[name] = kw.get("domain", ".google.com")

    def remove(self, name):
        self.removed.append(name)
        self.disk.pop(name, None)
        self.domains.pop(name, None)

    def clear(self):
        self.cleared += 1
        self.disk.clear()
        self.domains.clear()

    def update_from_response(self, resp):
        return None


def _init_client(monkeypatch, *, cfg_psid, cfg_psidts, disk, jar=None):
    """跑一次 initialize()，所有外部 I/O 摘掉，只留 Cookie 取舍这一段逻辑。

    传入 jar 可以复用同一个"磁盘"连跑两次启动（重启场景）。
    """
    jar = jar if jar is not None else _Jar(disk)
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

    async def _rotate():
        return RotationResult.STILL_VALID

    monkeypatch.setattr(client, "_rotate_cookies", _rotate)

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
    cookie_sets = [kv for kv in jar.sets if kv[0].startswith("__Secure")]
    assert cookie_sets == [], "回放磁盘值的分支本来就不重写 Cookie，不能多写"


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


def test_rotated_disk_psidts_survives_a_restart(monkeypatch):
    """配置一个字没改、磁盘上的 PSIDTS 被轮换换过：重启必须用磁盘上那个**新**值。

    这是"配置值优先"最容易伤到人的方向：PSIDTS 是小时级轮换的，轮换循环只把新值写进
    data/cookies/<hash>.json，从不回写 .env / accounts.json。于是凡是在配置里钉了
    PSIDTS 的部署，每次重启（升级、加账号、改配置）都会把累积的轮换成果退回当初那份
    早已失效的值 —— 账号重启即死，而唯一的日志把那份新值叫作"陈旧缓存"。
    """
    jar = _Jar({"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-AT-SETUP"})

    # 第一次启动：配置值 = 当初填进 .env 的那份
    first, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-AT-SETUP", disk=None, jar=jar,
    )
    assert first._psidts == "PSIDTS-AT-SETUP"

    # 跑了一小时，轮换循环把新值写进磁盘（jar 就是"磁盘"）
    jar.set("__Secure-1PSIDTS", "PSIDTS-ROTATED-FRESH")
    jar.sets.clear()

    # 第二次启动：.env 没动，仍然是 PSIDTS-AT-SETUP
    second, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-AT-SETUP", disk=None, jar=jar,
    )

    assert second._psidts == "PSIDTS-ROTATED-FRESH", "轮换来的新 PSIDTS 不能被配置里的旧值顶掉"
    assert jar.cleared == 0, "配置没变就不该清缓存"
    assert jar.disk["__Secure-1PSIDTS"] == "PSIDTS-ROTATED-FRESH"


def test_config_change_after_a_rotation_still_wins(monkeypatch):
    """运维真的改了 .env（出事时最常用的恢复手法）：即便磁盘上有更新的轮换值，也以配置为准。"""
    jar = _Jar({"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-AT-SETUP"})
    _init_client(monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-AT-SETUP",
                 disk=None, jar=jar)
    jar.set("__Secure-1PSIDTS", "PSIDTS-ROTATED")
    jar.set("NID", "stale-session-cookie")

    client, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-HAND-REPLACED", disk=None, jar=jar,
    )

    assert client._psidts == "PSIDTS-HAND-REPLACED"
    assert jar.cleared == 1, "配置真的变了：陈旧缓存整份清掉"
    assert "NID" not in jar.disk


def test_panel_updated_cookie_survives_a_restart(monkeypatch):
    """面板「更新 cookie」只改运行态 + 磁盘缓存，不回写配置 —— 它也不能被重启吞掉。"""
    jar = _Jar({"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-OLD"})
    _init_client(monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-OLD", disk=None, jar=jar)

    # 面板换上新 cookie（reload_cookies 的效果：写运行态 + 写磁盘）
    jar.set("__Secure-1PSID", "PSID-1")
    jar.set("__Secure-1PSIDTS", "PSIDTS-FROM-PANEL")

    client, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-OLD", disk=None, jar=jar,
    )

    assert client._psidts == "PSIDTS-FROM-PANEL"
    assert jar.cleared == 0


def test_legacy_cache_without_a_snapshot_keeps_the_old_precedence(monkeypatch):
    """升级的第一次启动（缓存里还没有配置快照）：沿用旧口径，配置值优先。只会发生一次。"""
    client, jar = _init_client(
        monkeypatch,
        cfg_psid="PSID-1",
        cfg_psidts="PSIDTS-FROM-ENV",
        disk={"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-IN-LEGACY-CACHE"},
    )

    assert client._psidts == "PSIDTS-FROM-ENV"
    assert jar.cleared == 1
    # 快照已经写进去了，下一次启动就能分辨方向
    assert jar.get("__cfg-1PSIDTS") == "PSIDTS-FROM-ENV"


def test_config_snapshot_is_never_sent_upstream(monkeypatch):
    """快照借 Cookie 罐当持久化载体，但它不是 Cookie：绝不能出现在发往 Google 的集合里。"""
    _client, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-1", disk={},
    )

    assert jar.get("__cfg-1PSIDTS") == "PSIDTS-1"
    assert "__cfg-1PSIDTS" not in jar.get_all()
    assert "__cfg-1PSIDTS" not in jar.get_all("google.com")


def test_clearing_psidts_from_config_drops_the_snapshot(monkeypatch):
    """配置里的 PSIDTS 被清空：快照也要撤掉，否则"重新填上"会被误判成没变。"""
    jar = _Jar({"__Secure-1PSID": "PSID-1", "__Secure-1PSIDTS": "PSIDTS-1"})
    _init_client(monkeypatch, cfg_psid="PSID-1", cfg_psidts="PSIDTS-1", disk=None, jar=jar)
    assert jar.get("__cfg-1PSIDTS") == "PSIDTS-1"

    _client, jar = _init_client(
        monkeypatch, cfg_psid="PSID-1", cfg_psidts="", disk=None, jar=jar,
    )

    assert jar.get("__cfg-1PSIDTS") is None
    assert "__cfg-1PSIDTS" in jar.removed


def test_startup_without_a_token_rotates_in_place_and_retries(monkeypatch):
    """启动取不到 token：就地轮换一次再重取，不许空等一个刷新周期。

    参考实现在 Init 里就有这一步（refs/gemini-web-to-api gemini_service.go:147-157）。
    过去我们只打一句 "Token not found, rotating cookies" 就把它交给 _auto_refresh_loop，
    而那个循环第一行就是 sleep(refresh_interval)：整池空窗一个周期，期间每个请求都是 503，
    账号则早已被 _init_account_client 标成 EXPIRED。
    """
    jar = _Jar({})
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    monkeypatch.setattr(gc, "PersistentCookieJar", lambda psid: jar)

    client = gc.GeminiWebClient(psid="PSID-1", psidts="PSIDTS-1")
    attempts = []
    rotations = []

    async def _obtain():
        attempts.append(True)
        # 第一次拿不到（会话 Cookie 脏了），轮换之后第二次拿到
        client._session_token = "TOKEN" if len(attempts) > 1 else ""

    async def _rotate():
        rotations.append(True)
        return RotationResult.RENEWED

    async def _heartbeat():
        return None

    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_rotate_cookies", _rotate)
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(client, "_ensure_refresh_task", lambda: None)

    asyncio.run(client.initialize())

    assert rotations == [True], "必须就地轮换一次"
    assert len(attempts) == 2, "轮换之后必须再取一次 token"
    assert client.is_healthy is True


def test_startup_does_not_rotate_when_the_token_is_fine(monkeypatch):
    """零回归：启动就拿到 token 时不许多打一次 RotateCookies。"""
    jar = _Jar({})
    monkeypatch.setattr(gc, "AsyncSession", _DummySession)
    monkeypatch.setattr(gc.fingerprint_config, "load", lambda: None)
    monkeypatch.setattr(gc.header_builder, "get_impersonate_target", lambda: "chrome120")
    monkeypatch.setattr(gc.settings, "health_check_enabled", False)
    monkeypatch.setattr(gc, "PersistentCookieJar", lambda psid: jar)

    client = gc.GeminiWebClient(psid="PSID-1", psidts="PSIDTS-1")
    rotations = []

    async def _obtain():
        client._session_token = "TOKEN"

    async def _rotate():
        rotations.append(True)
        return RotationResult.RENEWED

    async def _heartbeat():
        return None

    monkeypatch.setattr(client, "_obtain_session_token", _obtain)
    monkeypatch.setattr(client, "_rotate_cookies", _rotate)
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)
    monkeypatch.setattr(client, "_ensure_refresh_task", lambda: None)

    asyncio.run(client.initialize())

    assert rotations == []
    assert client.is_healthy is True


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

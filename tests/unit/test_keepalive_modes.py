"""每个账号「由谁保活」的持久化记录（data/keepalive-modes.json）。

浏览器和服务端共用同一个谷歌会话：两边各自调 RotateCookies 时，后一方拿着被对方换掉的
旧 PSIDTS 去换就 401、整个会话被踢下线（线上：服务端独自轮换 3 天零失败，浏览器一回来
当晚就开始 401）。所以插件推过来的账号要记成 browser、服务端从此不再轮换它 —— 这份记录
就是那个开关，它必须：
- 键 = sha256(PSID)[:16]（与 data/cookies/<hash>.json 同一算法），文件里不出现任何 cookie 值；
- 原子写、线程安全；读到坏文件不崩（当作空 = 全部 server）；
- 默认 server。
"""

import hashlib
import json
import threading
import time

import pytest
from starlette.datastructures import Headers

from app.core import keepalive_modes as km
from app.core.fingerprint.cookie_jar import PersistentCookieJar

PSID = "g.a000-test-psid-value-that-is-a-secret"
OTHER_PSID = "g.a000-another-account-psid"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把默认路径换到临时目录：client / 路由走的都是 path=None 这条默认路径。"""
    path = tmp_path / "data" / "keepalive-modes.json"
    monkeypatch.setattr(km, "MODES_PATH", path)
    return path


def _key(psid: str) -> str:
    return hashlib.sha256(psid.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# 读写语义
# --------------------------------------------------------------------------

def test_default_is_server_and_reading_creates_nothing(store):
    assert km.get_mode(PSID) == "server"
    assert not store.exists(), "只读查询不该在磁盘上留下任何东西"
    assert not store.parent.exists()


def test_roundtrip(store):
    assert km.set_mode(PSID, "browser") is True
    assert km.get_mode(PSID) == "browser"

    assert km.set_mode(PSID, "server") is True
    assert km.get_mode(PSID) == "server"


def test_other_accounts_are_preserved(store):
    km.set_mode(PSID, "browser")
    km.set_mode(OTHER_PSID, "server")

    assert km.get_mode(PSID) == "browser"
    assert km.get_mode(OTHER_PSID) == "server"
    assert set(json.loads(store.read_text(encoding="utf-8"))) == {_key(PSID), _key(OTHER_PSID)}


def test_explicit_path_argument_is_honoured(tmp_path, store):
    elsewhere = tmp_path / "elsewhere.json"
    km.set_mode(PSID, "browser", path=elsewhere)

    assert km.get_mode(PSID, path=elsewhere) == "browser"
    assert km.get_mode(PSID) == "server", "默认路径那份记录不该被写到"
    assert not store.exists()


def test_external_edit_is_picked_up_without_a_restart(store):
    """不许有陈旧的内存副本：运维手改文件（或别的写入方）之后，下一次查询就得看到。"""
    km.set_mode(PSID, "browser")
    assert km.get_mode(PSID) == "browser"

    store.write_text(json.dumps({_key(PSID): {"mode": "server", "updated_at": ""}}), encoding="utf-8")

    assert km.get_mode(PSID) == "server"


@pytest.mark.parametrize("psid", ["", None])
def test_missing_psid_is_server_and_cannot_be_recorded(store, psid):
    assert km.get_mode(psid) == "server"
    assert km.set_mode(psid, "browser") is False
    assert not store.exists()


def test_unknown_mode_is_rejected_without_writing(store):
    assert km.set_mode(PSID, "both") is False
    assert not store.exists()
    assert km.get_mode(PSID) == "server"


# --------------------------------------------------------------------------
# 键与内容：只有 PSID 的哈希，绝无 cookie 值
# --------------------------------------------------------------------------

def test_key_is_the_sha256_prefix_of_the_psid(store):
    km.set_mode(PSID, "browser")

    data = json.loads(store.read_text(encoding="utf-8"))
    assert list(data) == [_key(PSID)]
    assert km.psid_key(PSID) == _key(PSID)


def test_a_psid_that_is_not_valid_utf8_never_raises(store):
    """管理接口收的是 JSON，"\\ud800" 这种孤立代理项能原样进到 PSID 里。闸口在轮换热路径上，
    查记录绝不能因此抛异常（否则一次本该失败的 reload 会变成 500）。"""
    weird = "g.a000\ud800broken"

    assert km.get_mode(weird) == "server"
    assert km.set_mode(weird, "browser") is True
    assert km.get_mode(weird) == "browser"
    assert km.psid_key(PSID) == _key(PSID), "正常 PSID 的哈希不能因此改变"


def test_key_is_the_same_digest_as_the_cookie_cache_file_name():
    """与 data/cookies/<hash>.json 同一算法 —— 运维能把两份文件对上号。"""
    jar = PersistentCookieJar.__new__(PersistentCookieJar)  # 不跑 __init__：不碰真实磁盘
    jar._account_id = PSID
    assert km.psid_key(PSID) == jar._store_path().stem


def test_file_never_contains_cookie_values(store):
    km.set_mode(PSID, "browser")
    km.set_mode(OTHER_PSID, "server")

    raw = store.read_text(encoding="utf-8")
    assert PSID not in raw and OTHER_PSID not in raw
    for entry in json.loads(raw).values():
        assert set(entry) == {"mode", "updated_at"}, f"记录里多了不该有的字段: {entry}"


def test_updated_at_is_iso8601_utc(store):
    from datetime import datetime, timezone

    before = datetime.now(timezone.utc).replace(microsecond=0)
    km.set_mode(PSID, "browser")
    stamp = json.loads(store.read_text(encoding="utf-8"))[_key(PSID)]["updated_at"]

    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
    assert before <= parsed <= datetime.now(timezone.utc)


def test_a_hand_written_raw_psid_key_is_neither_honoured_nor_written_back(store):
    """有人把明文 PSID 当键手写进文件：不认（键只认哈希），下一次写入时把它清掉。"""
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({PSID: {"mode": "browser", "updated_at": ""}}), encoding="utf-8")

    assert km.get_mode(PSID) == "server"

    km.set_mode(OTHER_PSID, "browser")
    raw = store.read_text(encoding="utf-8")
    assert PSID not in raw


# --------------------------------------------------------------------------
# 坏文件：当作空，绝不崩
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"",
        b"[1, 2, 3]",
        b'"browser"',
        b"\xff\xfe\x00garbage",  # 连 UTF-8 都不是
    ],
)
def test_corrupt_file_reads_as_empty(store, content):
    store.parent.mkdir(parents=True)
    store.write_bytes(content)

    assert km.get_mode(PSID) == "server"
    # 坏文件不挡后续写入：写出来的是一份合法、只含新记录的文件
    assert km.set_mode(PSID, "browser") is True
    data = json.loads(store.read_text(encoding="utf-8"))
    assert list(data) == [_key(PSID)]
    assert data[_key(PSID)]["mode"] == "browser"


def test_bad_entries_are_ignored_individually(store):
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({
        _key(PSID): {"mode": "browser", "updated_at": "2026-10-26T00:00:00+00:00"},
        _key(OTHER_PSID): {"mode": "weird"},
        _key("third"): "browser",
    }), encoding="utf-8")

    assert km.get_mode(PSID) == "browser"
    assert km.get_mode(OTHER_PSID) == "server"
    assert km.get_mode("third") == "server"


# --------------------------------------------------------------------------
# 原子写 + 线程安全
# --------------------------------------------------------------------------

def test_a_failed_replace_leaves_the_previous_file_intact(store, monkeypatch):
    """原子写：替换那一步失败（磁盘满 / 断电的近似），旧文件原样、不留临时文件、调用方不炸。"""
    km.set_mode(PSID, "browser")
    before = store.read_text(encoding="utf-8")

    import app.utils.atomic_io as atomic_io

    def _boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_io.os, "replace", _boom)

    assert km.set_mode(OTHER_PSID, "browser") is False
    assert store.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in store.parent.iterdir()) == [store.name], "留下了临时文件"
    assert km.get_mode(PSID) == "browser"


def test_concurrent_writers_do_not_lose_updates(store, monkeypatch):
    """读-改-写必须整段持锁：否则两个并发写入各自读到旧内容，后写的把先写的覆盖掉。"""
    real_write = km.atomic_write_json

    def _slow_write(*a, **kw):
        time.sleep(0.02)  # 把竞态窗口撑大，没锁时几乎必丢
        return real_write(*a, **kw)

    monkeypatch.setattr(km, "atomic_write_json", _slow_write)

    psids = [f"g.a000-concurrent-{i}" for i in range(8)]
    barrier = threading.Barrier(len(psids))
    results = []

    def _worker(p):
        barrier.wait()
        results.append(km.set_mode(p, "browser"))

    threads = [threading.Thread(target=_worker, args=(p,)) for p in psids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results == [True] * len(psids)
    data = json.loads(store.read_text(encoding="utf-8"))
    assert set(data) == {_key(p) for p in psids}, "并发写入丢了记录"


# --------------------------------------------------------------------------
# 判定来源（只看请求头；何时写由路由决定：reload 成功之后）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"X-Gemini2API-Keepalive": "gemini2api-plugin/1.3.0"}, "browser"),
        ({"x-gemini2api-keepalive": "gemini2api-plugin/1.3.0"}, "browser"),
        # 头存在就算（值形如 gemini2api-plugin/1.3.0，但不按值判）
        ({"X-Gemini2API-Keepalive": "anything"}, "browser"),
        # 兼容现有 v1.2.3 插件：不带新头，只能靠扩展发起请求时浏览器带上的 Origin
        ({"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}, "browser"),
        ({"origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}, "browser"),
        # 新头优先：哪怕 Origin 是普通网页
        ({"X-Gemini2API-Keepalive": "gemini2api-plugin/1.3.0", "Origin": "http://127.0.0.1:5918"},
         "browser"),
        # 面板手动「更新 Cookie」（同源页面）、脚本调用 → server
        ({"Origin": "http://127.0.0.1:5918"}, "server"),
        ({"Origin": "https://gateway.example.com"}, "server"),
        ({}, "server"),
        ({"User-Agent": "curl/8.5.0"}, "server"),
        # 只认前缀，不认子串
        ({"Origin": "https://evil.example/chrome-extension://x"}, "server"),
    ],
)
def test_mode_from_headers(headers, expected):
    assert km.mode_from_headers(headers) == expected


def test_mode_from_headers_accepts_starlette_headers():
    raw = [(b"origin", b"chrome-extension://abc"), (b"content-type", b"application/json")]
    assert km.mode_from_headers(Headers(raw=raw)) == "browser"
    assert km.mode_from_headers(Headers(raw=[(b"origin", b"http://localhost:5918")])) == "server"

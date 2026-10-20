"""AccessKeyStore 的判定/计数/持久化/加载容错。

这些用例都断言**行为结果**（判定状态、计数值、落盘后重新加载的内容），不断言源码字面量。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.access_key_store import (
    AccessKeyStore,
    STATE_DISABLED,
    STATE_EXPIRED,
    STATE_NOT_FOUND,
    STATE_QUOTA_EXCEEDED,
    STATE_VALID,
    generate_access_key,
)


def _store(tmp_path, name="access_keys.json") -> AccessKeyStore:
    return AccessKeyStore(file_path=str(tmp_path / name))


def _now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------- 生成

def test_generated_key_shape_is_unique_and_prefixed():
    keys = {generate_access_key() for _ in range(50)}
    assert len(keys) == 50, "随机密钥撞了，熵不够"
    for k in keys:
        assert k.startswith("sk-")
        assert len(k) == 35
        assert k[3:].isalnum()


# ----------------------------------------------------------------- 四态判定

def test_four_states(tmp_path):
    store = _store(tmp_path)
    ok = store.create("ok")
    off = store.create("off")
    store.update(off.id, enabled=False)
    gone = store.create("gone", expires_at="2025-01-01T00:00:00+00:00")
    full = store.create("full", request_limit=1)

    assert store.validate("sk-nope", _now())[0] == STATE_NOT_FOUND
    assert store.validate(ok.key, _now())[0] == STATE_VALID
    assert store.validate(off.key, _now())[0] == STATE_DISABLED
    assert store.validate(gone.key, _now())[0] == STATE_EXPIRED

    assert store.validate_and_consume(full.key, _now())[0] == STATE_VALID
    assert store.validate(full.key, _now())[0] == STATE_QUOTA_EXCEEDED


def test_empty_provided_key_is_not_found(tmp_path):
    store = _store(tmp_path)
    store.create("x")
    assert store.validate("", _now())[0] == STATE_NOT_FOUND
    assert store.validate(None, _now())[0] == STATE_NOT_FOUND


def test_disabled_takes_precedence_over_quota(tmp_path):
    """停用是最终状态：既超额又被停用时必须报 disabled，别让运维以为重置用量就能恢复。"""
    store = _store(tmp_path)
    key = store.create("k", request_limit=1)
    store.validate_and_consume(key.key, _now())
    store.update(key.id, enabled=False)
    assert store.validate(key.key, _now())[0] == STATE_DISABLED


# ----------------------------------------------------------------- 惰性激活

def test_lazy_activation_sets_activated_and_expiry_on_first_use(tmp_path):
    store = _store(tmp_path)
    key = store.create("lazy", duration_days=1)
    assert key.activated_at is None
    assert key.expires_at is None

    t0 = _now()
    state, entry = store.validate_and_consume(key.key, t0)
    assert state == STATE_VALID
    assert entry.activated_at is not None, "首次使用必须落下 activated_at"
    assert entry.expires_at is not None, "首次使用必须据 duration_days 算出 expires_at"

    # 激活后 23 小时仍有效，25 小时后过期
    assert store.validate(key.key, t0 + timedelta(hours=23))[0] == STATE_VALID
    assert store.validate(key.key, t0 + timedelta(hours=25))[0] == STATE_EXPIRED


def test_lazy_activation_does_not_restart_on_second_use(tmp_path):
    """第二次使用不得刷新 activated_at，否则天天用的 key 永远不会过期。"""
    store = _store(tmp_path)
    key = store.create("lazy", duration_days=1)
    t0 = _now()
    _, first = store.validate_and_consume(key.key, t0)
    _, second = store.validate_and_consume(key.key, t0 + timedelta(hours=10))
    assert second.activated_at == first.activated_at
    assert second.expires_at == first.expires_at


def test_key_without_duration_stays_valid_forever(tmp_path):
    store = _store(tmp_path)
    key = store.create("forever")
    t0 = _now()
    store.validate_and_consume(key.key, t0)
    assert store.validate(key.key, t0 + timedelta(days=4000))[0] == STATE_VALID


# ----------------------------------------------------------------- 请求上限

def test_request_limit_blocks_then_reset_restores(tmp_path):
    store = _store(tmp_path)
    key = store.create("quota", request_limit=3)
    for _ in range(3):
        assert store.validate_and_consume(key.key, _now())[0] == STATE_VALID
    assert store.validate_and_consume(key.key, _now())[0] == STATE_QUOTA_EXCEEDED
    assert store.get(key.id).request_count == 3, "被拒的那次不得计数"

    store.reset_usage(key.id)
    assert store.get(key.id).request_count == 0
    assert store.validate_and_consume(key.key, _now())[0] == STATE_VALID


def test_request_limit_zero_is_rejected_like_duration_zero(tmp_path):
    """0 不是"不限"（不限 = 留空）。接受 0 只会产出一把签发即超额的废密钥，
    而管理员把 0 当成"无限制"填进来的概率远高于真想要这个结果。
    两个额度字段的口径必须一致：duration_days=0 本来就是 400。"""
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.create("zero", request_limit=0)
    with pytest.raises(ValueError):
        store.create("neg", request_limit=-1)
    with pytest.raises(ValueError):
        store.create("d0", duration_days=0)
    assert store.list_keys() == [], "被拒的签发不得留下半条记录"

    key = store.create("unlimited")
    assert key.request_limit is None
    assert store.validate_and_consume(key.key, _now())[0] == STATE_VALID


def test_consume_increments_and_stamps_last_used(tmp_path):
    store = _store(tmp_path)
    key = store.create("c")
    assert store.consume(key.id, _now()) is True
    entry = store.get(key.id)
    assert entry.request_count == 1
    assert entry.last_used_at is not None
    assert store.consume(99999) is False


# --------------------------------------------------------------- 并发安全性

def test_concurrent_validate_never_exceeds_request_limit(tmp_path):
    """check-then-act 竞态守卫：N 个线程同时打一把上限 limit 的 key，
    放行次数必须恰好等于 limit（既不多也不少）。"""
    import threading

    limit = 20
    store = _store(tmp_path)
    key = store.create("race", request_limit=limit)

    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(40)

    def worker():
        barrier.wait()
        state, _ = store.validate_and_consume(key.key, _now())
        with lock:
            results.append(state)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    allowed = results.count(STATE_VALID)
    assert allowed == limit, f"放行 {allowed} 次，上限是 {limit}"
    assert results.count(STATE_QUOTA_EXCEEDED) == 40 - limit
    assert store.get(key.id).request_count == limit


class _YieldingLock:
    """每次离开临界区就把 CPU 让给别的线程，制造确定性的交错。

    上面那条 Barrier 版用例依赖真实调度去撞竞态，窗口只有几微秒，check-then-act 的实现
    也能侥幸全绿（实测如此）。这个包装把"锁一放开就让别人插队"变成必然事件：
    - 判定与计数在**同一个**临界区里 → 让出时计数已经写回，后来者看到的是新值，不会超发
    - 判定与计数分成**两个**临界区 → 让出时计数还是旧值，所有线程都判"还有额度"，必然超发
    """

    def __init__(self, inner):
        self._inner = inner

    def __enter__(self):
        self._inner.acquire()
        return self

    def __exit__(self, *exc):
        self._inner.release()
        import time
        time.sleep(0.002)
        return False


def test_validate_and_consume_is_a_single_critical_section(tmp_path):
    """确定性竞态守卫：判定（含配额比较）与计数 +1 必须原子完成。"""
    import threading

    limit = 3
    store = _store(tmp_path)
    key = store.create("race2", request_limit=limit)
    store._lock = _YieldingLock(store._lock)

    results = []
    collect = threading.Lock()
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        state, _ = store.validate_and_consume(key.key, _now())
        with collect:
            results.append(state)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    allowed = results.count(STATE_VALID)
    assert allowed == limit, f"放行 {allowed} 次，上限是 {limit}（判定与计数不是一个临界区）"


# ------------------------------------------------------------------- CRUD

def test_ids_increment_and_are_not_recycled(tmp_path):
    store = _store(tmp_path)
    a = store.create("a")
    b = store.create("b")
    assert (a.id, b.id) == (1, 2)
    store.delete(a.id)
    c = store.create("c")
    assert c.id == 3, "删除后的 id 不得回收（会让旧日志/用量对不上人）"


def test_update_rejects_unknown_field_and_missing_id(tmp_path):
    store = _store(tmp_path)
    key = store.create("u")
    with pytest.raises(ValueError):
        store.update(key.id, request_count=99)
    assert store.update(4242, name="x") is None
    assert store.delete(4242) is False
    assert store.reset_usage(4242) is None


def test_update_clears_and_sets_scopes(tmp_path):
    store = _store(tmp_path)
    key = store.create("s", bound_account_ids=["account-0"], allowed_models=["gemini-3-pro"])
    assert store.get(key.id).bound_account_ids == ["account-0"]
    updated = store.update(key.id, bound_account_ids=None, allowed_models=[])
    assert updated.bound_account_ids is None
    assert updated.allowed_models is None, "空列表等于不限制，不能留下一个空列表"


def test_empty_name_falls_back_to_key_id(tmp_path):
    store = _store(tmp_path)
    key = store.create("")
    assert key.display_name == f"key-{key.id}"


def test_snapshot_is_a_copy(tmp_path):
    """返回的是快照：调用方改它不得影响库里的真实状态。"""
    store = _store(tmp_path)
    key = store.create("snap", request_limit=5)
    snap = store.get(key.id)
    snap.request_count = 999
    snap.enabled = False
    assert store.get(key.id).request_count == 0
    assert store.validate(key.key, _now())[0] == STATE_VALID


# ---------------------------------------------------------------- 持久化

def test_create_persists_immediately_and_survives_reload(tmp_path):
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    key = store.create("persist", request_limit=9, bound_account_ids=["account-1"])
    assert path.exists(), "签发必须立即落盘（重启丢 key 不可接受）"

    reloaded = AccessKeyStore(file_path=str(path))
    entry = reloaded.get(key.id)
    assert entry is not None
    assert entry.key == key.key
    assert entry.request_limit == 9
    assert entry.bound_account_ids == ["account-1"]
    assert reloaded.validate(key.key, _now())[0] == STATE_VALID


def test_usage_counter_survives_restart_after_flush(tmp_path):
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    key = store.create("count")
    for _ in range(4):
        store.validate_and_consume(key.key, _now())
    # 用量只打脏标记，由定时 flush 落盘
    store.flush()

    reloaded = AccessKeyStore(file_path=str(path))
    assert reloaded.get(key.id).request_count == 4
    assert reloaded.get(key.id).activated_at is not None


def test_flush_is_a_noop_when_not_dirty(tmp_path):
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    store.create("x")
    before = path.stat().st_mtime_ns
    store.flush()
    assert path.stat().st_mtime_ns == before, "没脏还重写文件 = 白糟蹋磁盘"


def test_no_file_is_created_when_nothing_was_issued(tmp_path):
    """零回归：一把访问密钥都没签发时，data/ 下不该多出文件。"""
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    store.flush()
    assert not path.exists()
    assert store.has_keys() is False


def test_next_id_survives_restart_even_after_deleting_all(tmp_path):
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    first = store.create("a")
    store.create("b")
    store.delete(first.id)
    store.delete(2)

    reloaded = AccessKeyStore(file_path=str(path))
    assert reloaded.create("c").id == 3


# ------------------------------------------------------------ 加载容错

def test_corrupt_file_starts_empty_without_raising(tmp_path, caplog):
    path = tmp_path / "access_keys.json"
    path.write_text("{ this is not json", encoding="utf-8")
    store = AccessKeyStore(file_path=str(path))  # 绝不抛，否则进程起不来
    assert store.list_keys() == []
    assert store.has_keys() is False
    # 库被当空的，但新签发仍然可用
    assert store.create("fresh").id == 1


def test_unexpected_toplevel_shape_starts_empty(tmp_path):
    path = tmp_path / "access_keys.json"
    path.write_text('"just a string"', encoding="utf-8")
    assert AccessKeyStore(file_path=str(path)).list_keys() == []


def test_single_corrupt_entry_is_skipped_and_others_kept(tmp_path):
    path = tmp_path / "access_keys.json"
    path.write_text(json.dumps({
        "next_id": 9,
        "keys": [
            {"id": 1, "key": "sk-good1", "name": "good1"},
            "not an object",
            {"id": 2, "name": "missing key field"},
            {"id": 3, "key": "sk-good2", "name": "good2", "request_count": 7},
            {"id": 4, "key": "sk-bad", "request_limit": "not a number"},
        ],
    }), encoding="utf-8")
    store = AccessKeyStore(file_path=str(path))
    names = sorted(k.name for k in store.list_keys())
    assert names == ["good1", "good2"], "坏记录应被跳过，好记录必须全部保留"
    assert store.get(3).request_count == 7
    assert store.validate("sk-good2", _now())[0] == STATE_VALID
    assert store.create("new").id == 9, "next_id 必须沿用文件里的值"


def test_bare_list_file_is_accepted(tmp_path):
    path = tmp_path / "access_keys.json"
    path.write_text(json.dumps([{"id": 5, "key": "sk-list", "name": "l"}]), encoding="utf-8")
    store = AccessKeyStore(file_path=str(path))
    assert store.validate("sk-list", _now())[0] == STATE_VALID
    assert store.create("after").id == 6


def test_malformed_keys_field_starts_empty(tmp_path):
    path = tmp_path / "access_keys.json"
    path.write_text(json.dumps({"keys": {"nope": 1}}), encoding="utf-8")
    assert AccessKeyStore(file_path=str(path)).list_keys() == []


# ------------------------------------------------------- 非法/极端 duration_days

def test_non_finite_duration_is_rejected_and_never_reaches_disk(tmp_path):
    """NaN/Infinity：Python 的 json.loads（FastAPI 用的就是它）认这两个字面量。
    一旦存进库，GET 列表端点会因为 JSONResponse 不允许 NaN 而永久 500——
    面板只剩一行加载失败，连本来健康的密钥也一起看不见，而且落盘的文件对别的
    消费者不再是合法 JSON，只能进容器手改。"""
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    good = store.create("good")

    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            store.create("bad", duration_days=bad)
        with pytest.raises(ValueError):
            store.update(good.id, duration_days=bad)

    text = path.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    # 库仍是合法 RFC-8259 JSON（parse_constant 会在遇到 NaN/Infinity 时抛）
    json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(AssertionError(c)))
    assert [k.name for k in store.list_keys()] == ["good"]
    assert store.get(good.id).duration_days is None


def test_absurd_duration_is_rejected_instead_of_500ing_the_first_request(tmp_path):
    """duration_days=1e7（"10000 天"多打一个零）过去会让持有人的**第一个**请求在
    全局鉴权依赖里撞上 datetime 溢出 → 500，而 activated_at 已经写下、expires_at
    还是空的，于是从第二个请求起这把密钥变成永不过期：管理员设的有效期静默没了。"""
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.create("huge", duration_days=10_000_000)
    assert store.list_keys() == []


def test_out_of_range_duration_already_on_disk_does_not_break_auth(tmp_path):
    """本版校验之前写进去的超大值：加载时当"没设"（记 warning），绝不能丢掉整条密钥
    （持有人直接 401），更不能让判定路径抛异常（那是业务请求的 500）。"""
    path = tmp_path / "access_keys.json"
    path.write_text(json.dumps({
        "next_id": 3,
        "keys": [
            {"id": 1, "key": "sk-huge", "name": "huge", "duration_days": 1e12},
            {"id": 2, "key": "sk-ok", "name": "ok"},
        ],
    }), encoding="utf-8")
    store = AccessKeyStore(file_path=str(path))
    assert sorted(k.name for k in store.list_keys()) == ["huge", "ok"]
    state, entry = store.validate_and_consume("sk-huge", _now())
    assert state == STATE_VALID
    assert entry.duration_days is None


def test_fractional_duration_days_is_honoured_to_the_hour(tmp_path):
    """0.5 天的试用密钥是合法输入（API 可以直接传）。把窗口算成 int(days) 的回归
    会让它在"激活它的那一个请求"上就过期，这里把小数语义钉住。"""
    store = _store(tmp_path)
    key = store.create("half", duration_days=0.5)
    t0 = _now()
    assert store.validate_and_consume(key.key, t0)[0] == STATE_VALID
    assert store.validate(key.key, t0 + timedelta(hours=11))[0] == STATE_VALID
    assert store.validate(key.key, t0 + timedelta(hours=13))[0] == STATE_EXPIRED


def test_clearing_expires_at_does_not_make_a_duration_key_immortal(tmp_path):
    """激活之后清掉 expires_at（面板保存 / PATCH clear）不能让密钥变成永不过期：
    duration_days 的语义是"首次使用起算 N 天"，随时能从 activated_at 重算回来。
    否则面板照着 duration_days 显示"7 天有效"，实际那把密钥永远不死。"""
    store = _store(tmp_path)
    key = store.create("dur", duration_days=7)
    t0 = _now()
    _, first = store.validate_and_consume(key.key, t0)
    assert first.expires_at is not None

    # 管理面清掉绝对过期时间：必须立刻按 activated_at 重算回来，面板上看到的才是真的
    cleared = store.update(key.id, expires_at=None)
    assert cleared.expires_at == first.expires_at

    # 库里真的只剩 duration_days（手改过 / 旧版本写下的）时，鉴权侧还要再兜一次
    store._keys[key.id].expires_at = None
    _, again = store.validate_and_consume(key.key, t0 + timedelta(days=1))
    assert again.expires_at == first.expires_at, "必须按原来的 activated_at 重算，不能顺延"
    assert store.validate(key.key, t0 + timedelta(days=8))[0] == STATE_EXPIRED

    # 反过来：还没用过的密钥不能被任何一次编辑提前开始计时
    pending = store.create("pending", duration_days=7)
    assert store.update(pending.id, name="renamed").expires_at is None
    assert store.get(pending.id).activated_at is None


# ----------------------------------------------------- 落盘失败必须抛（不能假成功）

def _break_disk(monkeypatch):
    import app.core.access_key_store as mod

    def boom(*a, **kw):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(mod, "atomic_write_json", boom)


def test_create_fails_loudly_when_it_cannot_be_persisted(tmp_path, monkeypatch):
    """data/ 不可写（bind mount 属主不对/磁盘满/只读卷）时签发必须失败。
    吞掉异常 = POST 回 200 + 一把明文密钥，管理员发出去，重启后持有人直接 401。"""
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    good = store.create("good")

    _break_disk(monkeypatch)
    with pytest.raises(OSError):
        store.create("ghost")

    assert [k.name for k in store.list_keys()] == ["good"], "失败的签发必须从内存里回滚掉"
    assert [k["name"] for k in json.loads(path.read_text(encoding="utf-8"))["keys"]] == ["good"]
    assert store.validate(good.key, _now())[0] == STATE_VALID


def test_delete_fails_loudly_when_it_cannot_be_persisted(tmp_path, monkeypatch):
    """吊销同理：回了 success=true 而磁盘没变，被吊销的密钥重启后原地复活。"""
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    key = store.create("leaked")

    _break_disk(monkeypatch)
    with pytest.raises(OSError):
        store.delete(key.id)

    assert store.get(key.id) is not None, "吊销失败就维持原状，别给出一个假的「已删除」"
    reloaded = AccessKeyStore(file_path=str(path))
    assert reloaded.get(key.id) is not None


def test_timed_flush_never_raises_so_the_loop_keeps_retrying(tmp_path, monkeypatch):
    """定时 flush 是另一回事：它只写用量数字，失败就保持脏标记、下轮重试，绝不抛。"""
    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    key = store.create("k")
    store.validate_and_consume(key.key, _now())

    _break_disk(monkeypatch)
    store.flush()  # 不抛
    monkeypatch.undo()
    store.flush()
    assert json.loads(path.read_text(encoding="utf-8"))["keys"][0]["request_count"] == 1


# ------------------------------------------- 后台 flush 与管理员写盘的交错（竞态）

def _slow_write(store, seconds=0.4):
    """只把**第一次**落盘拖慢，并告知"写盘已经开始"，用来精确制造交错窗口。

    只慢第一次（后台 flush 那次）才能确定性地复现真正的坏顺序：管理员的写盘先落地、
    后台 flush 的旧快照后落地把它覆盖掉。两次都慢的话谁先落地取决于调度，
    守卫就会时灵时不灵（实测：两次都慢时，把 flush 的取快照搬到 io 锁外也能侥幸全绿）。
    """
    import threading
    import time

    real = store._write
    started = threading.Event()
    seen = []

    def slow(data, version, *, raise_on_error):
        first = not seen
        seen.append(1)
        started.set()
        if first:
            time.sleep(seconds)
        return real(data, version, raise_on_error=raise_on_error)

    store._write = slow
    return started, real


def test_background_flush_cannot_resurrect_a_revoked_key(tmp_path):
    """密钥泄漏、管理员点删除，正好撞上 10 秒一次的用量 flush 落在 atomic_write_json 里：
    旧快照后落地就把这把密钥写回磁盘，重启后它又能通过鉴权——而面板显示删成功了。"""
    import threading

    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    keep = store.create("keep")
    leaked = store.create("leaked")
    store.validate_and_consume(keep.key, _now())  # 制造脏标记，让 flush 真的会写

    started, real = _slow_write(store)
    th = threading.Thread(target=store.flush)
    th.start()
    assert started.wait(5), "flush 没进到写盘"
    store.delete(leaked.id)  # 管理员在后台写盘进行中吊销
    th.join(10)
    store._write = real

    reloaded = AccessKeyStore(file_path=str(path))
    assert reloaded.get(leaked.id) is None, "被吊销的密钥不得被后台 flush 写回来"
    assert reloaded.get(keep.id) is not None


def test_background_flush_cannot_swallow_a_freshly_issued_key(tmp_path):
    """反向：签发撞在后台写盘里，旧快照后落地会把刚签的密钥抹掉（持有人 401）。"""
    import threading

    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    old = store.create("old")
    store.validate_and_consume(old.key, _now())

    started, real = _slow_write(store)
    th = threading.Thread(target=store.flush)
    th.start()
    assert started.wait(5)
    fresh = store.create("fresh")
    th.join(10)
    store._write = real

    reloaded = AccessKeyStore(file_path=str(path))
    assert reloaded.get(fresh.id) is not None, "刚签发的密钥不得被后台 flush 抹掉"
    assert reloaded.validate(fresh.key, _now())[0] == STATE_VALID


def test_increment_landing_during_a_write_is_not_marked_clean(tmp_path, monkeypatch):
    """落在写盘窗口里（两次 fsync）的用量 +1 不能被当成"已经写进去了"：
    否则它既不会被下一轮定时 flush 写出，也不会被退出前的同步 flush 写出，
    连 `docker compose down` 都救不回来——重启后计数变小，带额度的密钥白送请求。"""
    import app.core.access_key_store as mod

    path = tmp_path / "access_keys.json"
    store = AccessKeyStore(file_path=str(path))
    key = store.create("k")
    store.validate_and_consume(key.key, _now())

    real = mod.atomic_write_json
    seen = {"n": 0}

    def hooked(target, data, **kw):
        seen["n"] += 1
        if seen["n"] == 1:
            store.validate_and_consume(key.key, _now())  # 写盘期间又来一个请求
        real(target, data, **kw)

    monkeypatch.setattr(mod, "atomic_write_json", hooked)
    store.flush()
    assert json.loads(path.read_text(encoding="utf-8"))["keys"][0]["request_count"] == 1

    store.flush()  # 下一轮必须把那个 +1 补上
    assert json.loads(path.read_text(encoding="utf-8"))["keys"][0]["request_count"] == 2


# -------------------------------------------------- 时序侧信道 / 读写交错

def test_key_matching_is_constant_time_and_never_stops_early(tmp_path, monkeypatch):
    """源码里写明的两条不变量（VULN-011）必须有守卫：
    1) 必须用 secrets.compare_digest，不能退回逐字节提前退出的 `==`；
    2) 命中后不得 break/return —— 否则响应时间会泄漏"第几把命中"。"""
    import app.core.access_key_store as mod

    store = _store(tmp_path)
    keys = [store.create(f"k{i}") for i in range(5)]
    calls = []
    real = mod.secrets.compare_digest

    def counting(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(mod.secrets, "compare_digest", counting)

    calls.clear()
    assert store.validate("sk-nope", _now())[0] == STATE_NOT_FOUND
    assert len(calls) == 5, "未命中时也要恒定时间地逐个走完"

    for key in (keys[0], keys[-1]):
        calls.clear()
        assert store.validate(key.key, _now())[0] == STATE_VALID
        assert len(calls) == 5, "命中后提前 break/return 会泄漏命中位置"
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls)


def test_validate_tolerates_concurrent_admin_mutations(tmp_path):
    """鉴权的"读"与管理面的"写"必然并发（全局依赖 vs 管理员点按钮）。
    _validate_locked 遍历 self._keys 时若不持锁，一次毫不相干的签发/吊销就会让
    一个完全合法的租户请求抛 RuntimeError: dictionary changed size during iteration
    → 500。上面那两条配额竞态用例都看不见这一面。"""
    import sys
    import threading
    import time

    store = _store(tmp_path)
    store._write = lambda *a, **kw: True  # 只测内存态交错，别让几百次 fsync 拖慢用例
    victim = store.create("victim")
    for i in range(50):
        store.create(f"filler-{i}")

    errors = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                store.validate_and_consume(victim.key, _now())
        except Exception as e:  # noqa: BLE001 - 用例就是要抓任何异常
            errors.append(f"reader {type(e).__name__}: {e}")

    def writer():
        try:
            while not stop.is_set():
                entry = store.create("churn")
                store.delete(entry.id)
                store.update(victim.id, name="victim")
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer {type(e).__name__}: {e}")

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads += [threading.Thread(target=writer) for _ in range(2)]
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for th in threads:
            th.start()
        time.sleep(0.6)
        stop.set()
        for th in threads:
            th.join(10)
    finally:
        sys.setswitchinterval(old_interval)
        store._write = AccessKeyStore._write.__get__(store, AccessKeyStore)

    assert errors == [], errors
    assert store.get(victim.id) is not None

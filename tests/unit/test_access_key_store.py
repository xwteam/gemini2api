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


def test_request_limit_zero_blocks_everything(tmp_path):
    store = _store(tmp_path)
    key = store.create("zero", request_limit=0)
    assert store.validate_and_consume(key.key, _now())[0] == STATE_QUOTA_EXCEEDED


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

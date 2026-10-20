"""访问密钥（Access Key）存储：管理员签发、可分发给不同人的入站访问凭据。

与 `app/core/api_key_store.py`（出站第三方 key，兜底链用）**完全无关**，两者绝不可混用：
这里管的是「谁能调用本服务的业务 API」，每把 key 可独立设置有效期/请求数上限/
可用账号/可用模型，并可随时停用。

落盘策略（与 log_store 同款，见 flush()）：
- 管理员增删改 → 立即同步落盘（签发了 key 结果重启丢掉是不可接受的）
- 每请求的用量计数 → 只打脏标记，由 main.py 的定时循环每 10 秒 flush 一次，
  避免把两次 fsync 放进每个业务请求的鉴权热路径。
"""

import json
import logging
import math
import secrets
import string
import threading
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

ACCESS_KEYS_PATH = "data/access_keys.json"

# validate() 的判定结果（四态 + 超额）
STATE_NOT_FOUND = "not_found"
STATE_DISABLED = "disabled"
STATE_EXPIRED = "expired"
STATE_QUOTA_EXCEEDED = "quota_exceeded"
STATE_VALID = "valid"

_KEY_CHARS = string.ascii_letters + string.digits

# duration_days 的硬上限（100 年）。再大的值在 `now + timedelta(days=N)` 处会撞上
# datetime 的 year>9999 抛 OverflowError —— 那是在全局鉴权依赖里抛，业务请求直接 500；
# 而且 activated_at 已经写下、expires_at 还是空的，等于把管理员设的有效期静默弄丢。
MAX_DURATION_DAYS = 36500


def generate_access_key() -> str:
    """生成 `sk-` + 32 位随机串（字符集与 config._generate_api_key 一致，但不复用那个函数）。"""
    return "sk-" + "".join(secrets.choice(_KEY_CHARS) for _ in range(32))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """宽松解析 ISO8601；无法解析返回 None（当作"没设"，绝不因脏数据把 key 判死）。"""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class AccessKey:
    id: int
    key: str
    name: str = ""
    enabled: bool = True
    created_at: str = ""
    expires_at: Optional[str] = None
    # 惰性激活：首次使用时才按 duration_days 算出 expires_at
    duration_days: Optional[float] = None
    activated_at: Optional[str] = None
    request_limit: Optional[int] = None
    request_count: int = 0
    # None / 空列表 = 不限制
    bound_account_ids: Optional[list] = None
    allowed_models: Optional[list] = None
    last_used_at: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.name or f"key-{self.id}"

    def bound_account_set(self) -> Optional[set]:
        if not self.bound_account_ids:
            return None
        return {str(a) for a in self.bound_account_ids}

    def allowed_model_set(self) -> Optional[set]:
        if not self.allowed_models:
            return None
        return {str(m) for m in self.allowed_models}


def _coerce_str_list(value) -> Optional[list]:
    """把任意输入规整成去重后的字符串列表；None/空 → None（表示不限制）。"""
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        raise TypeError(f"expected list, got {type(value).__name__}")
    out: list = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out or None


def _coerce_positive_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("must be a finite number")
    n = int(value)
    if n <= 0:
        # 0 不是"不限"（不限 = 留空/None）。接受 0 只会产出一把签发即超额的废密钥，
        # 而管理员把 0 当成"无限制"填进来的概率远高于真想要这个结果。
        raise ValueError("must be > 0")
    return n


def _coerce_positive_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    f = float(value)
    if not math.isfinite(f):
        # NaN/Infinity：Python 的 json.loads（FastAPI 用的就是它）认这两个字面量。
        # 一旦存进库，GET 列表端点会因为 JSONResponse 不允许 NaN 而永久 500，
        # 面板只剩一行加载失败，而且落盘的文件对别的消费者也不再是合法 JSON。
        raise ValueError("must be a finite number")
    if f <= 0:
        raise ValueError("must be > 0")
    if f > MAX_DURATION_DAYS:
        raise ValueError(f"must be <= {MAX_DURATION_DAYS}")
    return f


def _coerce_duration_on_load(value, entry_id) -> Optional[float]:
    """加载路径对 duration_days 宽松：非法值记 warning 后当成「没设」，不整条丢掉密钥。

    整条丢掉等于持有人直接 401；而这类值（NaN/Infinity/超大）只可能出现在本版校验
    上线之前写下的库里，写入侧已经堵死了。
    """
    try:
        return _coerce_positive_float(value)
    except (TypeError, ValueError) as e:
        logger.warning(
            "access key #%s has an invalid duration_days (%r): %s; ignoring it",
            entry_id, value, e,
        )
        return None


def _add_days(moment: datetime, days: float) -> Optional[datetime]:
    """moment + days；超出 datetime 可表示范围时返回 None 而不是抛。

    库里可能还存着本版校验上线之前写进去的超大值，而这个计算就在鉴权热路径上：
    一个 OverflowError 会变成业务请求的 500，绝不能让它漏出去。
    """
    try:
        return moment + timedelta(days=float(days))
    except (OverflowError, ValueError, OSError):
        return None


def _sync_expiry_locked(entry: AccessKey) -> bool:
    """expires_at 空着、但 duration_days 和 activated_at 都在 → 按"首次使用起算"重算。

    duration_days 的语义就是"首次使用起 N 天"，所以这个推导随时可以重做。不重做的话，
    激活之后一旦有人把 expires_at 清掉（面板保存 / PATCH clear），密钥就永不过期了，
    而面板还照着 duration_days 显示"X 天有效"。
    还没首次使用（activated_at 为空）时什么也不做：有效期要等激活那一刻才落定。
    返回是否真的改了。
    """
    if entry.expires_at is not None or not entry.duration_days:
        return False
    started = parse_timestamp(entry.activated_at)
    if started is None:
        return False
    derived = _add_days(started, entry.duration_days)
    if derived is None:
        logger.warning(
            "access key %s has an out-of-range duration_days (%s); treating it as no expiry",
            entry.id, entry.duration_days,
        )
        return False
    entry.expires_at = _iso(derived)
    return True


class AccessKeyStore:
    def __init__(self, file_path: str = ACCESS_KEYS_PATH):
        self.file_path = Path(file_path)
        # 两把 threading 锁（不是 asyncio.Lock）：定时 flush 跑在 asyncio.to_thread 的
        # 工作线程里，要和事件循环线程互斥。获取顺序恒为 _io_lock → _lock，反过来会死锁。
        # _lock：保护内存态。鉴权热路径只碰它，锁内绝不做磁盘 IO。
        # _io_lock：把「取快照 + 写盘」串成一个整体。少了它，定时 flush 的旧快照会把
        #   管理员刚签发/刚吊销的结果覆盖回去（写盘期间别人能拿着 _lock 改内存并先落盘）。
        self._lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._keys: dict[int, AccessKey] = {}
        self._next_id = 1
        self._dirty = False
        # 内存态每改一次 +1。用来判断一次写盘用的快照是否已经过时（过时就不清脏标记）。
        self._version = 0
        self._load()

    # ------------------------------------------------------------------ 读

    def has_keys(self) -> bool:
        """一把访问密钥都没有时鉴权链路直接短路，保持与本功能引入前逐字节一致的行为。"""
        with self._lock:
            return bool(self._keys)

    def list_keys(self) -> list:
        with self._lock:
            return [replace(k) for k in sorted(self._keys.values(), key=lambda k: k.id)]

    def get(self, key_id: int) -> Optional[AccessKey]:
        with self._lock:
            entry = self._keys.get(int(key_id))
            return replace(entry) if entry else None

    # ------------------------------------------------------------- 校验/消费

    def validate(self, key_str: str, now: Optional[datetime] = None):
        """只判定、不计数。返回 (state, AccessKey 快照|None)。"""
        return self._validate_locked(key_str, now, consume=False)

    def validate_and_consume(self, key_str: str, now: Optional[datetime] = None):
        """判定 + 原子计数。

        判定（含配额比较）与计数 `+1` 必须在同一个临界区里完成，否则并发请求会在
        「检查通过」与「计数写回」之间互相穿插，放行数超过 request_limit。
        """
        return self._validate_locked(key_str, now, consume=True)

    def _validate_locked(self, key_str: str, now: Optional[datetime], *, consume: bool):
        now = now or _utc_now()
        provided = (key_str or "").encode("utf-8")
        with self._lock:
            matched: Optional[AccessKey] = None
            for entry in self._keys.values():
                # 恒定时间比较（VULN-011）；命中后**不提前 return**，整个字典都要走完，
                # 否则"第几把命中"会从响应时间泄漏出去。
                if provided and secrets.compare_digest(provided, entry.key.encode("utf-8")):
                    matched = entry
            if matched is None:
                return STATE_NOT_FOUND, None

            if not matched.enabled:
                return STATE_DISABLED, replace(matched)

            # 惰性激活：首次使用才开始计时
            changed = False
            if matched.activated_at is None:
                matched.activated_at = _iso(now)
                changed = True

            if _sync_expiry_locked(matched):
                changed = True

            expires_at = parse_timestamp(matched.expires_at)
            if expires_at is not None and now >= expires_at:
                if changed:
                    self._touch_locked()
                return STATE_EXPIRED, replace(matched)

            if matched.request_limit is not None and matched.request_count >= matched.request_limit:
                if changed:
                    self._touch_locked()
                return STATE_QUOTA_EXCEEDED, replace(matched)

            if consume:
                matched.request_count += 1
                matched.last_used_at = _iso(now)
                changed = True
            if changed:
                self._touch_locked()
            return STATE_VALID, replace(matched)

    def consume(self, key_id: int, now: Optional[datetime] = None) -> bool:
        """计数 +1 并更新 last_used_at。"""
        now = now or _utc_now()
        with self._lock:
            entry = self._keys.get(int(key_id))
            if entry is None:
                return False
            entry.request_count += 1
            entry.last_used_at = _iso(now)
            self._touch_locked()
            return True

    # ---------------------------------------------------------------- CRUD

    def _mutate(self, action):
        """管理员增删改的统一通道：改内存 → 全量落盘 → 失败回滚内存并抛出。

        `action()` 必须返回 `(changed, result)`；changed=False（例如 id 不存在）时不写盘。

        - 落盘在 _io_lock 内、_lock 外：fsync 不会卡住鉴权热路径，但两个并发的管理员
          操作、以及定时 flush，都不可能拿着各自的旧快照互相覆盖。
        - 落盘失败必须抛出去：吞掉异常会让 POST 回 200 + 一把明文密钥、DELETE 回
          success=true，而磁盘上什么都没变 —— 重启后新签的密钥消失、被吊销的密钥复活。
          （app/core/api_key_store.py 也是让 atomic_write_json 直接抛。）
        """
        with self._io_lock:
            with self._lock:
                backup = ({kid: replace(k) for kid, k in self._keys.items()}, self._next_id)
                try:
                    changed, result = action()
                except Exception:
                    # action 可能已经改了一半（update 逐字段赋值时第三个字段才抛）
                    self._keys, self._next_id = backup
                    raise
                if not changed:
                    return result
                self._touch_locked()
                data = self._serialize_locked()
                version = self._version
            try:
                self._write(data, version, raise_on_error=True)
            except Exception:
                with self._lock:
                    self._keys, self._next_id = backup
                    self._touch_locked()
                raise
            return result

    def create(self, name: str = "", **kwargs) -> AccessKey:
        return self.create_many([name], **kwargs)[0]

    def create_many(
        self,
        names,
        *,
        expires_at: Optional[str] = None,
        duration_days=None,
        request_limit=None,
        bound_account_ids=None,
        allowed_models=None,
        enabled: bool = True,
    ) -> list:
        """一次签发多把密钥，只做一次全量落盘。

        逐把 create() 的话，签发 50 把就是 50 次全量写（每次两个 fsync）、写出的字节数
        是 O(n²)，而且全在事件循环线程上 —— 整个网关会卡满这段时间。
        """
        duration = _coerce_positive_float(duration_days)
        limit = _coerce_positive_int(request_limit)
        accounts = _coerce_str_list(bound_account_ids)
        models = _coerce_str_list(allowed_models)
        expires = expires_at or None

        def _do():
            created = []
            for name in names:
                entry = AccessKey(
                    id=self._next_id,
                    key=generate_access_key(),
                    name=(name or "").strip(),
                    enabled=bool(enabled),
                    created_at=_iso(_utc_now()),
                    expires_at=expires,
                    duration_days=duration,
                    request_limit=limit,
                    bound_account_ids=list(accounts) if accounts else None,
                    allowed_models=list(models) if models else None,
                )
                self._next_id += 1
                self._keys[entry.id] = entry
                created.append(replace(entry))
            return bool(created), created

        return self._mutate(_do)

    _UPDATABLE = (
        "name", "enabled", "expires_at", "duration_days",
        "request_limit", "bound_account_ids", "allowed_models",
    )

    def update(self, key_id: int, **fields) -> Optional[AccessKey]:
        kid = int(key_id)

        def _do():
            entry = self._keys.get(kid)
            if entry is None:
                return False, None
            for field, value in fields.items():
                if field not in self._UPDATABLE:
                    raise ValueError(f"field '{field}' is not updatable")
                if field == "name":
                    entry.name = (value or "").strip()
                elif field == "enabled":
                    entry.enabled = bool(value)
                elif field == "expires_at":
                    entry.expires_at = value or None
                elif field == "duration_days":
                    entry.duration_days = _coerce_positive_float(value)
                elif field == "request_limit":
                    entry.request_limit = _coerce_positive_int(value)
                elif field == "bound_account_ids":
                    entry.bound_account_ids = _coerce_str_list(value)
                elif field == "allowed_models":
                    entry.allowed_models = _coerce_str_list(value)
            # 清掉 expires_at 的同时还留着 duration_days 时立刻重算，别让面板上
            # 出现一把"显示 7 天有效、其实永不过期"的密钥（鉴权侧也会再兜一次）。
            _sync_expiry_locked(entry)
            return True, replace(entry)

        return self._mutate(_do)

    def delete(self, key_id: int) -> bool:
        kid = int(key_id)

        def _do():
            if kid not in self._keys:
                return False, False
            del self._keys[kid]
            return True, True

        return self._mutate(_do)

    def reset_usage(self, key_id: int) -> Optional[AccessKey]:
        kid = int(key_id)

        def _do():
            entry = self._keys.get(kid)
            if entry is None:
                return False, None
            entry.request_count = 0
            return True, replace(entry)

        return self._mutate(_do)

    # ----------------------------------------------------------- 持久化

    def _touch_locked(self) -> None:
        """记一次内存态改动（需已持有 self._lock）。"""
        self._version += 1
        self._dirty = True

    def _serialize_locked(self) -> dict:
        return {
            "next_id": self._next_id,
            "keys": [asdict(k) for k in sorted(self._keys.values(), key=lambda k: k.id)],
        }

    def _write(self, data: dict, version: int, *, raise_on_error: bool) -> bool:
        """同步原子落盘。只有当这份快照仍是最新版本时才清脏标记。

        version 守卫：写盘期间（两次 fsync，真实磁盘上几毫秒到几十毫秒）落下的用量 +1
        不能被当成"已经写进去了" —— 否则那些增量既不会被下一轮定时 flush 写出，也不会
        被退出前的同步 flush 写出，等于静默丢失（连 `docker compose down` 都救不回来）。
        """
        try:
            atomic_write_json(self.file_path, data, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("failed to persist %s: %s", self.file_path, e)
            with self._lock:
                self._dirty = True
            if raise_on_error:
                raise
            return False
        with self._lock:
            if self._version == version:
                self._dirty = False
        return True

    def save(self) -> None:
        """强制落盘（忽略脏标记）；失败抛出。"""
        with self._io_lock:
            with self._lock:
                data = self._serialize_locked()
                version = self._version
            self._write(data, version, raise_on_error=True)

    def flush(self) -> None:
        """定时/退出前落盘：没脏就跳过；失败保持脏标记，下轮自动重试。"""
        with self._io_lock:
            with self._lock:
                if not self._dirty:
                    return
                data = self._serialize_locked()
                version = self._version
            self._write(data, version, raise_on_error=False)

    def load(self) -> None:
        """从磁盘重新加载（丢弃内存态）。"""
        with self._lock:
            self._keys = {}
            self._next_id = 1
            self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.file_path.exists():
            return
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception as e:
            # 整文件损坏：记 error 后当空库启动，绝不让进程起不来（照 account_pool 的等级）
            logger.error("access keys file %s is corrupt, starting empty: %s", self.file_path, e)
            return

        if isinstance(raw, list):
            items, next_id = raw, None
        elif isinstance(raw, dict):
            items = raw.get("keys") or []
            next_id = raw.get("next_id")
            if not isinstance(items, list):
                logger.error("access keys file %s has a malformed 'keys' field, starting empty", self.file_path)
                return
        else:
            logger.error("access keys file %s has unexpected shape, starting empty", self.file_path)
            return

        loaded: dict[int, AccessKey] = {}
        for i, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise TypeError("not an object")
                key_text = str(item.get("key") or "").strip()
                if not key_text:
                    raise KeyError("key")
                entry_id = int(item.get("id", i + 1))
                entry = AccessKey(
                    id=entry_id,
                    key=key_text,
                    name=str(item.get("name") or ""),
                    enabled=bool(item.get("enabled", True)),
                    created_at=str(item.get("created_at") or ""),
                    expires_at=item.get("expires_at") or None,
                    duration_days=_coerce_duration_on_load(item.get("duration_days"), entry_id),
                    activated_at=item.get("activated_at") or None,
                    request_limit=_coerce_positive_int(item.get("request_limit")),
                    request_count=int(item.get("request_count") or 0),
                    bound_account_ids=_coerce_str_list(item.get("bound_account_ids")),
                    allowed_models=_coerce_str_list(item.get("allowed_models")),
                    last_used_at=item.get("last_used_at") or None,
                )
            except Exception as e:
                # 单条坏记录跳过、保留其余，绝不清库
                logger.warning("Skipping corrupt access key entry #%d in %s: %s", i, self.file_path, e)
                continue
            if entry.id in loaded:
                logger.warning("Duplicate access key id %s in %s; later entry wins", entry.id, self.file_path)
            loaded[entry.id] = entry

        with self._lock:
            self._keys = loaded
            computed = (max(loaded) + 1) if loaded else 1
            try:
                self._next_id = max(int(next_id), computed) if next_id is not None else computed
            except (TypeError, ValueError):
                self._next_id = computed


# 模块级单例：verify_api_key 是全局依赖，测试里也常常不跑 lifespan，
# 挂 app.state 会在那些路径下取不到对象。照 account_pool 的做法用模块级单例。
access_key_store = AccessKeyStore()

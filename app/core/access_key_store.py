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
    n = int(value)
    if n < 0:
        raise ValueError("must be >= 0")
    return n


def _coerce_positive_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    f = float(value)
    if f <= 0:
        raise ValueError("must be > 0")
    return f


class AccessKeyStore:
    def __init__(self, file_path: str = ACCESS_KEYS_PATH):
        self.file_path = Path(file_path)
        # threading.Lock（不是 asyncio.Lock）：定时 flush 跑在 asyncio.to_thread 的工作线程里，
        # 要和事件循环线程互斥。锁内只做纯内存操作，磁盘 IO 一律在锁外。
        self._lock = threading.RLock()
        self._keys: dict[int, AccessKey] = {}
        self._next_id = 1
        self._dirty = False
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

            # 惰性激活：首次使用才开始计时，并据 duration_days 落定 expires_at
            newly_activated = False
            if matched.activated_at is None:
                matched.activated_at = _iso(now)
                newly_activated = True
                if matched.duration_days and not matched.expires_at:
                    matched.expires_at = _iso(now + timedelta(days=float(matched.duration_days)))

            expires_at = parse_timestamp(matched.expires_at)
            if expires_at is not None and now >= expires_at:
                if newly_activated:
                    self._dirty = True
                return STATE_EXPIRED, replace(matched)

            if matched.request_limit is not None and matched.request_count >= matched.request_limit:
                if newly_activated:
                    self._dirty = True
                return STATE_QUOTA_EXCEEDED, replace(matched)

            if consume:
                matched.request_count += 1
                matched.last_used_at = _iso(now)
            if consume or newly_activated:
                self._dirty = True
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
            self._dirty = True
            return True

    # ---------------------------------------------------------------- CRUD

    def create(
        self,
        name: str = "",
        *,
        expires_at: Optional[str] = None,
        duration_days=None,
        request_limit=None,
        bound_account_ids=None,
        allowed_models=None,
        enabled: bool = True,
    ) -> AccessKey:
        with self._lock:
            entry = AccessKey(
                id=self._next_id,
                key=generate_access_key(),
                name=(name or "").strip(),
                enabled=bool(enabled),
                created_at=_iso(_utc_now()),
                expires_at=(expires_at or None),
                duration_days=_coerce_positive_float(duration_days),
                request_limit=_coerce_positive_int(request_limit),
                bound_account_ids=_coerce_str_list(bound_account_ids),
                allowed_models=_coerce_str_list(allowed_models),
            )
            self._next_id += 1
            self._keys[entry.id] = entry
            snapshot = replace(entry)
            self._persist_locked()
        return snapshot

    _UPDATABLE = (
        "name", "enabled", "expires_at", "duration_days",
        "request_limit", "bound_account_ids", "allowed_models",
    )

    def update(self, key_id: int, **fields) -> Optional[AccessKey]:
        with self._lock:
            entry = self._keys.get(int(key_id))
            if entry is None:
                return None
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
            snapshot = replace(entry)
            self._persist_locked()
        return snapshot

    def delete(self, key_id: int) -> bool:
        with self._lock:
            if int(key_id) not in self._keys:
                return False
            del self._keys[int(key_id)]
            self._persist_locked()
        return True

    def reset_usage(self, key_id: int) -> Optional[AccessKey]:
        with self._lock:
            entry = self._keys.get(int(key_id))
            if entry is None:
                return None
            entry.request_count = 0
            snapshot = replace(entry)
            self._persist_locked()
        return snapshot

    # ----------------------------------------------------------- 持久化

    def _serialize_locked(self) -> dict:
        return {
            "next_id": self._next_id,
            "keys": [asdict(k) for k in sorted(self._keys.values(), key=lambda k: k.id)],
        }

    def _persist_locked(self) -> None:
        """在已持有 self._lock 的前提下同步落盘（管理员操作路径）。

        必须持锁写：若先在锁内取快照、再到锁外写，两个并发的管理员操作会各持一份
        快照，后落盘的那次会把前一次刚签发的密钥整条抹掉。管理员操作频率极低，
        为这点确定性付一次 fsync 完全值得（与 api_key_store 的行为一致）。
        """
        self._write(self._serialize_locked())

    def _write(self, data: dict) -> None:
        """同步原子落盘。成功才清脏标记。"""
        try:
            atomic_write_json(self.file_path, data, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("failed to persist %s: %s", self.file_path, e)
            with self._lock:
                self._dirty = True
            return
        with self._lock:
            self._dirty = False

    def save(self) -> None:
        """强制落盘（忽略脏标记）。"""
        with self._lock:
            self._persist_locked()

    def flush(self) -> None:
        """定时/退出前落盘：没脏就跳过；IO 在锁外；失败保持脏标记，下轮自动重试。"""
        with self._lock:
            if not self._dirty:
                return
            data = self._serialize_locked()
        self._write(data)

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
                    duration_days=_coerce_positive_float(item.get("duration_days")),
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

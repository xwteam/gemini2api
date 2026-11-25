"""Structured log store with circular buffer, filtering, pagination, and persistence."""

import json
import uuid
from collections import deque
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional


@dataclass
class LogRecord:
    id: str
    request_id: str
    direction: str
    ts: str
    method: str
    path: str
    model: Optional[str] = None
    provider: Optional[str] = None
    status: Optional[int] = None
    latency_ms: Optional[float] = None
    # 流式请求：从请求进入到第一个内容帧（正文或思考）发出的毫秒数；非流式 / 没有内容恒为 None。
    # 字段名是与面板「日志」页的约定，别改。旧记录没有这个字段，读进来就是 None。
    ttft_ms: Optional[float] = None
    stream: Optional[bool] = None
    error: Optional[str] = None
    tags: list = field(default_factory=list)
    request: Optional[dict] = None
    response: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def matches_search(self, query: str) -> bool:
        q = query.lower()
        searchable = [
            self.path,
            self.method,
            self.model or "",
            self.error or "",
            str(self.status) if self.status else "",
        ]
        return any(q in s.lower() for s in searchable)


@dataclass
class LogState:
    enabled: bool = True
    paused: bool = False


class LogStore:
    def __init__(self, capacity: int = 2000, persist_path: str = "data/logs.json"):
        self._buffer: deque[LogRecord] = deque(maxlen=capacity)
        self._lock = Lock()
        self._state = LogState()
        self._id_index: dict[str, LogRecord] = {}
        self._persist_path = Path(persist_path)
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            # 只取认得的字段：旧记录缺字段走默认值；更新版本写下的、本版不认识的字段直接丢掉，
            # 不能让一个未知 kwarg 把整份日志文件读挂（外层 except 会把所有记录一起吞掉）。
            known = {f.name for f in fields(LogRecord)}
            for item in raw:
                record = LogRecord(**{k: v for k, v in item.items() if k in known})
                self._buffer.append(record)
                self._id_index[record.id] = record
        except Exception:
            pass

    def flush(self) -> None:
        if not self._dirty:
            return
        with self._lock:
            # 落盘绝不带 request/response body（issue #10 followup F1a）：
            # 1) 隐私——用户完整提示词不该躺在 data/logs.json 里；
            # 2) 体积/性能——2000 条 * 32KB body 能把这次 write_text 从 0.6MB/56ms
            #    拖成 119MB/4s+，而 flush 是每 10s 跑一次的定时任务。
            # 内存里的 buffer（面板详情视图读的就是它）完全不受影响，body 仍在。
            data = []
            for r in self._buffer:
                d = r.to_dict()
                d["request"] = None
                d["response"] = None
                data.append(d)
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            self._dirty = False
        except Exception:
            pass

    @property
    def state(self) -> LogState:
        return self._state

    def add(self, record: LogRecord) -> None:
        if not self._state.enabled or self._state.paused:
            return
        with self._lock:
            if len(self._buffer) == self._buffer.maxlen:
                evicted = self._buffer[0]
                self._id_index.pop(evicted.id, None)
            self._buffer.append(record)
            self._id_index[record.id] = record
        self._dirty = True

    def query(
        self,
        limit: int = 50,
        offset: int = 0,
        direction: str = "all",
        search: str = "",
    ) -> dict:
        with self._lock:
            records = list(reversed(self._buffer))

        if direction != "all":
            records = [r for r in records if r.direction == direction]

        if search:
            records = [r for r in records if r.matches_search(search)]

        total = len(records)
        page = records[offset : offset + limit]
        return {
            "records": [r.to_dict() for r in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get(self, record_id: str) -> Optional[dict]:
        with self._lock:
            record = self._id_index.get(record_id)
        if record:
            return record.to_dict()
        return None

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._id_index.clear()
        self._dirty = True
        self.flush()

    def get_state(self) -> dict:
        return {"enabled": self._state.enabled, "paused": self._state.paused}

    def set_state(self, enabled: Optional[bool] = None, paused: Optional[bool] = None) -> dict:
        if enabled is not None:
            self._state.enabled = enabled
        if paused is not None:
            self._state.paused = paused
        return self.get_state()


def create_log_record(
    method: str,
    path: str,
    direction: str = "ingress",
    model: Optional[str] = None,
    status: Optional[int] = None,
    latency_ms: Optional[float] = None,
    stream: Optional[bool] = None,
    error: Optional[str] = None,
    ttft_ms: Optional[float] = None,
    request_body: Optional[dict] = None,
    response_body: Optional[dict] = None,
) -> LogRecord:
    now = datetime.now(timezone.utc).isoformat()
    return LogRecord(
        id=uuid.uuid4().hex[:12],
        request_id=uuid.uuid4().hex[:8],
        direction=direction,
        ts=now,
        method=method,
        path=path,
        model=model,
        provider="gemini",
        status=status,
        latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
        ttft_ms=round(ttft_ms, 1) if ttft_ms is not None else None,
        stream=stream,
        error=error,
        request=request_body,
        response=response_body,
    )

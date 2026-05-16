"""Usage statistics store."""

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("data/usage-stats.json")
DAY_MS = 86_400_000
BUCKET_MS = {"five_min": 300_000, "hourly": 3_600_000, "daily": 86_400_000}


def _ts_ms(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp() * 1000


def _diff_models(prev: dict, curr: dict) -> dict:
    r = {}
    for m in set(list(prev.keys()) + list(curr.keys())):
        d = curr.get(m, 0) - prev.get(m, 0)
        if d > 0:
            r[m] = d
    return r


def _bucketize(deltas: list, bucket_ms: int) -> list:
    if not deltas:
        return []
    buckets = {}
    for d in deltas:
        t = _ts_ms(d["timestamp"])
        key = int(t // bucket_ms) * bucket_ms
        if key in buckets:
            b = buckets[key]
            b["request_count"] += d["request_count"]
            b["error_count"] += d["error_count"]
            for m, c in d.get("model_requests", {}).items():
                b["model_requests"][m] = b["model_requests"].get(m, 0) + c
            b["_n"] += 1
            b["_ls"] += d["avg_latency_ms"]
            b["max_latency_ms"] = max(b["max_latency_ms"], d["max_latency_ms"])
            b["rotation_success"] += d["rotation_success"]
            b["rotation_failure"] += d["rotation_failure"]
            b["active_accounts"] = d["active_accounts"]
        else:
            ts = datetime.fromtimestamp(key / 1000, tz=timezone.utc).isoformat()
            buckets[key] = {
                "timestamp": ts,
                "request_count": d["request_count"],
                "error_count": d["error_count"],
                "model_requests": dict(d.get("model_requests", {})),
                "avg_latency_ms": d["avg_latency_ms"],
                "max_latency_ms": d["max_latency_ms"],
                "active_accounts": d["active_accounts"],
                "rotation_success": d["rotation_success"],
                "rotation_failure": d["rotation_failure"],
                "_n": 1, "_ls": d["avg_latency_ms"],
            }
    result = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        if b["_n"] > 0:
            b["avg_latency_ms"] = round(b["_ls"] / b["_n"], 1)
        del b["_n"]
        del b["_ls"]
        result.append(b)
    return result


class UsageStatsStore:
    def __init__(self, file_path=HISTORY_FILE, retention_days=30):
        self._file_path = file_path
        self._retention_days = retention_days
        self._snapshots = []
        self._baseline = {
            "request_count": 0, "error_count": 0,
            "model_requests": {}, "latency_sum_ms": 0.0,
            "latency_count": 0, "rotation_success": 0, "rotation_failure": 0,
        }
        self._start_time = time.time()
        self._load()

    def _load(self):
        try:
            if self._file_path.exists():
                data = json.loads(self._file_path.read_text())
                self._snapshots = data.get("snapshots", [])
                bl = data.get("baseline")
                if bl:
                    self._baseline = bl
                elif self._snapshots:
                    last = self._snapshots[-1]["totals"]
                    self._baseline = {
                        "request_count": last.get("request_count", 0),
                        "error_count": last.get("error_count", 0),
                        "model_requests": last.get("model_requests", {}),
                        "latency_sum_ms": last.get("latency_sum_ms", 0.0),
                        "latency_count": last.get("latency_count", 0),
                        "rotation_success": last.get("rotation_success", 0),
                        "rotation_failure": last.get("rotation_failure", 0),
                    }
                logger.info(f"[UsageStats] Loaded {len(self._snapshots)} snapshots")
        except Exception as e:
            logger.warning(f"[UsageStats] Load failed: {e}")

    def _save(self):
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file_path.with_suffix(".tmp")
            payload = {"version": 1, "baseline": self._baseline, "snapshots": self._snapshots}
            tmp.write_text(json.dumps(payload, ensure_ascii=False))
            tmp.rename(self._file_path)
        except Exception as e:
            logger.error(f"[UsageStats] Save failed: {e}")

    def _pool_live(self, pool) -> dict:
        req = err = active = total = 0
        for a in pool.accounts:
            req += a.request_count
            err += a.error_count
            if a.status.value == "active":
                active += 1
            total += 1
        return {"request_count": req, "error_count": err, "active_accounts": active, "total_accounts": total}

    def record_snapshot(self, pool, live_metrics: dict):
        live = self._pool_live(pool)
        if self._snapshots:
            prev_t = self._snapshots[-1]["totals"]
            prev_live_req = prev_t["request_count"] - self._baseline["request_count"]
            prev_live_err = prev_t["error_count"] - self._baseline["error_count"]
            if live["request_count"] < prev_live_req:
                self._baseline["request_count"] += prev_live_req - live["request_count"]
            if live["error_count"] < prev_live_err:
                self._baseline["error_count"] += prev_live_err - live["error_count"]
        for m, c in live_metrics.get("model_requests", {}).items():
            self._baseline["model_requests"][m] = self._baseline["model_requests"].get(m, 0) + c
        self._baseline["latency_sum_ms"] += live_metrics.get("latency_sum_ms", 0.0)
        self._baseline["latency_count"] += live_metrics.get("latency_count", 0)
        self._baseline["rotation_success"] += live_metrics.get("rotation_success", 0)
        self._baseline["rotation_failure"] += live_metrics.get("rotation_failure", 0)
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "totals": {
                "request_count": self._baseline["request_count"] + live["request_count"],
                "error_count": self._baseline["error_count"] + live["error_count"],
                "active_accounts": live["active_accounts"],
                "total_accounts": live["total_accounts"],
                "model_requests": dict(self._baseline["model_requests"]),
                "latency_sum_ms": self._baseline["latency_sum_ms"],
                "latency_count": self._baseline["latency_count"],
                "latency_max_ms": live_metrics.get("latency_max_ms", 0.0),
                "rotation_success": self._baseline["rotation_success"],
                "rotation_failure": self._baseline["rotation_failure"],
            },
        }
        self._snapshots.append(snapshot)
        if self._retention_days:
            cutoff = time.time() * 1000 - self._retention_days * DAY_MS
            self._snapshots = [s for s in self._snapshots if _ts_ms(s["timestamp"]) >= cutoff]
        self._save()

    def get_summary(self) -> dict:
        if not self._snapshots:
            return {
                "request_count": 0, "error_count": 0,
                "active_accounts": 0, "total_accounts": 0,
                "model_requests": {}, "avg_latency_ms": 0.0,
                "max_latency_ms": 0.0, "rotation_success": 0,
                "rotation_failure": 0, "uptime_seconds": 0,
            }
        last = self._snapshots[-1]["totals"]
        lat_count = last.get("latency_count", 0)
        lat_sum = last.get("latency_sum_ms", 0.0)
        avg_lat = round(lat_sum / lat_count, 1) if lat_count > 0 else 0.0
        return {
            "request_count": last.get("request_count", 0),
            "error_count": last.get("error_count", 0),
            "active_accounts": last.get("active_accounts", 0),
            "total_accounts": last.get("total_accounts", 0),
            "model_requests": last.get("model_requests", {}),
            "avg_latency_ms": avg_lat,
            "max_latency_ms": last.get("latency_max_ms", 0.0),
            "rotation_success": last.get("rotation_success", 0),
            "rotation_failure": last.get("rotation_failure", 0),
            "uptime_seconds": int(time.time() - self._start_time),
        }

    def get_history(self, granularity: str = "hourly", hours: int | None = 24) -> list:
        if len(self._snapshots) < 2:
            return []
        cutoff = None
        if hours is not None:
            cutoff = time.time() * 1000 - hours * 3_600_000
        filtered = self._snapshots
        if cutoff:
            filtered = [s for s in self._snapshots if _ts_ms(s["timestamp"]) >= cutoff]
        if len(filtered) < 2:
            filtered = self._snapshots[-2:]
        deltas = []
        for i in range(1, len(filtered)):
            prev_t = filtered[i - 1]["totals"]
            curr_t = filtered[i]["totals"]
            req_d = curr_t.get("request_count", 0) - prev_t.get("request_count", 0)
            err_d = curr_t.get("error_count", 0) - prev_t.get("error_count", 0)
            lat_count_d = curr_t.get("latency_count", 0) - prev_t.get("latency_count", 0)
            lat_sum_d = curr_t.get("latency_sum_ms", 0.0) - prev_t.get("latency_sum_ms", 0.0)
            avg_lat = round(lat_sum_d / lat_count_d, 1) if lat_count_d > 0 else 0.0
            rot_s = curr_t.get("rotation_success", 0) - prev_t.get("rotation_success", 0)
            rot_f = curr_t.get("rotation_failure", 0) - prev_t.get("rotation_failure", 0)
            model_d = _diff_models(
                prev_t.get("model_requests", {}), curr_t.get("model_requests", {})
            )
            deltas.append({
                "timestamp": filtered[i]["timestamp"],
                "request_count": max(req_d, 0),
                "error_count": max(err_d, 0),
                "model_requests": model_d,
                "avg_latency_ms": avg_lat,
                "max_latency_ms": curr_t.get("latency_max_ms", 0.0),
                "active_accounts": curr_t.get("active_accounts", 0),
                "rotation_success": max(rot_s, 0),
                "rotation_failure": max(rot_f, 0),
            })
        bucket_ms = BUCKET_MS.get(granularity)
        if bucket_ms:
            return _bucketize(deltas, bucket_ms)
        return deltas

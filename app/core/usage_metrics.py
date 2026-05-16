"""Lightweight in-memory metrics collector for usage between snapshots."""

import threading


class LiveMetricsCollector:
    """
    Thread-safe collector for per-request metrics.
    Accumulated between snapshots, then drained.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self._model_requests: dict[str, int] = {}
        self._latency_samples: list[float] = []
        self._latency_max: float = 0.0
        self._rotation_success: int = 0
        self._rotation_failure: int = 0

    def record_request(self, model: str, latency_ms: float):
        with self._lock:
            self._model_requests[model] = self._model_requests.get(model, 0) + 1
            self._latency_samples.append(latency_ms)
            if latency_ms > self._latency_max:
                self._latency_max = latency_ms

    def record_rotation(self, success: bool):
        with self._lock:
            if success:
                self._rotation_success += 1
            else:
                self._rotation_failure += 1

    def drain(self) -> dict:
        """Return accumulated metrics and reset. Called by snapshot timer."""
        with self._lock:
            result = {
                "model_requests": dict(self._model_requests),
                "latency_sum_ms": sum(self._latency_samples),
                "latency_count": len(self._latency_samples),
                "latency_max_ms": self._latency_max,
                "rotation_success": self._rotation_success,
                "rotation_failure": self._rotation_failure,
            }
            self._reset()
            return result

    def peek(self) -> dict:
        """Read without resetting (for summary endpoint)."""
        with self._lock:
            return {
                "model_requests": dict(self._model_requests),
                "latency_sum_ms": sum(self._latency_samples),
                "latency_count": len(self._latency_samples),
                "latency_max_ms": self._latency_max,
                "rotation_success": self._rotation_success,
                "rotation_failure": self._rotation_failure,
            }


live_metrics = LiveMetricsCollector()

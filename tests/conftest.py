"""Shared pytest configuration & fixtures for the Gemini2API test suite.

The test env is configured BEFORE the ``app`` package is imported so that
``app.config.Settings()`` (instantiated at import time) picks up deterministic,
side-effect-free values. Fixtures exercise the FastAPI app WITHOUT running the
lifespan startup, so tests never touch the network or the account pool.
"""

import os
import sys
from pathlib import Path

# Make `import app...` work regardless of the current working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Deterministic settings for tests. Must run before any `app.*` import.
# Background loops that would do real I/O are disabled here.
os.environ.setdefault("API_KEY", "sk-test-key")
os.environ.setdefault("LOG_LEVEL", "warning")
os.environ.setdefault("VERSION_SYNC_ENABLED", "false")
os.environ.setdefault("USAGE_STATS_ENABLED", "false")
os.environ.setdefault("CHAT_CLEANUP_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest

TEST_API_KEY = os.environ["API_KEY"]


@pytest.fixture
def app_main():
    """Import the FastAPI application module; skip if runtime deps are absent."""
    pytest.importorskip("fastapi", reason="fastapi not installed (runtime deps)")
    from app import main

    return main


@pytest.fixture
def client(app_main):
    """A TestClient that does NOT run the app lifespan (no startup / no network).

    The logging middleware reads ``app.state.log_store`` for API/admin paths,
    which is normally created during lifespan startup. We inject a no-op stub so
    those paths can be exercised deterministically without booting the pool.
    """
    from fastapi.testclient import TestClient

    class _DummyLogStore:
        def add(self, *args, **kwargs):
            return None

        def flush(self, *args, **kwargs):
            return None

    app_main.app.state.log_store = _DummyLogStore()
    return TestClient(app_main.app)


@pytest.fixture
def gem_client(app_main, tmp_path):
    """TestClient（不跑 lifespan），但把路由依赖的 app.state 对象用临时文件装好。"""
    from fastapi.testclient import TestClient
    from app.core.model_mapping import ModelMapping
    from app.core.gem_mapping import GemMapping

    class _DummyLogStore:
        def add(self, *a, **k): return None
        def flush(self, *a, **k): return None

    app_main.app.state.log_store = _DummyLogStore()
    app_main.app.state.model_mapping = ModelMapping(path=str(tmp_path / "mm.json"))
    app_main.app.state.gem_mapping = GemMapping(path=str(tmp_path / "gm.json"))
    return TestClient(app_main.app)

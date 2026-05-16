import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings, APP_VERSION
from app.core.account_pool import account_pool
from app.core.auth import verify_api_key
from app.core.fingerprint.version_sync import version_sync_loop
from app.core.usage_stats import UsageStatsStore
from app.core.usage_timer import snapshot_loop
from app.core.log_store import LogStore, create_log_record
from app.routers import openai, claude, gemini, research
from app.routers import admin
from app.routers import logs as logs_router
from app.routers import usage_stats as usage_stats_router
from app.routers import settings as settings_router
from app.routers import api_keys as api_keys_router
from app.routers import model_mapping as model_mapping_router
from app.core.api_key_store import ApiKeyPool
from app.core.model_mapping import ModelMapping

STATIC_DIR = Path(__file__).parent.parent / "static"

log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logging.getLogger("app").setLevel(log_level)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    logger.info(f"API Key: {settings.api_key}")
    await account_pool.initialize()

    app.state.log_store = LogStore()
    app.state.api_key_pool = ApiKeyPool()
    app.state.model_mapping = ModelMapping()

    version_task = None
    if settings.version_sync_enabled:
        version_task = asyncio.create_task(version_sync_loop())
        logger.info("Chrome version sync task started")

    snapshot_task = None
    if settings.usage_stats_enabled:
        store = UsageStatsStore(retention_days=settings.usage_stats_retention_days)
        app.state.usage_stats_store = store
        snapshot_task = asyncio.create_task(
            snapshot_loop(store, account_pool, interval=settings.usage_stats_interval)
        )
        logger.info("Usage stats snapshot loop started")

    yield

    logger.info("Shutting down...")
    if snapshot_task:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
    if version_task:
        version_task.cancel()
        try:
            await version_task
        except asyncio.CancelledError:
            pass
    await account_pool.shutdown()


app = FastAPI(
    title="Gemini2API",
    description="Gemini Web to API proxy",
    version=APP_VERSION,
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

if settings.rate_limit_enabled:
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "Rate limit exceeded", "type": "rate_limit"}},
        )


SKIP_LOG_PREFIXES = ("/static/", "/favicon.ico", "/admin/logs")


@app.middleware("http")
async def log_capture_middleware(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in SKIP_LOG_PREFIXES):
        return await call_next(request)

    import time
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - start) * 1000

    method = request.method
    status = response.status_code

    is_api = path.startswith(("/openai/", "/claude/", "/gemini/", "/v1/", "/v1beta/"))
    if not is_api and not path.startswith("/admin/"):
        return response

    direction = "egress" if path.startswith(("/v1beta/", "/gemini/")) else "ingress"

    model = None
    stream = None
    if hasattr(request.state, "_body_cache"):
        import json
        try:
            body = json.loads(request.state._body_cache)
            model = body.get("model")
            stream = body.get("stream")
        except Exception:
            pass

    error_msg = None
    if status >= 400:
        error_msg = f"HTTP {status}"

    log_store = request.app.state.log_store
    record = create_log_record(
        method=method,
        path=path,
        direction=direction,
        model=model,
        status=status,
        latency_ms=latency_ms,
        stream=stream,
        error=error_msg,
    )
    log_store.add(record)

    return response

app.include_router(openai.router)
app.include_router(claude.router)
app.include_router(gemini.router)
app.include_router(research.router)
app.include_router(admin.router)
app.include_router(logs_router.router)
app.include_router(usage_stats_router.router)
app.include_router(settings_router.router)
app.include_router(api_keys_router.router)
app.include_router(model_mapping_router.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "gemini2api"}


@app.get("/login.html")
async def login_page():
    login_file = STATIC_DIR / "login.html"
    if login_file.exists():
        return FileResponse(login_file, media_type="text/html")
    return HTMLResponse("<h1>Login page not found</h1>", status_code=404)


@app.get("/index.html")
async def index_page():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return HTMLResponse("<h1>Panel not found</h1>", status_code=404)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=False)

"""Usage statistics API endpoints."""

from fastapi import APIRouter, Request, Query

router = APIRouter(prefix="/admin/usage-stats", tags=["usage-stats"])


@router.get("/summary")
async def get_summary(request: Request):
    store = request.app.state.usage_stats_store
    return store.get_summary()


@router.get("/history")
async def get_history(
    request: Request,
    granularity: str = Query("hourly", regex="^(raw|five_min|hourly|daily)$"),
    hours: str = Query("24"),
):
    store = request.app.state.usage_stats_store
    h = None if hours == "all" else int(hours)
    return store.get_history(granularity=granularity, hours=h)

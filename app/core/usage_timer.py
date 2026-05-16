"""Background task for periodic usage snapshots."""

import asyncio
import logging

from app.core.usage_metrics import live_metrics

logger = logging.getLogger(__name__)


async def snapshot_loop(store, pool, interval: int = 300):
    """Take a usage snapshot every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        try:
            metrics = live_metrics.drain()
            store.record_snapshot(pool, metrics)
            logger.debug("Usage snapshot recorded")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Snapshot loop error: {e}")

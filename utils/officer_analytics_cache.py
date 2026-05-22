import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Optional

from config.postgredb import AsyncSessionLocal
from utils.redis_client import (
    DEFAULT_CACHE_TTL_SECONDS,
    cache_delete_pattern,
    cache_get_json,
    cache_set_json,
)

logger = logging.getLogger(__name__)

OFFICER_ANALYTICS_CACHE_KEY = "officer:analytics:payload:v1"
OFFICER_DISEASES_CACHE_KEY = "officer:analytics:diseases:v1"
OFFICER_ANALYTICS_REFRESH_INTERVAL_SECONDS = DEFAULT_CACHE_TTL_SECONDS

_analytics_refresh_task: asyncio.Task[None] | None = None


def _matches_filters(
    record: dict[str, Any],
    year: Optional[int] = None,
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
) -> bool:
    if year is not None and record.get("year") != year:
        return False
    if district_id is not None and record.get("district_id") != district_id:
        return False
    if disease_id is not None and record.get("disease_id") != disease_id:
        return False
    return True


async def refresh_officer_analytics_cache() -> dict[str, Any]:
    from controllers.reportController import (
        fetch_report_metadata,
        list_weekly_reports,
        fetch_officer_thresholds,
        fetch_officer_history_pattern,
    )

    # Build snapshot by reusing controller helpers where possible
    # metadata
    metadata = await fetch_report_metadata()

    # reports: paginate through list_weekly_reports to fetch all
    reports: list[dict[str, Any]] = []
    skip = 0
    limit = 200
    while True:
        page = await list_weekly_reports(limit=limit, skip=skip)
        batch = page.get("reports", [])
        reports.extend(batch)
        if len(batch) < limit:
            break
        skip += limit

    # thresholds
    thresholds = (await fetch_officer_thresholds()) or {"thresholds": []}

    # history pattern (larger limit)
    history = await fetch_officer_history_pattern(limit=2000)

    snapshot = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "reports": reports,
        "thresholds": thresholds.get("thresholds", []),
        "history": history.get("records", []),
    }

    await cache_set_json(OFFICER_ANALYTICS_CACHE_KEY, snapshot, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
    await cache_set_json(OFFICER_DISEASES_CACHE_KEY, metadata.get("diseases", []), ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
    return snapshot


async def get_officer_analytics_snapshot(force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = await cache_get_json(OFFICER_ANALYTICS_CACHE_KEY)
        if cached is not None:
            return cached

    return await refresh_officer_analytics_cache()


async def get_officer_analytics_payload(
    year: Optional[int] = None,
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
) -> dict[str, Any]:
    snapshot = await get_officer_analytics_snapshot()
    reports = [r for r in snapshot.get("reports", []) if _matches_filters(r, year=year, district_id=district_id, disease_id=disease_id)]
    history = [r for r in snapshot.get("history", []) if _matches_filters(r, year=year, district_id=district_id, disease_id=disease_id)]
    return {
        "refreshed_at": snapshot.get("refreshed_at"),
        "count": len(reports),
        "reports": reports,
        "thresholds": snapshot.get("thresholds", []),
        "history": history,
        "metadata": snapshot.get("metadata", {}),
    }


async def get_officer_diseases() -> list[dict[str, Any]]:
    cached = await cache_get_json(OFFICER_DISEASES_CACHE_KEY)
    if cached is not None:
        return cached

    snapshot = await get_officer_analytics_snapshot()
    return snapshot.get("metadata", {}).get("diseases", [])


async def invalidate_officer_analytics_cache() -> None:
    await cache_delete_pattern("officer:analytics:*")


async def _refresh_loop(interval_seconds: int) -> None:
    while True:
        try:
            await refresh_officer_analytics_cache()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - background refresh should not break requests
            logger.warning("Officer analytics refresh failed: %s", exc)

        await asyncio.sleep(interval_seconds)


def start_officer_analytics_background_service(
    interval_seconds: int = OFFICER_ANALYTICS_REFRESH_INTERVAL_SECONDS,
) -> asyncio.Task[None]:
    global _analytics_refresh_task

    if _analytics_refresh_task is not None and not _analytics_refresh_task.done():
        return _analytics_refresh_task

    _analytics_refresh_task = asyncio.create_task(_refresh_loop(interval_seconds))
    return _analytics_refresh_task


async def stop_officer_analytics_background_service() -> None:
    global _analytics_refresh_task

    if _analytics_refresh_task is None:
        return

    _analytics_refresh_task.cancel()
    with suppress(asyncio.CancelledError):
        await _analytics_refresh_task
    _analytics_refresh_task = None

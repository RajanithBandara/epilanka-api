import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from config.postgredb import AsyncSessionLocal
from models.diseaseModel import Disease
from models.districtModel import District
from models.historydataModel import HistoryData
from utils.redis_client import (
    DEFAULT_CACHE_TTL_SECONDS,
    cache_delete_pattern,
    cache_get_json,
    cache_set_json,
)

logger = logging.getLogger(__name__)

ADMIN_ANALYTICS_CACHE_KEY = "admin:analytics:historical-data:v1"
ADMIN_DISEASES_CACHE_KEY = "admin:analytics:diseases:v1"
ADMIN_ANALYTICS_REFRESH_INTERVAL_SECONDS = DEFAULT_CACHE_TTL_SECONDS

_analytics_refresh_task: asyncio.Task[None] | None = None


def _matches_filters(
    record: dict[str, Any],
    week_number: Optional[int] = None,
    year: Optional[int] = None,
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
) -> bool:
    if week_number is not None and record["week_number"] != week_number:
        return False
    if year is not None and record["year"] != year:
        return False
    if district_id is not None and record["district_id"] != district_id:
        return False
    if disease_id is not None and record["disease_id"] != disease_id:
        return False
    return True


async def refresh_admin_analytics_cache() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        historical_rows = (
            await session.execute(
                select(
                    HistoryData.data_id,
                    HistoryData.week_number,
                    HistoryData.year,
                    HistoryData.district_id,
                    District.district_name,
                    District.province_name,
                    HistoryData.disease_id,
                    Disease.disease_name,
                    HistoryData.case_count,
                )
                .join(District, HistoryData.district_id == District.district_id)
                .join(Disease, HistoryData.disease_id == Disease.disease_id)
                .order_by(
                    HistoryData.year.desc(),
                    HistoryData.week_number.desc(),
                    HistoryData.data_id.desc(),
                )
            )
        ).all()

        diseases_rows = (
            await session.execute(
                select(
                    Disease.disease_id,
                    Disease.disease_name,
                    Disease.description,
                ).order_by(Disease.disease_name)
            )
        ).all()

        snapshot = {
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "records": [
                {
                    "data_id": str(row[0]),
                    "week_number": row[1],
                    "year": row[2],
                    "district_id": row[3],
                    "district_name": row[4],
                    "province_name": row[5],
                    "disease_id": row[6],
                    "disease_name": row[7],
                    "case_count": row[8],
                }
                for row in historical_rows
            ],
            "diseases": [
                {
                    "disease_id": row[0],
                    "disease_name": row[1],
                    "description": row[2],
                }
                for row in diseases_rows
            ],
        }

    await cache_set_json(ADMIN_ANALYTICS_CACHE_KEY, snapshot, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
    await cache_set_json(
        ADMIN_DISEASES_CACHE_KEY,
        snapshot["diseases"],
        ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
    )
    return snapshot


async def get_admin_analytics_snapshot(force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = await cache_get_json(ADMIN_ANALYTICS_CACHE_KEY)
        if cached is not None:
            return cached

    return await refresh_admin_analytics_cache()


async def get_admin_historical_data(
    week_number: Optional[int] = None,
    year: Optional[int] = None,
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    payload = await get_admin_analytics_payload(
        week_number=week_number,
        year=year,
        district_id=district_id,
        disease_id=disease_id,
    )
    records = payload["records"]
    return records[skip : skip + limit]


async def get_admin_analytics_payload(
    week_number: Optional[int] = None,
    year: Optional[int] = None,
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
) -> dict[str, Any]:
    snapshot = await get_admin_analytics_snapshot()
    records = [
        record
        for record in snapshot.get("records", [])
        if _matches_filters(
            record,
            week_number=week_number,
            year=year,
            district_id=district_id,
            disease_id=disease_id,
        )
    ]
    return {
        "refreshed_at": snapshot.get("refreshed_at"),
        "count": len(records),
        "records": records,
    }


async def get_admin_diseases() -> list[dict[str, Any]]:
    cached = await cache_get_json(ADMIN_DISEASES_CACHE_KEY)
    if cached is not None:
        return cached

    snapshot = await get_admin_analytics_snapshot()
    return snapshot.get("diseases", [])


async def invalidate_admin_analytics_cache() -> None:
    await cache_delete_pattern("admin:analytics:*")


async def _refresh_loop(interval_seconds: int) -> None:
    while True:
        try:
            await refresh_admin_analytics_cache()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - background refresh should not break requests
            logger.warning("Admin analytics refresh failed: %s", exc)

        await asyncio.sleep(interval_seconds)


def start_admin_analytics_background_service(
    interval_seconds: int = ADMIN_ANALYTICS_REFRESH_INTERVAL_SECONDS,
) -> asyncio.Task[None]:
    global _analytics_refresh_task

    if _analytics_refresh_task is not None and not _analytics_refresh_task.done():
        return _analytics_refresh_task

    _analytics_refresh_task = asyncio.create_task(_refresh_loop(interval_seconds))
    return _analytics_refresh_task


async def stop_admin_analytics_background_service() -> None:
    global _analytics_refresh_task

    if _analytics_refresh_task is None:
        return

    _analytics_refresh_task.cancel()
    with suppress(asyncio.CancelledError):
        await _analytics_refresh_task
    _analytics_refresh_task = None
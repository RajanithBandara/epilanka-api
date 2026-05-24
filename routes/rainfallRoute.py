from fastapi import APIRouter, HTTPException, Query

from controllers.rainfallController import (
    fetch_and_store_rainfall_for_year,
    list_rainfall_records,
    update_rainfall_record,
)
from utils.auth_deps import get_current_admin, AppwriteUser
from fastapi import Depends
from pydantic import BaseModel
from typing import Optional

class RainfallUpdate(BaseModel):
    january: Optional[int] = None
    february: Optional[int] = None
    march: Optional[int] = None
    april: Optional[int] = None
    may: Optional[int] = None
    june: Optional[int] = None
    july: Optional[int] = None
    august: Optional[int] = None
    september: Optional[int] = None
    october: Optional[int] = None
    november: Optional[int] = None
    december: Optional[int] = None

router = APIRouter(prefix="/rainfall", tags=["rainfall"])


@router.post("/sync", status_code=200)
async def sync_rainfall_from_openmeteo(
    year: int | None = Query(
        default=None,
        description="Calendar year to fetch (defaults to the most recent fully-complete year).",
    ),
    concurrency: int = Query(
        default=4,
        ge=1,
        le=10,
        description="Number of concurrent Open-Meteo requests.",
    ),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Fetch monthly precipitation per district from Open-Meteo using stored
    coordinates and upsert into the ``rainfall_data`` table."""
    try:
        summary = await fetch_and_store_rainfall_for_year(
            year=year, concurrency=concurrency
        )
        return {
            "message": "Rainfall data synchronized from Open-Meteo",
            **summary,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/list", status_code=200)
async def get_rainfall_records():
    """Return all rainfall_data rows joined with district names."""
    try:
        records = await list_rainfall_records()
        return {"count": len(records), "records": records}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{district_id}", status_code=200)
async def update_rainfall(
    district_id: int,
    payload: RainfallUpdate,
    current: AppwriteUser = Depends(get_current_admin),
):
    """Partially update monthly rainfall for a district."""
    try:
        result = await update_rainfall_record(district_id, payload.model_dump(exclude_unset=True))
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["msg"])
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

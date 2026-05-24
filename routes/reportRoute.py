from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from pydantic import BaseModel, Field
from controllers.reportController import (
    fetchReportsbyLocation,
    fetchHistoricalChartData,
    fetch_report_metadata,
    create_weekly_report,
    list_weekly_reports,
    list_uploaded_reports_public,
)


router = APIRouter(prefix="/reports", tags=["reports"])


class WeeklyReportCreate(BaseModel):
    week_number: int = Field(..., ge=1, le=53)
    year: int = Field(..., ge=1900, le=2100)
    district_id: int
    disease_id: int
    actual_count: int = Field(..., ge=0)
    case_count: Optional[int] = Field(None, ge=0)


@router.get("/location", status_code=200)
async def get_reports_by_location(
    district_name: Optional[str] = Query(None, description="Filter by district name"),
    province_name: Optional[str] = Query(None, description="Filter by province name"),
    user_id: Optional[str] = Query(None, description="Current user id for vote status"),
    limit: int = Query(20, ge=1, le=100, description="Number of reports to return"),
    skip: int = Query(0, ge=0, description="Number of reports to skip (pagination)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back")
):

    return await fetchReportsbyLocation(
        district_name=district_name,
        province_name=province_name,
        user_id=user_id,
        limit=limit,
        skip=skip,
        days=days
    )

@router.get("/historical-chart", status_code=200)
async def get_historical_chart_data(
    district_name: str = Query(..., description="Filter by district name")
):
    return await fetchHistoricalChartData(district_name=district_name)


@router.get("/metadata", status_code=200)
async def get_report_metadata():
    return await fetch_report_metadata()


@router.get("/weekly-records", status_code=200)
async def get_weekly_records(
    district_id: Optional[int] = Query(None),
    disease_id: Optional[int] = Query(None),
    week_number: Optional[int] = Query(None, ge=1, le=53),
    year: Optional[int] = Query(None, ge=1900, le=2100),
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    return await list_weekly_reports(
        district_id=district_id,
        disease_id=disease_id,
        week_number=week_number,
        year=year,
        limit=limit,
        skip=skip,
    )


@router.get("/uploaded-records", status_code=200)
async def get_uploaded_records_public(
    year: Optional[int] = Query(None, ge=1900, le=2100),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """Public endpoint to list uploaded report PDFs (without uploader info)."""
    return await list_uploaded_reports_public(year=year, limit=limit, skip=skip)


@router.post("/weekly-records", status_code=201)
async def create_weekly_records(payload: WeeklyReportCreate):
    try:
        return await create_weekly_report(
            week_number=payload.week_number,
            year=payload.year,
            district_id=payload.district_id,
            disease_id=payload.disease_id,
            actual_count=payload.actual_count,
            case_count=payload.case_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

from fastapi import APIRouter, Query
from typing import Optional
from controllers.reportController import fetchReportsbyLocation


router = APIRouter(prefix="/reports", tags=["reports"])


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
    from controllers.reportController import fetchHistoricalChartData
    return await fetchHistoricalChartData(district_name=district_name)

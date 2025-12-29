from fastapi import APIRouter, Query
from typing import Optional
from controllers.reportController import fetchReportsbyLocation


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/location", status_code=200)
async def get_reports_by_location(
    district_name: Optional[str] = Query(None, description="Filter by district name"),
    province_name: Optional[str] = Query(None, description="Filter by province name"),
    limit: int = Query(20, ge=10, le=100, description="Number of reports to return"),
    skip: int = Query(0, ge=0, description="Number of reports to skip (pagination)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back")
):
    """
    Fetch recent disease reports by location.

    - **district_name**: Optional - Filter by specific district (e.g., "Colombo")
    - **province_name**: Optional - Filter by province (all districts in province)
    - **limit**: Number of reports to return (1-100, default: 20)
    - **skip**: Pagination offset (default: 0)
    - **days**: Days to look back (1-365, default: 30)

    **Examples:**
    - `/reports/location?district_name=Colombo&limit=10`
    - `/reports/location?province_name=Western&days=7`
    - `/reports/location?skip=20&limit=20` (all districts, page 2)
    """
    return await fetchReportsbyLocation(
        district_name=district_name,
        province_name=province_name,
        limit=limit,
        skip=skip,
        days=days
    )


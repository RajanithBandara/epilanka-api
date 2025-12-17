from fastapi import APIRouter, HTTPException

from controllers.mapController import fetch_nearest_area_from_postgres_only

router = APIRouter(prefix="/map", tags=["map"])

@router.get("/nearestlocation", status_code=200)
async def get_nearest_location(latitude: float, longitude: float):
    try:
        result = await fetch_nearest_area_from_postgres_only(latitude, longitude)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching nearest location: {e}")

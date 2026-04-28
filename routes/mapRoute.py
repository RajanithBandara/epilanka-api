from datetime import date

from fastapi import APIRouter, HTTPException

from controllers.mapController import fetch_nearest_area_from_postgres_only, fetch_all_districts_map_data, get_all_locations

router = APIRouter(prefix="/map", tags=["map"])

@router.get("/locations", status_code=200)
async def get_locations():
    """Get all available districts/locations for filtering"""
    try:
        result = await get_all_locations()
        return {"locations": result}
    except Exception as e:
        print(f"Error in locations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/nearestlocation", status_code=200)
async def get_nearest_location(latitude: float, longitude: float):
    try:
        result = await fetch_nearest_area_from_postgres_only(latitude, longitude)
        return result
    except Exception as e:
        print(f"Error in nearestlocation: {str(e)}")
        raise


@router.get("/alldistricts", status_code=200)
async def get_all_districts(target_date: date | None = None):
    """Get all districts with their risk levels and current alerts"""
    try:
        result = await fetch_all_districts_map_data(target_date)
        return result
    except Exception as e:
        print(f"Error in alldistricts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
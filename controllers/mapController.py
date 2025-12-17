from config.db import get_database
from config.postgredb import AsyncSessionLocal
from models.locationModel import LocationModel
from models.districtModel import District
from sqlalchemy import select, func

async def get_nearest_area_from_postgres(lat, lng):

    async with AsyncSessionLocal() as session:
        distance_expr = func.sqrt(
            func.pow(District.longitude - lat, 2) +
            func.pow(District.lattitude - lng, 2)
        )

        query = (
            select(
                District.district_id,
                District.district_name,
                District.longitude,  
                District.lattitude,  
                District.province_name,
                distance_expr.label('distance')
            )
            .order_by(distance_expr)
            .limit(1)
        )

        result = await session.execute(query)
        row = result.first()

        if row:
            return {
                "district_id": row[0],
                "district_name": row[1],
                "latitude": row[2],   
                "longitude": row[3],  
                "province_name": row[4],
                "distance": float(row[5])
            }

        return None


async def fetch_nearest_area_from_postgres_only(lat: float, lng: float):

    nearest_area = await get_nearest_area_from_postgres(lat, lng)

    if nearest_area:
        return {
            "user_location": {
                "latitude": lat,
                "longitude": lng
            },
            "nearest_area": nearest_area
        }
    else:
        return {
            "user_location": {
                "latitude": lat,
                "longitude": lng
            },
            "nearest_area": None,
            "message": "No districts found in database"
        }

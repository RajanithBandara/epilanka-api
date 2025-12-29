from datetime import datetime, timezone
from bson import ObjectId
from sqlalchemy import func, select

from config.db import get_database
from config.postgredb import AsyncSessionLocal
from models.user_reportModel import UserReport_Request
from models.districtModel import District


def get_current_week() -> int:
    return datetime.now().isocalendar()[1]


def get_current_year() -> int:
    return datetime.now().year


async def find_nearest_district(latitude: float, longitude: float):
    """
    Find the nearest district from PostgreSQL based on latitude and longitude.
    Returns district info with distance.
    """
    async with AsyncSessionLocal() as session:
        # Calculate distance using Euclidean distance formula
        distance_expr = func.sqrt(
            func.pow(District.longitude - longitude, 2) +
            func.pow(District.latitude - latitude, 2)
        )

        # Query to find nearest district
        query = (
            select(
                District.district_id,
                District.district_name,
                District.province_name,
                District.latitude,
                District.longitude,
                distance_expr.label('distance')
            )
            .order_by(distance_expr)
            .limit(1)
        )

        result = await session.execute(query)
        row = result.first()

        if row:
            # Convert distance to kilometers (approximate)
            distance_km = float(row[5]) * 111  # 1 degree ≈ 111 km

            return {
                "district_id": row[0],
                "district_name": row[1],
                "province_name": row[2],
                "district_latitude": row[3],
                "district_longitude": row[4],
                "distance_km": round(distance_km, 2)
            }

        return None


async def process_user_report(payload: UserReport_Request):
    """
    Process and save user disease report to MongoDB.
    Stores in epilanka->districtwisecases->{district_name} structure.
    """
    db = get_database()
    users_collection = db["users"]

    # Convert user_id to ObjectId if it's a string
    try:
        user_object_id = ObjectId(payload.user_id) if isinstance(payload.user_id, str) else payload.user_id
    except Exception:
        raise ValueError("Invalid user_id format")

    # Verify user exists
    user = users_collection.find_one({"_id": user_object_id})
    if not user:
        raise ValueError("User not found")

    # Find nearest district from PostgreSQL
    nearest_district = await find_nearest_district(payload.latitude, payload.longitude)

    if not nearest_district:
        raise ValueError("Could not find nearest district")

    # Prepare report document
    current_time = datetime.now(timezone.utc)
    current_week = get_current_week()
    current_year = get_current_year()

    # Extract district name for collection naming
    district_name = nearest_district["district_name"].replace(" ", "_").lower()
    district_collection_name = f"reports_{district_name}"
    district_collection = db[district_collection_name]

    # Build case report document
    case_doc = {
        "user_id": str(user_object_id),
        "description": payload.description,
        "user_latitude": payload.latitude,
        "user_longitude": payload.longitude,
        "district_info": {
            "district_id": nearest_district["district_id"],
            "district_name": nearest_district["district_name"],
            "province_name": nearest_district["province_name"],
            "distance_km": nearest_district["distance_km"]
        },
        "extracted_data": {
            "disease_name": payload.extracted_data.disease_name if payload.extracted_data else None,
            "disease_type": payload.extracted_data.disease_type if payload.extracted_data else "unknown",
            "cases_reported": payload.extracted_data.cases_reported if payload.extracted_data else None,
            "severity": payload.extracted_data.severity if payload.extracted_data else "unknown",
            "symptoms": payload.extracted_data.symptoms if payload.extracted_data else [],
            "time_period": payload.extracted_data.time_period if payload.extracted_data else None,
            "age_group": payload.extracted_data.age_group if payload.extracted_data else None,
            "location_specifics": payload.extracted_data.location_specifics if payload.extracted_data else None,
            "confidence": payload.extracted_data.confidence if payload.extracted_data else "low"
        },
        "week_number": current_week,
        "year": current_year,
        "status": "pending",
        "score": 0,
        "created_at": current_time,
        "updated_at": current_time
    }

    # Insert into district-specific collection
    result = district_collection.insert_one(case_doc)

    # Also maintain a reference in main user_reports collection for tracking
    user_reports_collection = db["user_reports"]
    user_reports_collection.insert_one({
        "report_id": result.inserted_id,
        "user_id": str(user_object_id),
        "district_collection": district_collection_name,
        "district_name": nearest_district["district_name"],
        "created_at": current_time
    })

    # Return response
    return {
        "report_id": str(result.inserted_id),
        "collection": district_collection_name,
        "nearest_location": {
            "district_name": nearest_district["district_name"],
            "province_name": nearest_district["province_name"],
            "distance_km": nearest_district["distance_km"]
        },
        "extracted_data": case_doc["extracted_data"],
        "created_at": current_time.isoformat()
    }

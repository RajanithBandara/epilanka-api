from google import genai
import json
import os
import math
from datetime import datetime, timezone
from sqlalchemy import select
from config.postgredb import AsyncSessionLocal
from config.db import get_database
from models.districtModel import District
from models.user_reportModel import UserReport_Request


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL_NAME = "gemini-2.5-flash"


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two coordinates using Haversine formula
    Returns distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


async def find_nearest_location(latitude: float, longitude: float) -> dict:
    """
    Find the nearest location (district) from PostgreSQL database
    """
    async with AsyncSessionLocal() as session:
        # Get all districts
        result = await session.execute(select(District))
        districts = result.scalars().all()

        if not districts:
            raise Exception("No districts found in database")

        # Find nearest district
        nearest_district = None
        min_distance = float('inf')

        for district in districts:
            distance = calculate_distance(
                latitude,
                longitude,
                district.latitude,  # Note: typo in DB schema
                district.longitude
            )

            if distance < min_distance:
                min_distance = distance
                nearest_district = district

        return {
            "district_id": nearest_district.district_id,
            "district_name": nearest_district.district_name,
            "province_name": nearest_district.province_name,
            "distance_km": round(min_distance, 2)
        }


async def extract_report_details(description: str) -> dict:
    """
    Analyze a free-text disease report and extract structured epidemiological data using AI.
    """
    prompt = f"""
You are an epidemiological information extraction system.

Extract and return ONLY valid JSON with these fields:
- disease_name (string or null)
- disease_type (bacterial / viral / parasitic / fungal / unknown)
- cases_reported (integer or null)
- time_period (string or null)
- confidence (high | medium | low)

User report:
\"\"\"
{description}
\"\"\"
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )

    try:
        extracted_data = json.loads(response.text)
        return extracted_data
    except Exception as e:
        # Return default structure if parsing fails
        return {
            "disease_name": None,
            "disease_type": "unknown",
            "cases_reported": None,
            "time_period": None,
            "confidence": "low",
            "error": str(e)
        }


async def get_next_report_id(db, collection_name: str) -> int:
    """
    Get the next report_id for a specific location collection
    """
    collection = db[collection_name]
    last_report = collection.find_one(sort=[("report_id", -1)])

    if last_report and "report_id" in last_report:
        return last_report["report_id"] + 1
    else:
        return 1


async def process_user_report(payload: UserReport_Request):
    """
    Main function to process user report:
    1. Extract AI data from description (including patient counts)
    2. Find nearest location from PostgreSQL
    3. Store in MongoDB under location-based collection
    4. Update location statistics
    """

    # Step 1: Extract details using AI
    extracted_data = await extract_report_details(payload.description)

    # Step 2: Find nearest location from PostgreSQL
    nearest_location = await find_nearest_location(payload.latitude, payload.longitude)

    # Step 3: Store in MongoDB
    db = get_database()

    # Collection name based on district name (sanitized)
    collection_name = f"reports_{nearest_location['district_name'].lower().replace(' ', '_')}"

    # Get next report ID for this location
    report_id = await get_next_report_id(db, collection_name)

    # Create comprehensive report document
    report_data = {
        "report_id": report_id,
        "user_id": payload.user_id,

        # Location information (nearest district, not exact user location for privacy)
        "location": {
            "district_id": nearest_location['district_id'],
            "district_name": nearest_location['district_name'],
            "province_name": nearest_location['province_name'],
            "district_latitude": nearest_location['district_latitude'],
            "district_longitude": nearest_location['district_longitude'],
            "distance_from_district_center_km": nearest_location['distance_km'],
            "location_specifics": extracted_data.get("location_specifics")
        },

        # Original report
        "description": payload.description,

        # Extracted disease information
        "disease_info": {
            "disease_name": extracted_data.get("disease_name"),
            "disease_type": extracted_data.get("disease_type"),
            "severity": extracted_data.get("severity"),
            "symptoms": extracted_data.get("symptoms", []),
            "confidence": extracted_data.get("confidence")
        },

        # Patient/case information
        "cases_info": {
            "cases_reported": extracted_data.get("cases_reported"),
            "age_group": extracted_data.get("age_group"),
            "time_period": extracted_data.get("time_period")
        },

        # Metadata
        "created_at": datetime.now(timezone.utc),
        "status": "pending_verification",  # Can be: pending_verification, verified, false_alarm
        "verified_by": None,
        "verification_date": None
    }

    # Insert into MongoDB collection
    collection = db[collection_name]
    result = collection.insert_one(report_data)

    # Step 4: Update location statistics
    await update_location_statistics(db, collection_name, extracted_data)

    return {
        "status": "success",
        "message": "Report submitted successfully",
        "data": {
            "report_id": report_id,
            "collection": collection_name,
            "nearest_location": {
                "district_name": nearest_location['district_name'],
                "province_name": nearest_location['province_name'],
                "distance_km": nearest_location['distance_km']
            },
            "extracted_data": {
                "disease_name": extracted_data.get("disease_name"),
                "disease_type": extracted_data.get("disease_type"),
                "cases_reported": extracted_data.get("cases_reported"),
                "time_period": extracted_data.get("time_period"),
                "confidence": extracted_data.get("confidence")
            },
            "mongodb_id": str(result.inserted_id)
        }
    }

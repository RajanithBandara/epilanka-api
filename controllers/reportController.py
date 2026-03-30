from typing import Optional
from datetime import datetime, timezone, timedelta
from config.db import get_database
from config.postgredb import AsyncSessionLocal
from sqlalchemy import select
from models.districtModel import District


async def fetchReportsbyLocation(
        district_name: Optional[str] = None,
        province_name: Optional[str] = None,
        limit: int = 20,
        skip: int = 0,
        days: int = 30
):
    """
    Fetch recent disease reports by location.

    Args:
        district_name: Filter by specific district (optional)
        province_name: Filter by province (optional)
        limit: Maximum number of reports to return
        skip: Number of reports to skip (for pagination)
        days: Number of days to look back (default: 30)

    Returns:
        List of recent reports with location and extracted data
    """
    db = get_database()

    # Calculate date threshold
    date_threshold = datetime.now(timezone.utc) - timedelta(days=days)

    # Build query based on filters
    if district_name:
        # Query specific district collection
        district_collection_name = f"reports_{district_name.replace(' ', '_').lower()}"
        collection = db[district_collection_name]

        query = {"created_at": {"$gte": date_threshold}}

        # Execute query for single district
        reports = list(collection.find(query).sort("created_at", -1).skip(skip).limit(limit))
        total = collection.count_documents(query)

        return {
            "total": total,
            "limit": limit,
            "skip": skip,
            "district": district_name,
            "reports": [
                {
                    "report_id": str(report["_id"]),
                    "user_id": report.get("user_id"),
                    "description": report.get("description"),
                    "district_info": report.get("district_info"),
                    "extracted_data": report.get("extracted_data"),
                    "week_number": report.get("week_number"),
                    "year": report.get("year"),
                    "status": report.get("status"),
                    "created_at": report.get("created_at").isoformat() if report.get("created_at") else None
                }
                for report in reports
            ]
        }

    elif province_name:
        # Query all district collections in the province
        # First, get districts in the province from PostgreSQL
        async with AsyncSessionLocal() as session:
            districts_query = select(District.district_name).where(
                District.province_name == province_name
            )
            result = await session.execute(districts_query)
            districts = [row[0] for row in result.fetchall()]

        # Aggregate reports from all district collections in the province
        all_reports = []
        for district in districts:
            district_collection_name = f"reports_{district.replace(' ', '_').lower()}"
            if district_collection_name in db.list_collection_names():
                collection = db[district_collection_name]
                reports = list(collection.find(
                    {"created_at": {"$gte": date_threshold}}
                ).sort("created_at", -1))
                all_reports.extend(reports)

        # Sort combined results by created_at
        all_reports.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)

        # Apply pagination
        paginated_reports = all_reports[skip:skip + limit]

        return {
            "total": len(all_reports),
            "limit": limit,
            "skip": skip,
            "reports": [
                {
                    "report_id": str(report["_id"]),
                    "user_id": report.get("user_id"),
                    "description": report.get("description"),
                    "district_info": report.get("district_info"),
                    "extracted_data": report.get("extracted_data"),
                    "week_number": report.get("week_number"),
                    "year": report.get("year"),
                    "status": report.get("status"),
                    "created_at": report.get("created_at").isoformat() if report.get("created_at") else None
                }
                for report in paginated_reports
            ]
        }

    else:
        # Query all district collections
        all_reports = []
        district_collections = [
            name for name in db.list_collection_names()
            if name.startswith("reports_")
        ]

        for collection_name in district_collections:
            collection = db[collection_name]
            reports = list(collection.find(
                {"created_at": {"$gte": date_threshold}}
            ).sort("created_at", -1))
            all_reports.extend(reports)

        # Sort combined results
        all_reports.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)

        # Apply pagination
        paginated_reports = all_reports[skip:skip + limit]

        return {
            "total": len(all_reports),
            "limit": limit,
            "skip": skip,
            "reports": [
                {
                    "report_id": str(report["_id"]),
                    "user_id": report.get("user_id"),
                    "description": report.get("description"),
                    "district_info": report.get("district_info"),
                    "extracted_data": report.get("extracted_data"),
                    "week_number": report.get("week_number"),
                    "year": report.get("year"),
                    "status": report.get("status"),
                    "created_at": report.get("created_at").isoformat() if report.get("created_at") else None
                }
                for report in paginated_reports
            ]
        }
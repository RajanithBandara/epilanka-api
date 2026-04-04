from typing import Optional
from datetime import datetime, timezone, timedelta
from config.db import get_database
from config.postgredb import AsyncSessionLocal
from sqlalchemy import select
from models.districtModel import District
from models.historydataModel import HistoryData
from models.diseaseModel import Disease
from collections import defaultdict


async def fetchReportsbyLocation(
        district_name: Optional[str] = None,
        province_name: Optional[str] = None,
    user_id: Optional[str] = None,
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

    # Build vote lookup keys for has_voted flag
    vote_keys = set()
    if user_id:
        users = db["users"]
        user_doc = users.find_one({"appwrite_id": user_id})
        if user_doc:
            vote_keys.add(user_id)
            vote_keys.add(str(user_doc.get("_id")))
        else:
            try:
                from bson import ObjectId
                object_id = ObjectId(user_id)
                user_doc = users.find_one({"_id": object_id})
                if user_doc:
                    vote_keys.add(str(object_id))
                    appwrite_id = user_doc.get("appwrite_id")
                    if appwrite_id:
                        vote_keys.add(appwrite_id)
            except Exception:
                # Ignore invalid ObjectId format here; has_voted will remain false.
                pass

    def serialize_report(report):
        voted_users = report.get("voted_users", []) or []
        has_voted = any(key in voted_users for key in vote_keys) if vote_keys else False
        return {
            "report_id": str(report["_id"]),
            "user_id": report.get("user_id"),
            "description": report.get("description"),
            "district_info": report.get("district_info"),
            "extracted_data": report.get("extracted_data"),
            "week_number": report.get("week_number"),
            "year": report.get("year"),
            "status": report.get("status"),
            "score": report.get("score", 0),
            "has_voted": has_voted,
            "created_at": report.get("created_at").isoformat() if report.get("created_at") else None,
        }

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
            "reports": [serialize_report(report) for report in reports]
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
            "reports": [serialize_report(report) for report in paginated_reports]
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
            "reports": [serialize_report(report) for report in paginated_reports]
        }

async def fetchHistoricalChartData(district_name: str):
    """
    Fetch historical disease case data formatted for charts by district.
    """
    async with AsyncSessionLocal() as session:
        query = (
            select(HistoryData.year, HistoryData.week_number, Disease.disease_name, HistoryData.case_count)
            .join(District, HistoryData.district_id == District.district_id)
            .join(Disease, HistoryData.disease_id == Disease.disease_id)
            .where(District.district_name == district_name)
            .order_by(HistoryData.year, HistoryData.week_number)
        )
        result = await session.execute(query)
        
        grouped = defaultdict(dict)
        for year, week, disease_name, count in result:
            key = f"{year}-W{week:02d}"
            if "period" not in grouped[key]:
                grouped[key]["period"] = key
                grouped[key]["year"] = year
                grouped[key]["week"] = week
            
            # Add or sum the case counts per disease
            if disease_name in grouped[key]:
                grouped[key][disease_name] += count
            else:
                grouped[key][disease_name] = count
                
        return list(grouped.values())

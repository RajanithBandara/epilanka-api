from typing import Optional, List
from datetime import datetime, timezone, timedelta
from config.db import get_database
from config.postgredb import AsyncSessionLocal
from sqlalchemy import select, func, text
from models.districtModel import District
from models.historydataModel import HistoryData
from models.diseaseModel import Disease
from models.reportsModel import Report
from models.riskModel import RiskLevel
from collections import defaultdict
from utils.redis_client import (
    cache_get_json,
    cache_set_json,
    cache_delete_pattern,
    DEFAULT_CACHE_TTL_SECONDS,
)
from utils.officer_analytics_cache import invalidate_officer_analytics_cache


def _cache_key_safe(value: str) -> str:
    return "_".join(value.strip().lower().split())


def _cache_key_value(value: Optional[int]) -> str:
    return "all" if value is None else str(value)


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
    district_key = _cache_key_safe(district_name)
    cache_key = f"reports:historical-chart:v1:{district_key}"
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

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

        response = list(grouped.values())
        await cache_set_json(cache_key, response, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
        return response


async def fetch_report_metadata():
    """Return districts and diseases for report submission forms."""
    cache_key = "reports:metadata:v2"
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as session:
        districts_result = await session.execute(
            select(
                District.district_id,
                District.district_name,
                District.province_name,
                District.latitude,
                District.longitude,
            ).order_by(District.district_name)
        )
        diseases_result = await session.execute(
            select(Disease.disease_id, Disease.disease_name).order_by(Disease.disease_name)
        )
        history_disease_years_result = await session.execute(
            select(HistoryData.disease_id, HistoryData.year).distinct()
        )
        reports_disease_years_result = await session.execute(
            select(Report.disease_id, Report.year).distinct()
        )

        years_set: set[int] = set()
        disease_years_map: dict[int, set[int]] = defaultdict(set)

        for disease_id_val, year_val in history_disease_years_result.fetchall():
            if year_val is None:
                continue
            years_set.add(year_val)
            if disease_id_val is not None:
                disease_years_map[disease_id_val].add(year_val)

        for disease_id_val, year_val in reports_disease_years_result.fetchall():
            if year_val is None:
                continue
            years_set.add(year_val)
            if disease_id_val is not None:
                disease_years_map[disease_id_val].add(year_val)

        all_years = sorted(list(years_set), reverse=True)
        disease_years = {
            str(did): sorted(list(years), reverse=True)
            for did, years in disease_years_map.items()
        }

        response = {
            "districts": [
                {
                    "district_id": row[0],
                    "district_name": row[1],
                    "province_name": row[2],
                    "latitude": row[3],
                    "longitude": row[4],
                }
                for row in districts_result.fetchall()
            ],
            "diseases": [
                {"disease_id": row[0], "disease_name": row[1]}
                for row in diseases_result.fetchall()
            ],
            "years": all_years,
            "disease_years": disease_years,
        }
        await cache_set_json(cache_key, response, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
        return response


async def create_weekly_report(
    week_number: int,
    year: int,
    district_id: int,
    disease_id: int,
    actual_count: int,
    case_count: Optional[int] = None,
):
    """Update only actual_count for an existing predicted weekly row.

    Matching key: week/year/district/disease.
    case_count (predicted value) is never changed by this workflow.
    """
    async with AsyncSessionLocal() as session:
        district = await session.get(District, district_id)
        if not district:
            raise ValueError(f"Invalid district_id: {district_id}")

        disease = await session.get(Disease, disease_id)
        if not disease:
            raise ValueError(f"Invalid disease_id: {disease_id}")

        existing_query = select(Report).where(
            Report.week_number == week_number,
            Report.year == year,
            Report.district_id == district_id,
            Report.disease_id == disease_id,
        )
        existing_report = (await session.execute(existing_query)).scalars().first()

        if not existing_report:
            raise ValueError(
                "No predicted record found for the selected week, year, district, and disease"
            )

        existing_report.actual_count = actual_count
        await session.commit()
        await session.refresh(existing_report)

        # Weekly analytics depend on this table, so clear cached slices.
        await cache_delete_pattern("reports:weekly-records:v1:*")
        # Invalidate officer analytics snapshot as well
        await invalidate_officer_analytics_cache()

        return {
            "report_id": str(existing_report.report_id),
            "week_number": existing_report.week_number,
            "year": existing_report.year,
            "district_id": existing_report.district_id,
            "district_name": district.district_name,
            "province_name": district.province_name,
            "disease_id": existing_report.disease_id,
            "disease_name": disease.disease_name,
            "case_count": existing_report.case_count,
            "actual_count": existing_report.actual_count,
        }


async def bulk_upsert_weekly_reports(
    week_number: int,
    year: int,
    disease_id: int,
    entries: List[dict],
) -> dict:
    """
    Upsert actual_count for multiple districts in one INSERT ... ON CONFLICT query.

    `entries` is a list of {district_id: int, actual_count: int}.
    Only rows where the predicted record already exists are updated;
    rows with no matching predicted record are skipped and reported back.
    """
    if not entries:
        return {"updated": 0, "skipped": [], "message": "No entries provided"}

    # Build a VALUES list and update each actual_count where the row exists.
    # We use a raw SQL ON CONFLICT targeting the natural key so this is a
    # single round-trip regardless of how many districts are submitted.
    async with AsyncSessionLocal() as session:
        # Collect district ids that actually have a predicted record for this
        # week/year/disease combination so we can report skipped ones.
        existing_query = select(Report.district_id).where(
            Report.week_number == week_number,
            Report.year == year,
            Report.disease_id == disease_id,
            Report.district_id.in_([e["district_id"] for e in entries]),
        )
        existing_district_ids = set(
            (await session.execute(existing_query)).scalars().all()
        )

        rows_to_update = [
            e for e in entries if e["district_id"] in existing_district_ids
        ]
        skipped_ids = [
            e["district_id"] for e in entries if e["district_id"] not in existing_district_ids
        ]

        if rows_to_update:
            # Build parameterised SQL for bulk update
            cases = " ".join(
                f"WHEN district_id = {row['district_id']} THEN {int(row['actual_count'])}"
                for row in rows_to_update
            )
            district_ids_str = ", ".join(str(row["district_id"]) for row in rows_to_update)

            stmt = text(
                f"""
                UPDATE reports
                SET actual_count = CASE {cases} END
                WHERE week_number = :week_number
                  AND year       = :year
                  AND disease_id = :disease_id
                  AND district_id IN ({district_ids_str})
                """
            )
            await session.execute(
                stmt,
                {"week_number": week_number, "year": year, "disease_id": disease_id},
            )
            await session.commit()

        # Bust related cache entries.
        await cache_delete_pattern("reports:weekly-records:v1:*")
        # Invalidate officer analytics snapshot as well
        await invalidate_officer_analytics_cache()
        return {
            "updated": len(rows_to_update),
            "skipped": skipped_ids,
            "message": (
                f"{len(rows_to_update)} record(s) updated."
                + (f" {len(skipped_ids)} district(s) had no predicted record and were skipped." if skipped_ids else "")
            ),
        }


async def list_weekly_reports(
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
    week_number: Optional[int] = None,
    year: Optional[int] = None,
    limit: int = 20,
    skip: int = 0,
):
    """List weekly reports with district and disease names."""
    cache_key = (
        "reports:weekly-records:v1:"
        f"district:{_cache_key_value(district_id)}:"
        f"disease:{_cache_key_value(disease_id)}:"
        f"week:{_cache_key_value(week_number)}:"
        f"year:{_cache_key_value(year)}:"
        f"limit:{limit}:skip:{skip}"
    )
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as session:
        filters = []
        if district_id is not None:
            filters.append(Report.district_id == district_id)
        if disease_id is not None:
            filters.append(Report.disease_id == disease_id)
        if week_number is not None:
            filters.append(Report.week_number == week_number)
        if year is not None:
            filters.append(Report.year == year)

        total_query = select(func.count()).select_from(Report)
        if filters:
            total_query = total_query.where(*filters)
        total = int((await session.execute(total_query)).scalar() or 0)

        query = (
            select(
                Report,
                District.district_name,
                District.province_name,
                Disease.disease_name,
            )
            .join(District, Report.district_id == District.district_id)
            .join(Disease, Report.disease_id == Disease.disease_id)
            .order_by(Report.year.desc(), Report.week_number.desc(), Report.report_id.desc())
            .offset(skip)
            .limit(limit)
        )
        if filters:
            query = query.where(*filters)

        rows = (await session.execute(query)).all()

        response = {
            "total": total,
            "limit": limit,
            "skip": skip,
            "reports": [
                {
                    "report_id": str(report.report_id),
                    "week_number": report.week_number,
                    "year": report.year,
                    "district_id": report.district_id,
                    "district_name": district_name,
                    "province_name": province_name,
                    "disease_id": report.disease_id,
                    "disease_name": disease_name,
                    "case_count": report.case_count,
                    "actual_count": report.actual_count,
                }
                for report, district_name, province_name, disease_name in rows
            ],
        }
        await cache_set_json(cache_key, response, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
        return response


async def fetch_officer_thresholds(
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
):
    cache_key = (
        "officer:analytics:thresholds:v1:"
        f"district:{_cache_key_value(district_id)}:"
        f"disease:{_cache_key_value(disease_id)}"
    )
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as session:
        query = (
            select(RiskLevel, Disease.disease_name)
            .join(Disease, RiskLevel.disease_id == Disease.disease_id)
            .order_by(RiskLevel.year.desc(), RiskLevel.week_number.desc(), RiskLevel.calculated_at.desc())
        )

        if district_id is not None:
            query = query.where(RiskLevel.district_id == district_id)
        if disease_id is not None:
            query = query.where(RiskLevel.disease_id == disease_id)

        rows = (await session.execute(query)).all()

        latest_by_disease: dict[int, dict] = {}
        for risk, disease_name in rows:
            if risk.disease_id in latest_by_disease:
                continue
            latest_by_disease[risk.disease_id] = {
                "risk_id": str(risk.risk_id),
                "district_id": risk.district_id,
                "disease_id": risk.disease_id,
                "disease_name": disease_name,
                "week_number": risk.week_number,
                "year": risk.year,
                "risk_level": risk.risk_level,
                "lower_threshold": risk.lower_threshold,
                "upper_threshold": risk.upper_threshold,
                "outbreak_threshold": risk.outbreak_threshold,
                "risk_score": risk.risk_score,
                "calculated_at": risk.calculated_at.isoformat() if risk.calculated_at else None,
            }

        response = {
            "count": len(latest_by_disease),
            "thresholds": sorted(latest_by_disease.values(), key=lambda x: x["disease_name"].lower()),
        }
        await cache_set_json(cache_key, response, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
        return response


async def fetch_officer_history_pattern(
    district_id: Optional[int] = None,
    disease_id: Optional[int] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    limit: int = 400,
):
    cache_key = (
        "officer:analytics:history-pattern:v1:"
        f"district:{_cache_key_value(district_id)}:"
        f"disease:{_cache_key_value(disease_id)}:"
        f"from:{_cache_key_value(year_from)}:"
        f"to:{_cache_key_value(year_to)}:"
        f"limit:{limit}"
    )
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as session:
        query = (
            select(
                HistoryData.year,
                HistoryData.week_number,
                HistoryData.case_count,
                HistoryData.disease_id,
                Disease.disease_name,
                HistoryData.district_id,
                District.district_name,
                District.province_name,
            )
            .join(Disease, HistoryData.disease_id == Disease.disease_id)
            .join(District, HistoryData.district_id == District.district_id)
        )

        if district_id is not None:
            query = query.where(HistoryData.district_id == district_id)
        if disease_id is not None:
            query = query.where(HistoryData.disease_id == disease_id)
        if year_from is not None:
            query = query.where(HistoryData.year >= year_from)
        if year_to is not None:
            query = query.where(HistoryData.year <= year_to)

        rows = (
            (await session.execute(query.order_by(HistoryData.year.desc(), HistoryData.week_number.desc()).limit(limit)))
            .all()
        )

        records = [
            {
                "year": row[0],
                "week_number": row[1],
                "case_count": row[2],
                "disease_id": row[3],
                "disease_name": row[4],
                "district_id": row[5],
                "district_name": row[6],
                "province_name": row[7],
            }
            for row in rows
        ]

        records.reverse()

        response = {
            "count": len(records),
            "records": records,
        }
        await cache_set_json(cache_key, response, ttl_seconds=DEFAULT_CACHE_TTL_SECONDS)
        return response

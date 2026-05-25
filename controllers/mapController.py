from datetime import date, datetime
from sqlalchemy import select, func, and_

from config.postgredb import AsyncSessionLocal
from models.districtModel import District
from models.reportsModel import Report
from models.diseaseModel import Disease
from models.riskModel import RiskLevel


def get_current_week_and_year() -> tuple[int, int]:
    """Return today's ISO (week_number, year)."""
    iso = datetime.now().isocalendar()
    return int(iso[1]), int(iso[0])


def get_current_week() -> int:
    return get_current_week_and_year()[0]


def get_current_year() -> int:
    return get_current_week_and_year()[1]


def get_week_and_year_for_date(target_date: date | None) -> tuple[int, int]:
    """Resolve a (week, year) for an explicit date, or the current week if None."""
    if target_date is None:
        return get_current_week_and_year()
    iso = target_date.isocalendar()
    return int(iso[1]), int(iso[0])


def normalize_risk_level(level: str | None) -> str | None:
    if not level:
        return None

    normalized = level.strip().lower()
    if normalized in {"safe", "low", "medium", "high"}:
        return normalized

    if "high" in normalized:
        return "high"
    if "medium" in normalized or "moderate" in normalized:
        return "medium"
    if "low" in normalized:
        return "low"
    if "safe" in normalized or "normal" in normalized:
        return "safe"

    return None


async def resolve_map_period(
    session, target_date: date | None = None
) -> tuple[int, int]:
    """Resolve the (week_number, year) the map endpoints should query.

    Defaults to the current ISO week (from ``datetime.now()``). The optional
    ``session`` argument is accepted for symmetry but not used; callers may
    pass ``None``.
    """
    _ = session  # kept for backwards compatibility with previous signature
    return get_week_and_year_for_date(target_date)


async def get_risk_levels_lookup(session, week_number: int, year: int) -> dict[tuple[int, int], str]:
    risk_query = (
        select(
            RiskLevel.district_id,
            RiskLevel.disease_id,
            RiskLevel.risk_level,
            RiskLevel.calculated_at,
            RiskLevel.risk_id,
        )
        .where(
            and_(
                RiskLevel.week_number == week_number,
                RiskLevel.year == year,
            )
        )
        .order_by(
            RiskLevel.district_id,
            RiskLevel.disease_id,
            RiskLevel.calculated_at.desc(),
            RiskLevel.risk_id.desc(),
        )
    )

    rows = (await session.execute(risk_query)).all()

    latest_lookup: dict[tuple[int, int], str] = {}
    for district_id, disease_id, risk_level, _, _ in rows:
        key = (int(district_id), int(disease_id))
        if key in latest_lookup:
            continue

        normalized = normalize_risk_level(risk_level)
        if normalized:
            latest_lookup[key] = normalized

    return latest_lookup


async def get_all_diseases(session):
    query = select(Disease.disease_id, Disease.disease_name)
    result = await session.execute(query)
    return result.all()


async def get_nearest_area_with_risk_levels(lat, lng):
    async with AsyncSessionLocal() as session:
        current_week, current_year = await resolve_map_period(session)
        risk_levels_lookup = await get_risk_levels_lookup(session, current_week, current_year)

        diseases = await get_all_diseases(session)

        distance_expr = func.sqrt(
            func.pow(District.longitude - lng, 2) +
            func.pow(District.latitude - lat, 2)
        )

        district_query = (
            select(
                District.district_id,
                District.district_name,
                District.latitude,
                District.longitude,
                District.province_name,
                distance_expr.label('distance'),
            )
            .order_by(distance_expr)
            .limit(1)
        )

        nearest = (await session.execute(district_query)).first()
        if not nearest:
            return None

        district_id = int(nearest[0])

        case_count_lookup = await get_projected_cases_for_district(
            session, district_id, current_week, current_year
        )

        risk_levels = {}
        for disease_id, disease_name in diseases:
            case_count = int(case_count_lookup.get(int(disease_id), 0))
            table_risk_level = risk_levels_lookup.get((district_id, int(disease_id)))
            risk_levels[f'disease_{disease_id}'] = {
                'disease_id': disease_id,
                'disease_name': disease_name,
                'count': case_count,
                'level': table_risk_level if table_risk_level else get_risk_level(case_count),
            }

        return {
            "district_id": nearest[0],
            "district_name": nearest[1],
            "latitude": nearest[2],
            "longitude": nearest[3],
            "province_name": nearest[4],
            "distance": float(nearest[5]),
            "week_number": current_week,
            "year": current_year,
            "risk_levels": risk_levels,
        }


async def get_projected_cases_for_district(
    session, district_id: int, week_number: int, year: int
) -> dict[int, int]:
    """Return a {disease_id: summed_case_count} map for one district + week."""
    query = (
        select(Report.disease_id, func.sum(Report.case_count).label('total'))
        .where(
            and_(
                Report.district_id == district_id,
                Report.week_number == week_number,
                Report.year == year,
            )
        )
        .group_by(Report.disease_id)
    )
    rows = (await session.execute(query)).all()
    return {int(disease_id): int(total or 0) for disease_id, total in rows}


def get_risk_level(case_count: int) -> str:
    if case_count <= 0:
        return "safe"
    elif case_count < 5:
        return "low"
    elif case_count < 15:
        return "medium"
    else:
        return "high"


async def fetch_nearest_area_from_postgres_only(lat: float, lng: float):
    nearest_area = await get_nearest_area_with_risk_levels(lat, lng)

    if nearest_area:
        current_alerts = build_current_alerts(nearest_area["risk_levels"])
        return {
            "user_location": {
                "latitude": lat,
                "longitude": lng
            },
            "nearest_area": nearest_area,
            "current_alerts": current_alerts,
            "warning": generate_warning(nearest_area["risk_levels"]),
            "data_period": f"Week {nearest_area['week_number']}, {nearest_area['year']}"
        }
    else:
        return {
            "user_location": {
                "latitude": lat,
                "longitude": lng
            },
            "nearest_area": None,
            "current_alerts": [],
            "message": "No districts found in database"
        }


def build_current_alerts(risk_levels: dict) -> list[dict]:
    alerts = []

    for disease_data in risk_levels.values():
        if disease_data["level"] in ["medium", "high"]:
            alerts.append(
                {
                    "disease_id": disease_data["disease_id"],
                    "disease_name": disease_data["disease_name"],
                    "level": disease_data["level"],
                    "count": disease_data["count"],
                }
            )

    severity_order = {"high": 2, "medium": 1, "low": 0, "safe": 0}
    alerts.sort(key=lambda x: (severity_order.get(x["level"], 0), x["count"]), reverse=True)
    return alerts


def generate_warning(risk_levels: dict) -> str:
    warnings = []

    for disease_key, disease_data in risk_levels.items():
        if disease_data["level"] in ["medium", "high"]:
            warnings.append(
                f"{disease_data['disease_name']}: {disease_data['level']} risk "
                f"({disease_data['count']} cases)"
            )

    if warnings:
        return "⚠️ " + " | ".join(warnings)

    return "✅ Area is safe this week"


async def get_all_districts_with_risks(target_date: date | None = None):
    """Get risk data for all districts in Sri Lanka.

    The week/year resolves to ``target_date``'s ISO week when provided, or
    the current ISO week from ``datetime.now()`` otherwise — matching what
    ``/map/nearestlocation`` uses so both views stay aligned.
    """
    async with AsyncSessionLocal() as session:
        current_week, current_year = await resolve_map_period(session, target_date)
        risk_levels_lookup = await get_risk_levels_lookup(session, current_week, current_year)

        diseases = await get_all_diseases(session)

        district_query = (
            select(
                District.district_id,
                District.district_name,
                District.latitude,
                District.longitude,
                District.province_name,
            )
            .order_by(District.district_id)
        )
        district_rows = (await session.execute(district_query)).all()

        # One aggregate query for all districts × diseases this week.
        counts_query = (
            select(
                Report.district_id,
                Report.disease_id,
                func.sum(Report.case_count).label('total'),
            )
            .where(
                and_(
                    Report.week_number == current_week,
                    Report.year == current_year,
                )
            )
            .group_by(Report.district_id, Report.disease_id)
        )
        counts_rows = (await session.execute(counts_query)).all()
        counts_lookup: dict[tuple[int, int], int] = {
            (int(d_id), int(dis_id)): int(total or 0)
            for d_id, dis_id, total in counts_rows
        }

        districts_data = []
        for row in district_rows:
            district_id = int(row[0])
            risk_levels = {}
            for disease_id, disease_name in diseases:
                case_count = counts_lookup.get((district_id, int(disease_id)), 0)
                table_risk_level = risk_levels_lookup.get((district_id, int(disease_id)))
                risk_levels[f'disease_{disease_id}'] = {
                    'disease_id': disease_id,
                    'disease_name': disease_name,
                    'count': case_count,
                    'level': table_risk_level if table_risk_level else get_risk_level(case_count),
                }

            max_risk = "safe"
            risk_priority = {"safe": 0, "low": 1, "medium": 2, "high": 3}
            for risk_data in risk_levels.values():
                if risk_priority[risk_data['level']] > risk_priority[max_risk]:
                    max_risk = risk_data['level']

            districts_data.append({
                "district_id": row[0],
                "district_name": row[1],
                "latitude": float(row[2]),
                "longitude": float(row[3]),
                "province_name": row[4],
                "overall_risk": max_risk,
                "week_number": current_week,
                "year": current_year,
                "risk_levels": risk_levels,
            })

        return districts_data


async def fetch_all_districts_map_data(target_date: date | None = None):
    """Fetch all districts with alerts and warnings."""
    current_week, current_year = get_week_and_year_for_date(target_date)
    districts = await get_all_districts_with_risks(target_date)
    
    # Build alerts across all districts
    all_alerts = []
    for district in districts:
        alerts = build_current_alerts(district["risk_levels"])
        all_alerts.extend([
            {
                **alert,
                "district_name": district["district_name"],
                "province_name": district["province_name"],
                "district_id": district["district_id"]
            }
            for alert in alerts
        ])
    
    # Sort alerts by severity
    severity_order = {"high": 2, "medium": 1, "low": 0, "safe": 0}
    all_alerts.sort(key=lambda x: (severity_order.get(x["level"], 0), x["count"]), reverse=True)
    
    return {
        "districts": districts,
        "current_alerts": all_alerts[:10],  # Top 10 alerts
        "total_alerts": len(all_alerts),
        "data_period": f"Week {current_week}, {current_year}",
        "week_number": current_week,
        "year": current_year,
        "selected_date": (target_date.isoformat() if target_date else datetime.now().date().isoformat()),
        "high_risk_count": sum(1 for d in districts if d["overall_risk"] == "high"),
        "medium_risk_count": sum(1 for d in districts if d["overall_risk"] == "medium"),
        "low_risk_count": sum(1 for d in districts if d["overall_risk"] == "low"),
        "safe_count": sum(1 for d in districts if d["overall_risk"] == "safe"),
    }


async def get_all_locations():
    """Get all districts/locations sorted by name for dropdown"""
    async with AsyncSessionLocal() as session:
        query = select(
            District.district_id,
            District.district_name,
            District.province_name
        ).order_by(District.district_name)
        
        result = await session.execute(query)
        districts = result.all()
        
        return [
            {
                "district_id": row[0],
                "district_name": row[1],
                "province_name": row[2]
            }
            for row in districts
        ]

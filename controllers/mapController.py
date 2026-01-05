from datetime import datetime
from sqlalchemy import select, func, and_
from sqlalchemy.orm import aliased

from config.postgredb import AsyncSessionLocal
from models.districtModel import District
from models.reportsModel import Report
from models.diseaseModel import Disease


def get_current_week() -> int:
    return datetime.now().isocalendar()[1]


def get_current_year() -> int:
    return datetime.now().year


async def get_all_diseases():
    async with AsyncSessionLocal() as session:
        query = select(Disease.disease_id, Disease.disease_name)
        result = await session.execute(query)
        return result.all()


async def get_nearest_area_with_risk_levels(lat, lng):
    async with AsyncSessionLocal() as session:
        current_week = get_current_week()
        current_year = get_current_year()

        # Fetch all diseases
        diseases = await get_all_diseases()

        distance_expr = func.sqrt(
            func.pow(District.longitude - lng, 2) +
            func.pow(District.latitude - lat, 2)
        )

        # Create aliases and build select columns dynamically
        disease_aliases = {}
        select_columns = [
            District.district_id,
            District.district_name,
            District.latitude,
            District.longitude,
            District.province_name,
            distance_expr.label('distance')
        ]

        # Build dynamic columns and joins for each disease
        query = select(*select_columns)

        for disease_id, disease_name in diseases:
            alias = aliased(Report)
            disease_aliases[disease_id] = {
                'alias': alias,
                'name': disease_name
            }

            # Add count column for this disease
            count_expr = func.coalesce(
                func.sum(alias.case_count).filter(
                    and_(
                        alias.disease_id == disease_id,
                        alias.week_number == current_week,
                        alias.year == current_year
                    )
                ), 0
            ).label(f'disease_{disease_id}_count')

            query = query.add_columns(count_expr)

            # Add outer join for this disease
            query = query.outerjoin(alias, and_(
                District.district_id == alias.district_id,
                alias.disease_id == disease_id,
                alias.week_number == current_week,
                alias.year == current_year
            ))

        # Complete the query
        query = (
            query
            .group_by(
                District.district_id,
                District.district_name,
                District.latitude,
                District.longitude,
                District.province_name
            )
            .order_by(distance_expr)
            .limit(1)
        )

        result = await session.execute(query)
        row = result.first()

        if row:
            # Build risk levels dynamically
            risk_levels = {}
            for idx, (disease_id, disease_name) in enumerate(diseases):
                case_count = int(row[6 + idx])  # Start from index 6 (after basic district info)
                risk_levels[f'disease_{disease_id}'] = {
                    'disease_id': disease_id,
                    'disease_name': disease_name,
                    'count': case_count,
                    'level': get_risk_level(case_count)
                }

            return {
                "district_id": row[0],
                "district_name": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "province_name": row[4],
                "distance": float(row[5]),
                "week_number": current_week,
                "year": current_year,
                "risk_levels": risk_levels
            }

        return None


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
        return {
            "user_location": {
                "latitude": lat,
                "longitude": lng
            },
            "nearest_area": nearest_area,
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
            "message": "No districts found in database"
        }


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

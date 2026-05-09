from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_
from datetime import datetime
from models.diseaseModel import Disease
from models.reportsModel import Report
from models.riskModel import RiskLevel
from config.postgredb import AsyncSessionLocal

async def add_disease(db_session: AsyncSession, disease_name: str, description: str = None):
    new_disease = Disease(disease_name=disease_name, description=description)
    db_session.add(new_disease)
    await db_session.commit()
    await db_session.refresh(new_disease)
    return new_disease

async def list_diseases(db_session: AsyncSession):
    result = await db_session.execute(select(Disease))
    diseases = result.scalars().all()
    return diseases

async def delete_disease(db_session: AsyncSession, disease_id: int):
    result = await db_session.execute(select(Disease).filter(Disease.disease_id == disease_id))
    disease = result.scalar_one_or_none()
    if disease:
        await db_session.delete(disease)
        await db_session.commit()
        return True
    return False

async def update_disease(db_session: AsyncSession, disease_id: int, disease_name: str = None, description: str = None):
    result = await db_session.execute(select(Disease).filter(Disease.disease_id == disease_id))
    disease = result.scalar_one_or_none()
    if disease:
        if disease_name:
            disease.disease_name = disease_name
        if description:
            disease.description = description
        await db_session.commit()
        await db_session.refresh(disease)
        return disease
    return None


def _get_iso_week_year() -> tuple[int, int]:
    iso = datetime.now().isocalendar()
    return int(iso[1]), int(iso[0])


def _normalize_risk(level: str | None) -> str:
    if not level:
        return "safe"
    level = level.strip().lower()
    if level in {"safe", "low", "medium", "high"}:
        return level
    if "high" in level:
        return "high"
    if "medium" in level or "moderate" in level:
        return "medium"
    if "low" in level:
        return "low"
    return "safe"


async def get_disease_context() -> dict:
    """
    Fetch all tracked diseases with their descriptions, current-week case totals
    (summed across all districts), and the latest risk level — for use as AI chat context.
    """
    week_number, year = _get_iso_week_year()

    async with AsyncSessionLocal() as session:
        # 1. All diseases (id, name, description)
        diseases_result = await session.execute(
            select(Disease.disease_id, Disease.disease_name, Disease.description)
            .order_by(Disease.disease_name)
        )
        diseases = diseases_result.all()

        if not diseases:
            return {"week_number": week_number, "year": year, "diseases": []}

        disease_ids = [d[0] for d in diseases]

        # 2. Current-week case totals per disease (sum across all districts)
        cases_result = await session.execute(
            select(
                Report.disease_id,
                func.coalesce(func.sum(Report.case_count), 0).label("total_cases"),
            )
            .where(
                and_(
                    Report.week_number == week_number,
                    Report.year == year,
                    Report.disease_id.in_(disease_ids),
                )
            )
            .group_by(Report.disease_id)
        )
        cases_map: dict[int, int] = {row[0]: int(row[1]) for row in cases_result.all()}

        # 3. Latest risk level per disease (most recent calculated_at, any district)
        #    We take the highest risk level seen this week across all districts.
        risk_priority = {"safe": 0, "low": 1, "medium": 2, "high": 3}
        risk_result = await session.execute(
            select(RiskLevel.disease_id, RiskLevel.risk_level)
            .where(
                and_(
                    RiskLevel.week_number == week_number,
                    RiskLevel.year == year,
                    RiskLevel.disease_id.in_(disease_ids),
                )
            )
        )
        risk_map: dict[int, str] = {}
        for disease_id, risk_level in risk_result.all():
            normalized = _normalize_risk(risk_level)
            current = risk_map.get(disease_id, "safe")
            if risk_priority.get(normalized, 0) > risk_priority.get(current, 0):
                risk_map[disease_id] = normalized

        # 4. Build response
        disease_list = [
            {
                "disease_id": d[0],
                "disease_name": d[1],
                "description": d[2] or "",
                "current_cases": cases_map.get(d[0], 0),
                "risk_level": risk_map.get(d[0], "safe"),
            }
            for d in diseases
        ]

        # Sort: highest risk / most cases first
        disease_list.sort(
            key=lambda x: (risk_priority.get(x["risk_level"], 0), x["current_cases"]),
            reverse=True,
        )

        return {
            "week_number": week_number,
            "year": year,
            "diseases": disease_list,
        }

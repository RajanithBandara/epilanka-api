"""
Threshold management for the `risk_levels` table.

This controller mirrors the formula used in epilanka_ML/pipeline/compute_risk.py:

    incidence_per_100k = (cases_reported / population) * 100_000
    lower_threshold    = max(0, mean(incidence) - std(incidence))
    upper_threshold    = mean(incidence) + std(incidence)
    outbreak_threshold = mean(incidence) + 2 * std(incidence)

A row is classified as:
    incidence < lower               → "Below Expected"
    lower ≤ incidence ≤ upper       → "Normal"
    upper < incidence ≤ outbreak    → "Warning"
    incidence > outbreak            → "High Risk"

Two distinct writers populate `risk_levels`:
  • The ML pipeline (labels: Below Expected / Normal / Warning / High Risk)
  • The CERI engine (labels: low / moderate / high / critical, with fixed
    thresholds 15/40/65 and risk_score on a 0-100 scale)

So when we re-classify after a manual edit we only touch rows that look
ML-shaped; CERI-augmented rows keep their label/score untouched.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, case, distinct, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config.postgredb import AsyncSessionLocal
from models.diseaseModel import Disease
from models.districtModel import District
from models.historydataModel import HistoryData
from models.perdistrictPopulationModel import PerDistrictPopulation
from models.reportsModel import Report
from models.riskModel import RiskLevel
from utils.officer_analytics_cache import invalidate_officer_analytics_cache
from utils.redis_client import cache_delete_pattern

ML_RISK_LABELS = {"Below Expected", "Normal", "Warning", "High Risk"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _classify(incidence: float, lower: int, upper: int, outbreak: int) -> str:
    if incidence is None or math.isnan(incidence):
        return "Unknown"
    if incidence < lower:
        return "Below Expected"
    if incidence <= upper:
        return "Normal"
    if incidence <= outbreak:
        return "Warning"
    return "High Risk"


async def _invalidate_caches() -> None:
    """Drop the threshold/analytics caches so the UI refreshes immediately."""
    try:
        await cache_delete_pattern("officer:analytics:thresholds:*")
    except Exception:
        pass
    try:
        await invalidate_officer_analytics_cache()
    except Exception:
        pass


# ── Reads ────────────────────────────────────────────────────────────────────

async def list_threshold_years() -> dict:
    """Return the distinct years that have rows in risk_levels."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(distinct(RiskLevel.year)).order_by(RiskLevel.year.desc())
            )
        ).all()
    years = [int(r[0]) for r in rows if r[0] is not None]
    return {"count": len(years), "years": years}


async def list_year_thresholds(
    year: int,
    disease_id: Optional[int] = None,
    district_id: Optional[int] = None,
) -> dict:
    """List unique (district, disease) threshold rows for the given year.

    Several weekly rows share the same threshold values within a year; we
    collapse them to a single representative row, keyed by the most recent
    `calculated_at` so live edits surface first.
    """
    async with AsyncSessionLocal() as session:
        query = (
            select(
                RiskLevel.district_id,
                RiskLevel.disease_id,
                District.district_name,
                District.province_name,
                Disease.disease_name,
                RiskLevel.lower_threshold,
                RiskLevel.upper_threshold,
                RiskLevel.outbreak_threshold,
                RiskLevel.calculated_at,
                func.count(RiskLevel.risk_id).label("week_count"),
            )
            .join(District, District.district_id == RiskLevel.district_id)
            .join(Disease, Disease.disease_id == RiskLevel.disease_id)
            .where(RiskLevel.year == year)
            .group_by(
                RiskLevel.district_id,
                RiskLevel.disease_id,
                District.district_name,
                District.province_name,
                Disease.disease_name,
                RiskLevel.lower_threshold,
                RiskLevel.upper_threshold,
                RiskLevel.outbreak_threshold,
                RiskLevel.calculated_at,
            )
            .order_by(
                Disease.disease_name.asc(),
                District.district_name.asc(),
                RiskLevel.calculated_at.desc(),
            )
        )
        if disease_id is not None:
            query = query.where(RiskLevel.disease_id == disease_id)
        if district_id is not None:
            query = query.where(RiskLevel.district_id == district_id)

        rows = (await session.execute(query)).all()

    seen: set[tuple[int, int]] = set()
    items: list[dict] = []
    for r in rows:
        key = (int(r.district_id), int(r.disease_id))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "year": year,
                "district_id": int(r.district_id),
                "district_name": r.district_name,
                "province_name": r.province_name,
                "disease_id": int(r.disease_id),
                "disease_name": r.disease_name,
                "lower_threshold": int(r.lower_threshold),
                "upper_threshold": int(r.upper_threshold),
                "outbreak_threshold": int(r.outbreak_threshold),
                "week_count": int(r.week_count),
                "calculated_at": r.calculated_at.isoformat() if r.calculated_at else None,
            }
        )

    return {"year": year, "count": len(items), "items": items}


# ── Writes ───────────────────────────────────────────────────────────────────

async def update_year_threshold(
    year: int,
    disease_id: int,
    district_id: int,
    lower_threshold: int,
    upper_threshold: int,
    outbreak_threshold: int,
    reclassify: bool = True,
) -> dict:
    """Update the three threshold columns on every weekly row that matches
    (year, disease_id, district_id). Optionally re-classify the `risk_level`
    column for ML-style rows based on each row's stored incidence.
    """

    if not (0 <= lower_threshold <= upper_threshold <= outbreak_threshold):
        raise ValueError(
            "Thresholds must satisfy 0 ≤ lower ≤ upper ≤ outbreak"
        )

    async with AsyncSessionLocal() as session:
        # 1. Bulk-update the three numeric columns.
        result = await session.execute(
            update(RiskLevel)
            .where(
                and_(
                    RiskLevel.year == year,
                    RiskLevel.disease_id == disease_id,
                    RiskLevel.district_id == district_id,
                )
            )
            .values(
                lower_threshold=int(lower_threshold),
                upper_threshold=int(upper_threshold),
                outbreak_threshold=int(outbreak_threshold),
            )
        )
        rows_updated = int(result.rowcount or 0)

        reclassified = 0
        if reclassify and rows_updated:
            # Reload the affected rows so we can reclassify locally.
            rows = (
                await session.execute(
                    select(RiskLevel).where(
                        and_(
                            RiskLevel.year == year,
                            RiskLevel.disease_id == disease_id,
                            RiskLevel.district_id == district_id,
                        )
                    )
                )
            ).scalars().all()

            for row in rows:
                # Skip CERI-augmented rows to avoid clobbering their labels.
                if row.risk_level not in ML_RISK_LABELS:
                    continue
                new_label = _classify(
                    float(row.risk_score) if row.risk_score is not None else 0.0,
                    int(lower_threshold),
                    int(upper_threshold),
                    int(outbreak_threshold),
                )
                if new_label != row.risk_level:
                    row.risk_level = new_label
                    reclassified += 1

        await session.commit()

    if rows_updated:
        await _invalidate_caches()

    return {
        "year": year,
        "disease_id": disease_id,
        "district_id": district_id,
        "lower_threshold": int(lower_threshold),
        "upper_threshold": int(upper_threshold),
        "outbreak_threshold": int(outbreak_threshold),
        "rows_updated": rows_updated,
        "rows_reclassified": reclassified,
    }


async def _ensure_risk_levels_constraint(session) -> None:
    """Ensure the 4-column unique constraint exists on `risk_levels` so the
    ON CONFLICT upsert below has something to target.

    Mirrors the migration done in `epilanka_ML/pipeline/compute_risk.py`:
    the original alembic migration created a 3-column constraint
    `(district_id, week_number, year)`; the ML pipeline replaces it with a
    4-column version that includes `disease_id` on first run. We replicate
    that here so threshold recomputes work even if the ML pipeline has
    never been run against this database.
    """
    check = await session.execute(
        text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'risk_levels'
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (district_id, week_number, year, disease_id)'
            LIMIT 1
            """
        )
    )
    if check.first() is not None:
        return

    # Drop the pre-disease_id constraint if it exists, then add the new one.
    await session.execute(
        text("ALTER TABLE risk_levels DROP CONSTRAINT IF EXISTS risk_levels_district_week_year_uniq")
    )
    await session.execute(
        text(
            """
            ALTER TABLE risk_levels
            ADD CONSTRAINT risk_levels_district_week_year_uniq
            UNIQUE (district_id, week_number, year, disease_id)
            """
        )
    )


async def _load_year_weekly_counts(
    session,
    year: int,
    disease_id: Optional[int],
    district_id: Optional[int],
) -> tuple[dict[tuple[int, int, int], int], str]:
    """Load weekly case counts for the year, returning {(district_id, disease_id, week): count}.

    Source selection (matches the ML pipeline's intent — historicaldata is the
    authoritative source for past years, the reports table fills in the current
    year via predictions + officer-confirmed actuals):

      1. Pull from `historicaldata` (case_count).
      2. For weeks not present in historicaldata, pull from `reports`
         (coalesce(actual_count, case_count) so officer-confirmed values
         win over the model's prediction).
    """
    historical_query = select(
        HistoryData.district_id,
        HistoryData.disease_id,
        HistoryData.week_number,
        HistoryData.case_count,
    ).where(HistoryData.year == year)
    if disease_id is not None:
        historical_query = historical_query.where(HistoryData.disease_id == disease_id)
    if district_id is not None:
        historical_query = historical_query.where(HistoryData.district_id == district_id)
    historical_rows = (await session.execute(historical_query)).all()

    reports_count = func.coalesce(Report.actual_count, Report.case_count).label("cnt")
    reports_query = select(
        Report.district_id,
        Report.disease_id,
        Report.week_number,
        reports_count,
    ).where(Report.year == year)
    if disease_id is not None:
        reports_query = reports_query.where(Report.disease_id == disease_id)
    if district_id is not None:
        reports_query = reports_query.where(Report.district_id == district_id)
    report_rows = (await session.execute(reports_query)).all()

    weekly: dict[tuple[int, int, int], int] = {}

    # Reports first (so historicaldata overrides them when both exist).
    for d_id, dis_id, week, cnt in report_rows:
        if d_id is None or dis_id is None or week is None:
            continue
        weekly[(int(d_id), int(dis_id), int(week))] = int(cnt or 0)
    for d_id, dis_id, week, cnt in historical_rows:
        if d_id is None or dis_id is None or week is None:
            continue
        weekly[(int(d_id), int(dis_id), int(week))] = int(cnt or 0)

    if historical_rows and report_rows:
        source = "historicaldata + reports"
    elif historical_rows:
        source = "historicaldata"
    elif report_rows:
        source = "reports"
    else:
        source = "none"
    return weekly, source


async def recompute_year_thresholds(
    year: int,
    disease_id: Optional[int] = None,
    district_id: Optional[int] = None,
    reclassify: bool = True,
) -> dict:
    """Recompute thresholds for every (disease, district) pair in `year`
    using the same mean ± σ formula as the ML pipeline, and upsert one
    `risk_levels` row per (district, disease, week) so the values land
    even for years that don't have rows yet.
    """
    async with AsyncSessionLocal() as session:
        # 0. Make sure ON CONFLICT has a unique constraint to target.
        await _ensure_risk_levels_constraint(session)

        # 1. Pull population per district.
        pop_rows = (
            await session.execute(
                select(
                    PerDistrictPopulation.district_id,
                    PerDistrictPopulation.population,
                )
            )
        ).all()
        population_by_district: dict[int, int] = {
            int(d_id): int(p) for d_id, p in pop_rows if p and p > 0
        }

        # 2. Pull weekly case counts for the year (historical + reports).
        weekly_counts, data_source = await _load_year_weekly_counts(
            session, year, disease_id, district_id
        )

        if not weekly_counts:
            return {
                "year": year,
                "pairs_recomputed": 0,
                "rows_upserted": 0,
                "rows_inserted": 0,
                "rows_updated": 0,
                "rows_reclassified": 0,
                "data_source": data_source,
                "message": (
                    f"No case-count rows found for {year} in either historicaldata "
                    "or reports. Load 2026 predictions/actuals first, then recompute."
                ),
                "items": [],
            }

        # 3. Group weekly incidences by (disease, district).
        bucket: dict[tuple[int, int], list[tuple[int, float]]] = {}
        for (d_id, dis_id, week), cnt in weekly_counts.items():
            pop = population_by_district.get(d_id)
            if not pop:
                continue
            incidence = (cnt / pop) * 100_000.0
            bucket.setdefault((dis_id, d_id), []).append((week, incidence))

        if not bucket:
            return {
                "year": year,
                "pairs_recomputed": 0,
                "rows_upserted": 0,
                "rows_inserted": 0,
                "rows_updated": 0,
                "rows_reclassified": 0,
                "data_source": data_source,
                "message": (
                    "Case counts were found but no district has a matching row in "
                    "perdistrictpopulation, so incidence can't be computed."
                ),
                "items": [],
            }

        # 4. Compute thresholds per pair and collect every weekly row to upsert.
        now = datetime.utcnow()
        total_inserted = 0
        total_updated = 0
        total_reclassified = 0
        computed_summary: list[dict] = []
        rows_to_upsert: list[dict] = []

        for (dis_id, d_id), week_pairs in bucket.items():
            values = [v for _, v in week_pairs]
            n = len(values)
            mean = sum(values) / n
            if n > 1:
                var = sum((v - mean) ** 2 for v in values) / (n - 1)
                std = math.sqrt(var)
            else:
                std = 0.0
            lower = max(0, round(mean - std))
            upper = round(mean + std)
            outbreak = round(mean + 2 * std)

            computed_summary.append(
                {
                    "disease_id": dis_id,
                    "district_id": d_id,
                    "lower_threshold": int(lower),
                    "upper_threshold": int(upper),
                    "outbreak_threshold": int(outbreak),
                    "mean_incidence": round(mean, 3),
                    "std_incidence": round(std, 3),
                    "weeks": n,
                }
            )

            for week, incidence in week_pairs:
                rows_to_upsert.append(
                    {
                        "risk_id": uuid.uuid4(),
                        "district_id": d_id,
                        "disease_id": dis_id,
                        "week_number": int(week),
                        "year": int(year),
                        "risk_level": _classify(incidence, int(lower), int(upper), int(outbreak)),
                        "lower_threshold": int(lower),
                        "upper_threshold": int(upper),
                        "outbreak_threshold": int(outbreak),
                        "risk_score": float(incidence),
                        "calculated_at": now,
                    }
                )

        # 5. Batched upserts.
        #
        # The previous version issued one INSERT per (district × disease × week),
        # which meant ~4000 round-trips to PostgreSQL across the whole year and
        # blew past the 15s axios timeout. We now batch in chunks of 500 rows
        # (~5500 bound parameters per call, well under Postgres' 65535 cap) and
        # collect the inserted/updated split with RETURNING (xmax = 0).
        ml_label_array = list(ML_RISK_LABELS)
        existing_ml_check = RiskLevel.risk_level.in_(ml_label_array)
        BATCH_SIZE = 500

        for i in range(0, len(rows_to_upsert), BATCH_SIZE):
            chunk = rows_to_upsert[i : i + BATCH_SIZE]
            stmt = pg_insert(RiskLevel).values(chunk)

            set_clause: dict = {
                "lower_threshold": stmt.excluded.lower_threshold,
                "upper_threshold": stmt.excluded.upper_threshold,
                "outbreak_threshold": stmt.excluded.outbreak_threshold,
                "calculated_at": stmt.excluded.calculated_at,
            }
            if reclassify:
                # SET clause: thresholds always refresh; risk_level + risk_score
                # only when the *existing* row is ML-shaped (preserves CERI).
                set_clause["risk_level"] = case(
                    (existing_ml_check, stmt.excluded.risk_level),
                    else_=RiskLevel.risk_level,
                )
                set_clause["risk_score"] = case(
                    (existing_ml_check, stmt.excluded.risk_score),
                    else_=RiskLevel.risk_score,
                )

            stmt = stmt.on_conflict_do_update(
                index_elements=["district_id", "week_number", "year", "disease_id"],
                set_=set_clause,
            ).returning(text("(xmax = 0) AS inserted"))

            result = await session.execute(stmt)
            for row in result.fetchall():
                if bool(row[0]):
                    total_inserted += 1
                else:
                    total_updated += 1
                    if reclassify:
                        total_reclassified += 1

        await session.commit()

    await _invalidate_caches()

    return {
        "year": year,
        "pairs_recomputed": len(computed_summary),
        "rows_upserted": total_inserted + total_updated,
        "rows_inserted": total_inserted,
        "rows_updated": total_updated,
        "rows_reclassified": total_reclassified,
        "data_source": data_source,
        "items": computed_summary,
    }

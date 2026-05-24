"""
CERI — Community Epidemic Risk Index
=====================================
Automated disease-risk scoring engine for EpiWatch Lanka.

Equation:
    CERI(d, district, week) = DSM(d) × (α·RD + β·VC + γ·TU)

Components:
    DSM  — Disease Severity Multiplier  (derived from AI-extracted severity & confidence)
    RD   — Report Density               (confidence-weighted report count / active users)
    VC   — Vote Credibility             (community validation signal)
    TU   — Temporal Urgency             (week-over-week growth rate)

Weights: α=0.45, β=0.35, γ=0.20
Output:  0–100 score → risk level (low / moderate / high / critical)
"""

import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from config.db import get_database
from config.postgredb import AsyncSessionLocal
from models.diseaseModel import Disease
from models.districtModel import District
from models.riskModel import RiskLevel
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

COMPONENT_WEIGHTS = {"report_density": 0.45, "vote_credibility": 0.35, "temporal_urgency": 0.20}

SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 1.40,
    "severe": 1.20,
    "moderate": 1.00,
    "mild": 0.70,
    "unknown": 0.85,
}

# Ordered from most to least severe — used for tie-breaking
_SEVERITY_ORDER: list[str] = ["critical", "severe", "moderate", "mild", "unknown"]

CONFIDENCE_NUMERIC: dict[str, float] = {"high": 1.0, "medium": 0.75, "low": 0.5}

CONFIDENCE_BOOST: dict[str, float] = {"high": 1.10, "medium": 1.00, "low": 0.80}

# CERI threshold boundaries for risk classification
RISK_THRESHOLDS = {
    "low": (0, 15),
    "moderate": (16, 40),
    "high": (41, 65),
    "critical": (66, 100),
}

RISK_LEVEL_ORDER: dict[str, int] = {"low": 0, "moderate": 1, "high": 2, "critical": 3}

# Sensitivity constants
REPORT_SENSITIVITY_K = 0.01   # 1% of users reporting = max RD score
VOTE_SENSITIVITY_V = 0.02     # Expected vote participation rate


# ── Component Calculators ────────────────────────────────────────────────────

def _compute_dsm(reports: list[dict]) -> tuple[float, dict]:
    """Compute the Disease Severity Multiplier from aggregated report data.

    Returns:
        (dsm_value, breakdown_dict) where breakdown contains intermediate values.
    """
    if not reports:
        return 1.0, {"severity_mode": "unknown", "severity_weight": 0.85,
                      "avg_confidence": 0.5, "confidence_level": "low",
                      "confidence_boost": 0.80, "dsm": 0.68}

    # ── Severity: take the mode (most frequent), tie-break by higher severity
    severity_counts: Counter[str] = Counter()
    for r in reports:
        extracted = r.get("extracted_data") or {}
        sev = (extracted.get("severity") or "unknown").lower().strip()
        if sev not in SEVERITY_WEIGHTS:
            sev = "unknown"
        severity_counts[sev] += 1

    max_count = max(severity_counts.values())
    candidates = [s for s, c in severity_counts.items() if c == max_count]
    # Tie-break: pick the most severe
    severity_mode = min(candidates, key=lambda s: _SEVERITY_ORDER.index(s) if s in _SEVERITY_ORDER else 99)
    severity_weight = SEVERITY_WEIGHTS.get(severity_mode, 0.85)

    # ── Confidence: weighted average across reports
    conf_values: list[float] = []
    for r in reports:
        extracted = r.get("extracted_data") or {}
        conf_str = (extracted.get("confidence") or "low").lower().strip()
        conf_values.append(CONFIDENCE_NUMERIC.get(conf_str, 0.5))

    avg_confidence = sum(conf_values) / len(conf_values) if conf_values else 0.5

    if avg_confidence >= 0.8:
        confidence_level = "high"
    elif avg_confidence >= 0.5:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    confidence_boost = CONFIDENCE_BOOST[confidence_level]

    dsm = severity_weight * confidence_boost
    breakdown = {
        "severity_mode": severity_mode,
        "severity_weight": severity_weight,
        "avg_confidence": round(avg_confidence, 3),
        "confidence_level": confidence_level,
        "confidence_boost": confidence_boost,
        "dsm": round(dsm, 3),
    }
    return dsm, breakdown


def _compute_report_density(reports: list[dict], n_active: int) -> float:
    """Confidence-weighted report count normalised by active user base.

    RD = min(100, (R_w / (N_active × k)) × 100)
    """
    if n_active <= 0:
        return 0.0

    r_w = 0.0
    for r in reports:
        extracted = r.get("extracted_data") or {}
        conf_str = (extracted.get("confidence") or "low").lower().strip()
        r_w += CONFIDENCE_NUMERIC.get(conf_str, 0.5)

    denominator = n_active * REPORT_SENSITIVITY_K
    if denominator <= 0:
        return 0.0

    return min(100.0, (r_w / denominator) * 100.0)


def _compute_vote_credibility(reports: list[dict], n_active: int) -> float:
    """Community validation signal: average votes per report vs expected max.

    VC = min(100, (V_total / (R_count × E_max)) × 100)
    """
    r_count = len(reports)
    if r_count == 0 or n_active <= 0:
        return 0.0

    v_total = sum(r.get("score", 0) for r in reports)
    e_max = max(5, n_active * VOTE_SENSITIVITY_V)
    denominator = r_count * e_max

    if denominator <= 0:
        return 0.0

    return min(100.0, (v_total / denominator) * 100.0)


def _compute_temporal_urgency(current_count: int, previous_count: int) -> float:
    """Week-over-week growth rate, clamped to [0, 100].

    TU = min(100, max(0, ((current - previous) / max(1, previous)) × 100))
    """
    baseline = max(1, previous_count)
    growth = (current_count - previous_count) / baseline * 100.0
    return min(100.0, max(0.0, growth))


def _classify_risk_level(ceri_score: float) -> str:
    """Map a CERI score (0-100) to a risk level string."""
    if ceri_score <= 15:
        return "low"
    elif ceri_score <= 40:
        return "moderate"
    elif ceri_score <= 65:
        return "high"
    else:
        return "critical"


# ── Helper: fetch reports from MongoDB ───────────────────────────────────────

def _fetch_reports_for_disease_district(
    db: Any,
    district_name: str,
    disease_name: str,
    week_number: int,
    year: int,
) -> list[dict]:
    """Fetch reports matching disease name from a district collection for a given week."""
    collection_name = f"reports_{district_name.replace(' ', '_').lower()}"
    available = db.list_collection_names()
    if collection_name not in available:
        return []

    collection = db[collection_name]

    # Case-insensitive match on extracted_data.disease_name
    disease_pattern = re.compile(f"^{re.escape(disease_name)}$", re.IGNORECASE)

    query = {
        "week_number": week_number,
        "year": year,
        "status": "approved",
        "extracted_data.disease_name": {"$regex": disease_pattern},
    }

    return list(collection.find(query))


# ── Main Entry Point ─────────────────────────────────────────────────────────

async def calculate_ceri_scores() -> dict:
    """Calculate CERI risk scores for all disease-district pairs.

    Workflow:
        1. Load diseases and districts from PostgreSQL
        2. Count active users from MongoDB
        3. For each (disease, district) pair, compute CERI components
        4. Detect risk-level transitions (for notification dispatch)
        5. Write updated scores to risk_levels table

    Returns:
        Dict with keys: scores, transitions, calculated_at, active_users,
        diseases_checked, districts_checked
    """
    logger.info("🔬 Starting CERI risk score calculation...")
    now = datetime.now(timezone.utc)
    current_week = datetime.now().isocalendar()[1]
    current_year = datetime.now().year
    previous_week = current_week - 1 if current_week > 1 else 52
    previous_year = current_year if current_week > 1 else current_year - 1

    db = get_database()

    # ── Step 1: Load reference data from PostgreSQL ──────────────────────
    async with AsyncSessionLocal() as session:
        diseases_result = await session.execute(
            select(Disease.disease_id, Disease.disease_name)
        )
        diseases = [{"id": r[0], "name": r[1]} for r in diseases_result.fetchall()]

        districts_result = await session.execute(
            select(District.district_id, District.district_name)
        )
        districts = [{"id": r[0], "name": r[1]} for r in districts_result.fetchall()]

    if not diseases:
        logger.warning("No diseases found in database — skipping CERI calculation")
        return {"scores": [], "transitions": [], "calculated_at": now.isoformat(),
                "active_users": 0, "diseases_checked": 0, "districts_checked": 0}

    if not districts:
        logger.warning("No districts found in database — skipping CERI calculation")
        return {"scores": [], "transitions": [], "calculated_at": now.isoformat(),
                "active_users": 0, "diseases_checked": 0, "districts_checked": 0}

    # ── Step 2: Active user count ────────────────────────────────────────
    n_active = db["users"].count_documents({"banned": {"$ne": True}})
    if n_active == 0:
        logger.warning("No active users found — CERI scores will be zero")
        n_active = 1  # Avoid division by zero; scores will still be 0

    logger.info(
        "📊 CERI params: %d diseases × %d districts, %d active users, week %d/%d",
        len(diseases), len(districts), n_active, current_week, current_year,
    )

    # ── Step 3: Load previous risk levels for transition detection ───────
    previous_levels: dict[tuple[int, int], str] = {}
    async with AsyncSessionLocal() as session:
        prev_query = select(
            RiskLevel.disease_id,
            RiskLevel.district_id,
            RiskLevel.risk_level,
        ).where(
            RiskLevel.week_number == previous_week,
            RiskLevel.year == previous_year,
        )
        prev_result = await session.execute(prev_query)
        for disease_id, district_id, risk_level in prev_result.fetchall():
            previous_levels[(disease_id, district_id)] = risk_level

    # Also load current week's levels to detect if already calculated
    current_levels: dict[tuple[int, int], str] = {}
    async with AsyncSessionLocal() as session:
        curr_query = select(
            RiskLevel.disease_id,
            RiskLevel.district_id,
            RiskLevel.risk_level,
        ).where(
            RiskLevel.week_number == current_week,
            RiskLevel.year == current_year,
        )
        curr_result = await session.execute(curr_query)
        for disease_id, district_id, risk_level in curr_result.fetchall():
            current_levels[(disease_id, district_id)] = risk_level

    # ── Step 4: Compute CERI for every (disease, district) pair ──────────
    scores: list[dict] = []
    transitions: list[dict] = []
    risk_records_to_upsert: list[dict] = []

    for disease in diseases:
        for district in districts:
            try:
                # Current week reports
                reports_current = _fetch_reports_for_disease_district(
                    db, district["name"], disease["name"], current_week, current_year,
                )

                # Previous week reports (for temporal urgency)
                reports_previous = _fetch_reports_for_disease_district(
                    db, district["name"], disease["name"], previous_week, previous_year,
                )

                # Skip if no reports in either week (no signal)
                if not reports_current and not reports_previous:
                    continue

                # Compute components
                dsm, dsm_breakdown = _compute_dsm(reports_current)
                rd = _compute_report_density(reports_current, n_active)
                vc = _compute_vote_credibility(reports_current, n_active)
                tu = _compute_temporal_urgency(len(reports_current), len(reports_previous))

                # Final CERI
                base_score = (
                    COMPONENT_WEIGHTS["report_density"] * rd
                    + COMPONENT_WEIGHTS["vote_credibility"] * vc
                    + COMPONENT_WEIGHTS["temporal_urgency"] * tu
                )
                ceri = min(100.0, dsm * base_score)
                risk_level = _classify_risk_level(ceri)

                score_entry = {
                    "disease_id": disease["id"],
                    "disease_name": disease["name"],
                    "district_id": district["id"],
                    "district_name": district["name"],
                    "ceri_score": round(ceri, 2),
                    "risk_level": risk_level,
                    "report_count": len(reports_current),
                    "vote_total": sum(r.get("score", 0) for r in reports_current),
                    "components": {
                        "report_density": round(rd, 2),
                        "vote_credibility": round(vc, 2),
                        "temporal_urgency": round(tu, 2),
                        "base_score": round(base_score, 2),
                        "dsm": dsm_breakdown,
                    },
                }
                scores.append(score_entry)

                # Record for PostgreSQL upsert
                risk_records_to_upsert.append({
                    "disease_id": disease["id"],
                    "district_id": district["id"],
                    "week_number": current_week,
                    "year": current_year,
                    "risk_level": risk_level,
                    "risk_score": round(ceri, 2),
                    "calculated_at": now,
                })

                # Transition detection: compare with previous week or earlier this week
                old_level = current_levels.get(
                    (disease["id"], district["id"]),
                    previous_levels.get((disease["id"], district["id"]), "low"),
                )
                old_order = RISK_LEVEL_ORDER.get(old_level, 0)
                new_order = RISK_LEVEL_ORDER.get(risk_level, 0)

                if new_order > old_order:
                    transitions.append({
                        "disease_id": disease["id"],
                        "disease_name": disease["name"],
                        "district_id": district["id"],
                        "district_name": district["name"],
                        "old_level": old_level,
                        "new_level": risk_level,
                        "ceri_score": round(ceri, 2),
                        "report_count": len(reports_current),
                        "dsm": dsm_breakdown,
                    })

            except Exception:
                logger.exception(
                    "Error computing CERI for disease=%s district=%s",
                    disease["name"], district["name"],
                )
                continue

    # ── Step 5: Persist risk levels to PostgreSQL ────────────────────────
    if risk_records_to_upsert:
        async with AsyncSessionLocal() as session:
            for record in risk_records_to_upsert:
                # Check if a row already exists for this combination
                existing_query = select(RiskLevel).where(
                    RiskLevel.disease_id == record["disease_id"],
                    RiskLevel.district_id == record["district_id"],
                    RiskLevel.week_number == record["week_number"],
                    RiskLevel.year == record["year"],
                )
                existing = (await session.execute(existing_query)).scalars().first()

                if existing:
                    existing.risk_level = record["risk_level"]
                    existing.risk_score = record["risk_score"]
                    existing.calculated_at = record["calculated_at"]
                else:
                    new_risk = RiskLevel(
                        risk_id=uuid.uuid4(),
                        disease_id=record["disease_id"],
                        district_id=record["district_id"],
                        week_number=record["week_number"],
                        year=record["year"],
                        risk_level=record["risk_level"],
                        lower_threshold=15,
                        upper_threshold=40,
                        outbreak_threshold=65,
                        risk_score=record["risk_score"],
                        calculated_at=record["calculated_at"],
                    )
                    session.add(new_risk)

            await session.commit()

    # ── Step 6: Persist CERI scores to MongoDB district-wise collections ─
    if scores:
        for score in scores:
            district_name = score["district_name"]
            collection_name = f"ceri_{district_name.replace(' ', '_').lower()}"
            collection = db[collection_name]
            
            query = {
                "disease_id": score["disease_id"],
                "week_number": current_week,
                "year": current_year
            }
            
            doc = {
                "$set": {
                    "disease_id": score["disease_id"],
                    "disease_name": score["disease_name"],
                    "district_id": score["district_id"],
                    "district_name": district_name,
                    "week_number": current_week,
                    "year": current_year,
                    "ceri_score": score["ceri_score"],
                    "risk_level": score["risk_level"],
                    "report_count": score["report_count"],
                    "vote_total": score["vote_total"],
                    "components": score["components"],
                    "calculated_at": now
                }
            }
            
            try:
                collection.update_one(query, doc, upsert=True)
            except Exception:
                logger.exception("Failed to save CERI to MongoDB for district %s", district_name)

    logger.info(
        "✅ CERI calculation complete: %d scores, %d risk transitions detected",
        len(scores), len(transitions),
    )

    return {
        "scores": scores,
        "transitions": transitions,
        "calculated_at": now.isoformat(),
        "active_users": n_active,
        "diseases_checked": len(diseases),
        "districts_checked": len(districts),
        "week": current_week,
        "year": current_year,
    }

"""
CERI Risk Calculation Background Scheduler
==========================================
Periodically runs the CERI algorithm and dispatches automated
risk-alert notifications when disease risk levels escalate.

Usage (in main.py lifespan):
    from utils.risk_scheduler import (
        run_risk_calculation,
        start_risk_calculation_service,
        stop_risk_calculation_service,
    )

    # Startup
    await run_risk_calculation()           # initial run
    start_risk_calculation_service()       # start background loop

    # Shutdown
    await stop_risk_calculation_service()
"""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime as _dt

from controllers.notificationController import create_notification
from models.notificationModel import (
    NotificationCategory,
    NotificationCreate,
    NotificationSeverity,
)
from utils.websocket_manager import notification_manager

logger = logging.getLogger(__name__)

RISK_CALCULATION_INTERVAL_SECONDS = 21_600  # 6 hours

_risk_calculation_task: asyncio.Task[None] | None = None

# Risk-level ordering for upward-transition detection
_RISK_LEVEL_ORDER: dict[str, int] = {"low": 0, "moderate": 1, "high": 2, "critical": 3}

# Map new risk level → notification severity
_SEVERITY_MAP: dict[str, NotificationSeverity] = {
    "moderate": NotificationSeverity.WARNING,
    "high": NotificationSeverity.WARNING,
    "critical": NotificationSeverity.CRITICAL,
}


def _ensure_json_safe(doc: dict) -> dict:
    """Guarantee all datetime fields are ISO-8601 strings for Socket.IO broadcast."""
    result = dict(doc)
    for field in ("created_at", "read_at"):
        val = result.get(field)
        if isinstance(val, _dt):
            result[field] = val.isoformat()
    return result


async def run_risk_calculation() -> dict:
    """Execute a single CERI calculation cycle and dispatch transition alerts.

    Returns:
        The result dict from ``calculate_ceri_scores()``.
    """
    # Lazy import to avoid circular dependency at module load time
    from utils.risk_engine import calculate_ceri_scores

    logger.info("🧮 Running scheduled CERI risk calculation …")

    result = await calculate_ceri_scores()

    transitions = result.get("transitions", [])
    notifications_sent = 0

    for t in transitions:
        disease_name = t["disease_name"]
        district_name = t["district_name"]
        new_level = t["new_level"]
        old_level = t["old_level"]
        ceri_score = t["ceri_score"]

        # Only send notification for upward transitions
        new_order = _RISK_LEVEL_ORDER.get(new_level, 0)
        old_order = _RISK_LEVEL_ORDER.get(old_level, 0)
        if new_order <= old_order:
            continue

        severity = _SEVERITY_MAP.get(new_level, NotificationSeverity.WARNING)

        notification_data = NotificationCreate(
            title=f"⚠️ {disease_name} Risk Alert — {district_name}",
            text=(
                f"{disease_name} risk level has escalated to {new_level.upper()} "
                f"in {district_name}. CERI Score: {ceri_score:.1f}/100. "
                f"Stay alert and follow health guidelines."
            ),
            severity=severity,
            category=NotificationCategory.ALERT,
            metadata={
                "disease": disease_name,
                "district": district_name,
                "risk_level": new_level,
                "previous_level": old_level,
                "ceri_score": round(ceri_score, 2),
                "algorithm": "CERI",
                "report_count": t.get("report_count", 0),
            },
        )

        try:
            # create_notification is synchronous (uses sync pymongo)
            created_doc = create_notification(notification_data)
            safe_doc = _ensure_json_safe(created_doc)

            # Broadcast to all connected Socket.IO clients (async)
            await notification_manager.broadcast_to_all(safe_doc, event_name="notification")

            notifications_sent += 1
            logger.info(
                "🔔 Risk alert sent: %s → %s in %s (CERI %.1f)",
                disease_name, new_level.upper(), district_name, ceri_score,
            )
        except Exception:
            logger.exception(
                "Failed to dispatch risk notification for %s in %s",
                disease_name, district_name,
            )

    logger.info(
        "📋 CERI cycle done — %d scores computed, %d transitions, %d notifications sent",
        len(result.get("scores", [])),
        len(transitions),
        notifications_sent,
    )

    return result


# ── Background loop ──────────────────────────────────────────────────────────

async def _risk_calculation_loop(interval_seconds: int) -> None:
    """Infinite loop that periodically runs the CERI calculation."""
    while True:
        try:
            await run_risk_calculation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning("CERI risk calculation failed: %s", exc, exc_info=True)

        await asyncio.sleep(interval_seconds)


def start_risk_calculation_service(
    interval_seconds: int = RISK_CALCULATION_INTERVAL_SECONDS,
) -> asyncio.Task[None]:
    """Start the background CERI risk calculation loop.

    Safe to call multiple times — returns the existing task if already running.
    """
    global _risk_calculation_task

    if _risk_calculation_task is not None and not _risk_calculation_task.done():
        return _risk_calculation_task

    _risk_calculation_task = asyncio.create_task(_risk_calculation_loop(interval_seconds))
    logger.info(
        "🚀 CERI risk calculation service started (interval: %ds)",
        interval_seconds,
    )
    return _risk_calculation_task


async def stop_risk_calculation_service() -> None:
    """Gracefully stop the background CERI risk calculation loop."""
    global _risk_calculation_task

    if _risk_calculation_task is None:
        return

    _risk_calculation_task.cancel()
    with suppress(asyncio.CancelledError):
        await _risk_calculation_task
    _risk_calculation_task = None
    logger.info("🛑 CERI risk calculation service stopped")

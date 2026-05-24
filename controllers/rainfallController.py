"""Rainfall controller — fetches per-district rainfall from Open-Meteo using
district coordinates stored in the ``districts`` table and upserts results into
``rainfall_data``.

Open-Meteo Archive API is used because it exposes daily ``precipitation_sum``
for any historical date range. We aggregate daily values into monthly totals
(plus an annual total) to match the ``rainfall_data`` schema.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config.postgredb import AsyncSessionLocal
from models.districtModel import District
from models.rainfalldataModel import RainfallData


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

MONTH_DB_COLUMNS: list[str] = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def _resolve_target_year(year: int | None) -> int:
    """Open-Meteo archive has a small ingestion lag, so default to the most
    recent fully-complete calendar year."""
    if year is not None:
        return int(year)
    today = datetime.utcnow().date()
    return today.year - 1


async def _ensure_unique_constraint(session) -> None:
    """``rainfall_data.district_id`` has no unique constraint by default,
    which blocks ON CONFLICT upserts. Add one if missing."""
    await session.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname = 'rainfall_data'
                      AND c.contype = 'u'
                      AND pg_get_constraintdef(c.oid) = 'UNIQUE (district_id)'
                ) THEN
                    ALTER TABLE rainfall_data
                    ADD CONSTRAINT rainfall_data_district_id_uniq UNIQUE (district_id);
                END IF;
            END
            $$;
            """
        )
    )
    await session.commit()


async def _fetch_district_precipitation(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    """Call Open-Meteo Archive API and return [(day, mm), ...]."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": "precipitation_sum",
        "timezone": "Asia/Colombo",
    }
    response = await client.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    values = daily.get("precipitation_sum") or []

    output: list[tuple[date, float]] = []
    for day_str, value in zip(times, values):
        if value is None:
            continue
        try:
            output.append((date.fromisoformat(day_str), float(value)))
        except (TypeError, ValueError):
            continue
    return output


def _aggregate_monthly(daily_rows: Iterable[tuple[date, float]]) -> dict[int, int]:
    monthly_sum: dict[int, float] = defaultdict(float)
    for day, value in daily_rows:
        monthly_sum[day.month] += value
    return {month: int(round(total)) for month, total in monthly_sum.items()}


async def fetch_and_store_rainfall_for_year(
    year: int | None = None,
    *,
    concurrency: int = 4,
) -> dict:
    """For each district in ``districts``, fetch Open-Meteo monthly precipitation
    for the given year and upsert into ``rainfall_data``.

    Returns a summary dict with counts and any per-district errors.
    """
    target_year = _resolve_target_year(year)
    start = date(target_year, 1, 1)
    end = date(target_year, 12, 31)

    async with AsyncSessionLocal() as session:
        await _ensure_unique_constraint(session)

        districts_result = await session.execute(
            select(
                District.district_id,
                District.district_name,
                District.latitude,
                District.longitude,
            ).order_by(District.district_id)
        )
        districts = districts_result.all()

        if not districts:
            return {
                "year": target_year,
                "districts_processed": 0,
                "districts_skipped": 0,
                "errors": ["No districts found in database"],
            }

        semaphore = asyncio.Semaphore(max(1, concurrency))
        errors: list[str] = []
        success_records: list[dict] = []

        async with httpx.AsyncClient() as client:

            async def _process(row) -> None:
                district_id, district_name, latitude, longitude = row
                if latitude is None or longitude is None:
                    errors.append(f"{district_name}: missing coordinates")
                    return

                async with semaphore:
                    try:
                        daily_rows = await _fetch_district_precipitation(
                            client,
                            float(latitude),
                            float(longitude),
                            start,
                            end,
                        )
                    except Exception as exc:
                        errors.append(f"{district_name}: fetch failed — {exc}")
                        return

                if not daily_rows:
                    errors.append(f"{district_name}: no rainfall data returned")
                    return

                monthly = _aggregate_monthly(daily_rows)
                if not monthly:
                    errors.append(f"{district_name}: empty monthly aggregation")
                    return

                record = {
                    "district_id": int(district_id),
                    **{
                        column: int(monthly.get(month_num, 0))
                        for month_num, column in enumerate(MONTH_DB_COLUMNS, start=1)
                    },
                }
                record["annual_rainfall"] = int(
                    sum(monthly.get(m, 0) for m in range(1, 13))
                )
                success_records.append(record)

            await asyncio.gather(*[_process(row) for row in districts])

        for record in success_records:
            stmt = pg_insert(RainfallData).values(**record)
            update_columns = {
                column: stmt.excluded[column]
                for column in (*MONTH_DB_COLUMNS, "annual_rainfall")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["district_id"],
                set_=update_columns,
            )
            await session.execute(stmt)

        await session.commit()

    return {
        "year": target_year,
        "districts_processed": len(success_records),
        "districts_skipped": len(districts) - len(success_records),
        "errors": errors,
    }


async def list_rainfall_records() -> list[dict]:
    """Return the current contents of ``rainfall_data`` joined with district
    names for a quick read endpoint."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                RainfallData.district_id,
                District.district_name,
                RainfallData.january, RainfallData.february, RainfallData.march,
                RainfallData.april, RainfallData.may, RainfallData.june,
                RainfallData.july, RainfallData.august, RainfallData.september,
                RainfallData.october, RainfallData.november, RainfallData.december,
                RainfallData.annual_rainfall,
            )
            .join(District, District.district_id == RainfallData.district_id)
            .order_by(RainfallData.district_id)
        )
        rows = result.all()

    return [
        {
            "district_id": row[0],
            "district_name": row[1],
            "monthly_mm": dict(zip(MONTH_DB_COLUMNS, [int(v) for v in row[2:14]])),
            "annual_rainfall_mm": int(row[14]),
        }
        for row in rows
    ]


async def update_rainfall_record(district_id: int, updates: dict) -> dict:
    """Partially update monthly rainfall for a district and recalculate annual_rainfall."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RainfallData).filter(RainfallData.district_id == district_id)
        )
        record = result.scalars().first()
        
        if not record:
            return {"error": True, "msg": f"Rainfall record for district {district_id} not found."}
            
        for k, v in updates.items():
            if k in MONTH_DB_COLUMNS and v is not None:
                setattr(record, k, int(v))
                
        # Recalculate annual
        annual = sum(getattr(record, m) for m in MONTH_DB_COLUMNS)
        record.annual_rainfall = annual
        
        await session.commit()
        
    return {"error": False, "msg": "Updated successfully", "annual_rainfall": annual}

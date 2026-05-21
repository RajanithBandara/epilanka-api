"""
Admin controller — uses Appwrite server-side Users API to manage admins.
Admins are Appwrite users with the label "admin".
Legacy MongoDB-based admin functions are preserved for ban/activity features.
"""

from datetime import datetime, timezone, date, time
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from appwrite.exception import AppwriteException
from appwrite.id import ID
from bson import ObjectId
from sqlalchemy import text

from config.db import get_database
from config.postgredb import AsyncSessionLocal
from utils.appwrite_client import get_users_service


# ── JSON serialisation helper ──────────────────────────────────────────────

def to_jsonable(v: Any):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return v.hex()
    return v


# ── Appwrite-based admin management ───────────────────────────────────────

def admin_register_appwrite(email: str, password: str, name: str) -> Dict[str, Any]:
    """
    Create a new admin user in Appwrite and tag them with the 'admin' label.
    """
    users_service = get_users_service()

    # Create user
    try:
        user = users_service.create(
            user_id=ID.unique(),
            email=email,
            password=password,
            name=name,
        )
    except AppwriteException as exc:
        if "already" in str(exc.message).lower():
            return {"msg": "Email already registered", "error": True}
        return {"msg": str(exc.message), "error": True}

    # Apply 'admin' label
    try:
        users_service.update_labels(user.id, ["admin"])
    except AppwriteException as exc:
        return {"msg": f"User created but failed to set admin label: {exc.message}", "error": True}

    # Upsert MongoDB profile
    db = get_database()
    admins_col = db["admins"]
    now = datetime.now(timezone.utc)
    admins_col.update_one(
        {"appwrite_id": user.id},
        {"$set": {"appwrite_id": user.id, "email": email, "name": name, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    return {
        "msg": "Admin registered successfully",
        "admin_id": user.id,
        "email": email,
        "name": name,
        "error": False,
    }


def get_all_admins_appwrite() -> list:
    """List all Appwrite users who have the 'admin' label."""
    users_service = get_users_service()
    try:
        result = users_service.list()
        admins = [u for u in result.users if "admin" in (getattr(u, "labels", None) or [])]
        return admins
    except AppwriteException:
        return []


def officer_register_appwrite(email: str, password: str, name: str) -> Dict[str, Any]:
    """
    Create a new officer user in Appwrite and tag them with the 'officer' label.
    """
    users_service = get_users_service()

    try:
        user = users_service.create(
            user_id=ID.unique(),
            email=email,
            password=password,
            name=name,
        )
    except AppwriteException as exc:
        if "already" in str(exc.message).lower():
            return {"msg": "Email already registered", "error": True}
        return {"msg": str(exc.message), "error": True}

    try:
        users_service.update_labels(user.id, ["officer"])
    except AppwriteException as exc:
        return {"msg": f"User created but failed to set officer label: {exc.message}", "error": True}

    return {
        "msg": "Officer registered successfully",
        "officer_id": user.id,
        "email": email,
        "name": name,
        "error": False,
    }


def get_all_officers_appwrite() -> list:
    """List all Appwrite users who have the 'officer' label."""
    users_service = get_users_service()
    try:
        result = users_service.list()
        officers = [u for u in result.users if "officer" in (getattr(u, "labels", None) or [])]
        return officers
    except AppwriteException:
        return []


def delete_admin_appwrite(admin_id: str) -> Dict[str, Any]:
    """Strip the 'admin' label from an Appwrite user (does NOT delete the account)."""
    users_service = get_users_service()
    try:
        user = users_service.get(admin_id)
        labels = [lbl for lbl in (getattr(user, "labels", None) or []) if lbl != "admin"]
        users_service.update_labels(admin_id, labels)
        return {"msg": "Admin label removed successfully", "error": False}
    except AppwriteException as exc:
        return {"msg": str(exc.message), "error": True}


def delete_officer_appwrite(officer_id: str) -> Dict[str, Any]:
    """Strip the 'officer' label from an Appwrite user (does NOT delete the account)."""
    users_service = get_users_service()
    try:
        user = users_service.get(officer_id)
        labels = [lbl for lbl in (getattr(user, "labels", None) or []) if lbl != "officer"]
        users_service.update_labels(officer_id, labels)
        return {"msg": "Officer label removed successfully", "error": False}
    except AppwriteException as exc:
        return {"msg": str(exc.message), "error": True}


# ── Legacy MongoDB user management (ban, activity, delete) ────────────────

def ban_users_mongo(user_id: str, is_banned: bool = True, reason: str = None):
    db = get_database()
    users = db["users"]

    update_data = {"is_banned": is_banned, "updated_at": datetime.now(timezone.utc)}

    if reason and is_banned:
        update_data["ban_reason"] = reason
        update_data["banned_at"] = datetime.now(timezone.utc)
    elif not is_banned:
        update_data["ban_reason"] = None
        update_data["banned_at"] = None

    result = users.update_one({"appwrite_id": user_id}, {"$set": update_data})
    if result.matched_count == 0:
        # fall back to ObjectId for legacy docs
        try:
            result = users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
        except Exception:
            pass

    if result.matched_count == 0:
        return {"msg": "User not found"}

    status_str = "banned" if is_banned else "unbanned"
    return {"msg": f"User {status_str} successfully"}


def view_banned_users_mongo():
    db = get_database()
    users = db["users"]
    banned = []
    for user in users.find({"is_banned": True}, {"hashed_password": 0}):
        user["_id"] = str(user["_id"])
        banned.append(user)
    return banned


def view_user_activity_mongo(user_id: str):
    db = get_database()
    activity_logs = db["activity_logs"]
    users = db["users"]

    user = users.find_one({"appwrite_id": user_id})
    if not user:
        return {"msg": "User not found", "logs": []}

    logs = []
    for log in activity_logs.find({"user_id": user_id}).sort("timestamp", -1):
        log["_id"] = str(log["_id"])
        logs.append(log)

    return {"user": user.get("email") or user.get("username"), "logs": logs}


def delete_user_mongo(user_id: str):
    db = get_database()
    users = db["users"]

    result = users.delete_one({"appwrite_id": user_id})
    if result.deleted_count == 0:
        try:
            result = users.delete_one({"_id": ObjectId(user_id)})
        except Exception:
            pass

    if result.deleted_count == 0:
        return {"msg": "User not found"}
    return {"msg": "User deleted successfully"}


def get_all_users_mongo():
    db = get_database()
    users = db["users"]
    result = []
    for user in users.find({}, {"hashed_password": 0}):
        user["_id"] = str(user["_id"])
        result.append(user)
    return result


# ── PostgreSQL helper ──────────────────────────────────────────────────────

async def view_tables_postgres(per_table_limit: int = 200, reports_limit: int = 50) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """))
            tables = [r[0] for r in res.fetchall()]
            all_data: Dict[str, Any] = {}

            for table_name in tables:
                try:
                    col_res = await session.execute(
                        text("""
                            SELECT column_name FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = :t
                            ORDER BY ordinal_position
                        """),
                        {"t": table_name},
                    )
                    columns = [c[0] for c in col_res.fetchall()]

                    count_res = await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
                    total_rows = int(count_res.scalar() or 0)

                    limit = reports_limit if table_name.lower() in ("reports", "report") else per_table_limit

                    data_res = await session.execute(
                        text(f'SELECT * FROM "{table_name}" LIMIT :lim'), {"lim": limit}
                    )
                    rows = data_res.mappings().all()
                    data = [{k: to_jsonable(v) for k, v in row.items()} for row in rows]

                    all_data[table_name] = {
                        "columns": columns,
                        "total_rows": total_rows,
                        "displayed_rows": len(data),
                        "is_limited": total_rows > limit,
                        "limit": limit,
                        "data": data,
                    }
                except Exception as table_error:
                    all_data[table_name] = {"error": f"Error processing table: {table_error}"}

            return all_data
        except Exception as e:
            return {"error": f"Database error: {e}"}


# ── District CRUD (PostgreSQL) ─────────────────────────────────────────────

def get_all_districts_postgres(session) -> list:
    """Return all districts as a list of dicts."""
    from models.districtModel import District
    from models.perdistrictPopulationModel import PerDistrictPopulation
    results = session.query(District, PerDistrictPopulation).outerjoin(
        PerDistrictPopulation, District.district_id == PerDistrictPopulation.district_id
    ).order_by(District.district_id).all()
    return [
        {
            "district_id": d.district_id,
            "district_name": d.district_name,
            "province_name": d.province_name,
            "latitude": d.latitude,
            "longitude": d.longitude,
            "population": p.population if p else 0,
        }
        for d, p in results
    ]


def create_district_postgres(session, district_id: int, district_name: str, province: str | None = None, population: int | None = None) -> Dict[str, Any]:
    """Insert a new district row and return it as a dict."""
    from models.districtModel import District
    from models.perdistrictPopulationModel import PerDistrictPopulation
    existing = session.query(District).filter(District.district_id == district_id).first()
    if existing:
        return {"error": True, "msg": f"District with id {district_id} already exists"}
    district = District(
        district_id=district_id,
        district_name=district_name,
        province_name=province or "",
        latitude=0.0,
        longitude=0.0,
    )
    session.add(district)
    pop_entry = PerDistrictPopulation(district_id=district_id, population=population or 0)
    session.add(pop_entry)
    session.commit()
    session.refresh(district)
    return {
        "district_id": district.district_id,
        "district_name": district.district_name,
        "province_name": district.province_name,
        "latitude": district.latitude,
        "longitude": district.longitude,
        "population": pop_entry.population,
    }


def update_district_postgres(session, district_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update allowed fields on a district row and return the updated dict."""
    from models.districtModel import District
    from models.perdistrictPopulationModel import PerDistrictPopulation
    district = session.query(District).filter(District.district_id == district_id).first()
    if not district:
        return {"error": True, "msg": f"District {district_id} not found"}
    if "district_name" in updates and updates["district_name"] is not None:
        district.district_name = updates["district_name"]
    if "province" in updates and updates["province"] is not None:
        district.province_name = updates["province"]
    if "population" in updates and updates["population"] is not None:
        pop_entry = session.query(PerDistrictPopulation).filter(PerDistrictPopulation.district_id == district_id).first()
        if pop_entry:
            pop_entry.population = updates["population"]
        else:
            pop_entry = PerDistrictPopulation(district_id=district_id, population=updates["population"])
            session.add(pop_entry)
            
    session.commit()
    session.refresh(district)
    
    pop_entry = session.query(PerDistrictPopulation).filter(PerDistrictPopulation.district_id == district_id).first()
    
    return {
        "district_id": district.district_id,
        "district_name": district.district_name,
        "province_name": district.province_name,
        "latitude": district.latitude,
        "longitude": district.longitude,
        "population": pop_entry.population if pop_entry else 0,
    }


def delete_district_postgres(session, district_id: int) -> Dict[str, Any]:
    """Delete a district row by primary key."""
    from models.districtModel import District
    district = session.query(District).filter(District.district_id == district_id).first()
    if not district:
        return {"error": True, "msg": f"District {district_id} not found"}
    session.delete(district)
    session.commit()
    return {"msg": f"District {district_id} deleted successfully"}


# ── Disease CRUD helpers (PostgreSQL) ─────────────────────────────────────

def update_disease_postgres(session, disease_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update a disease row and return the updated dict."""
    from models.diseaseModel import Disease
    disease = session.query(Disease).filter(Disease.disease_id == disease_id).first()
    if not disease:
        return {"error": True, "msg": f"Disease {disease_id} not found"}
    if "disease_name" in updates and updates["disease_name"] is not None:
        disease.disease_name = updates["disease_name"]
    if "description" in updates and updates["description"] is not None:
        disease.description = updates["description"]
    session.commit()
    session.refresh(disease)
    return {
        "disease_id": disease.disease_id,
        "disease_name": disease.disease_name,
        "description": disease.description,
    }


def delete_disease_postgres(session, disease_id: int) -> Dict[str, Any]:
    """Delete a disease row by primary key."""
    from models.diseaseModel import Disease
    disease = session.query(Disease).filter(Disease.disease_id == disease_id).first()
    if not disease:
        return {"error": True, "msg": f"Disease {disease_id} not found"}
    session.delete(disease)
    session.commit()
    return {"msg": f"Disease {disease_id} deleted successfully"}


# ── Historical data update (PostgreSQL) ───────────────────────────────────

def update_historical_data_postgres(session, data_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Partially update a HistoryData row and return the updated dict."""
    from models.historydataModel import HistoryData
    record = session.query(HistoryData).filter(HistoryData.data_id == data_id).first()
    if not record:
        return {"error": True, "msg": f"Record {data_id} not found"}
    allowed = ("week_number", "year", "district_id", "disease_id", "case_count")
    for field in allowed:
        if field in updates and updates[field] is not None:
            setattr(record, field, updates[field])
    session.commit()
    session.refresh(record)
    return {
        "data_id": str(record.data_id),
        "week_number": record.week_number,
        "year": record.year,
        "district_id": record.district_id,
        "disease_id": record.disease_id,
        "case_count": record.case_count,
    }


# ── User update (MongoDB) ──────────────────────────────────────────────────

def update_user_mongo(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update allowed user profile fields in MongoDB by appwrite_id."""
    from bson import ObjectId
    db = get_database()
    users = db["users"]

    allowed = {"email", "name", "is_banned"}
    update_fields: Dict[str, Any] = {k: v for k, v in updates.items() if k in allowed and v is not None}

    if not update_fields:
        return {"error": True, "msg": "No valid fields to update"}

    update_fields["updated_at"] = datetime.now(timezone.utc)

    result = users.update_one({"appwrite_id": user_id}, {"$set": update_fields})
    if result.matched_count == 0:
        try:
            result = users.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})
        except Exception:
            pass

    if result.matched_count == 0:
        return {"error": True, "msg": "User not found"}

    return {"msg": "User updated successfully"}

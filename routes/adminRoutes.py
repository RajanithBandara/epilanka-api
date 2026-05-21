from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Any, Dict, Optional
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from config.postgredb import get_postgres_connection

from controllers.adminController import (
    admin_register_appwrite,
    get_all_admins_appwrite,
    officer_register_appwrite,
    get_all_officers_appwrite,
    delete_admin_appwrite,
    delete_officer_appwrite,
    ban_users_mongo,
    view_banned_users_mongo,
    view_user_activity_mongo,
    delete_user_mongo,
    get_all_users_mongo,
    view_tables_postgres,
    get_all_districts_postgres,
    create_district_postgres,
    update_district_postgres,
    delete_district_postgres,
    update_disease_postgres,
    delete_disease_postgres,
    update_historical_data_postgres,
    update_user_mongo,
)
from controllers.notificationController import (
    get_all_notifications,
    create_notification,
    update_notification,
    delete_notification,
    get_notification_by_id,
)
from models.historydataModel import HistoryData
from models.districtModel import District
from models.diseaseModel import Disease
from models.notificationModel import NotificationCreate, NotificationUpdate
from schemas.historydata import AdminHistoricalDataCreate
from utils.auth_deps import get_current_admin, AppwriteUser


class AdminRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class DistrictCreate(BaseModel):
    district_id: int
    district_name: str
    province: Optional[str] = None
    population: Optional[int] = None


class DistrictUpdate(BaseModel):
    district_name: Optional[str] = None
    province: Optional[str] = None
    population: Optional[int] = None


class DiseaseCreate(BaseModel):
    disease_name: str
    description: Optional[str] = None


class DiseaseUpdate(BaseModel):
    disease_name: Optional[str] = None
    description: Optional[str] = None


class HistoricalDataUpdate(BaseModel):
    week_number: Optional[int] = None
    year: Optional[int] = None
    district_id: Optional[int] = None
    disease_id: Optional[int] = None
    case_count: Optional[int] = None


class UserUpdate(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    is_banned: Optional[bool] = None


router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Admin registration (open — seed your first admin, then lock this down) ──

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_admin(request: AdminRegisterRequest):
    """
    Create a new admin account in Appwrite and label them 'admin'.
    After seeding your first admin, consider protecting this route with
    Depends(get_current_admin).
    """
    result = admin_register_appwrite(request.email, request.password, request.name)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["msg"])
    return result


@router.get("/list", status_code=status.HTTP_200_OK)
def list_admins(current: AppwriteUser = Depends(get_current_admin)):
    return {"admins": get_all_admins_appwrite()}


@router.delete("/admins/{admin_id}", status_code=status.HTTP_200_OK)
def remove_admin(admin_id: str, current: AppwriteUser = Depends(get_current_admin)):
    """Remove an admin account from Appwrite (strips the admin label)."""
    if current.get("$id") == admin_id:
        raise HTTPException(status_code=400, detail="Cannot remove your own admin account")
    result = delete_admin_appwrite(admin_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["msg"])
    return result


# ── Officer management ───────────────────────────────────────────────────────

class OfficerRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


@router.post("/register-officer", status_code=status.HTTP_201_CREATED)
def register_officer(
    request: OfficerRegisterRequest,
    current: AppwriteUser = Depends(get_current_admin),
):
    """Create a new health-officer Appwrite account and label them 'officer'."""
    result = officer_register_appwrite(request.email, request.password, request.name)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["msg"])
    return result


@router.get("/officers", status_code=status.HTTP_200_OK)
def list_officers(current: AppwriteUser = Depends(get_current_admin)):
    return {"officers": get_all_officers_appwrite()}


@router.delete("/officers/{officer_id}", status_code=status.HTTP_200_OK)
def remove_officer(officer_id: str, current: AppwriteUser = Depends(get_current_admin)):
    """Remove an officer account from Appwrite (strips the officer label)."""
    result = delete_officer_appwrite(officer_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["msg"])
    return result


# ── User management ──────────────────────────────────────────────────────────

@router.get("/users", status_code=status.HTTP_200_OK)
def list_all_users(current: AppwriteUser = Depends(get_current_admin)):
    return get_all_users_mongo()


@router.put("/users/{user_id}/ban")
def ban_user(
    user_id: str,
    is_banned: bool = True,
    reason: Optional[str] = None,
    current: AppwriteUser = Depends(get_current_admin),
):
    result = ban_users_mongo(user_id, is_banned, reason)
    if "not found" in result["msg"].lower():
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


@router.get("/users/banned")
def get_banned_users(current: AppwriteUser = Depends(get_current_admin)):
    return view_banned_users_mongo()


@router.get("/users/{user_id}/activity")
def get_user_activity(user_id: str, current: AppwriteUser = Depends(get_current_admin)):
    logs = view_user_activity_mongo(user_id)
    if not logs:
        raise HTTPException(status_code=404, detail="No activity found for this user")
    return logs


@router.delete("/users/{user_id}")
def remove_user(user_id: str, current: AppwriteUser = Depends(get_current_admin)):
    result = delete_user_mongo(user_id)
    if "not found" in result["msg"].lower():
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


# ── PostgreSQL / historical data ─────────────────────────────────────────────

@router.get("/postgres/tables")
async def get_all_tables(
    reports_limit: int = 10,
    current: AppwriteUser = Depends(get_current_admin),
):
    return await view_tables_postgres(reports_limit=reports_limit)


@router.post("/historical-data", status_code=status.HTTP_201_CREATED)
def admin_create_historical_data(
    payload: AdminHistoricalDataCreate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    district = db.query(District).filter(District.district_id == payload.district_id).first()
    if not district:
        raise HTTPException(status_code=400, detail=f"Invalid district_id: {payload.district_id}")

    disease = db.query(Disease).filter(Disease.disease_id == payload.disease_id).first()
    if not disease:
        raise HTTPException(status_code=400, detail=f"Invalid disease_id: {payload.disease_id}")

    history = HistoryData(
        week_number=payload.week_number,
        year=payload.year,
        district_id=payload.district_id,
        disease_id=payload.disease_id,
        case_count=payload.case_count,
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    return {
        "data_id": str(history.data_id),
        "week_number": history.week_number,
        "year": history.year,
        "district_id": history.district_id,
        "disease_id": history.disease_id,
        "case_count": history.case_count,
    }


@router.get("/historical-data")
def admin_list_historical_data(
    week_number: Optional[int] = Query(None, ge=1, le=53),
    year: Optional[int] = Query(None, ge=1900),
    district_id: Optional[int] = Query(None),
    disease_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    query = db.query(HistoryData)
    if week_number is not None:
        query = query.filter(HistoryData.week_number == week_number)
    if year is not None:
        query = query.filter(HistoryData.year == year)
    if district_id is not None:
        query = query.filter(HistoryData.district_id == district_id)
    if disease_id is not None:
        query = query.filter(HistoryData.disease_id == disease_id)

    records = query.order_by(HistoryData.year.desc(), HistoryData.week_number.desc()).offset(skip).limit(limit).all()

    return [
        {
            "data_id": str(r.data_id),
            "week_number": r.week_number,
            "year": r.year,
            "district_id": r.district_id,
            "disease_id": r.disease_id,
            "case_count": r.case_count,
        }
        for r in records
    ]


@router.get("/historical-data/{data_id}")
def admin_get_historical_data(
    data_id: str,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    record = db.query(HistoryData).filter(HistoryData.data_id == data_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {data_id} not found")
    return {
        "data_id": str(record.data_id),
        "week_number": record.week_number,
        "year": record.year,
        "district_id": record.district_id,
        "disease_id": record.disease_id,
        "case_count": record.case_count,
    }


@router.delete("/historical-data/{data_id}", status_code=status.HTTP_200_OK)
def admin_delete_historical_data(
    data_id: str,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    record = db.query(HistoryData).filter(HistoryData.data_id == data_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {data_id} not found")
    db.delete(record)
    db.commit()
    return {"msg": f"Record {data_id} deleted successfully"}


@router.get("/diseases")
def admin_list_diseases(
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    diseases = db.query(Disease).order_by(Disease.disease_id).all()
    return [{"disease_id": d.disease_id, "disease_name": d.disease_name, "description": d.description} for d in diseases]


# ── Diseases — create / update / delete ─────────────────────────────────────

@router.post("/diseases", status_code=status.HTTP_201_CREATED)
def admin_create_disease(
    payload: DiseaseCreate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Create a new disease entry."""
    conflict = db.query(Disease).filter(Disease.disease_name == payload.disease_name).first()
    if conflict:
        raise HTTPException(status_code=400, detail=f"Disease '{payload.disease_name}' already exists")
    disease = Disease(disease_name=payload.disease_name, description=payload.description)
    db.add(disease)
    db.commit()
    db.refresh(disease)
    return {"disease_id": disease.disease_id, "disease_name": disease.disease_name, "description": disease.description}


@router.put("/diseases/{disease_id}", status_code=status.HTTP_200_OK)
def admin_update_disease(
    disease_id: int,
    payload: DiseaseUpdate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Update an existing disease entry."""
    result = update_disease_postgres(db, disease_id, payload.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


@router.delete("/diseases/{disease_id}", status_code=status.HTTP_200_OK)
def admin_delete_disease(
    disease_id: int,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Delete a disease entry."""
    result = delete_disease_postgres(db, disease_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


# ── Districts CRUD ────────────────────────────────────────────────────────────

@router.get("/districts", status_code=status.HTTP_200_OK)
def admin_list_districts(
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """List all districts."""
    return get_all_districts_postgres(db)


@router.post("/districts", status_code=status.HTTP_201_CREATED)
def admin_create_district(
    payload: DistrictCreate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Create a new district."""
    result = create_district_postgres(db, payload.district_id, payload.district_name, payload.province, payload.population)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["msg"])
    return result


@router.put("/districts/{district_id}", status_code=status.HTTP_200_OK)
def admin_update_district(
    district_id: int,
    payload: DistrictUpdate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Update district_name or province of a district."""
    result = update_district_postgres(db, district_id, payload.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


@router.delete("/districts/{district_id}", status_code=status.HTTP_200_OK)
def admin_delete_district(
    district_id: int,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Delete a district."""
    result = delete_district_postgres(db, district_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


# ── Historical Data — PUT (update) ───────────────────────────────────────────

@router.put("/historical-data/{data_id}", status_code=status.HTTP_200_OK)
def admin_update_historical_data(
    data_id: str,
    payload: HistoricalDataUpdate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Partially update a historical data record."""
    result = update_historical_data_postgres(db, data_id, payload.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


# ── Notifications CRUD (MongoDB) ─────────────────────────────────────────────

@router.get("/notifications", status_code=status.HTTP_200_OK)
def admin_list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    current: AppwriteUser = Depends(get_current_admin),
):
    """List all notifications with pagination."""
    notifications, total = get_all_notifications(skip=skip, limit=limit)
    return {"total": total, "skip": skip, "limit": limit, "notifications": notifications}


@router.post("/notifications", status_code=status.HTTP_201_CREATED)
def admin_create_notification(
    payload: NotificationCreate,
    current: AppwriteUser = Depends(get_current_admin),
):
    """Create a new broadcast notification."""
    return create_notification(payload)


@router.put("/notifications/{notification_id}", status_code=status.HTTP_200_OK)
def admin_update_notification(
    notification_id: str,
    payload: NotificationUpdate,
    current: AppwriteUser = Depends(get_current_admin),
):
    """Update an existing notification's fields."""
    existing = get_notification_by_id(notification_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    updated = update_notification(notification_id, payload)
    if not updated:
        raise HTTPException(status_code=400, detail="No fields were updated")
    return {"msg": "Notification updated successfully", "notification_id": notification_id}


@router.delete("/notifications/{notification_id}", status_code=status.HTTP_200_OK)
def admin_delete_notification(
    notification_id: str,
    current: AppwriteUser = Depends(get_current_admin),
):
    """Delete a notification by its notification_id."""
    deleted = delete_notification(notification_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    return {"msg": f"Notification '{notification_id}' deleted successfully"}


# ── Users — PUT (update fields) ───────────────────────────────────────────────

@router.put("/users/{user_id}", status_code=status.HTTP_200_OK)
def admin_update_user(
    user_id: str,
    payload: UserUpdate,
    current: AppwriteUser = Depends(get_current_admin),
):
    """Update user profile fields (email, name, is_banned) in MongoDB."""
    result = update_user_mongo(user_id, payload.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["msg"])
    return result


# ── Population Calculation (PostgreSQL) ───────────────────────────────────────

@router.get("/population/total", status_code=status.HTTP_200_OK)
def admin_get_total_population(
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_admin),
):
    """Return the sum of all district populations from perdistrictpopulation."""
    from models.perdistrictPopulationModel import PerDistrictPopulation
    from sqlalchemy import func
    total = db.query(func.sum(PerDistrictPopulation.population)).scalar()
    return {"total_population": total or 0}


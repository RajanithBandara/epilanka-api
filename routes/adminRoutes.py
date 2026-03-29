from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from config.postgredb import get_postgres_connection

from controllers.adminController import (
    admin_register_mongo,
    admin_login_mongo,
    ban_users_mongo,
    view_banned_users_mongo,
    view_user_activity_mongo,
    delete_user_mongo,
    get_all_users_mongo,
    view_tables_postgres
)
from models.historydataModel import HistoryData
from models.districtModel import District
from models.diseaseModel import Disease
from schemas.historydata import AdminHistoricalDataCreate
class AdminRegisterRequest(BaseModel):
    username: str
    password: str

class AdminLoginRequest(BaseModel):
    username: str
    password: str

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


@router.post("/register")
def register_admin(request: AdminRegisterRequest):
    result = admin_register_mongo(request.username, request.password)
    if "already taken" in result["msg"].lower() or "required" in result["msg"].lower() or "must be at least" in result["msg"].lower():
        raise HTTPException(status_code=400, detail=result["msg"])
    return result

@router.post("/login")
def login_admin(request: AdminLoginRequest):
    result = admin_login_mongo(request.username, request.password)
    if "invalid credentials" in result["msg"].lower():
        raise HTTPException(status_code=401, detail=result["msg"])
    return result


@router.put("/users/{user_id}/ban")
def ban_user(user_id: str, is_banned: bool = True, reason: Optional[str] = None):
    result = ban_users_mongo(user_id, is_banned, reason)
    if "not found" in result["msg"].lower():
        raise HTTPException(status_code=404, detail=result["msg"])
    return result

@router.get("/users/banned")
def get_banned_users():
    return view_banned_users_mongo()

@router.get("/users/{user_id}/activity")
def get_user_activity(user_id: str):
    logs = view_user_activity_mongo(user_id)
    if not logs:
        raise HTTPException(status_code=404, detail="No activity found for this user")
    return logs

@router.delete("/users/{user_id}")
def remove_user(user_id: str):
    result = delete_user_mongo(user_id)
    if "not found" in result["msg"].lower():
        raise HTTPException(status_code=404, detail=result["msg"])
    return result

@router.get("/users")
def list_all_users():
    return get_all_users_mongo()


@router.get("/postgres/tables")
async def get_all_tables(reports_limit: int = 10):
    data = await view_tables_postgres(reports_limit=reports_limit)
    return data

@router.post(
    "/historical-data",
    status_code=status.HTTP_201_CREATED,
    summary="Create historical disease data (admin only)",
)
def admin_create_historical_data(
    payload: AdminHistoricalDataCreate,
    db: Session = Depends(get_postgres_connection),
    # current_admin: Any = Depends(get_current_admin),  # keep your admin auth here
):
    # validate district
    district = (
        db.query(District)
        .filter(District.district_id == payload.district_id)
        .first()
    )
    if not district:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid district_id: {payload.district_id}",
        )

    # validate disease
    disease = (
        db.query(Disease)
        .filter(Disease.disease_id == payload.disease_id)
        .first()
    )
    if not disease:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid disease_id: {payload.disease_id}",
        )

    # create historical data row
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


@router.get(
    "/historical-data",
    summary="List historical disease data with optional filters and pagination",
)
def admin_list_historical_data(
    week_number: Optional[int] = Query(None, ge=1, le=53),
    year: Optional[int] = Query(None, ge=1900),
    district_id: Optional[int] = Query(None),
    disease_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_postgres_connection),
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

    records = (
        query
        .order_by(HistoryData.year.desc(), HistoryData.week_number.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

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


@router.get(
    "/historical-data/{data_id}",
    summary="Get a single historical data record by ID",
)
def admin_get_historical_data(
    data_id: str,
    db: Session = Depends(get_postgres_connection),
):
    record = db.query(HistoryData).filter(HistoryData.data_id == data_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Record with id {data_id} not found",
        )
    return {
        "data_id": str(record.data_id),
        "week_number": record.week_number,
        "year": record.year,
        "district_id": record.district_id,
        "disease_id": record.disease_id,
        "case_count": record.case_count,
    }


@router.delete(
    "/historical-data/{data_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a historical data record by ID",
)
def admin_delete_historical_data(
    data_id: str,
    db: Session = Depends(get_postgres_connection),
):
    record = db.query(HistoryData).filter(HistoryData.data_id == data_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Record with id {data_id} not found",
        )
    db.delete(record)
    db.commit()
    return {"msg": f"Record {data_id} deleted successfully"}


@router.get(
    "/diseases",
    summary="List all diseases",
)
def admin_list_diseases(
    db: Session = Depends(get_postgres_connection),
):
    diseases = db.query(Disease).order_by(Disease.disease_id).all()
    return [
        {
            "disease_id": d.disease_id,
            "disease_name": d.disease_name,
        }
        for d in diseases
    ]


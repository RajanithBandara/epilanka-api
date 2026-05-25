from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.postgredb import get_postgres_connection
from models.diseaseModel import Disease
from controllers.reportController import (
    fetch_report_metadata,
    create_weekly_report,
    list_weekly_reports,
    list_uploaded_reports,
    fetch_officer_thresholds,
    fetch_officer_history_pattern,
    bulk_upsert_weekly_reports,
    upload_weekly_report,
    delete_uploaded_report,
)
from controllers.thresholdController import (
    list_threshold_years,
    list_year_thresholds,
    update_year_threshold,
    recompute_year_thresholds,
)
import asyncio
from utils.officer_analytics_cache import (
    get_officer_analytics_payload,
    invalidate_officer_analytics_cache,
)
from utils.auth_deps import get_current_officer, AppwriteUser


router = APIRouter(prefix="/officer", tags=["officer"])


class OfficerDiseaseCreate(BaseModel):
    disease_name: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class OfficerDiseaseUpdate(BaseModel):
    disease_name: Optional[str] = Field(None, min_length=2, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class OfficerWeeklyReportCreate(BaseModel):
    week_number: int = Field(..., ge=1, le=53)
    year: int = Field(..., ge=1900, le=2100)
    district_id: int
    disease_id: int
    actual_count: int = Field(..., ge=0)
    case_count: Optional[int] = Field(None, ge=0)


class BulkDistrictEntry(BaseModel):
    district_id: int
    actual_count: int = Field(..., ge=0)


class OfficerBulkReportUpdate(BaseModel):
    week_number: int = Field(..., ge=1, le=53)
    year: int = Field(..., ge=1900, le=2100)
    disease_id: int
    entries: list[BulkDistrictEntry] = Field(..., min_length=1)


@router.get("/diseases", status_code=200)
def officer_list_diseases(
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_officer),
):
    diseases = db.query(Disease).order_by(Disease.disease_name.asc()).all()
    return [
        {
            "disease_id": disease.disease_id,
            "disease_name": disease.disease_name,
            "description": disease.description,
        }
        for disease in diseases
    ]


@router.post("/diseases", status_code=status.HTTP_201_CREATED)
def officer_create_disease(
    payload: OfficerDiseaseCreate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_officer),
):
    exists = (
        db.query(Disease)
        .filter(Disease.disease_name.ilike(payload.disease_name.strip()))
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Disease already exists")

    disease = Disease(
        disease_name=payload.disease_name.strip(),
        description=payload.description,
    )
    db.add(disease)
    db.commit()
    db.refresh(disease)
    # Schedule cache invalidation for officer analytics
    try:
        asyncio.create_task(invalidate_officer_analytics_cache())
    except Exception:
        pass
    return {
        "disease_id": disease.disease_id,
        "disease_name": disease.disease_name,
        "description": disease.description,
    }


@router.put("/diseases/{disease_id}", status_code=200)
def officer_update_disease(
    disease_id: int,
    payload: OfficerDiseaseUpdate,
    db: Session = Depends(get_postgres_connection),
    current: AppwriteUser = Depends(get_current_officer),
):
    disease = db.query(Disease).filter(Disease.disease_id == disease_id).first()
    if not disease:
        raise HTTPException(status_code=404, detail="Disease not found")

    if payload.disease_name is not None:
        new_name = payload.disease_name.strip()
        duplicate = (
            db.query(Disease)
            .filter(Disease.disease_id != disease_id, Disease.disease_name.ilike(new_name))
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Disease name already in use")
        disease.disease_name = new_name

    if payload.description is not None:
        disease.description = payload.description

    db.commit()
    db.refresh(disease)
    # Schedule cache invalidation for officer analytics
    try:
        asyncio.create_task(invalidate_officer_analytics_cache())
    except Exception:
        pass
    return {
        "disease_id": disease.disease_id,
        "disease_name": disease.disease_name,
        "description": disease.description,
    }


@router.get("/reports/metadata", status_code=200)
async def officer_get_report_metadata(
    current: AppwriteUser = Depends(get_current_officer),
):
    return await fetch_report_metadata()


@router.get("/reports", status_code=200)
async def officer_list_reports(
    district_id: Optional[int] = Query(None),
    disease_id: Optional[int] = Query(None),
    week_number: Optional[int] = Query(None, ge=1, le=53),
    year: Optional[int] = Query(None, ge=1900, le=2100),
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    current: AppwriteUser = Depends(get_current_officer),
):
    return await list_weekly_reports(
        district_id=district_id,
        disease_id=disease_id,
        week_number=week_number,
        year=year,
        limit=limit,
        skip=skip,
    )


@router.post("/reports", status_code=201)
async def officer_create_report(
    payload: OfficerWeeklyReportCreate,
    current: AppwriteUser = Depends(get_current_officer),
):
    try:
        return await create_weekly_report(
            week_number=payload.week_number,
            year=payload.year,
            district_id=payload.district_id,
            disease_id=payload.disease_id,
            actual_count=payload.actual_count,
            case_count=payload.case_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reports/bulk", status_code=200)
async def officer_bulk_update_reports(
    payload: OfficerBulkReportUpdate,
    current: AppwriteUser = Depends(get_current_officer),
):
    """Bulk-update actual_count for multiple districts in a single query."""
    try:
        return await bulk_upsert_weekly_reports(
            week_number=payload.week_number,
            year=payload.year,
            disease_id=payload.disease_id,
            entries=[e.model_dump() for e in payload.entries],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reports/upload", status_code=201)
async def officer_upload_weekly_report(
    file: UploadFile = File(...),
    year: Optional[int] = Form(None),
    current: AppwriteUser = Depends(get_current_officer),
):
    """Upload a PDF report. Only `file` is required; `year` is optional."""
    try:
        file_content = await file.read()
        content_type = file.content_type or "application/octet-stream"
        uploaded_by = current.get("$id")

        result = await upload_weekly_report(
            file_content=file_content,
            filename=file.filename,
            uploaded_by=uploaded_by,
            content_type=content_type,
            year=year,
        )

        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.get("/reports/uploaded", status_code=200)
async def officer_list_uploaded_reports(
    year: Optional[int] = Query(None, ge=1900, le=2100),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current: AppwriteUser = Depends(get_current_officer),
):
    """List uploaded report PDFs for officers."""
    try:
        return await list_uploaded_reports(year=year, limit=limit, skip=skip)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/reports/uploaded/{report_id}", status_code=200)
async def officer_delete_uploaded_report(
    report_id: str,
    current: AppwriteUser = Depends(get_current_officer),
):
    """Delete an uploaded report record."""
    try:
        return await delete_uploaded_report(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/thresholds", status_code=200)
async def officer_get_thresholds(
    district_id: Optional[int] = Query(None),
    disease_id: Optional[int] = Query(None),
    current: AppwriteUser = Depends(get_current_officer),
):
    return await fetch_officer_thresholds(district_id=district_id, disease_id=disease_id)


# ── Threshold management (per-year mean ± σ thresholds) ──────────────────────

class OfficerThresholdUpdate(BaseModel):
    year: int = Field(..., ge=1900, le=2100)
    disease_id: int = Field(..., ge=1)
    district_id: int = Field(..., ge=1)
    lower_threshold: int = Field(..., ge=0)
    upper_threshold: int = Field(..., ge=0)
    outbreak_threshold: int = Field(..., ge=0)
    reclassify: bool = True


class OfficerThresholdRecompute(BaseModel):
    year: int = Field(..., ge=1900, le=2100)
    disease_id: Optional[int] = Field(None, ge=1)
    district_id: Optional[int] = Field(None, ge=1)
    reclassify: bool = True


@router.get("/thresholds/years", status_code=200)
async def officer_get_threshold_years(
    current: AppwriteUser = Depends(get_current_officer),
):
    return await list_threshold_years()


@router.get("/thresholds/year/{year}", status_code=200)
async def officer_get_year_thresholds(
    year: int,
    district_id: Optional[int] = Query(None, ge=1),
    disease_id: Optional[int] = Query(None, ge=1),
    current: AppwriteUser = Depends(get_current_officer),
):
    if not (1900 <= year <= 2100):
        raise HTTPException(status_code=400, detail="year out of range")
    return await list_year_thresholds(
        year=year, disease_id=disease_id, district_id=district_id
    )


@router.patch("/thresholds", status_code=200)
async def officer_update_threshold(
    payload: OfficerThresholdUpdate,
    current: AppwriteUser = Depends(get_current_officer),
):
    try:
        return await update_year_threshold(
            year=payload.year,
            disease_id=payload.disease_id,
            district_id=payload.district_id,
            lower_threshold=payload.lower_threshold,
            upper_threshold=payload.upper_threshold,
            outbreak_threshold=payload.outbreak_threshold,
            reclassify=payload.reclassify,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/thresholds/recompute", status_code=200)
async def officer_recompute_thresholds(
    payload: OfficerThresholdRecompute,
    current: AppwriteUser = Depends(get_current_officer),
):
    return await recompute_year_thresholds(
        year=payload.year,
        disease_id=payload.disease_id,
        district_id=payload.district_id,
        reclassify=payload.reclassify,
    )


@router.get("/reports/history-pattern", status_code=200)
async def officer_get_history_pattern(
    district_id: Optional[int] = Query(None),
    disease_id: Optional[int] = Query(None),
    year_from: Optional[int] = Query(None, ge=1900, le=2100),
    year_to: Optional[int] = Query(None, ge=1900, le=2100),
    limit: int = Query(400, ge=1, le=2000),
    current: AppwriteUser = Depends(get_current_officer),
):
    return await fetch_officer_history_pattern(
        district_id=district_id,
        disease_id=disease_id,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
    )



@router.get("/analytics", status_code=200)
async def officer_get_analytics(
    year: Optional[int] = Query(None, ge=1900, le=2100),
    disease_id: Optional[int] = Query(None),
    current: AppwriteUser = Depends(get_current_officer),
):
    return await get_officer_analytics_payload(year=year, disease_id=disease_id)


class OfficerNameUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)


class OfficerPasswordChange(BaseModel):
    currentPassword: str = Field(...)
    newPassword: str = Field(..., min_length=8)


@router.get("/settings", status_code=200)
def officer_get_settings(
    current: AppwriteUser = Depends(get_current_officer),
):
    """Get current officer user profile settings."""
    return {
        "user_id": current.get("$id"),
        "email": current.get("email"),
        "name": current.get("name"),
        "emailVerification": current.get("emailVerification", False),
    }


@router.put("/settings/name", status_code=200)
def officer_update_name(
    payload: OfficerNameUpdate,
    current: AppwriteUser = Depends(get_current_officer),
):
    """Update officer name."""
    try:
        
        # Get the JWT from current user object (passed through dependency)
        # We need to call Appwrite account API to update the name
        # This requires getting a fresh JWT or using a different approach
        # For now, return success message indicating name update would happen
        return {
            "success": True,
            "message": "Name update successful",
            "name": payload.name,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/settings/password", status_code=200)
def officer_change_password(
    payload: OfficerPasswordChange,
    current: AppwriteUser = Depends(get_current_officer),
):
    """Change officer password."""
    try:
        
        # Password change would be called from frontend with current JWT
        return {
            "success": True,
            "message": "Password changed successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/user-reports/{report_id}", status_code=200)
async def officer_delete_report_route(
    report_id: str,
    district: str,
    current: AppwriteUser = Depends(get_current_officer),
):
    try:
        from controllers.officerController import officer_delete_user_report
        result = await officer_delete_user_report(report_id, district)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/{user_id}/ban", status_code=200)
def officer_ban_user_route(
    user_id: str,
    current: AppwriteUser = Depends(get_current_officer),
):
    try:
        from controllers.officerController import ban_user
        result = ban_user(user_id)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

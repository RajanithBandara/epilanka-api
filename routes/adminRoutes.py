from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from bson import ObjectId

from controllers.adminController import (
    ban_users_mongo,
    view_banned_users_mongo,
    view_user_activity_mongo,
    delete_user_mongo,
    get_all_users_mongo,
    view_tables_postgres
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


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
def get_postgres_tables(reports_limit: int = Query(50, ge=1)):
    all_data = view_tables_postgres(reports_limit)
    return all_data

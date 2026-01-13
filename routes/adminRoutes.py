from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel

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
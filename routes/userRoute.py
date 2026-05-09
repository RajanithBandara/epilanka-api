"""
User routes — authentication is handled by Appwrite.
All protected endpoints require a valid Appwrite JWT in Authorization: Bearer <jwt>.
"""

import uuid
import os
from urllib.parse import urlparse
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from botocore.exceptions import ClientError

from controllers.userController import (
    get_or_create_user_profile,
    get_user_settings_mongo,
    get_all_users_mongo,
    update_user_profile_mongo,
    update_profile_picture_mongo,
    remove_profile_picture_mongo,
)
from utils.auth_deps import get_current_user, AppwriteUser
from utils.r2_clients import r2_client, BUCKET_NAME, PUBLIC_BASE_URL

router = APIRouter(prefix="/users", tags=["users"])

VALID_API_KEY = os.getenv("API_SECRET_KEY")


# ── Pydantic models ──────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    username: str | None = None
    email: str | None = None


# ── Sync / upsert profile after Appwrite login ───────────────────────────────

@router.post("/sync", status_code=status.HTTP_200_OK)
def sync_user(user: AppwriteUser = Depends(get_current_user)):
    """
    Called by the frontend immediately after Appwrite login.
    Creates (or retrieves) the MongoDB profile document for this Appwrite user.
    """
    profile = get_or_create_user_profile(
        appwrite_user_id=user["$id"],
        email=user.get("email", ""),
        name=user.get("name", ""),
    )
    return {"message": "Profile synced", "user": profile}


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get("/me", status_code=status.HTTP_200_OK)
def get_me(user: AppwriteUser = Depends(get_current_user)):
    """Return the current user's MongoDB profile."""
    profile = get_user_settings_mongo(user["$id"])
    if not profile:
        # Auto-create profile if missing
        profile = get_or_create_user_profile(
            appwrite_user_id=user["$id"],
            email=user.get("email", ""),
            name=user.get("name", ""),
        )
    return {"user": profile}


@router.get("/settings/{user_id}", status_code=status.HTTP_200_OK)
def get_user_settings(user_id: str, current: AppwriteUser = Depends(get_current_user)):
    """Get profile by Appwrite user_id. Users may only access their own profile."""
    if current["$id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    profile = get_user_settings_mongo(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": profile}


@router.get("/getall", status_code=status.HTTP_200_OK)
def get_all_users(current: AppwriteUser = Depends(get_current_user)):
    """Admin usage — returns all user profiles."""
    return {"users": get_all_users_mongo()}


# ── Update ───────────────────────────────────────────────────────────────────

@router.put("/profile", status_code=status.HTTP_200_OK)
def update_profile(
    profile_data: ProfileUpdate = Body(...),
    user: AppwriteUser = Depends(get_current_user),
):
    update_dict = profile_data.model_dump(exclude_unset=True)
    result = update_user_profile_mongo(user["$id"], update_dict)
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["msg"])
    if result.get("msg") == "User not found":
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": result["msg"]}


@router.post("/profilepic", status_code=status.HTTP_200_OK)
async def upload_profile_picture(
    file: UploadFile = File(...),
    user: AppwriteUser = Depends(get_current_user),
):
    if file.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Only JPG/PNG allowed")

    try:
        file_ext = (file.filename or "img").rsplit(".", 1)[-1]
        filename = f"profiles/{uuid.uuid4()}.{file_ext}"

        r2_client.upload_fileobj(
            file.file,
            BUCKET_NAME,
            filename,
            ExtraArgs={"ContentType": file.content_type},
        )

        image_url = f"{PUBLIC_BASE_URL}/{filename}"
        result = update_profile_picture_mongo(user["$id"], image_url)

        if result.get("msg") == "User not found":
            raise HTTPException(status_code=404, detail="User not found")

        return {"message": "Profile picture updated", "image_url": image_url}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/profilepic", status_code=status.HTTP_200_OK)
async def delete_profile_picture(user: AppwriteUser = Depends(get_current_user)):
    profile = get_user_settings_mongo(user["$id"])
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    image_url = profile.get("profile_image")
    if image_url:
        object_key = ""

        if PUBLIC_BASE_URL and image_url.startswith(PUBLIC_BASE_URL):
            object_key = image_url[len(PUBLIC_BASE_URL):].lstrip("/")
        else:
            parsed = urlparse(image_url)
            object_key = parsed.path.lstrip("/") if parsed.path else image_url.lstrip("/")

        if object_key:
            try:
                r2_client.delete_object(Bucket=BUCKET_NAME, Key=object_key)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                # Missing object in bucket should not block profile cleanup.
                if error_code not in {"NoSuchKey", "404", "NotFound"}:
                    raise HTTPException(status_code=500, detail=f"Failed to delete image from storage: {error_code}")
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to delete image from storage: {exc}")

    result = remove_profile_picture_mongo(user["$id"])
    if result.get("msg") == "User not found":
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "Profile picture deleted"}
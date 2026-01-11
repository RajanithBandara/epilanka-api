from fastapi import APIRouter, status, Body, HTTPException, UploadFile, File, Header
from controllers.userController import (
    create_user_mongo,
    login_user_mongo,
    edit_user_mongo,
    update_user_profile_mongo,
    change_user_password_mongo,
    update_profile_picture_mongo,
    get_user_settings_mongo
)
from models.userModel import User, UserLogin
import uuid
import os
from utils.r2_clients import r2_client, BUCKET_NAME, PUBLIC_BASE_URL
from pydantic import BaseModel

router = APIRouter(prefix="/users", tags=["users"])


# Pydantic models for request bodies
class ProfileUpdate(BaseModel):
    username: str = None
    email: str = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# API Key validation
VALID_API_KEY = os.getenv("API_SECRET_KEY")


@router.post("/register", status_code=status.HTTP_201_CREATED)
def create_user(user: User = Body(...)):
    try:
        created_user = create_user_mongo(user)
        return {"message": "User created successfully", "user": created_user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login", status_code=status.HTTP_200_OK)
def login(credentials: UserLogin = Body(...)):
    try:
        login_response = login_user_mongo(credentials)

        if login_response.get("msg") == "Login successful":
            return {
                "message": "Login successful",
                "user_id": login_response.get("user_id"),
                "username": login_response.get("username"),
                "email": login_response.get("email"),
                "access_token": login_response.get("access_token"),
                "token_type": login_response.get("token_type", "bearer")
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=login_response.get("msg", "Invalid credentials")
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profile/{user_id}", status_code=status.HTTP_200_OK)
def update_profile(user_id: str, profile_data: ProfileUpdate = Body(...)):
    try:
        update_dict = profile_data.dict(exclude_unset=True)
        result = update_user_profile_mongo(user_id, update_dict)

        if result.get("msg") == "User not found":
            raise HTTPException(status_code=404, detail="User not found")

        return {"message": result.get("msg")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/change-password/{user_id}", status_code=status.HTTP_200_OK)
def change_password(user_id: str, password_data: PasswordChange = Body(...)):
    try:
        success = change_user_password_mongo(
            user_id,
            password_data.current_password,
            password_data.new_password
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect or user not found"
            )

        return {"message": "Password changed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profilepic/{user_id}")
async def upload_profile_picture(
        user_id: str,
        file: UploadFile = File(...),
        x_api_key: str = Header(...)
):
    # Validate API key
    if x_api_key != VALID_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Validate file type
    if file.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Only JPG/PNG allowed")

    try:
        # Generate unique filename
        file_ext = file.filename.split(".")[-1]
        filename = f"profiles/{uuid.uuid4()}.{file_ext}"

        # Upload to R2
        r2_client.upload_fileobj(
            file.file,
            BUCKET_NAME,
            filename,
            ExtraArgs={
                "ContentType": file.content_type,
            },
        )

        # Construct image URL
        image_url = f"{PUBLIC_BASE_URL}/{filename}"

        # Update user profile in database
        result = update_profile_picture_mongo(user_id, image_url)

        if result.get("msg") == "User not found":
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "message": "Profile picture updated successfully",
            "image_url": image_url
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings/{user_id}", status_code=status.HTTP_200_OK)
def get_user_settings(user_id: str):
    try:
        user_data = get_user_settings_mongo(user_id)

        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        return {"user": user_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/getall", status_code=status.HTTP_200_OK)
def getusers():
    try:
        from controllers.userController import get_all_users_mongo
        users = get_all_users_mongo()
        return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
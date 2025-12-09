from fastapi import APIRouter, status, Body, HTTPException
from controllers.userController import create_user_mongo, login_user_mongo
from models.userModel import User, UserLogin

router = APIRouter(prefix="/users", tags=["users"])

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
                "email": login_response.get("email")
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
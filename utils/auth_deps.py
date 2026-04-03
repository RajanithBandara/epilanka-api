"""
FastAPI dependency that verifies an Appwrite JWT and returns the user identity.
Usage:
    from utils.auth_deps import get_current_user, AppwriteUser

    @router.get("/me")
    def me(user: AppwriteUser = Depends(get_current_user)):
        return {"user_id": user["$id"], "email": user["email"]}
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from appwrite.exception import AppwriteException
from utils.appwrite_client import get_account_service

bearer_scheme = HTTPBearer(auto_error=False)

AppwriteUser = dict  # type alias for the Appwrite account document


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AppwriteUser:
    """
    Extract the Bearer JWT from the Authorization header, verify it against
    Appwrite, and return the account document.
    Raises 401 if the token is missing or invalid.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwt = credentials.credentials
    try:
        account = get_account_service(jwt)
        user_obj = account.get()

        # The Appwrite Python SDK returns a typed model object, not a dict.
        # Convert to a plain dict with the $-prefixed keys used across the codebase.
        user: AppwriteUser = {
            "$id":              getattr(user_obj, "id", None) or getattr(user_obj, "$id", None),
            "email":            getattr(user_obj, "email", ""),
            "name":             getattr(user_obj, "name", ""),
            "labels":           getattr(user_obj, "labels", []) or [],
            "status":           getattr(user_obj, "status", True),
            "emailVerification": getattr(user_obj, "email_verification", False),
            "$createdAt":       getattr(user_obj, "created_at", None),
            "$updatedAt":       getattr(user_obj, "updated_at", None),
        }
        return user
    except AppwriteException as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc.message}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AppwriteUser:
    """
    Same as get_current_user but also checks that the account has the
    'admin' label set via Appwrite server-side Users API.
    """
    user = get_current_user(credentials)
    labels = user.get("labels", [])
    if "admin" not in labels:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user

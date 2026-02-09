from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from controllers.user_reportController import process_user_report, update_report_score
from models.user_reportModel import UserReport_Request
from utils.jwtutils import decode_access_token

router = APIRouter(prefix="/user_reports", tags=["user_reports"])
security = HTTPBearer()


@router.post("/submit", status_code=201)
async def submit_report(
    payload: UserReport_Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    print("Auth header received ", credentials)
    """
    Submit a user disease report with JWT authentication.
    Requires Bearer token in Authorization header.
    User ID is extracted from the token automatically.
    """
    try:
        token_payload = decode_access_token(credentials.credentials)
        user_id = token_payload.get("user_id")

        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token - user_id not found"
            )

        # Override the user_id from payload with the one from token
        payload.user_id = str(user_id)

        # Process the report
        result = await process_user_report(payload)
        return {
            "status": "success",
            "message": "Report submitted successfully",
            "data": result
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": str(ve)
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e)
            }
        )

@router.post("/vote", status_code=201)
async def voteReport(reportid: str, userid: str, location: str):
    await update_report_score(reportid, userid,  location)
    return {
        "status": "success",
        "message": "Vote recorded successfully"
    }

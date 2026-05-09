from fastapi import APIRouter, HTTPException, Depends

from controllers.user_reportController import (
    process_user_report,
    update_report_score,
    remove_report_vote,
    has_user_voted,
)
from models.user_reportModel import UserReport_Request
from utils.auth_deps import get_current_user, AppwriteUser

router = APIRouter(prefix="/user_reports", tags=["user_reports"])


@router.post("/submit", status_code=201)
async def submit_report(
    payload: UserReport_Request,
    user: AppwriteUser = Depends(get_current_user)
):
    """
    Submit a user disease report with Appwrite JWT authentication.
    Requires Bearer token in Authorization header.
    User ID is extracted from the Appwrite token automatically.
    """
    try:
        user_id = user.get("$id")

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
    try:
        result = await update_report_score(reportid, userid, location)
        return {
            "status": "success",
            "message": "Vote recorded successfully",
            "data": result,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unvote", status_code=200)
async def unvoteReport(reportid: str, userid: str, location: str):
    try:
        result = await remove_report_vote(reportid, userid, location)
        return {
            "status": "success",
            "message": "Vote removed successfully",
            "data": result,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/voted", status_code=200)
async def getVotedStatus(reportid: str, userid: str, location: str):
    try:
        result = await has_user_voted(reportid, userid, location)
        return {
            "status": "success",
            "message": "Vote status fetched",
            "data": result,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from pydantic import BaseModel

class UserReport_Update(BaseModel):
    description: str

@router.put("/update", status_code=200)
async def update_report(
    reportid: str,
    location: str,
    payload: UserReport_Update,
    user: AppwriteUser = Depends(get_current_user)
):
    try:
        from controllers.user_reportController import update_user_report
        result = await update_user_report(reportid, user.get("$id"), location, payload.description)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/delete", status_code=200)
async def delete_report(
    reportid: str,
    location: str,
    user: AppwriteUser = Depends(get_current_user)
):
    try:
        from controllers.user_reportController import delete_user_report
        result = await delete_user_report(reportid, user.get("$id"), location)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

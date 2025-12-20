from fastapi import APIRouter, HTTPException

from controllers.user_reportController import process_user_report
from models.user_reportModel import UserReport_Request

router = APIRouter(prefix="/user_reports", tags=["user_reports"])


@router.post("/submit", status_code=201)
async def submit_report(payload: UserReport_Request):

    try:
        result = await process_user_report(payload)
        return {
            "status": "success",
            "message": "Report submitted successfully",
            "data": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e)
            }
        )

from bson import ObjectId
from config.db import get_async_database
from utils.appwrite_client import get_users_service

async def officer_delete_user_report(report_id: str, district_name: str):
    db = get_async_database()
    try:
        report_object_id = ObjectId(report_id)
    except Exception:
        raise ValueError("Invalid report_id format")

    district_collection_name = f"reports_{district_name.replace(' ', '_').lower()}"
    district_collection = db[district_collection_name]

    report = await district_collection.find_one({"_id": report_object_id})
    if not report:
        raise ValueError("Report not found")

    await district_collection.delete_one({"_id": report_object_id})
    
    user_reports_collection = db["user_reports"]
    await user_reports_collection.delete_one({"report_id": report_object_id})

    return {"success": True, "message": "Report deleted successfully by officer"}

def ban_user(user_id: str):
    try:
        users_service = get_users_service()
        # The update_status method expects user_id and boolean status
        # True = active, False = blocked/disabled
        result = users_service.update_status(user_id, False)
        return {"success": True, "message": "User has been banned successfully"}
    except Exception as e:
        raise ValueError(f"Failed to ban user: {str(e)}")

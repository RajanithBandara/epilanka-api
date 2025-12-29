from typing import Optional, List

from pydantic import BaseModel, Field


#mongodb store these data

class ExtractedData(BaseModel):
    disease_name: Optional[str] = None
    disease_type: str = "unknown"
    cases_reported: Optional[int] = None
    severity: str = "unknown"
    symptoms: List[str] = []
    time_period: Optional[str] = None
    age_group: Optional[str] = None
    location_specifics: Optional[str] = None
    confidence: str = "low"


class UserReport_Request(BaseModel):
    user_id: str  # Changed to str to accept MongoDB ObjectId
    description: str
    latitude: float
    longitude: float
    extracted_data: Optional[ExtractedData] = None

class Districtwise_Report(BaseModel):
    report_id: int
    reported_week: int
    cases_count: int
    disease_type: str
    disease_name: str

class UserReport_Request(BaseModel):
    user_id: str  # MongoDB ObjectId as string
    description: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    extracted_data: Optional[ExtractedData] = None

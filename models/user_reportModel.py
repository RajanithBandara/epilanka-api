from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

#mongodb store these data

class UserReport(BaseModel):
    report_id: int
    user_id: int
    nearest_location: str
    description: str
    disease_name: Optional[str] = None
    disease_type: Optional[str] = None
    cases_reported: Optional[int] = None
    time_period: Optional[str] = None
    confidence: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Districtwise_Report(BaseModel):
    report_id: int
    reported_week: int
    cases_count: int
    disease_type: str
    disease_name: str

class UserReport_Request(BaseModel):
    user_id: int
    description: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)

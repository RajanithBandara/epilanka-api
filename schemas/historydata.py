from pydantic import BaseModel, conint
from typing import Optional

class AdminHistoricalDataCreate(BaseModel):
    week_number: conint(ge=1, le=53)
    year: conint(ge=1900)
    district_id: int
    disease_id: int
    case_count: conint(ge=0)


class AdminHistoricalDataUpdate(BaseModel):
    week_number: Optional[conint(ge=1, le=53)] = None
    year: Optional[conint(ge=1900)] = None
    district_id: Optional[int] = None
    disease_id: Optional[int] = None
    case_count: Optional[conint(ge=0)] = None
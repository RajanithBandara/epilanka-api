from pydantic import BaseModel, conint


class AdminHistoricalDataCreate(BaseModel):
    week_number: conint(ge=1, le=53)
    year: conint(ge=1900)
    district_id: int
    disease_id: int
    case_count: conint(ge=0)
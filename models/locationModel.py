from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr

class LocationModel(BaseModel):
    user_id: Optional[str] = None
    email: Optional[EmailStr] = None
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_bson(self) -> Dict[str, Any]:
        """
        Convert the model to a dict suitable for MongoDB insertion.
        """
        doc = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timestamp": self.timestamp,
        }
        if self.user_id:
            doc["user_id"] = self.user_id
        if self.email:
            doc["email"] = self.email
        return doc


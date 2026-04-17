"""
Notification Model for MongoDB
Handles global notifications that are sent to users with severity levels and metadata.
"""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from enum import Enum
from typing import Optional


class NotificationSeverity(str, Enum):
    """Severity levels for notifications"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    SUCCESS = "success"


class Notification(BaseModel):
    """Notification Pydantic model"""
    notification_id: str = Field(..., description="Unique notification ID")
    text: str = Field(..., description="Notification message text")
    severity: NotificationSeverity = Field(default=NotificationSeverity.INFO, description="Severity level")
    user_id: Optional[str] = Field(default=None, description="Target user ID (leave None for all users)")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    read: Optional[bool] = Field(default=False, description="Whether notification has been read")
    read_at: Optional[datetime] = Field(default=None, description="When notification was read")
    metadata: Optional[dict] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "notification_id": "notif_123456",
                "text": "New disease report received in Colombo district",
                "severity": "critical",
                "user_id": "user_abc123",
                "metadata": {"district": "Colombo", "disease": "Dengue"}
            }
        }


class NotificationCreate(BaseModel):
    """Schema for creating a new notification"""
    text: str = Field(..., min_length=1, max_length=500, description="Notification message")
    severity: NotificationSeverity = Field(default=NotificationSeverity.INFO)
    user_id: Optional[str] = Field(default=None, description="Recipient user ID")
    metadata: Optional[dict] = Field(default_factory=dict)


class NotificationUpdate(BaseModel):
    """Schema for updating a notification"""
    read: Optional[bool] = Field(default=None)
    text: Optional[str] = Field(default=None, max_length=500)
    severity: Optional[NotificationSeverity] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)


class NotificationResponse(BaseModel):
    """Response schema for notifications"""
    id: str = Field(None, alias="_id", description="MongoDB object ID")
    notification_id: str
    text: str
    severity: NotificationSeverity
    user_id: Optional[str]
    created_at: datetime
    read: bool
    read_at: Optional[datetime]
    metadata: dict

    model_config = ConfigDict(
        populate_by_name=True,  # Allow both 'id' and '_id' in input
        from_attributes=True    # Support ORM mode
    )

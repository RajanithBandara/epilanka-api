"""
Notification Model for MongoDB
Global broadcast notifications sent to all users with severity levels and metadata.
"""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from enum import Enum
from typing import Optional, Literal


class NotificationSeverity(str, Enum):
    """Severity levels for notifications"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    SUCCESS = "success"


class NotificationCategory(str, Enum):
    """Logical category / source of the notification"""
    DISEASE = "disease"
    REPORT = "report"
    SYSTEM = "system"
    ALERT = "alert"
    ANNOUNCEMENT = "announcement"


class NotificationCreate(BaseModel):
    """Schema for creating a new broadcast notification"""
    text: str = Field(..., min_length=1, max_length=600, description="Notification message")
    severity: NotificationSeverity = Field(default=NotificationSeverity.INFO)
    category: NotificationCategory = Field(default=NotificationCategory.SYSTEM)
    title: Optional[str] = Field(default=None, max_length=120, description="Short title / heading")
    metadata: Optional[dict] = Field(default_factory=dict, description="Extra contextual data")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "New Dengue Alert",
                "text": "Dengue cases have risen sharply in the Western Province. Please review the latest report.",
                "severity": "critical",
                "category": "disease",
                "metadata": {"district": "Colombo", "disease": "Dengue", "week": 21}
            }
        }
    )


class NotificationUpdate(BaseModel):
    """Schema for updating a notification (admin only)"""
    read: Optional[bool] = Field(default=None)
    text: Optional[str] = Field(default=None, max_length=600)
    title: Optional[str] = Field(default=None, max_length=120)
    severity: Optional[NotificationSeverity] = Field(default=None)
    category: Optional[NotificationCategory] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)


class NotificationResponse(BaseModel):
    """API response schema for a single notification"""
    id: str = Field(None, alias="_id", description="MongoDB ObjectID as string")
    notification_id: str
    title: Optional[str]
    text: str
    severity: NotificationSeverity
    category: NotificationCategory
    created_at: str  # ISO-8601 string — always serialised before returning
    read: bool
    read_at: Optional[str]
    metadata: dict

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
    )

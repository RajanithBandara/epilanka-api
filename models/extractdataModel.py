from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from pydantic import Base
from datetime import datetime


class UserReport(Base):
    __tablename__ = "user_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Extracted fields
    disease_name = Column(String, nullable=True)
    disease_type = Column(String, nullable=False)
    cases_reported = Column(Integer, nullable=True)
    severity = Column(String, nullable=False)
    symptoms = Column(JSON, nullable=True)
    time_period = Column(String, nullable=True)
    age_group = Column(String, nullable=True)
    location_specifics = Column(String, nullable=True)
    confidence = Column(String, nullable=False)

    status = Column(String, default="pending")  # pending, verified, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="reports")
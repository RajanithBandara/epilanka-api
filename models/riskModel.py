from sqlalchemy import Column, Integer, ForeignKey, String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from config.postgredb import Base

class RiskLevel(Base):
    __tablename__ = "risk_levels"

    risk_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    district_id = Column(Integer, ForeignKey("districts.district_id"), nullable=False)
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    risk_level = Column(String, nullable=False)
    risk_score = Column(Float, nullable=False)
    calculated_at = Column(DateTime, default=datetime.utcnow)

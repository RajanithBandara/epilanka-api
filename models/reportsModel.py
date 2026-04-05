from sqlalchemy import Column, Integer, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
from config.postgredb import Base

class Report(Base):
    __tablename__ = "reports"

    report_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    district_id = Column(Integer, ForeignKey("districts.district_id"), nullable=False)
    disease_id = Column(Integer, ForeignKey("diseases.disease_id"), nullable=False)
    case_count = Column(Integer, nullable=False)
    actual_count = Column(Integer, nullable=True)

from sqlalchemy import Column, Integer, String
from config.postgredb import Base

class ForecastPrediction(Base):
    __tablename__ = "forecast_predictions"

    id = Column(Integer, primary_key=True, index=True)

    district_id = Column(Integer, nullable=False, foreign_keys="districts.district_id")
    predicted_cases = Column(Integer, nullable=False)
    lower_ci = Column(Integer, nullable=False)
    upper_ci = Column(Integer, nullable=False)

    severity = Column(String, nullable=False)
    createdAt = Column(String, nullable=False)

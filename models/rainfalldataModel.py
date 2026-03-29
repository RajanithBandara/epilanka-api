from sqlalchemy import Column, Integer, String
from config.postgredb import Base

class RainfallData(Base):
    __tablename__ = "rainfall_data"
    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, nullable=False, foreign_key="districts.district_id")
    january = Column(Integer, nullable=False)
    february = Column(Integer, nullable=False)
    march = Column(Integer, nullable=False)
    april = Column(Integer, nullable=False)
    may = Column(Integer, nullable=False)
    june = Column(Integer, nullable=False)
    july = Column(Integer, nullable=False)
    august = Column(Integer, nullable=False)
    september = Column(Integer, nullable=False)
    october = Column(Integer, nullable=False)
    november = Column(Integer, nullable=False)
    december = Column(Integer, nullable=False)
    annual_rainfall = Column(Integer, nullable=False)
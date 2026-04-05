from sqlalchemy import Column, ForeignKey, Integer
from config.postgredb import Base

class PerDistrictPopulation(Base):
    __tablename__ = "perdistrictpopulation"

    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey("districts.district_id"), nullable=False)
    population = Column(Integer, nullable=False)

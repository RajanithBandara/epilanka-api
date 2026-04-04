from sqlalchemy import Column, Integer, String
from config.postgredb import Base

class PerDistrictPopulation(Base):
    __tablename__ = "perdistrictpopulation"

    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, nullable=False, foreign_key="districts.district_id")
    population = Column(Integer, nullable=False)
from sqlalchemy import Column, Integer, String, Float
from config.postgredb import Base

class District(Base):
    __tablename__ = "districts"

    district_id = Column(Integer, primary_key=True, index=True)
    district_name = Column(String, nullable=False)
    longitude = Column(Float, nullable=False)
    lattitude = Column(Float, nullable=False)
    province_name = Column(String, nullable=False)

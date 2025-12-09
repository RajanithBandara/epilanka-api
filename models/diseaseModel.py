from sqlalchemy import Column, Integer, String
from config.postgredb import Base

class Disease(Base):
    __tablename__ = "diseases"

    disease_id = Column(Integer, primary_key=True, index=True)
    disease_name = Column(String, nullable=False)
    description = Column(String, nullable=True)

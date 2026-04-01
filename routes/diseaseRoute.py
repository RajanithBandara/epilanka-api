from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from controllers.diseaseController import add_disease, list_diseases, update_disease, delete_disease
from config.postgredb import get_async_db

router = APIRouter(prefix="/diseases", tags=["diseases"])

@router.post("/add", status_code=201)
async def create_disease(disease_name: str, description: str = None, db_session: AsyncSession = Depends(get_async_db)):
    new_disease = await add_disease(db_session, disease_name, description)
    return {"message": "Disease added successfully", "disease": new_disease}

@router.get("/list", status_code=200)
async def get_diseases(db_session: AsyncSession = Depends(get_async_db)):
    diseases = await list_diseases(db_session)
    return {"diseases": diseases}

@router.post("/update/{disease_id}", status_code=200)
async def modify_disease(disease_id: int, disease_name: str = None, description: str = None, db_session: AsyncSession = Depends(get_async_db)):
    updated_disease = await update_disease(db_session, disease_id, disease_name, description)
    if updated_disease:
        return {"message": "Disease updated successfully", "disease": updated_disease}
    return {"message": "Disease not found"}

@router.delete("/delete/{disease_id}", status_code=200)
async def remove_disease(disease_id: int, db_session: AsyncSession = Depends(get_async_db)):
    success = await delete_disease(db_session, disease_id)
    if success:
        return {"message": "Disease deleted successfully"}
    return {"message": "Disease not found"}

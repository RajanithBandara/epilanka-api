from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.diseaseModel import Disease

async def add_disease(db_session: AsyncSession, disease_name: str, description: str = None):
    new_disease = Disease(disease_name=disease_name, description=description)
    db_session.add(new_disease)
    await db_session.commit()
    await db_session.refresh(new_disease)
    return new_disease

async def list_diseases(db_session: AsyncSession):
    result = await db_session.execute(select(Disease))
    diseases = result.scalars().all()
    return diseases

async def delete_disease(db_session: AsyncSession, disease_id: int):
    result = await db_session.execute(select(Disease).filter(Disease.disease_id == disease_id))
    disease = result.scalar_one_or_none()
    if disease:
        await db_session.delete(disease)
        await db_session.commit()
        return True
    return False

async def update_disease(db_session: AsyncSession, disease_id: int, disease_name: str = None, description: str = None):
    result = await db_session.execute(select(Disease).filter(Disease.disease_id == disease_id))
    disease = result.scalar_one_or_none()
    if disease:
        if disease_name:
            disease.disease_name = disease_name
        if description:
            disease.description = description
        await db_session.commit()
        await db_session.refresh(disease)
        return disease
    return None

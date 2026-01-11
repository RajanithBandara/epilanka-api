import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import psycopg2

# Load .env file if present
load_dotenv()

DB_HOST = os.getenv("POSTGRE_HOST")
DB_PORT = os.getenv("POSTGRE_PORT")
DB_NAME = os.getenv("POSTGRE_DBNAME")
DB_USER = os.getenv("POSTGRE_USER")
DB_PASSWORD = os.getenv("POSTGRE_PASSWORD")

def get_postgres_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

if not all([DB_NAME, DB_USER, DB_PASSWORD]):
    raise RuntimeError("DB_NAME, DB_USER and DB_PASSWORD environment variables must be set")

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

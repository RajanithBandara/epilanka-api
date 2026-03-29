import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# Load .env file if present
load_dotenv()

DB_HOST = os.getenv("POSTGRE_HOST")
DB_PORT = os.getenv("POSTGRE_PORT")
DB_NAME = os.getenv("POSTGRE_DBNAME")
DB_USER = os.getenv("POSTGRE_USER")
DB_PASSWORD = os.getenv("POSTGRE_PASSWORD")

if not all([DB_NAME, DB_USER, DB_PASSWORD]):
    raise RuntimeError("DB_NAME, DB_USER and DB_PASSWORD environment variables must be set")

# ── Async engine (used by existing async controllers) ──────────────────────
DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Sync engine (used by synchronous SQLAlchemy ORM routes) ────────────────
SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


def get_postgres_connection():
    """FastAPI Depends generator — yields a SQLAlchemy sync Session."""
    db: Session = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()

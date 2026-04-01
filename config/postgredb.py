import os
from typing import AsyncGenerator
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
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

# Async engine with proper connection pooling
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,  # Number of connections to maintain in the pool
    max_overflow=10,  # Additional connections to create beyond pool_size
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,  # Recycle connections after 1 hour to avoid stale connections
    connect_args={
        "timeout": 10,
        "server_settings": {"application_name": "epilanka_api"}
    }
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ── Sync engine (used by synchronous SQLAlchemy ORM routes) ────────────────
SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    poolclass=pool.QueuePool,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends generator for async sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_postgres_connection():
    """FastAPI Depends generator — yields a SQLAlchemy sync Session."""
    db: Session = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


async def close_postgres_connection() -> None:
    """Close PostgreSQL connections."""
    await engine.dispose()
    print("✅ PostgreSQL async engine disposed")



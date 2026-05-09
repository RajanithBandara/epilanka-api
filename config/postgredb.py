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

_TEST_MODE = os.getenv("TESTING") == "1" or bool(os.getenv("PYTEST_CURRENT_TEST"))

if _TEST_MODE:
    DB_HOST = DB_HOST or "127.0.0.1"
    DB_PORT = DB_PORT or "5432"
    DB_NAME = DB_NAME or "epilanka_test"
    DB_USER = DB_USER or "test_user"
    DB_PASSWORD = DB_PASSWORD or "test_password"


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default

if not _TEST_MODE and not all([DB_NAME, DB_USER, DB_PASSWORD]):
    raise RuntimeError("DB_NAME, DB_USER and DB_PASSWORD environment variables must be set")

# ── Async engine (used by existing async controllers) ──────────────────────
DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

PG_POOL_SIZE = _env_int("POSTGRE_POOL_SIZE", 5)
PG_MAX_OVERFLOW = _env_int("POSTGRE_MAX_OVERFLOW", 2)
PG_POOL_TIMEOUT = _env_int("POSTGRE_POOL_TIMEOUT", 15)
PG_POOL_RECYCLE = _env_int("POSTGRE_POOL_RECYCLE", 1800)

# Async engine with proper connection pooling
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=PG_POOL_SIZE,
    max_overflow=PG_MAX_OVERFLOW,
    pool_timeout=PG_POOL_TIMEOUT,
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=PG_POOL_RECYCLE,
    pool_use_lifo=True,
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
    pool_size=PG_POOL_SIZE,
    max_overflow=PG_MAX_OVERFLOW,
    pool_timeout=PG_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=PG_POOL_RECYCLE,
    pool_use_lifo=True,
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
        # Ensure any dangling transaction is closed before returning to pool.
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


async def close_postgres_connection() -> None:
    """Close PostgreSQL connections."""
    await engine.dispose()
    sync_engine.dispose()
    print("✅ PostgreSQL async/sync engines disposed")



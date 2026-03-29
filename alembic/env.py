from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from config.postgredb import Base

from models.riskModel import RiskLevel
from models.diseaseModel import Disease
from models.reportsModel import Report
from models.districtModel import District
from models.historydataModel import HistoryData

from dotenv import load_dotenv
import os

load_dotenv()

config = context.config

config.set_main_option(
    "sqlalchemy.url",
    f"postgresql://{os.getenv('POSTGRE_USER')}:{os.getenv('POSTGRE_PASSWORD')}"
    f"@{os.getenv('POSTGRE_HOST')}:{os.getenv('POSTGRE_PORT')}/{os.getenv('POSTGRE_DBNAME')}"
)

# Must be Base.metadata, NOT None
target_metadata = Base.metadata

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database.base import Base

logger = logging.getLogger(__name__)

DATABASE_URL = settings.DATABASE_URL
_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns() -> None:
    """Tiny forward-only migration: add columns that exist on the models but not in the DB.

    `create_all` only creates missing tables, so databases created by older versions of
    this project would otherwise miss newly added (nullable) columns.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
            default = getattr(column.server_default, "arg", None)
            if isinstance(default, str):
                ddl += f" DEFAULT '{default}'"
            logger.info("Migrating: %s", ddl)
            with engine.begin() as conn:
                conn.execute(text(ddl))


def init_db() -> None:
    from app.database import models  # noqa: F401  (registers the models)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - depends on infrastructure
        logger.exception("Database health check failed")
        return False

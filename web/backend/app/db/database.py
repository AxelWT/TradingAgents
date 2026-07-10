import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import get_settings

logger = logging.getLogger(__name__)

engine = None
SessionLocal = None


def init_db():
    global engine, SessionLocal
    settings = get_settings()
    connect_args = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    from app.db.models import Base

    Base.metadata.create_all(bind=engine)
    migrate_schema()


def migrate_schema():
    """Lightweight migration: add missing columns to existing databases to avoid data loss."""
    if engine is None:
        return
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    new_columns = {
        "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "is_whitelisted": "BOOLEAN NOT NULL DEFAULT 0",
    }
    with engine.begin() as conn:
        for col_name, col_def in new_columns.items():
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                logger.info("migrate_schema: added column users.%s", col_name)

"""Konfigurasi koneksi database SQLAlchemy dan dependency injection session."""

import os
import sqlite3
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sevima.db")


def attach_sqlite_fk_pragma(target_engine: Engine) -> None:
    """Aktifkan PRAGMA foreign_keys=ON dan busy_timeout pada koneksi SQLite."""

    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
attach_sqlite_fk_pragma(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Menyediakan session database per request melalui dependency injection FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

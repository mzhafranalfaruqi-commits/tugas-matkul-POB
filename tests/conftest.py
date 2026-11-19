"""Fixtures pytest untuk isolasi database in-memory dan TestClient FastAPI."""

from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import attach_sqlite_fk_pragma, get_db
from app.main import app
from app.models.pmb import Base, JalurMasuk, ProgramStudi


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Membuat database SQLite in-memory bersih beserta data referensi untuk tiap tes."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    attach_sqlite_fk_pragma(test_engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                ProgramStudi(
                    kode="001",
                    nama="Teknik Informatika",
                    fakultas="Fakultas Teknik",
                ),
                ProgramStudi(
                    kode="002",
                    nama="Sistem Informasi",
                    fakultas="Fakultas Ilmu Komputer",
                ),
                ProgramStudi(
                    kode="003",
                    nama="Teknik Elektro",
                    fakultas="Fakultas Teknik",
                ),
                JalurMasuk(nama="SNBP"),
                JalurMasuk(nama="SNBT"),
                JalurMasuk(nama="Mandiri"),
            ]
        )
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Menyediakan TestClient FastAPI dengan override dependency get_db ke db_session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_payload() -> dict[str, object]:
    """Menyediakan data pendaftaran dummy yang valid sesuai AI-First Charter."""
    return {
        "nama_lengkap": "Budi Santoso",
        "email": "budi1@example.com",
        "phone": "081234567890",
        "tanggal_lahir": "2006-05-14",
        "alamat": "Jl. Merdeka No. 10, Bandung",
        "program_studi_id": 1,
        "jalur_masuk_id": 1,
    }

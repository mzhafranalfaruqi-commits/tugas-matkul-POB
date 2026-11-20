"""Unit dan integration tests untuk Modul PMB SEVIMA-Mini."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import attach_sqlite_fk_pragma, get_db
from app.main import app
from app.models.pmb import (
    Base,
    CalonMahasiswa,
    JalurMasuk,
    NimCounter,
    ProgramStudi,
    StatusPMB,
)
from app.services.nim_generator import format_nim, generate_nim
from app.services.pmb_service import PMBService
from seed import seed_data


def test_register_success(client: TestClient, sample_payload: dict[str, object]) -> None:
    """Data registrasi valid harus mengembalikan 201 dan status awal pending."""
    response = client.post("/api/pmb/register", json=sample_payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] >= 1
    assert body["nama_lengkap"] == "Budi Santoso"
    assert body["email"] == "budi1@example.com"
    assert body["status"] == "pending"
    assert "alamat" not in body
    assert "tanggal_lahir" not in body


def test_register_duplicate_email(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Registrasi dengan email yang sama (termasuk beda huruf kapital) harus ditolak 409."""
    first = client.post("/api/pmb/register", json=sample_payload)
    assert first.status_code == 201

    duplicate_payload = dict(sample_payload)
    duplicate_payload["nama_lengkap"] = "Budi Duplikat"
    duplicate_payload["email"] = "BUDI1@Example.COM"
    second = client.post("/api/pmb/register", json=duplicate_payload)
    assert second.status_code == 409
    assert "sudah terdaftar" in second.json()["detail"].lower()


def test_register_duplicate_email_integrity_error_fallback(
    client: TestClient,
    db_session: Session,
    sample_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jika IntegrityError terjadi akibat race condition saat commit, tetap kembalikan 409."""
    original_commit = db_session.commit
    rollback_called = {"flag": False}
    original_rollback = db_session.rollback

    def failing_commit() -> None:
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

    def tracked_rollback() -> None:
        rollback_called["flag"] = True
        original_rollback()

    monkeypatch.setattr(db_session, "commit", failing_commit)
    monkeypatch.setattr(db_session, "rollback", tracked_rollback)

    response = client.post("/api/pmb/register", json=sample_payload)
    monkeypatch.setattr(db_session, "commit", original_commit)

    assert response.status_code == 409
    assert rollback_called["flag"] is True


@pytest.mark.parametrize(
    "phone",
    [
        "02155551234",
        "08012345678",
        "12345",
        "0812-3456-789",
        "abc0812345678",
    ],
)
def test_invalid_phone_format(
    client: TestClient, sample_payload: dict[str, object], phone: str
) -> None:
    """Format nomor HP non-seluler Indonesia atau mengandung karakter non-digit harus ditolak 400."""
    payload = dict(sample_payload)
    payload["phone"] = phone
    response = client.post("/api/pmb/register", json=payload)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "phone",
    [
        "081234567890",
        "6281234567890",
        "+6281234567890",
    ],
)
def test_valid_phone_formats(
    client: TestClient, sample_payload: dict[str, object], phone: str
) -> None:
    """Format HP Indonesia (08, 628, +628) harus diterima dengan status 201."""
    payload = dict(sample_payload)
    payload["phone"] = phone
    payload["email"] = f"user_{phone.replace('+', '')}@example.com"
    response = client.post("/api/pmb/register", json=payload)
    assert response.status_code == 201


@pytest.mark.parametrize(
    "email",
    [
        "bukanemail",
        "budi@",
        "@example.com",
        "budi@example",
    ],
)
def test_invalid_email_format(
    client: TestClient, sample_payload: dict[str, object], email: str
) -> None:
    """Format email invalid harus ditolak dengan status code 400."""
    payload = dict(sample_payload)
    payload["email"] = email
    response = client.post("/api/pmb/register", json=payload)
    assert response.status_code == 400


def test_invalid_tanggal_lahir_future_and_blank_fields(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Tanggal lahir di masa depan dan teks hanya spasi harus ditolak 400."""
    future_payload = dict(sample_payload)
    future_payload["tanggal_lahir"] = (date.today() + timedelta(days=1)).isoformat()
    res_future = client.post("/api/pmb/register", json=future_payload)
    assert res_future.status_code == 400

    blank_name_payload = dict(sample_payload)
    blank_name_payload["nama_lengkap"] = "     "
    res_blank = client.post("/api/pmb/register", json=blank_name_payload)
    assert res_blank.status_code == 400


def test_register_invalid_prodi_dan_jalur(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Referensi program_studi_id atau jalur_masuk_id yang tidak ada harus ditolak 400."""
    bad_prodi = dict(sample_payload)
    bad_prodi["program_studi_id"] = 999
    res_prodi = client.post("/api/pmb/register", json=bad_prodi)
    assert res_prodi.status_code == 400

    bad_jalur = dict(sample_payload)
    bad_jalur["jalur_masuk_id"] = 999
    res_jalur = client.post("/api/pmb/register", json=bad_jalur)
    assert res_jalur.status_code == 400


def test_get_status_success_and_not_found(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Cek status pendaftar yang ada harus 200, sedangkan ID tidak ada harus 404."""
    reg = client.post("/api/pmb/register", json=sample_payload)
    pendaftar_id = reg.json()["id"]

    res_ok = client.get(f"/api/pmb/status/{pendaftar_id}")
    assert res_ok.status_code == 200
    body = res_ok.json()
    assert body["id"] == pendaftar_id
    assert body["program_studi_kode"] == "001"
    assert body["program_studi_nama"] == "Teknik Informatika"
    assert body["jalur_masuk"] == "SNBP"
    assert body["status"] == "pending"
    assert body["nim"] is None

    res_missing = client.get("/api/pmb/status/99999")
    assert res_missing.status_code == 404


def test_format_nim_pure_unit() -> None:
    """Pure unit test format_nim tanpa DB: zero-padding, batas maksimum, dan validasi input."""
    assert format_nim(2025, "001", 1) == "2025001-0001"
    assert format_nim(2025, "001", 7) == "2025001-0007"
    assert format_nim(2025, "003", 9999) == "2025003-9999"

    with pytest.raises(ValueError, match="Nomor urut habis"):
        format_nim(2025, "001", 10000)
    with pytest.raises(ValueError):
        format_nim(2025, "001", 0)
    with pytest.raises(ValueError):
        format_nim(2025, "001", True)
    with pytest.raises(ValueError):
        format_nim(1999, "001", 1)
    with pytest.raises(ValueError):
        format_nim(True, "001", 1)
    with pytest.raises(ValueError):
        format_nim(2025, "01", 1)
    with pytest.raises(ValueError):
        format_nim(2025, "ABC", 1)


def test_approve_generate_nim(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Approve harus menghasilkan NIM sesuai format [Tahun:4][Kode:3]-[Seq:4] secara berurutan."""
    payload_1 = dict(sample_payload)
    payload_1["email"] = "mhs1@example.com"
    id_1 = client.post("/api/pmb/register", json=payload_1).json()["id"]

    payload_2 = dict(sample_payload)
    payload_2["email"] = "mhs2@example.com"
    id_2 = client.post("/api/pmb/register", json=payload_2).json()["id"]

    payload_si = dict(sample_payload)
    payload_si["email"] = "mhs3@example.com"
    payload_si["program_studi_id"] = 2  # Kode 002 Sistem Informasi
    id_si = client.post("/api/pmb/register", json=payload_si).json()["id"]

    app_1 = client.put(f"/api/pmb/approve/{id_1}?tahun=2025")
    assert app_1.status_code == 200
    nim_1 = app_1.json()["nim"]
    assert re.fullmatch(r"^\d{4}001-\d{4}$", nim_1) is not None
    assert nim_1 == "2025001-0001"
    assert app_1.json()["status"] == "approved"
    assert app_1.json()["already_approved"] is False

    app_2 = client.put(f"/api/pmb/approve/{id_2}?tahun=2025")
    assert app_2.status_code == 200
    nim_2 = app_2.json()["nim"]
    assert re.fullmatch(r"^\d{4}001-\d{4}$", nim_2) is not None
    assert int(nim_2.split("-")[-1]) == int(nim_1.split("-")[-1]) + 1
    assert nim_2 == "2025001-0002"

    app_si = client.put(f"/api/pmb/approve/{id_si}?tahun=2025")
    assert app_si.status_code == 200
    assert app_si.json()["nim"] == "2025002-0001"

    status_1 = client.get(f"/api/pmb/status/{id_1}").json()
    assert status_1["status"] == "approved"
    assert status_1["nim"] == "2025001-0001"
    assert status_1["approved_at"] is not None


def test_approve_idempotent(
    client: TestClient, db_session: Session, sample_payload: dict[str, object]
) -> None:
    """Approve 2x pada pendaftar yang sama harus idempotent dan tidak melompatkan counter."""
    p1 = dict(sample_payload)
    p1["email"] = "idem1@example.com"
    id_1 = client.post("/api/pmb/register", json=p1).json()["id"]

    p2 = dict(sample_payload)
    p2["email"] = "idem2@example.com"
    id_2 = client.post("/api/pmb/register", json=p2).json()["id"]

    first = client.put(f"/api/pmb/approve/{id_1}?tahun=2025")
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["nim"] == "2025001-0001"
    assert first_data["already_approved"] is False

    second = client.put(f"/api/pmb/approve/{id_1}?tahun=2025")
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["nim"] == first_data["nim"]
    assert second_data["approved_at"] == first_data["approved_at"]
    assert second_data["already_approved"] is True

    next_cand = client.put(f"/api/pmb/approve/{id_2}?tahun=2025")
    assert next_cand.status_code == 200
    assert next_cand.json()["nim"] == "2025001-0002"

    counter = db_session.get(NimCounter, (2025, "001"))
    assert counter is not None
    assert counter.last_number == 2


def test_approve_invalid_data(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Approve pada ID tidak ditemukan harus 404, dan pendaftar rejected harus 409 Conflict."""
    res_missing = client.put("/api/pmb/approve/99999?tahun=2025")
    assert res_missing.status_code == 404

    reg = client.post("/api/pmb/register", json=sample_payload)
    pendaftar_id = reg.json()["id"]
    rej = client.put(f"/api/pmb/reject/{pendaftar_id}")
    assert rej.status_code == 200

    res_rejected = client.put(f"/api/pmb/approve/{pendaftar_id}?tahun=2025")
    assert res_rejected.status_code == 409
    assert "bukan pending" in res_rejected.json()["detail"].lower()


def test_approve_invalid_kode_prodi_400(
    client: TestClient, db_session: Session, sample_payload: dict[str, object]
) -> None:
    """Jika data prodi pendaftar tidak memiliki kode 3 digit angka, approve mengembalikan 400."""
    bad_prodi = ProgramStudi(kode="01", nama="Prodi Kode Pendek", fakultas="Fakultas Teknik")
    db_session.add(bad_prodi)
    db_session.commit()
    db_session.refresh(bad_prodi)

    payload = dict(sample_payload)
    payload["email"] = "badprodi@example.com"
    payload["program_studi_id"] = bad_prodi.id
    reg = client.post("/api/pmb/register", json=payload)
    assert reg.status_code == 201
    pendaftar_id = reg.json()["id"]

    res = client.put(f"/api/pmb/approve/{pendaftar_id}?tahun=2025")
    assert res.status_code == 400
    assert "3 digit" in res.json()["detail"].lower()

    res_bad_tahun = client.put(f"/api/pmb/approve/{pendaftar_id}?tahun=1999")
    assert res_bad_tahun.status_code == 400


def test_reject_pendaftar(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    """Endpoint reject harus mengubah status, idempotent, 404 jika hilang, dan 409 jika approved."""
    assert client.put("/api/pmb/reject/99999").status_code == 404

    p1 = dict(sample_payload)
    p1["email"] = "rej1@example.com"
    id_1 = client.post("/api/pmb/register", json=p1).json()["id"]

    r1 = client.put(f"/api/pmb/reject/{id_1}")
    assert r1.status_code == 200
    assert r1.json()["status"] == "rejected"

    r1_again = client.put(f"/api/pmb/reject/{id_1}")
    assert r1_again.status_code == 200
    assert r1_again.json()["status"] == "rejected"

    p2 = dict(sample_payload)
    p2["email"] = "rej2@example.com"
    id_2 = client.post("/api/pmb/register", json=p2).json()["id"]
    assert client.put(f"/api/pmb/approve/{id_2}?tahun=2025").status_code == 200

    res_conflict = client.put(f"/api/pmb/reject/{id_2}")
    assert res_conflict.status_code == 409


def test_stats_endpoint(client: TestClient, sample_payload: dict[str, object]) -> None:
    """Endpoint /stats harus mengembalikan statistik akurat saat kosong maupun terisi."""
    empty_stats = client.get("/api/pmb/stats")
    assert empty_stats.status_code == 200
    assert empty_stats.json()["total_pendaftar"] == 0
    assert empty_stats.json()["per_status"] == {
        "pending": 0,
        "approved": 0,
        "rejected": 0,
    }

    p1 = dict(sample_payload)
    p1["email"] = "stat1@example.com"
    id_1 = client.post("/api/pmb/register", json=p1).json()["id"]

    p2 = dict(sample_payload)
    p2["email"] = "stat2@example.com"
    p2["program_studi_id"] = 2
    p2["jalur_masuk_id"] = 2
    id_2 = client.post("/api/pmb/register", json=p2).json()["id"]

    p3 = dict(sample_payload)
    p3["email"] = "stat3@example.com"
    p3["jalur_masuk_id"] = 3
    client.post("/api/pmb/register", json=p3)

    client.put(f"/api/pmb/approve/{id_1}?tahun=2025")
    client.put(f"/api/pmb/reject/{id_2}")

    stats = client.get("/api/pmb/stats").json()
    assert stats["total_pendaftar"] == 3
    assert stats["per_status"] == {"pending": 1, "approved": 1, "rejected": 1}
    prodi_001 = next(p for p in stats["per_program_studi"] if p["kode"] == "001")
    assert prodi_001["total"] == 2
    assert prodi_001["approved"] == 1
    assert prodi_001["pending"] == 1
    jalur_map = {j["nama"]: j["total"] for j in stats["per_jalur_masuk"]}
    assert jalur_map == {"SNBP": 1, "SNBT": 1, "Mandiri": 1}


def test_nim_generator_unit_dan_validasi(db_session: Session) -> None:
    """Uji langsung fungsi generate_nim berbasis nim_counter dan validasi inputnya."""
    assert generate_nim(2025, "001", db_session) == "2025001-0001"
    assert generate_nim(2025, "001", db_session) == "2025001-0002"
    assert generate_nim(2025, "003", db_session) == "2025003-0001"
    db_session.commit()

    with pytest.raises(ValueError):
        generate_nim(1999, "001", db_session)
    with pytest.raises(ValueError):
        generate_nim(True, "001", db_session)
    with pytest.raises(ValueError):
        generate_nim(2025, "01", db_session)
    with pytest.raises(ValueError):
        generate_nim(2025, 1, db_session)  # type: ignore[arg-type]


def test_generate_nim_overflow_dan_atomicity(
    client: TestClient,
    db_session: Session,
    sample_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uji batas kapasitas nomor urut 9999 dan rollback atomik bila commit approve gagal."""
    db_session.add(NimCounter(tahun=2026, kode_prodi="001", last_number=9999))
    db_session.commit()

    with pytest.raises(ValueError, match="Nomor urut habis"):
        generate_nim(2026, "001", db_session)
    db_session.rollback()

    payload = dict(sample_payload)
    payload["email"] = "atomic@example.com"
    pendaftar_id = client.post("/api/pmb/register", json=payload).json()["id"]

    original_commit = db_session.commit

    def failing_commit() -> None:
        raise IntegrityError("UPDATE", {}, Exception("simulated commit failure"))

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(IntegrityError):
        PMBService.approve(db_session, pendaftar_id, tahun=2027)
    monkeypatch.setattr(db_session, "commit", original_commit)

    calon = db_session.get(CalonMahasiswa, pendaftar_id)
    assert calon is not None
    assert calon.status == StatusPMB.pending
    assert calon.nim is None
    assert calon.approved_at is None
    assert db_session.get(NimCounter, (2027, "001")) is None


def test_nim_generator_thread_safe(tmp_path: Path) -> None:
    """Eksekusi approve paralel (DB lock + BEGIN IMMEDIATE + retry) tanpa threading.Lock Python."""
    db_file = tmp_path / "concurrent_pmb.db"
    file_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    attach_sqlite_fk_pragma(file_engine)
    LocalSession = sessionmaker(autocommit=False, autoflush=False, bind=file_engine)
    Base.metadata.create_all(bind=file_engine)

    try:
        with LocalSession() as db:
            seed_data(db)
            candidate_ids: list[int] = []
            for idx in range(1, 6):
                calon = CalonMahasiswa(
                    nama_lengkap=f"Calon Paralel {idx}",
                    email=f"paralel{idx}@example.com",
                    phone="081234567890",
                    tanggal_lahir=date(2006, 1, 10),
                    alamat="Jl. Kampus Merdeka No. 1",
                    program_studi_id=1,
                    jalur_masuk_id=1,
                )
                db.add(calon)
                db.flush()
                candidate_ids.append(calon.id)

            same_calon = CalonMahasiswa(
                nama_lengkap="Calon Race Idempotent",
                email="race.idem@example.com",
                phone="081234567890",
                tanggal_lahir=date(2006, 2, 15),
                alamat="Jl. Kampus Merdeka No. 2",
                program_studi_id=2,
                jalur_masuk_id=1,
            )
            db.add(same_calon)
            db.flush()
            same_id = same_calon.id
            db.commit()

        def worker(cid: int) -> str:
            with LocalSession() as session:
                approved, _ = PMBService.approve(session, cid, tahun=2025)
                assert approved.nim is not None
                return approved.nim

        with ThreadPoolExecutor(max_workers=5) as executor:
            nims = list(executor.map(worker, candidate_ids))

        assert sorted(nims) == [
            "2025001-0001",
            "2025001-0002",
            "2025001-0003",
            "2025001-0004",
            "2025001-0005",
        ]

        def worker_same(_: int) -> tuple[str, bool]:
            with LocalSession() as session:
                approved, already = PMBService.approve(session, same_id, tahun=2025)
                assert approved.nim is not None
                return approved.nim, already

        with ThreadPoolExecutor(max_workers=2) as executor:
            same_results = list(executor.map(worker_same, [1, 2]))

        assert [r[0] for r in same_results] == ["2025002-0001", "2025002-0001"]
        assert sorted(r[1] for r in same_results) == [False, True]

        with LocalSession() as verify_db:
            counter_001 = verify_db.get(NimCounter, (2025, "001"))
            counter_002 = verify_db.get(NimCounter, (2025, "002"))
            assert counter_001 is not None and counter_001.last_number == 5
            assert counter_002 is not None and counter_002.last_number == 1
    finally:
        file_engine.dispose()


def test_database_constraints_directly(db_session: Session) -> None:
    """Constraint DB (FK, CHECK status, CHECK phone, CHECK email, UNIQUE) harus aktif di SQLite."""
    # 1. Foreign key invalid ditolak
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO calon_mahasiswa
                (nama_lengkap, email, phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk_id, status)
                VALUES ('FK Invalid', 'fk1@example.com', '081234567890', '2006-01-01', 'Alamat Lengkap', 999, 1, 'pending')
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    # 2. Status typo ("aproved") ditolak oleh CHECK constraint enum
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO calon_mahasiswa
                (nama_lengkap, email, phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk_id, status)
                VALUES ('Typo Status', 'typo@example.com', '081234567890', '2006-01-01', 'Alamat Lengkap', 1, 1, 'aproved')
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    # 3. Panjang nomor HP invalid ditolak CHECK constraint
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO calon_mahasiswa
                (nama_lengkap, email, phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk_id, status)
                VALUES ('HP Pendek', 'hp@example.com', '0812', '2006-01-01', 'Alamat Lengkap', 1, 1, 'pending')
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    # 4. Email tanpa domain valid ditolak CHECK constraint
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO calon_mahasiswa
                (nama_lengkap, email, phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk_id, status)
                VALUES ('Email Salah', 'bukanemail', '081234567890', '2006-01-01', 'Alamat Lengkap', 1, 1, 'pending')
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    # 5. Seed idempotent tidak menambah baris ganda
    seed_data(db_session)
    assert db_session.query(ProgramStudi).count() == 3
    assert db_session.query(JalurMasuk).count() == 3


def test_swagger_docs_root_and_get_db(client: TestClient) -> None:
    """Endpoint root, Swagger /docs, ReDoc /redoc, /openapi.json, serta get_db harus berfungsi."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["docs"] == "/docs"

    res_docs = client.get("/docs")
    assert res_docs.status_code == 200

    res_redoc = client.get("/redoc")
    assert res_redoc.status_code == 200

    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 200
    paths = res_openapi.json()["paths"]
    assert "/api/pmb/register" in paths
    assert "/api/pmb/status/{pendaftar_id}" in paths
    assert "/api/pmb/approve/{pendaftar_id}" in paths
    assert "/api/pmb/reject/{pendaftar_id}" in paths
    assert "/api/pmb/stats" in paths

    approve_responses = paths["/api/pmb/approve/{pendaftar_id}"]["put"]["responses"]
    assert "200" in approve_responses
    assert "400" in approve_responses
    assert "404" in approve_responses
    assert "409" in approve_responses

    reject_responses = paths["/api/pmb/reject/{pendaftar_id}"]["put"]["responses"]
    assert "200" in reject_responses
    assert "404" in reject_responses
    assert "409" in reject_responses

    gen = get_db()
    session = next(gen)
    assert session is not None
    gen.close()

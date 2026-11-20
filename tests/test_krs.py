"""Unit, integration, dan concurrency tests untuk Modul KRS SEVIMA-Mini (Minggu 5)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import attach_sqlite_fk_pragma
from app.models import (
    Base,
    CalonMahasiswa,
    JalurMasuk,
    KRS,
    KRSDetail,
    KRSStatus,
    MataKuliah,
    ProgramStudi,
    SkalaNilai,
    StatusPMB,
    prerequisite,
)
from app.services.exceptions import (
    KRSStatusTidakValid,
    KRSTidakDitemukan,
    KRSValidasiGagal,
)
from app.services.krs_manager import KRSManager
from app.services.krs_queries import prasyarat_belum_lulus
from app.validators import (
    ConflictValidator,
    DuplicateValidator,
    KRSContext,
    PrerequisiteValidator,
    SKSValidator,
    ValidationResult,
    Validator,
    bentrok,
    build_chain,
)
from seed import seed_data, seed_krs_data


def _setup_krs_sample_db(db: Session) -> str:
    """Mengisi data skala nilai, mata kuliah, prasyarat, dan riwayat mahasiswa uji."""
    seed_krs_data(db)
    return "2025001-0001"


def test_krs_schema_relationship_and_constraints(db_session: Session) -> None:
    """Uji arah self-referencing M2M prerequisite serta CHECK, UNIQUE, dan FK constraints."""
    _setup_krs_sample_db(db_session)

    algoritma = db_session.get(MataKuliah, "IF101")
    struktur_data = db_session.get(MataKuliah, "IF102")
    assert algoritma is not None and struktur_data is not None
    assert [m.kode_mk for m in struktur_data.prasyarat] == ["IF101"]
    assert algoritma.prasyarat == []

    # CHECK sks 1..4
    with pytest.raises(IntegrityError):
        db_session.add(
            MataKuliah(
                kode_mk="BADSKS",
                nama="MK SKS 5",
                sks=5,
                hari=1,
                jam_mulai=time(8, 0),
                jam_selesai=time(10, 0),
            )
        )
        db_session.commit()
    db_session.rollback()

    # CHECK hari 1..6
    with pytest.raises(IntegrityError):
        db_session.add(
            MataKuliah(
                kode_mk="BADHARI",
                nama="MK Minggu",
                sks=2,
                hari=7,
                jam_mulai=time(8, 0),
                jam_selesai=time(10, 0),
            )
        )
        db_session.commit()
    db_session.rollback()

    # CHECK jam_mulai < jam_selesai
    with pytest.raises(IntegrityError):
        db_session.add(
            MataKuliah(
                kode_mk="BADJAM",
                nama="MK Jam Terbalik",
                sks=2,
                hari=1,
                jam_mulai=time(11, 0),
                jam_selesai=time(9, 0),
            )
        )
        db_session.commit()
    db_session.rollback()

    # CHECK prerequisite tidak boleh merujuk ke dirinya sendiri
    with pytest.raises(IntegrityError):
        db_session.execute(
            prerequisite.insert().values(kode_mk="IF101", kode_prasyarat="IF101")
        )
        db_session.commit()
    db_session.rollback()

    # FK krs.nim menolak NIM yang belum ada
    with pytest.raises(IntegrityError):
        db_session.add(KRS(nim="9999999-9999", semester="20251", status=KRSStatus.DRAFT))
        db_session.commit()
    db_session.rollback()

    # UNIQUE (nim, semester) dan UNIQUE (krs_id, kode_mk)
    with pytest.raises(IntegrityError):
        db_session.add(KRS(nim="2025001-0001", semester="20242", status=KRSStatus.DRAFT))
        db_session.commit()
    db_session.rollback()

    hist_krs = db_session.execute(
        select(KRS).where(KRS.nim == "2025001-0001", KRS.semester == "20242")
    ).scalar_one()
    with pytest.raises(IntegrityError):
        db_session.add(KRSDetail(krs_id=hist_krs.id, kode_mk="IF101", nilai="A"))
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    ("hari_a", "mulai_a", "selesai_a", "hari_b", "mulai_b", "selesai_b", "expected"),
    [
        (1, time(8, 0), time(10, 30), 1, time(9, 0), time(11, 0), True),  # sebagian
        (1, time(8, 0), time(11, 0), 1, time(9, 0), time(10, 0), True),  # di dalam
        (1, time(8, 0), time(10, 30), 1, time(8, 0), time(10, 30), True),  # persis sama
        (1, time(8, 0), time(10, 30), 1, time(10, 30), time(12, 0), False),  # bersambung
        (1, time(8, 0), time(10, 0), 2, time(8, 0), time(10, 0), False),  # beda hari
    ],
)
def test_bentrok_interval_cases(
    hari_a: int,
    mulai_a: time,
    selesai_a: time,
    hari_b: int,
    mulai_b: time,
    selesai_b: time,
    expected: bool,
) -> None:
    """Uji 5 kasus irisan interval jadwal termasuk kuliah bersambung tepat."""
    mk_a = MataKuliah(
        kode_mk="MKA", nama="MK A", sks=3, hari=hari_a, jam_mulai=mulai_a, jam_selesai=selesai_a
    )
    mk_b = MataKuliah(
        kode_mk="MKB", nama="MK B", sks=3, hari=hari_b, jam_mulai=mulai_b, jam_selesai=selesai_b
    )
    assert bentrok(mk_a, mk_b) is expected
    assert bentrok(mk_b, mk_a) is expected


def test_validators_unit_dan_build_chain(db_session: Session) -> None:
    """Uji masing-masing validator secara terpisah serta fail-fast pada build_chain."""
    with pytest.raises(ValueError):
        build_chain([])

    mk1 = MataKuliah(
        kode_mk="MK1", nama="Mata Kuliah 1", sks=4, hari=1, jam_mulai=time(8, 0), jam_selesai=time(10, 0)
    )
    mk2 = MataKuliah(
        kode_mk="MK2", nama="Mata Kuliah 2", sks=4, hari=1, jam_mulai=time(9, 0), jam_selesai=time(11, 0)
    )
    mk_heavy = MataKuliah(
        kode_mk="MKH", nama="MK Berat", sks=21, hari=2, jam_mulai=time(8, 0), jam_selesai=time(10, 0)
    )
    d1 = KRSDetail(krs_id=1, kode_mk="MK1", matakuliah=mk1)
    d_heavy = KRSDetail(krs_id=1, kode_mk="MKH", matakuliah=mk_heavy)

    # DuplicateValidator
    dup_val = DuplicateValidator()
    res_dup = dup_val.check(KRSContext("2025001-0001", "20251", [d1], mk1, db_session))
    assert res_dup.ok is False
    assert "Sudah ada di KRS: Mata Kuliah 1" == res_dup.message
    assert dup_val.check(KRSContext("2025001-0001", "20251", [d1], mk2, db_session)).ok is True

    # SKSValidator: tepat 24 lolos, 25 gagal dengan angka di pesan
    sks_val = SKSValidator()
    mk_3 = MataKuliah(
        kode_mk="MK3", nama="MK 3", sks=3, hari=3, jam_mulai=time(8, 0), jam_selesai=time(10, 0)
    )
    assert sks_val.check(KRSContext("2025001-0001", "20251", [d_heavy], mk_3, db_session)).ok is True
    res_over = sks_val.check(KRSContext("2025001-0001", "20251", [d_heavy], mk1, db_session))
    assert res_over.ok is False
    assert "25" in res_over.message and "24" in res_over.message

    # ConflictValidator
    conf_val = ConflictValidator()
    res_conf = conf_val.check(KRSContext("2025001-0001", "20251", [d1], mk2, db_session))
    assert res_conf.ok is False
    assert "Mata Kuliah 2" in res_conf.message and "Mata Kuliah 1" in res_conf.message
    assert conf_val.check(KRSContext("2025001-0001", "20251", [d1], mk_3, db_session)).ok is True

    # Spy validator membuktikan chain berhenti saat gagal lebih awal
    called = {"spy": False}

    class SpyValidator(Validator):
        def check(self, _ctx: KRSContext) -> ValidationResult:
            called["spy"] = True
            return ValidationResult(True)

    chain = build_chain([DuplicateValidator(), SKSValidator(), SpyValidator()])
    res_chain = chain.validate(KRSContext("2025001-0001", "20251", [d1, d_heavy], mk1, db_session))
    assert res_chain.ok is False
    assert res_chain.message.startswith("Sudah ada di KRS")
    assert called["spy"] is False


def test_prerequisite_query_bobot_dan_semester(db_session: Session) -> None:
    """Query prasyarat NOT EXISTS memakai bobot skala_nilai (>= C) pada semester < aktif."""
    nim = _setup_krs_sample_db(db_session)

    # Budi sudah lulus IF101 (B=3.0) di 20242 -> IF102 boleh diambil di 20251
    assert prasyarat_belum_lulus(db_session, nim, "IF102", "20251") == []

    # Budi hanya dapat D (1.0) untuk MA101 -> MA102 ditolak menyebut Kalkulus I
    assert prasyarat_belum_lulus(db_session, nim, "MA102", "20251") == ["Kalkulus I"]

    # Nilai "C" tepat (bobot 2.0) di semester lalu harus lulus; nilai "B" tidak boleh kalah oleh string 'B' < 'C'
    hist_detail_ma101 = db_session.execute(
        select(KRSDetail)
        .join(KRS, KRS.id == KRSDetail.krs_id)
        .where(KRS.nim == nim, KRS.semester == "20242", KRSDetail.kode_mk == "MA101")
    ).scalar_one()
    hist_detail_ma101.nilai = "C"
    db_session.commit()
    assert prasyarat_belum_lulus(db_session, nim, "MA102", "20251") == []

    # Jika diperbaiki ke E atau None, kembali tidak terpenuhi
    hist_detail_ma101.nilai = "E"
    db_session.commit()
    assert prasyarat_belum_lulus(db_session, nim, "MA102", "20251") == ["Kalkulus I"]
    hist_detail_ma101.nilai = None
    db_session.commit()
    assert prasyarat_belum_lulus(db_session, nim, "MA102", "20251") == ["Kalkulus I"]

    # Nilai A di semester SAMA ("20251") tidak boleh dihitung sebagai prasyarat di "20251"
    curr_krs = KRS(nim=nim, semester="20251", status=KRSStatus.DRAFT)
    curr_krs.details.append(KRSDetail(kode_mk="IF102", nilai="A"))
    db_session.add(curr_krs)
    db_session.commit()
    assert prasyarat_belum_lulus(db_session, nim, "IF203", "20251") == ["Struktur Data"]

    # PrerequisiteValidator format pesan
    mk_if203 = db_session.get(MataKuliah, "IF203")
    assert mk_if203 is not None
    res = PrerequisiteValidator().check(KRSContext(nim, "20251", [], mk_if203, db_session))
    assert res.ok is False
    assert res.message == "Prasyarat tidak terpenuhi: Struktur Data"


def test_krs_manager_add_remove_validate_and_stubs(db_session: Session) -> None:
    """Uji operasi lengkap KRSManager termasuk REVISION, validate_krs collect-all, dan stub Minggu 6."""
    nim = _setup_krs_sample_db(db_session)
    mgr = KRSManager(db_session, semester="20251")

    # Belum ada KRS -> validate_krs mengembalikan []
    assert mgr.validate_krs(nim) == []

    # Tambah IF102 (lulus prasyarat IF101=B) dan IF201 (Senin 08:00-10:30)
    d1 = mgr.add_course(nim, "IF102")
    assert d1.kode_mk == "IF102"
    d2 = mgr.add_course(nim, "IF201")
    assert d2.kode_mk == "IF201"

    # Bersambung IF203 butuh IF102 yang baru diambil di 20251 -> ditolak prasyarat
    with pytest.raises(KRSValidasiGagal, match="Prasyarat tidak terpenuhi: Struktur Data"):
        mgr.add_course(nim, "IF203")

    # Jadwal bentrok IF202 (Senin 09:00-11:00) vs IF201 (Senin 08:00-10:30)
    with pytest.raises(KRSValidasiGagal, match="Jadwal bentrok: Statistika dengan Basis Data"):
        mgr.add_course(nim, "IF202")

    # Duplikat IF102
    with pytest.raises(KRSValidasiGagal, match="Sudah ada di KRS: Struktur Data"):
        mgr.add_course(nim, "IF102")

    # Hapus IF201 berhasil dan delete-orphan terhapus di DB
    mgr.remove_course(nim, "IF201")
    krs = mgr.get_krs(nim)
    assert [d.kode_mk for d in krs.details] == ["IF102"]

    # Hapus MK tidak ada -> KRSTidakDitemukan
    with pytest.raises(KRSTidakDitemukan):
        mgr.remove_course(nim, "IF201")

    # Status REVISION masih boleh diubah, SUBMITTED tidak boleh diubah
    krs.status = KRSStatus.REVISION
    db_session.commit()
    mgr.add_course(nim, "IF201")

    krs.status = KRSStatus.SUBMITTED
    db_session.commit()
    with pytest.raises(KRSStatusTidakValid):
        mgr.add_course(nim, "IF204")
    with pytest.raises(KRSStatusTidakValid):
        mgr.remove_course(nim, "IF201")

    # Uji validate_krs mengumpulkan seluruh kesalahan sekaligus (sisipkan data bermasalah ganda di DB)
    krs.status = KRSStatus.DRAFT
    krs.details.append(KRSDetail(kode_mk="MA102"))  # gagal prasyarat Kalkulus I
    krs.details.append(KRSDetail(kode_mk="IF202"))  # bentrok IF201
    for extra in ("IF204", "IF205", "IF206", "IF207", "IF208"):
        krs.details.append(KRSDetail(kode_mk=extra))  # membuat total SKS > 24
    db_session.commit()

    all_errors = mgr.validate_krs(nim)
    messages = [e.message for e in all_errors]
    assert any("melebihi batas 24" in m for m in messages)
    assert any("Prasyarat tidak terpenuhi: Kalkulus I" in m for m in messages)
    assert any("Jadwal bentrok" in m for m in messages)

    # Unknown student / MK / KRS
    with pytest.raises(KRSTidakDitemukan):
        mgr.add_course("0000000-0000", "IF101")
    with pytest.raises(KRSTidakDitemukan):
        mgr.add_course(nim, "NOTEXIST")
    with pytest.raises(KRSTidakDitemukan):
        mgr.validate_krs("0000000-0000")
    with pytest.raises(KRSTidakDitemukan):
        KRSManager(db_session, semester="20261").remove_course(nim, "IF101")

    # Stubs Minggu 6
    with pytest.raises(NotImplementedError):
        mgr.submit_krs(nim)
    with pytest.raises(NotImplementedError):
        mgr.approve_krs(nim, 101)


def test_krs_concurrency_dua_tab_satu_detik_27_sks(tmp_path: Path) -> None:
    """Skenario slide '2 tab, 1 detik, 27 SKS': hanya 1 yang boleh lolos (maks 24 SKS)."""
    db_file = tmp_path / "concurrent_krs.db"
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
            seed_krs_data(db)
            # Tambah 2 MK 3-SKS yang tidak bentrok dengan MK lain di hari 5 & 6 siang
            db.add_all(
                [
                    MataKuliah(
                        kode_mk="MKT1",
                        nama="Proyek Perangkat Lunak",
                        sks=3,
                        hari=5,
                        jam_mulai=time(13, 0),
                        jam_selesai=time(15, 30),
                    ),
                    MataKuliah(
                        kode_mk="MKT2",
                        nama="Kapita Selekta AI",
                        sks=3,
                        hari=6,
                        jam_mulai=time(13, 0),
                        jam_selesai=time(15, 30),
                    ),
                    # MK ekstra untuk mengisi total awal tepat 21 SKS tanpa bentrok & tanpa prasyarat
                    MataKuliah(
                        kode_mk="MKP1",
                        nama="Dasar Pemrograman",
                        sks=4,
                        hari=1,
                        jam_mulai=time(13, 0),
                        jam_selesai=time(16, 0),
                    ),
                    MataKuliah(
                        kode_mk="MKP2",
                        nama="Matematika Diskrit",
                        sks=3,
                        hari=2,
                        jam_mulai=time(13, 0),
                        jam_selesai=time(15, 30),
                    ),
                ]
            )
            db.commit()

            mgr = KRSManager(db, semester="20251")
            # 3 + 4 + 4 + 4 + 4 + 2 = 21 SKS (tunggu: IF201(3)+IF204(3)+IF205(4)+IF206(4)+IF207(4)+MKP2(3) = 21 SKS)
            for code in ("IF201", "IF204", "IF205", "IF206", "IF207", "MKP2"):
                mgr.add_course("2025001-0001", code)

        def worker(kode_mk: str) -> str:
            with LocalSession() as session:
                worker_mgr = KRSManager(session, semester="20251")
                try:
                    worker_mgr.add_course("2025001-0001", kode_mk)
                    return f"OK:{kode_mk}"
                except KRSValidasiGagal as exc:
                    return f"REJECT:{exc}"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(worker, ["MKT1", "MKT2"]))

        ok_list = [o for o in outcomes if o.startswith("OK:")]
        reject_list = [o for o in outcomes if o.startswith("REJECT:")]
        assert len(ok_list) == 1
        assert len(reject_list) == 1
        assert "melebihi batas 24" in reject_list[0]

        with LocalSession() as verify_db:
            final_krs = KRSManager(verify_db, semester="20251").get_krs("2025001-0001")
            total_sks = sum(d.matakuliah.sks for d in final_krs.details)
            assert total_sks == 24
    finally:
        file_engine.dispose()


def test_krs_api_endpoints_and_openapi(
    client: TestClient, db_session: Session
) -> None:
    """Uji endpoint REST API /api/krs/* dan keberadaannya pada /openapi.json."""
    nim = _setup_krs_sample_db(db_session)

    # Belum punya KRS di 20251 -> GET 404
    assert client.get(f"/api/krs/{nim}?semester=20251").status_code == 404

    # Tambah IF102 -> 201 Created
    add_ok = client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "IF102"})
    assert add_ok.status_code == 201
    assert add_ok.json()["kode_mk"] == "IF102"
    assert add_ok.json()["sks"] == 3

    # Tambah IF102 lagi -> 400 duplikat
    add_dup = client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "IF102"})
    assert add_dup.status_code == 400
    assert "Sudah ada di KRS" in add_dup.json()["detail"]

    # Tambah MA102 (gagal prasyarat Kalkulus I) -> 400
    add_pre = client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "MA102"})
    assert add_pre.status_code == 400
    assert "Prasyarat tidak terpenuhi: Kalkulus I" == add_pre.json()["detail"]

    # Tambah kode blank -> 400 (RequestValidationError handler)
    assert client.post(f"/api/krs/{nim}/courses", json={"kode_mk": "   "}).status_code == 400

    # Mahasiswa atau MK tidak ada -> 404
    assert client.post("/api/krs/9999999-9999/courses", json={"kode_mk": "IF101"}).status_code == 404
    assert client.post(f"/api/krs/{nim}/courses", json={"kode_mk": "XXXX"}).status_code == 404

    # GET KRS -> 200
    res_get = client.get(f"/api/krs/{nim}?semester=20251")
    assert res_get.status_code == 200
    assert res_get.json()["total_sks"] == 3
    assert len(res_get.json()["details"]) == 1

    # GET validate -> 200 valid=True
    res_val = client.get(f"/api/krs/{nim}/validate?semester=20251")
    assert res_val.status_code == 200
    assert res_val.json() == {
        "nim": nim,
        "semester": "20251",
        "valid": True,
        "errors": [],
    }
    assert client.get("/api/krs/9999999-9999/validate").status_code == 404

    # Lock KRS ke SUBMITTED -> POST & DELETE harus mengembalikan 409 Conflict
    krs_row = db_session.execute(
        select(KRS).where(KRS.nim == nim, KRS.semester == "20251")
    ).scalar_one()
    krs_row.status = KRSStatus.SUBMITTED
    db_session.commit()

    assert client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "IF201"}).status_code == 409
    assert client.delete(f"/api/krs/{nim}/courses/IF102?semester=20251").status_code == 409

    # Kembalikan ke DRAFT lalu DELETE -> 200, kemudian DELETE lagi -> 404
    krs_row.status = KRSStatus.DRAFT
    db_session.commit()
    res_del = client.delete(f"/api/krs/{nim}/courses/IF102?semester=20251")
    assert res_del.status_code == 200
    assert client.delete(f"/api/krs/{nim}/courses/IF102?semester=20251").status_code == 404

    # OpenAPI mempublikasikan endpoint /api/krs/*
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/krs/{nim}" in paths
    assert "/api/krs/{nim}/courses" in paths
    assert "/api/krs/{nim}/courses/{kode_mk}" in paths
    assert "/api/krs/{nim}/validate" in paths

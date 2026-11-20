"""Unit, integration, dan concurrency tests untuk Modul KRS SEVIMA-Mini (Minggu 5–6)."""

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
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    ProgramStudi,
    SkalaNilai,
    StatusPMB,
    prerequisite,
)
from app.services.exceptions import (
    ForbiddenError,
    KRSLockedError,
    KRSStatusTidakValid,
    KRSTidakDitemukan,
    KRSValidasiGagal,
    StaleVersionError,
    TransitionError,
)
from app.services.krs_manager import KRSManager
from app.services.krs_queries import prasyarat_belum_lulus
from app.services.krs_recommender import KRSRecommender
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


def test_tambah_mk_tanpa_prasyarat_error(db_session: Session) -> None:
    """Sesuai modul: mengambil mata kuliah yang prasyaratnya belum lulus wajib ditolak."""
    nim = _setup_krs_sample_db(db_session)
    mgr = KRSManager(db_session, semester="20251")
    with pytest.raises(KRSValidasiGagal, match="Prasyarat tidak terpenuhi: Kalkulus I"):
        mgr.add_course(nim, "MA102")


def test_jadwal_bentrok_error(db_session: Session) -> None:
    """Sesuai modul: mengambil dua mata kuliah dengan jadwal beririsan wajib ditolak."""
    nim = _setup_krs_sample_db(db_session)
    mgr = KRSManager(db_session, semester="20251")
    mgr.add_course(nim, "IF201")
    with pytest.raises(
        KRSValidasiGagal, match="Jadwal bentrok: Statistika dengan Basis Data"
    ):
        mgr.add_course(nim, "IF202")


def test_krs_manager_add_remove_and_validate(db_session: Session) -> None:
    """Uji operasi lengkap KRSManager: add, remove, submit/revise lock, dan validate_krs collect-all."""
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

    # Submit -> terkunci (SUBMITTED), lalu Revise -> kembali editable (REVISION)
    submitted = mgr.submit_krs(nim)
    assert submitted.status == KRSStatus.SUBMITTED
    with pytest.raises(KRSStatusTidakValid):
        mgr.add_course(nim, "IF204")
    with pytest.raises(KRSLockedError):
        mgr.remove_course(nim, "IF102")

    revised = mgr.revise_krs(nim, 101, "Tambahkan Basis Data")
    assert revised.status == KRSStatus.REVISION
    mgr.add_course(nim, "IF201")

    # Uji validate_krs mengumpulkan seluruh kesalahan sekaligus (sisipkan data korup langsung di DB)
    krs = mgr.get_krs(nim)
    krs.details.append(KRSDetail(kode_mk="MA102"))  # gagal prasyarat Kalkulus I
    krs.details.append(KRSDetail(kode_mk="IF202"))  # bentrok IF201
    for extra in ("IF204", "IF205", "IF206", "IF207", "IF208"):
        krs.details.append(KRSDetail(kode_mk=extra))  # membuat total SKS > 24
    db_session.commit()

    # Submit KRS yang sudah korup di DB wajib ditolak oleh validasi ulang
    with pytest.raises(KRSValidasiGagal):
        mgr.submit_krs(nim)

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

    # Submit KRS lewat endpoint -> POST & DELETE courses harus mengembalikan 409 Conflict
    res_submit = client.post(f"/api/krs/{nim}/submit?semester=20251")
    assert res_submit.status_code == 200
    assert res_submit.json()["status"] == "SUBMITTED"

    assert client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "IF201"}).status_code == 409
    assert client.delete(f"/api/krs/{nim}/courses/IF102?semester=20251").status_code == 409

    # Kembalikan ke REVISION melalui dosen PA lalu DELETE -> 200, kemudian DELETE lagi -> 404
    res_revise = client.post(
        f"/api/krs/{nim}/revise?semester=20251",
        json={"dosen_pa_id": 101, "catatan": "Sesuaikan jadwal"},
    )
    assert res_revise.status_code == 200
    assert res_revise.json()["status"] == "REVISION"

    res_del = client.delete(f"/api/krs/{nim}/courses/IF102?semester=20251")
    assert res_del.status_code == 200
    assert client.delete(f"/api/krs/{nim}/courses/IF102?semester=20251").status_code == 404

    # OpenAPI mempublikasikan seluruh endpoint /api/krs/* termasuk alur workflow & recommend
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/krs/{nim}" in paths
    assert "/api/krs/{nim}/courses" in paths
    assert "/api/krs/{nim}/courses/{kode_mk}" in paths
    assert "/api/krs/{nim}/validate" in paths
    assert "/api/krs/{nim}/submit" in paths
    assert "/api/krs/{nim}/approve" in paths
    assert "/api/krs/{nim}/revise" in paths
    assert "/api/krs/{nim}/recommend" in paths


def test_workflow_submit_revise_resubmit_approve_dan_audit_log(db_session: Session) -> None:
    """Uji siklus lengkap DRAFT -> SUBMITTED -> REVISION -> SUBMITTED -> APPROVED beserta audit log."""
    nim = _setup_krs_sample_db(db_session)
    mgr = KRSManager(db_session, semester="20251")

    # Submit sebelum KRS ada -> 404
    with pytest.raises(KRSTidakDitemukan):
        mgr.submit_krs(nim)

    # Buat KRS lalu kosongkan isinya -> submit KRS kosong wajib gagal (400)
    mgr.add_course(nim, "IF102")
    v_awal = mgr.get_krs(nim).version
    mgr.add_course(nim, "IF201")
    v_tambah = mgr.get_krs(nim).version
    assert v_tambah > v_awal

    mgr.remove_course(nim, "IF201")
    v_hapus = mgr.get_krs(nim).version
    assert v_hapus > v_tambah

    mgr.remove_course(nim, "IF102")
    with pytest.raises(KRSValidasiGagal, match="KRS kosong"):
        mgr.submit_krs(nim)

    # Isi kembali dan submit pertama (DRAFT -> SUBMITTED)
    mgr.add_course(nim, "IF102")
    submitted_1 = mgr.submit_krs(nim)
    assert submitted_1.status == KRSStatus.SUBMITTED
    assert submitted_1.submitted_at is not None
    assert submitted_1.dosen_pa_id == 101

    # Submit ulang saat SUBMITTED wajib gagal TransitionError
    with pytest.raises(TransitionError):
        mgr.submit_krs(nim)

    # Catatan revisi kosong/spasi wajib ditolak
    with pytest.raises(KRSValidasiGagal, match="Catatan revisi wajib diisi"):
        mgr.revise_krs(nim, 101, "   ")

    # Dosen PA kembalikan untuk revisi (SUBMITTED -> REVISION)
    revised = mgr.revise_krs(nim, 101, "Ambil Basis Data juga")
    v_rev = revised.version
    assert revised.status == KRSStatus.REVISION
    assert revised.catatan_revisi == "Ambil Basis Data juga"

    # Mahasiswa edit lagi (version naik) lalu submit ulang -> SUBMITTED -> APPROVED
    mgr.add_course(nim, "IF201")
    assert mgr.get_krs(nim).version > v_rev
    submitted_2 = mgr.submit_krs(nim)
    assert submitted_2.status == KRSStatus.SUBMITTED

    approved = mgr.approve_krs(nim, 101, expected_version=submitted_2.version)
    assert approved.status == KRSStatus.APPROVED
    assert approved.approved_at is not None

    # Setelah APPROVED tidak bisa di-approve atau di-revise ulang
    with pytest.raises(TransitionError):
        mgr.approve_krs(nim, 101)
    with pytest.raises(TransitionError):
        mgr.revise_krs(nim, 101, "Telat revisi")

    # Verifikasi catatan KRSLog dan Notifikasi
    logs = db_session.execute(
        select(KRSLog).where(KRSLog.krs_id == approved.id).order_by(KRSLog.id)
    ).scalars().all()
    assert [log.aksi for log in logs] == ["SUBMIT", "REVISE", "SUBMIT", "APPROVE"]

    notifs = db_session.execute(
        select(Notifikasi).where(Notifikasi.nim == nim).order_by(Notifikasi.id)
    ).scalars().all()
    assert len(notifs) == 2
    assert "revisi" in notifs[0].pesan.lower()
    assert "disetujui" in notifs[1].pesan.lower()
    assert all(n.terbaca is False for n in notifs)


def test_otorisasi_dosen_pa_403_dan_optimistic_lock_409(
    db_session: Session, tmp_path: Path
) -> None:
    """Bedakan 403 Forbidden (bukan dosen PA) vs 409 Conflict (state ilegal & stale version)."""
    nim = _setup_krs_sample_db(db_session)
    mgr = KRSManager(db_session, semester="20251")

    # Approve/Revise KRS yang belum ada -> 404
    with pytest.raises(KRSTidakDitemukan):
        mgr.approve_krs(nim, 101)
    with pytest.raises(KRSTidakDitemukan):
        mgr.revise_krs(nim, 101, "Belum ada")

    # Buat mahasiswa baru tanpa riwayat KRS (dosen_pa_id = None) -> siapa pun ditolak 403
    prodi_id = db_session.execute(
        select(ProgramStudi.id).where(ProgramStudi.kode == "001")
    ).scalar_one()
    jalur_id = db_session.execute(
        select(JalurMasuk.id).where(JalurMasuk.nama == "SNBP")
    ).scalar_one()
    db_session.add(
        CalonMahasiswa(
            nama_lengkap="Siti Aminah",
            email="siti@example.com",
            phone="081299988877",
            tanggal_lahir=date(2006, 8, 17),
            alamat="Jl. Asia Afrika",
            program_studi_id=prodi_id,
            jalur_masuk_id=jalur_id,
            status=StatusPMB.approved,
            nim="2025001-0099",
            approved_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    mgr.add_course("2025001-0099", "IF101")
    mgr.submit_krs("2025001-0099")
    with pytest.raises(ForbiddenError):
        mgr.approve_krs("2025001-0099", 101)

    # Mahasiswa Budi (dosen_pa_id=101): status DRAFT di-approve oleh dosen PA benar -> 409 TransitionError
    mgr.add_course(nim, "IF102")
    v_draft = mgr.get_krs(nim).version
    with pytest.raises(TransitionError):
        mgr.approve_krs(nim, 101)

    # Status SUBMITTED: dosen PA salah (999) wajib mendapat 403 Forbidden (bukan 409)
    submitted = mgr.submit_krs(nim)
    with pytest.raises(ForbiddenError, match="bukan dosen PA"):
        mgr.approve_krs(nim, 999)
    with pytest.raises(ForbiddenError, match="bukan dosen PA"):
        mgr.revise_krs(nim, 999, "Bukan bimbingan saya")

    # Optimistic locking expected_version basi -> 409 StaleVersionError
    assert v_draft < submitted.version
    with pytest.raises(StaleVersionError, match="muat ulang"):
        mgr.approve_krs(nim, 101, expected_version=v_draft)
    with pytest.raises(StaleVersionError, match="muat ulang"):
        mgr.revise_krs(nim, 101, "Versi basi", expected_version=v_draft)

    # Uji StaleDataError SQLAlchemy murni (version_id_col) via KRSManager pada 2 session konkuren
    db_file = tmp_path / "stale_lock.db"
    file_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    attach_sqlite_fk_pragma(file_engine)
    LocalSession = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=file_engine
    )
    Base.metadata.create_all(bind=file_engine)

    try:
        with LocalSession() as setup_db:
            seed_data(setup_db)
            seed_krs_data(setup_db)
            KRSManager(setup_db, semester="20251").add_course(nim, "IF102")

        with LocalSession() as sess_a, LocalSession() as sess_b:
            mgr_a = KRSManager(sess_a, semester="20251")
            krs_a = mgr_a.get_krs(nim)
            v_seen_a = krs_a.version
            sess_a.commit()  # Lepas read lock SQLite, identity map tetap menyimpan version lama

            # Session B diam-diam menambah MK dan menaikkan version di database
            mgr_b = KRSManager(sess_b, semester="20251")
            mgr_b.add_course(nim, "IF201")
            assert mgr_b.get_krs(nim).version > v_seen_a

            # Session A mencoba submit dengan entity ber-version basi -> StaleDataError -> StaleVersionError
            with pytest.raises(StaleVersionError, match="muat ulang"):
                mgr_a.submit_krs(nim)
    finally:
        file_engine.dispose()


def test_approve_dan_revise_rollback_atomik_saat_commit_gagal(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jika commit gagal di tengah jalan, status KRS, log, dan notifikasi wajib rollback utuh."""
    nim = _setup_krs_sample_db(db_session)
    mgr = KRSManager(db_session, semester="20251")
    mgr.add_course(nim, "IF102")
    krs_sub = mgr.submit_krs(nim)

    def gagal_commit() -> None:
        raise RuntimeError("Simulasi kegagalan commit database")

    monkeypatch.setattr(db_session, "commit", gagal_commit)
    with pytest.raises(RuntimeError, match="Simulasi kegagalan"):
        mgr.approve_krs(nim, 101)
    with pytest.raises(RuntimeError, match="Simulasi kegagalan"):
        mgr.revise_krs(nim, 101, "Coba revisi")
    monkeypatch.undo()

    krs_after = mgr.get_krs(nim)
    assert krs_after.status == KRSStatus.SUBMITTED
    assert krs_after.approved_at is None
    assert krs_after.catatan_revisi is None

    logs = db_session.execute(
        select(KRSLog).where(KRSLog.krs_id == krs_sub.id)
    ).scalars().all()
    assert [log.aksi for log in logs] == ["SUBMIT"]
    assert db_session.execute(select(Notifikasi)).scalars().all() == []


def test_krs_api_workflow_submit_approve_revise_403_409(
    client: TestClient, db_session: Session
) -> None:
    """Uji endpoint HTTP /submit, /approve, /revise untuk status 200, 400, 403, 404, dan 409."""
    nim = _setup_krs_sample_db(db_session)

    # Submit KRS belum ada -> 404
    assert client.post(f"/api/krs/{nim}/submit?semester=20251").status_code == 404

    # Tambah MK dan submit -> 200 SUBMITTED
    assert client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "IF102"}).status_code == 201
    res_sub1 = client.post(f"/api/krs/{nim}/submit?semester=20251")
    assert res_sub1.status_code == 200
    v_sub1 = res_sub1.json()["version"]

    # Dosen PA salah -> 403 Forbidden
    res_403 = client.post(
        f"/api/krs/{nim}/approve?semester=20251",
        json={"dosen_pa_id": 888, "expected_version": v_sub1},
    )
    assert res_403.status_code == 403
    assert "bukan dosen PA" in res_403.json()["detail"]

    # Revisi dengan catatan kosong -> 400
    assert (
        client.post(
            f"/api/krs/{nim}/revise?semester=20251",
            json={"dosen_pa_id": 101, "catatan": "   "},
        ).status_code
        == 400
    )

    # Revisi oleh PA benar -> 200 REVISION
    res_rev = client.post(
        f"/api/krs/{nim}/revise?semester=20251",
        json={"dosen_pa_id": 101, "catatan": "Tambah IF201", "expected_version": v_sub1},
    )
    assert res_rev.status_code == 200
    v_rev = res_rev.json()["version"]
    assert res_rev.json()["catatan_revisi"] == "Tambah IF201"

    # Tambah IF201 -> submit ulang -> versi naik -> expected_version lama ditolak 409 Conflict
    assert client.post(f"/api/krs/{nim}/courses?semester=20251", json={"kode_mk": "IF201"}).status_code == 201
    res_sub2 = client.post(f"/api/krs/{nim}/submit?semester=20251")
    assert res_sub2.status_code == 200
    v_sub2 = res_sub2.json()["version"]
    assert v_sub2 > v_rev

    res_stale = client.post(
        f"/api/krs/{nim}/approve?semester=20251",
        json={"dosen_pa_id": 101, "expected_version": v_rev},
    )
    assert res_stale.status_code == 409
    assert "muat ulang" in res_stale.json()["detail"]

    # Approve dengan versi terbaru -> 200 APPROVED
    res_ok = client.post(
        f"/api/krs/{nim}/approve?semester=20251",
        json={"dosen_pa_id": 101, "expected_version": v_sub2},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["status"] == "APPROVED"
    assert res_ok.json()["approved_at"] is not None

    # Submit atau revise ulang setelah APPROVED -> 409 Conflict
    assert client.post(f"/api/krs/{nim}/submit?semester=20251").status_code == 409
    assert (
        client.post(
            f"/api/krs/{nim}/revise?semester=20251",
            json={"dosen_pa_id": 101, "catatan": "Sudah approved"},
        ).status_code
        == 409
    )


def test_krs_recommender_csp_wajib_conflict_dan_prasyarat(
    client: TestClient, db_session: Session
) -> None:
    """Uji CSP recommender: prioritaskan MK wajib, hindari bentrok/prasyarat gagal, <= max_sks."""
    nim = _setup_krs_sample_db(db_session)
    recommender = KRSRecommender()

    # IF201 (Senin 08:00-10:30) dan IF202 (Senin 09:00-11:00) bentrok.
    # IF202 wajib -> harus menang atas IF201 pilihan!
    # MA102 & IF203 gagal prasyarat -> harus masuk daftar ditolak.
    res = recommender.recommend(
        db_session,
        nim=nim,
        semester="20251",
        wajib=["IF202", "IF102"],
        pilihan=["IF201", "MA102", "IF203", "IF204"],
        max_sks=24,
    )
    kode_terpilih = {mk.kode_mk for mk in res.selected}
    assert {"IF202", "IF102", "IF204"}.issubset(kode_terpilih)
    assert "IF201" not in kode_terpilih
    assert res.total_sks <= 24
    assert set(res.wajib_terpilih) == {"IF202", "IF102"}
    assert "Kalkulus I" in res.ditolak["MA102"]
    assert "Struktur Data" in res.ditolak["IF203"]
    assert "bentrok" in res.ditolak["IF201"].lower()

    # Batas SKS sempit (max_sks=10) via REST endpoint tanpa list eksplisit (pakai seluruh katalog DB)
    api_res = client.post(
        f"/api/krs/{nim}/recommend?semester=20251",
        json={"max_sks": 10},
    )
    assert api_res.status_code == 200
    body = api_res.json()
    assert 1 <= body["total_sks"] <= 10
    assert "MA102" in body["ditolak"]
    assert "IF203" in body["ditolak"]

    # Error handling: NIM/MK tidak ditemukan -> 404, max_sks tidak valid -> 400
    assert (
        client.post(f"/api/krs/9999999-9999/recommend?semester=20251", json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/krs/{nim}/recommend?semester=20251",
            json={"wajib": ["TIDAKADA"]},
        ).status_code
        == 404
    )
    with pytest.raises(KRSValidasiGagal):
        recommender.recommend(db_session, nim=nim, max_sks=30)

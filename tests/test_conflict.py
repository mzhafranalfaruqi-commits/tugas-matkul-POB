"""Unit, integration, constraint, concurrency, dan seed tests untuk Modul Jadwal & Ruangan."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, time
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import attach_sqlite_fk_pragma
from app.models import (
    Base,
    CalonMahasiswa,
    Dosen,
    Jadwal,
    JalurMasuk,
    Kelas,
    KRS,
    KRSDetail,
    KRSStatus,
    MataKuliah,
    ProgramStudi,
    Ruangan,
    StatusPMB,
)
from app.schemas.jadwal import JadwalIn
from app.services.conflict import (
    Conflict,
    JadwalSlot,
    detect_naive,
    detect_schedule_conflict,
)
from app.services.exceptions import (
    CapacityError,
    NotFoundError,
    ScheduleConflictError,
)
from app.services.scheduling_service import SchedulingService, cek_kapasitas
from seed import seed_data, seed_jadwal_data


def _slot(
    id_jadwal: int,
    hari: int,
    mulai: str,
    selesai: str,
    ruang: str = "A101",
    dosen: int = 1,
) -> JadwalSlot:
    """Helper ringkas pembentuk JadwalSlot dari string HH:MM."""
    return JadwalSlot(
        id=id_jadwal,
        hari=hari,
        jam_mulai=time.fromisoformat(mulai),
        jam_selesai=time.fromisoformat(selesai),
        ruangan_kode=ruang,
        dosen_id=dosen,
    )


R = "room_conflict"
L = "lecturer_conflict"


@pytest.mark.parametrize(
    ("jadwal_list", "harap"),
    [
        # 1. Bentrok ruangan (hari sama, ruang sama, dosen beda, waktu bertumpuk)
        (
            [_slot(1, 1, "08:00", "09:40"), _slot(2, 1, "09:00", "11:00", dosen=2)],
            {Conflict(R, (1, 2))},
        ),
        # 2. Bentrok dosen (hari sama, ruang beda, dosen sama, waktu bertumpuk)
        (
            [_slot(1, 1, "08:00", "09:40"), _slot(2, 1, "09:00", "11:00", ruang="B201")],
            {Conflict(L, (1, 2))},
        ),
        # 3. Kuliah bersambung tepat di 09:40 -> BUKAN bentrok (jaga bug <= vs <)
        (
            [_slot(1, 1, "08:00", "09:40"), _slot(2, 1, "09:40", "11:20")],
            set(),
        ),
        # 4. Beda hari -> BUKAN bentrok (jaga bug lupa cek hari)
        (
            [_slot(1, 1, "08:00", "09:40"), _slot(2, 2, "08:00", "09:40")],
            set(),
        ),
        # 5. Interval di dalam interval dengan ruang & dosen sama -> 2 konflik tanpa duplikat
        (
            [_slot(1, 1, "08:00", "09:40"), _slot(2, 1, "08:30", "09:00")],
            {Conflict(R, (1, 2)), Conflict(L, (1, 2))},
        ),
        # 6. Waktu overlap saja dengan ruang & dosen berbeda -> kondisi normal (bukan konflik)
        (
            [
                _slot(1, 1, "08:00", "09:40", ruang="A101", dosen=1),
                _slot(2, 1, "08:30", "10:00", ruang="B201", dosen=2),
            ],
            set(),
        ),
        # 7. Jam satu digit vs dua digit (09:00-10:00 vs 10:00-11:00) -> bersambung (jaga bug string)
        (
            [_slot(1, 1, "09:00", "10:00"), _slot(2, 1, "10:00", "11:00")],
            set(),
        ),
        # 8. Jam 09:00-10:30 vs 10:00-11:30 di ruang berbeda, dosen sama -> bentrok
        (
            [
                _slot(1, 1, "09:00", "10:30", ruang="A101", dosen=3),
                _slot(2, 1, "10:00", "11:30", ruang="A102", dosen=3),
            ],
            {Conflict(L, (1, 2))},
        ),
        # 9. Tiga jadwal bertumpuk di ruang sama -> tepat 3 pasangan kanonik
        (
            [
                _slot(1, 1, "08:00", "10:00", ruang="A101", dosen=1),
                _slot(2, 1, "08:30", "10:30", ruang="A101", dosen=2),
                _slot(3, 1, "09:00", "11:00", ruang="A101", dosen=3),
            ],
            {Conflict(R, (1, 2)), Conflict(R, (1, 3)), Conflict(R, (2, 3))},
        ),
    ],
)
def test_detect_schedule_conflict_cases(
    jadwal_list: list[JadwalSlot], harap: set[Conflict]
) -> None:
    """Memverifikasi sweep dan versi naif menangkap semua kasus batas tanpa duplikat."""
    hasil_sweep = detect_schedule_conflict(jadwal_list)
    hasil_naif = detect_naive(jadwal_list)

    assert len(hasil_sweep) == len(harap)
    assert len(hasil_naif) == len(harap)
    assert set(hasil_sweep) == harap
    assert set(hasil_naif) == harap


def _siapkan_data_dasar(db: Session) -> tuple[Kelas, Kelas, Ruangan, Ruangan, Dosen, Dosen]:
    """Menyiapkan entitas minimum MK, 2 kelas, 2 ruangan, dan 2 dosen untuk pengujian."""
    mk1 = MataKuliah(
        kode_mk="MA101",
        nama="Kalkulus I",
        sks=3,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(10, 0),
    )
    mk2 = MataKuliah(
        kode_mk="IF201",
        nama="Basis Data",
        sks=3,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(10, 0),
    )
    r_40 = Ruangan(kode="A101", kapasitas=40)
    r_30 = Ruangan(kode="A104", kapasitas=30)
    d1 = Dosen(nidn="0001018501", nama="Dr. Ahmad")
    d2 = Dosen(nidn="0001018502", nama="Dr. Siti")
    db.add_all([mk1, mk2, r_40, r_30, d1, d2])
    db.flush()

    k1 = Kelas(kode_mk="MA101", nama="A", kuota=40, semester="20251")
    k2 = Kelas(kode_mk="IF201", nama="A", kuota=35, semester="20251")
    db.add_all([k1, k2])
    db.commit()
    return k1, k2, r_40, r_30, d1, d2


def test_jadwal_db_constraints(db_session: Session) -> None:
    """Menguji penegakan CHECK dan UNIQUE constraint ORM modul jadwal di SQLite."""
    k1, _, r_40, _, d1, _ = _siapkan_data_dasar(db_session)

    with pytest.raises(IntegrityError):
        db_session.add(Ruangan(kode="BADR", kapasitas=0))
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(Kelas(kode_mk="MA101", nama="Z", kuota=0, semester="20251"))
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(Dosen(nidn="0001018501", nama="Duplikat NIDN"))
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(
            Jadwal(
                kelas_id=k1.id,
                hari=7,
                jam_mulai=time(8, 0),
                jam_selesai=time(9, 40),
                ruangan_kode=r_40.kode,
                dosen_id=d1.id,
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(
            Jadwal(
                kelas_id=k1.id,
                hari=1,
                jam_mulai=time(10, 0),
                jam_selesai=time(10, 0),
                ruangan_kode=r_40.kode,
                dosen_id=d1.id,
            )
        )
        db_session.commit()
    db_session.rollback()


def test_cek_kapasitas_kuota_dan_terdaftar(db_session: Session) -> None:
    """Uji cek_kapasitas pada batas tepat, kuota > kapasitas, dan peserta terdaftar > kapasitas."""
    k1, k2, r_40, r_30, _, _ = _siapkan_data_dasar(db_session)

    # Tepat 40 kursi untuk kapasitas 40 -> boleh
    cek_kapasitas(db_session, k1.id, r_40.kode)

    # Kelas kuota 35 di ruang kapasitas 30 -> CapacityError meski pendaftar masih 0
    with pytest.raises(CapacityError, match="A104"):
        cek_kapasitas(db_session, k2.id, r_30.kode)

    # Ruang atau kelas tidak ada -> NotFoundError
    with pytest.raises(NotFoundError):
        cek_kapasitas(db_session, 9999, r_40.kode)
    with pytest.raises(NotFoundError):
        cek_kapasitas(db_session, k1.id, "NOPE")

    # Peserta terdaftar (via KRSDetail.kelas_id) melebihi kapasitas meski kuota kecil
    r_kecil = Ruangan(kode="R2", kapasitas=2)
    k_kecil = Kelas(kode_mk="MA101", nama="Kecil", kuota=1, semester="20251")
    db_session.add_all([r_kecil, k_kecil])
    db_session.flush()

    prodi = db_session.execute(select(ProgramStudi).limit(1)).scalar_one()
    jalur = db_session.execute(select(JalurMasuk).limit(1)).scalar_one()
    for i in range(3):
        nim = f"2025001-{i+10:04d}"
        db_session.add(
            CalonMahasiswa(
                nama_lengkap=f"Mhs {i}",
                email=f"mhs{i}@example.com",
                phone="081234567890",
                tanggal_lahir=date(2006, 1, 1),
                alamat="Bandung",
                program_studi_id=prodi.id,
                jalur_masuk_id=jalur.id,
                status=StatusPMB.approved,
                nim=nim,
            )
        )
        db_session.flush()
        krs = KRS(nim=nim, semester="20251", status=KRSStatus.DRAFT)
        db_session.add(krs)
        db_session.flush()
        db_session.add(KRSDetail(krs_id=krs.id, kode_mk="MA101", kelas_id=k_kecil.id))
    db_session.commit()

    with pytest.raises(CapacityError, match="butuh 3 kursi"):
        cek_kapasitas(db_session, k_kecil.id, r_kecil.kode)


def test_jadwal_api_crud_conflicts_dan_status_codes(
    client: TestClient, db_session: Session
) -> None:
    """Uji endpoint POST/PUT/DELETE/GET conflicts termasuk 201, 200, 204, 404, 409, dan 422."""
    k1, k2, r_40, r_30, d1, d2 = _siapkan_data_dasar(db_session)

    # POST valid -> 201
    res1 = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k1.id,
            "hari": 1,
            "jam_mulai": "08:00:00",
            "jam_selesai": "09:40:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
    )
    assert res1.status_code == 201
    id1 = res1.json()["id"]

    # POST bersambung tepat di ruang & dosen sama -> 201
    res_sambung = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k1.id,
            "hari": 1,
            "jam_mulai": "09:40:00",
            "jam_selesai": "11:20:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
    )
    assert res_sambung.status_code == 201
    id_sambung = res_sambung.json()["id"]

    # POST bentrok ruangan saja (08:30-09:30 hanya menabrak id1) -> 409 dengan payload conflicts
    res_room_409 = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k2.id,
            "hari": 1,
            "jam_mulai": "08:30:00",
            "jam_selesai": "09:30:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d2.id,
        },
    )
    assert res_room_409.status_code == 409
    assert res_room_409.json()["conflicts"] == [{"type": "room_conflict", "affected": [id1]}]

    # POST bentrok dengan dua slot bersambung sekaligus (08:30-10:00 menabrak id1 & id_sambung)
    res_two_409 = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k2.id,
            "hari": 1,
            "jam_mulai": "08:30:00",
            "jam_selesai": "10:00:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d2.id,
        },
    )
    assert res_two_409.status_code == 409
    assert res_two_409.json()["conflicts"] == [
        {"type": "room_conflict", "affected": [id1]},
        {"type": "room_conflict", "affected": [id_sambung]},
    ]

    # POST bentrok dosen saja -> 409
    res_lec_409 = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k2.id,
            "hari": 1,
            "jam_mulai": "08:30:00",
            "jam_selesai": "09:30:00",
            "ruangan_kode": r_30.kode,
            "dosen_id": d1.id,
        },
    )
    assert res_lec_409.status_code == 409
    assert res_lec_409.json()["conflicts"] == [{"type": "lecturer_conflict", "affected": [id1]}]

    # POST bentrok ganda (ruang + dosen sekaligus) -> 409 memuat kedua konflik
    res_dual_409 = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k2.id,
            "hari": 1,
            "jam_mulai": "08:30:00",
            "jam_selesai": "09:30:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
    )
    assert res_dual_409.status_code == 409
    assert res_dual_409.json()["conflicts"] == [
        {"type": "room_conflict", "affected": [id1]},
        {"type": "lecturer_conflict", "affected": [id1]},
    ]

    # POST kapasitas kurang (k2 kuota 35 di A104 kapasitas 30) -> 409
    res_cap_409 = client.post(
        "/api/jadwal",
        json={
            "kelas_id": k2.id,
            "hari": 2,
            "jam_mulai": "08:00:00",
            "jam_selesai": "09:40:00",
            "ruangan_kode": r_30.kode,
            "dosen_id": d2.id,
        },
    )
    assert res_cap_409.status_code == 409
    assert "kapasitas" in res_cap_409.json()["detail"].lower()

    # POST referensi hilang -> 404
    assert (
        client.post(
            "/api/jadwal",
            json={
                "kelas_id": k1.id,
                "hari": 2,
                "jam_mulai": "08:00:00",
                "jam_selesai": "09:40:00",
                "ruangan_kode": "TIDAKADA",
                "dosen_id": d1.id,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/jadwal",
            json={
                "kelas_id": 9999,
                "hari": 2,
                "jam_mulai": "08:00:00",
                "jam_selesai": "09:40:00",
                "ruangan_kode": r_40.kode,
                "dosen_id": d1.id,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/jadwal",
            json={
                "kelas_id": k1.id,
                "hari": 2,
                "jam_mulai": "08:00:00",
                "jam_selesai": "09:40:00",
                "ruangan_kode": r_40.kode,
                "dosen_id": 9999,
            },
        ).status_code
        == 404
    )

    # POST format invalid (jam terbalik / sama / hari=7 / ruang blank) -> 422
    for bad_payload in (
        {
            "kelas_id": k1.id,
            "hari": 1,
            "jam_mulai": "10:00:00",
            "jam_selesai": "09:00:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
        {
            "kelas_id": k1.id,
            "hari": 1,
            "jam_mulai": "10:00:00",
            "jam_selesai": "10:00:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
        {
            "kelas_id": k1.id,
            "hari": 7,
            "jam_mulai": "08:00:00",
            "jam_selesai": "09:40:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
        {
            "kelas_id": k1.id,
            "hari": 1,
            "jam_mulai": "08:00:00",
            "jam_selesai": "09:40:00",
            "ruangan_kode": "   ",
            "dosen_id": d1.id,
        },
    ):
        assert client.post("/api/jadwal", json=bad_payload).status_code == 422

    # Rute PMB/KRS tetap mengembalikan 400 untuk error validasi Pydantic (kompatibilitas ADR-003)
    assert client.post("/api/pmb/register", json={}).status_code == 400

    # PUT menggeser jadwal kedua 15 menit (09:40-11:20 -> 09:55-11:35) tanpa bentrok diri sendiri -> 200
    res_put_ok = client.put(
        f"/api/jadwal/{id_sambung}",
        json={
            "kelas_id": k1.id,
            "hari": 1,
            "jam_mulai": "09:55:00",
            "jam_selesai": "11:35:00",
            "ruangan_kode": r_40.kode,
            "dosen_id": d1.id,
        },
    )
    assert res_put_ok.status_code == 200
    assert res_put_ok.json()["jam_mulai"] == "09:55:00"

    # PUT menggeser menabrak jadwal pertama -> 409, id hilang -> 404, jam terbalik -> 422
    assert (
        client.put(
            f"/api/jadwal/{id_sambung}",
            json={
                "kelas_id": k1.id,
                "hari": 1,
                "jam_mulai": "09:00:00",
                "jam_selesai": "11:00:00",
                "ruangan_kode": r_40.kode,
                "dosen_id": d1.id,
            },
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/jadwal/9999",
            json={
                "kelas_id": k1.id,
                "hari": 1,
                "jam_mulai": "13:00:00",
                "jam_selesai": "14:40:00",
                "ruangan_kode": r_40.kode,
                "dosen_id": d1.id,
            },
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/jadwal/{id_sambung}",
            json={
                "kelas_id": k1.id,
                "hari": 1,
                "jam_mulai": "11:00:00",
                "jam_selesai": "09:00:00",
                "ruangan_kode": r_40.kode,
                "dosen_id": d1.id,
            },
        ).status_code
        == 422
    )

    # GET conflicts bersih -> []
    res_conflicts = client.get("/api/jadwal/conflicts")
    assert res_conflicts.status_code == 200
    assert res_conflicts.json() == []

    # DELETE -> 204, lalu DELETE lagi -> 404
    res_del = client.delete(f"/api/jadwal/{id_sambung}")
    assert res_del.status_code == 204
    assert res_del.content == b""
    assert client.delete(f"/api/jadwal/{id_sambung}").status_code == 404

    # Verifikasi OpenAPI mempublikasikan semua endpoint /api/jadwal/*
    openapi = client.get("/openapi.json").json()
    assert "/api/jadwal" in openapi["paths"]
    assert "/api/jadwal/{jadwal_id}" in openapi["paths"]
    assert "/api/jadwal/conflicts" in openapi["paths"]
    assert "409" in openapi["paths"]["/api/jadwal"]["post"]["responses"]
    assert "422" in openapi["paths"]["/api/jadwal"]["post"]["responses"]


def test_scheduling_concurrency_dua_admin_satu_ruangan(tmp_path: Path) -> None:
    """Dua thread admin membuat jadwal bentrok bersamaan: tepat 1 sukses, 1 ditolak, 0 bentrok."""
    db_file = tmp_path / "jadwal_race.db"
    file_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    attach_sqlite_fk_pragma(file_engine)
    LocalSession = sessionmaker(autocommit=False, autoflush=False, bind=file_engine)
    Base.metadata.create_all(bind=file_engine)

    try:
        with LocalSession() as setup_db:
            seed_data(setup_db)
            k1, k2, r_40, _, d1, d2 = _siapkan_data_dasar(setup_db)
            payload_1 = JadwalIn(
                kelas_id=k1.id,
                hari=1,
                jam_mulai=time(8, 0),
                jam_selesai=time(9, 40),
                ruangan_kode=r_40.kode,
                dosen_id=d1.id,
            )
            payload_2 = JadwalIn(
                kelas_id=k2.id,
                hari=1,
                jam_mulai=time(8, 30),
                jam_selesai=time(10, 0),
                ruangan_kode=r_40.kode,
                dosen_id=d2.id,
            )

        barrier = Barrier(2)

        def _create_worker(data: JadwalIn) -> str:
            with LocalSession() as db:
                barrier.wait()
                try:
                    SchedulingService(db).create(data)
                    return "ok"
                except ScheduleConflictError:
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_create_worker, payload_1)
            f2 = pool.submit(_create_worker, payload_2)
            hasil = sorted([f1.result(), f2.result()])

        assert hasil == ["conflict", "ok"]
        with LocalSession() as verify_db:
            assert verify_db.query(Jadwal).count() == 1
            assert SchedulingService(verify_db).list_conflicts() == []
    finally:
        file_engine.dispose()


def test_seed_jadwal_idempotent_dan_endpoint_conflicts(
    client: TestClient, db_session: Session
) -> None:
    """Uji seed_jadwal_data idempotent (2x jalan) & endpoint GET /api/jadwal/conflicts."""
    seed_jadwal_data(db_session)
    jumlah_awal = (
        db_session.query(Ruangan).count(),
        db_session.query(Dosen).count(),
        db_session.query(Kelas).count(),
        db_session.query(Jadwal).count(),
    )
    seed_jadwal_data(db_session)
    jumlah_kedua = (
        db_session.query(Ruangan).count(),
        db_session.query(Dosen).count(),
        db_session.query(Kelas).count(),
        db_session.query(Jadwal).count(),
    )

    assert jumlah_awal == jumlah_kedua
    assert jumlah_awal[0] >= 10
    assert jumlah_awal[1] >= 15
    assert jumlah_awal[2] == 24
    assert jumlah_awal[3] >= 40

    res = client.get("/api/jadwal/conflicts")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 6
    tipe_count = {
        "room_conflict": sum(1 for item in data if item["type"] == "room_conflict"),
        "lecturer_conflict": sum(1 for item in data if item["type"] == "lecturer_conflict"),
    }
    assert tipe_count == {"room_conflict": 3, "lecturer_conflict": 3}

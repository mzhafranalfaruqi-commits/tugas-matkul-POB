"""Unit, integration, security (JWT/replay/rate limit/geofence), Excel export, GradeService, & AI tests Modul Presensi."""

from collections.abc import Generator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.services.presensi_service as presensi_mod
from app.domain.presensi import (
    RekordPresensiInput,
    analisis_pola_presensi,
    hitung_jarak_haversine_meter,
    normalisasi_hari,
    tentukan_status_kehadiran,
)
from app.models import (
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
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
    SkalaNilai,
    StatusPMB,
)
from app.services.exceptions import (
    AttendanceDuplicateError,
    AttendanceExpiredError,
    AttendanceForbiddenError,
    AttendanceNotFoundError,
    AttendanceRateLimitError,
    AttendanceValidationError,
)
from app.services.presensi_service import (
    WIB,
    PresensiService,
    SlidingWindowRateLimiter,
    decode_attendance_token,
    get_scan_rate_limiter,
)
from seed import (
    seed_data,
    seed_jadwal_data,
    seed_keuangan_data,
    seed_krs_data,
    seed_nilai_demo_data,
    seed_presensi_data,
    seed_transkrip_demo_data,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Generator[None, None, None]:
    """Mengosongkan bucket rate limiter antar test agar pengujian terisolasi."""
    limiter = get_scan_rate_limiter()
    limiter.reset()
    yield
    limiter.reset()


def _siapkan_kelas_presensi(
    db: Session,
) -> tuple[Dosen, Dosen, Kelas, Jadwal, Jadwal, str, str]:
    """Menyiapkan 2 dosen, 2 kelas (Senin 08:00 & Selasa 10:00), dan 2 mahasiswa."""
    for huruf, bobot, lulus in (
        ("A", Decimal("4.00"), True),
        ("B", Decimal("3.00"), True),
        ("C", Decimal("2.00"), True),
        ("D", Decimal("1.00"), False),
        ("E", Decimal("0.00"), False),
    ):
        if db.get(SkalaNilai, huruf) is None:
            db.add(SkalaNilai(huruf=huruf, bobot=bobot, lulus=lulus))

    mk1 = MataKuliah(
        kode_mk="IF101",
        nama="Algoritma",
        sks=3,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
    )
    mk2 = MataKuliah(
        kode_mk="IF201",
        nama="Basis Data",
        sks=3,
        hari=2,
        jam_mulai=time(10, 0),
        jam_selesai=time(11, 40),
    )
    r1 = Ruangan(kode="A101", kapasitas=40)
    r2 = Ruangan(kode="A102", kapasitas=40)
    d1 = Dosen(nidn="0012018501", nama="Dr. Andi Pengampu")
    d2 = Dosen(nidn="0012018502", nama="Dr. Citra Pengampu")
    db.add_all([mk1, mk2, r1, r2, d1, d2])
    db.flush()

    k1 = Kelas(kode_mk="IF101", nama="A", kuota=40, semester="20251")
    k2 = Kelas(kode_mk="IF201", nama="A", kuota=40, semester="20251")
    db.add_all([k1, k2])
    db.flush()

    j1 = Jadwal(
        kelas_id=k1.id,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
        ruangan_kode=r1.kode,
        dosen_id=d1.id,
    )
    j2 = Jadwal(
        kelas_id=k2.id,
        hari=2,
        jam_mulai=time(10, 0),
        jam_selesai=time(11, 40),
        ruangan_kode=r2.kode,
        dosen_id=d2.id,
    )
    db.add_all([j1, j2])

    prodi = db.execute(select(ProgramStudi).limit(1)).scalar_one()
    jalur = db.execute(select(JalurMasuk).limit(1)).scalar_one()
    nim_peserta = "2025001-0501"
    nim_orang_lain = "2025001-0502"
    for idx, (nim, nama) in enumerate(
        [(nim_peserta, "Andi Terdaftar"), (nim_orang_lain, "Budi Kelas Lain")],
        start=1,
    ):
        db.add(
            CalonMahasiswa(
                nama_lengkap=nama,
                email=f"presensi{idx}@example.com",
                phone="081234567890",
                tanggal_lahir=date(2006, 2, 1),
                alamat="Bandung",
                program_studi_id=prodi.id,
                jalur_masuk_id=jalur.id,
                status=StatusPMB.approved,
                nim=nim,
            )
        )
    db.flush()

    # nim_peserta hanya terdaftar di k1 (IF101-A); nim_orang_lain hanya terdaftar di k2 (IF201-A).
    db.add_all(
        [
            KRS(
                nim=nim_peserta,
                semester="20251",
                status=KRSStatus.APPROVED,
                dosen_pa_id=101,
                details=[KRSDetail(kode_mk="IF101", kelas_id=k1.id)],
            ),
            KRS(
                nim=nim_orang_lain,
                semester="20251",
                status=KRSStatus.APPROVED,
                dosen_pa_id=101,
                details=[KRSDetail(kode_mk="IF201", kelas_id=k2.id)],
            ),
        ]
    )
    db.commit()
    return d1, d2, k1, j1, j2, nim_peserta, nim_orang_lain


def test_domain_murni_presensi_helpers_dan_ai_analyzer() -> None:
    """Uji helper waktu scan, Haversine, normalisasi hari, dan analisis pola presensi."""
    assert tentukan_status_kehadiran(0.0) == "hadir"
    assert tentukan_status_kehadiran(15.0) == "hadir"
    assert tentukan_status_kehadiran(15.1) == "terlambat"
    assert tentukan_status_kehadiran(30.0) == "terlambat"

    for invalid in (-0.1, 30.1, float("nan")):
        with pytest.raises(ValueError):
            tentukan_status_kehadiran(invalid)

    assert normalisasi_hari(1) == 1
    assert normalisasi_hari("Senin") == 1
    assert normalisasi_hari("monday") == 1
    with pytest.raises(ValueError):
        normalisasi_hari(True)
    with pytest.raises(ValueError):
        normalisasi_hari(8)
    with pytest.raises(ValueError):
        normalisasi_hari("funday")

    # Jarak ITB (~111m per 0.001 derajat lintang)
    jarak = hitung_jarak_haversine_meter(-6.8915, 107.6107, -6.8924, 107.6107)
    assert 95.0 <= jarak <= 105.0

    # Analisis pola: Mahasiswa X sering absent Senin pagi + Kelas Y jam 07:00 absen rate 40%+
    rekords = [
        # Mahasiswa X: 3 alpha dari 4 sesi Senin 07:00 (hadir 1/4 = 25% < 75%)
        RekordPresensiInput("2025001-0001", "IF101-A", 1, time(7, 0), "hadir", "Mahasiswa X"),
        RekordPresensiInput("2025001-0001", "IF101-A", 1, time(7, 0), "alpha", "Mahasiswa X"),
        RekordPresensiInput("2025001-0001", "IF101-A", 1, time(7, 0), "alpha", "Mahasiswa X"),
        RekordPresensiInput("2025001-0001", "IF101-A", 1, time(7, 0), "alpha", "Mahasiswa X"),
        # Mahasiswa Y: hadir semua (4/4 = 100%)
        RekordPresensiInput("2025001-0002", "IF101-A", 1, time(7, 0), "hadir", "Mahasiswa Y"),
        RekordPresensiInput("2025001-0002", "IF101-A", 1, time(7, 0), "hadir", "Mahasiswa Y"),
        RekordPresensiInput("2025001-0002", "IF101-A", 1, time(7, 0), "hadir", "Mahasiswa Y"),
        RekordPresensiInput("2025001-0002", "IF101-A", 1, time(7, 0), "hadir", "Mahasiswa Y"),
        # Mahasiswa Z: hanya ikut 2 sesi dan alpha 1x -> 50% (warning tanpa pola >=2 hari sama)
        RekordPresensiInput("2025001-0003", "IF101-A", 1, time(7, 0), "hadir", "Mahasiswa Z"),
        RekordPresensiInput("2025001-0003", "IF101-A", 1, time(7, 0), "alpha", "Mahasiswa Z"),
    ]
    hasil = analisis_pola_presensi(rekords)
    assert len(hasil.warning_mahasiswa) == 2
    assert any("2 mahasiswa berisiko" in ins for ins in hasil.insights)
    assert any("sering absent hari Senin pagi" in act for act in hasil.actions)
    assert any("IF101-A di jam 07:00 absen rate 40.00%" in act for act in hasil.actions)


def test_presensi_db_constraints(db_session: Session) -> None:
    """Verifikasi constraint CHECK, UNIQUE, dan FK pada tabel presensi."""
    d1, _d2, _k1, j1, _j2, nim1, _nim2 = _siapkan_kelas_presensi(db_session)
    now_utc = datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc)

    # 1. CHECK valid_minutes 1..30
    with pytest.raises(IntegrityError):
        db_session.add(
            AttendanceSession(
                jadwal_id=j1.id,
                pertemuan_ke=1,
                tanggal=date(2026, 11, 23),
                dosen_id=d1.id,
                active_jti="JTI-BAD-MIN",
                generated_at=now_utc,
                expires_at=now_utc + timedelta(minutes=15),
                valid_minutes=45,
            )
        )
        db_session.commit()
    db_session.rollback()

    # 2. UNIQUE (jadwal_id, tanggal) & UNIQUE (session_id, nim)
    s1 = AttendanceSession(
        jadwal_id=j1.id,
        pertemuan_ke=1,
        tanggal=date(2026, 11, 23),
        dosen_id=d1.id,
        active_jti="JTI-UNIQ-1",
        generated_at=now_utc,
        expires_at=now_utc + timedelta(minutes=15),
        valid_minutes=15,
    )
    db_session.add(s1)
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.add(
            AttendanceSession(
                jadwal_id=j1.id,
                pertemuan_ke=2,
                tanggal=date(2026, 11, 23),
                dosen_id=d1.id,
                active_jti="JTI-UNIQ-2",
                generated_at=now_utc,
                expires_at=now_utc + timedelta(minutes=15),
                valid_minutes=15,
            )
        )
        db_session.commit()
    db_session.rollback()

    db_session.add(
        AttendanceRecord(
            session_id=s1.id,
            nim=nim1,
            status=AttendanceStatus.hadir,
            scanned_at=now_utc,
        )
    )
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.add(
            AttendanceRecord(
                session_id=s1.id,
                nim=nim1,
                status=AttendanceStatus.terlambat,
                scanned_at=now_utc,
            )
        )
        db_session.commit()
    db_session.rollback()


def test_qr_generation_jwt_rotasi_anti_replay_dan_validasi_scan(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uji penuh QR PNG/JWT 15 menit, rotasi token, expired, bukan peserta 403, duplikat 409, geofence, & rate limit 429."""
    d1, d2, k1, j1, _j2, nim_peserta, nim_orang_lain = _siapkan_kelas_presensi(
        db_session
    )

    # Senin 2026-11-23 pukul 08:05 WIB = 01:05 UTC
    senin_0805_utc = datetime(2026, 11, 23, 1, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(
        presensi_mod,
        "_ensure_utc",
        lambda dt=None: senin_0805_utc
        if dt is None
        else (
            dt.replace(tzinfo=WIB).astimezone(timezone.utc)
            if dt.tzinfo is None
            else dt.astimezone(timezone.utc)
        ),
    )

    # 1. Dosen salah mengakses QR jadwal orang lain -> 403
    res_403_dosen = client.get(
        f"/attendance/qr/{j1.id}", headers={"X-Dosen-Id": str(d2.id)}
    )
    assert res_403_dosen.status_code == 403
    assert client.get("/attendance/qr/999999").status_code == 404

    # 2. Generate QR valid PNG melalui GET /attendance/qr/{schedule_id}
    res_qr = client.get(
        f"/attendance/qr/{j1.id}", headers={"X-Dosen-Id": str(d1.id)}
    )
    assert res_qr.status_code == 200
    assert res_qr.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(res_qr.content))
    assert img.format == "PNG"
    assert img.size[0] > 100

    token_lama = res_qr.headers["x-attendance-token"]
    payload = decode_attendance_token(token_lama, current_time=senin_0805_utc)
    assert payload["schedule_id"] == j1.id
    assert int(payload["exp"]) - int(payload["iat"]) == 15 * 60

    # 3. Rotasi QR mengganti jti sehingga token lama otomatis tertolak 401 (anti-replay)
    res_qr_rot = client.post(
        f"/api/presensi/qr/{j1.id}",
        json={
            "valid_minutes": 15,
            "latitude": -6.8915,
            "longitude": 107.6107,
            "max_radius_meters": 150,
        },
        headers={"X-Dosen-Id": str(d1.id)},
    )
    assert res_qr_rot.status_code == 200
    token_baru = res_qr_rot.json()["token"]
    assert token_baru != token_lama

    scan_replay = client.post(
        "/attendance/scan",
        json={
            "token": token_lama,
            "nim": nim_peserta,
            "latitude": -6.8915,
            "longitude": 107.6107,
        },
    )
    assert scan_replay.status_code == 401

    # 4. Mahasiswa tidak terdaftar pada kelas tidak bisa scan QR kelas orang lain -> 403
    scan_other = client.post(
        "/attendance/scan",
        json={
            "token": token_baru,
            "nim": nim_orang_lain,
            "latitude": -6.8915,
            "longitude": 107.6107,
        },
    )
    assert scan_other.status_code == 403

    # 5. Geofence: tanpa koordinat -> 400; di luar radius -> 403
    scan_no_gps = client.post(
        "/attendance/scan", json={"token": token_baru, "nim": nim_peserta}
    )
    assert scan_no_gps.status_code == 400

    scan_far = client.post(
        "/attendance/scan",
        json={
            "token": token_baru,
            "nim": nim_peserta,
            "latitude": -6.9200,
            "longitude": 107.6107,
        },
    )
    assert scan_far.status_code == 403

    # 6. Scan valid di dalam radius pada menit ke-5 -> 200 'hadir'
    scan_ok = client.post(
        "/attendance/scan",
        json={
            "token": token_baru,
            "nim": nim_peserta,
            "latitude": -6.8918,
            "longitude": 107.6107,
        },
    )
    assert scan_ok.status_code == 200
    body_ok = scan_ok.json()
    assert body_ok["success"] is True
    assert body_ok["status"] == "hadir"
    assert body_ok["distance_meters"] < 150.0

    # 7. Scan ulang sesi yang sama -> 409 Conflict
    scan_dup = client.post(
        "/attendance/scan",
        json={
            "token": token_baru,
            "nim": nim_peserta,
            "latitude": -6.8918,
            "longitude": 107.6107,
        },
    )
    assert scan_dup.status_code == 409

    # 8. Uji keterlambatan (menit 18 -> 'terlambat'), >30 menit -> 400, hari salah -> 400, & expired -> 401
    svc = PresensiService(db_session, rate_limiter=SlidingWindowRateLimiter(100, 60.0))
    selasa_tgl = date(2026, 11, 24)
    # Buat sesi pertemuan ke-2 (Senin minggu depan 2026-11-30) pukul 08:10 WIB
    senin_depan_0810 = datetime(2026, 11, 30, 8, 10, tzinfo=WIB)
    qr_sesi2 = svc.create_or_rotate_qr(
        j1.id, valid_minutes=15, tanggal=date(2026, 11, 30), now=senin_depan_0810
    )

    # Expired sesudah menit ke-25 (15 menit setelah 08:10 -> 08:25)
    with pytest.raises(AttendanceExpiredError):
        svc.scan_qr(
            qr_sesi2.token,
            nim_peserta,
            now=datetime(2026, 11, 30, 8, 26, tzinfo=WIB),
        )

    # Hari salah (Selasa memakai jadwal Senin) -> AttendanceValidationError
    qr_selasa_palsu = svc.create_or_rotate_qr(
        j1.id,
        valid_minutes=15,
        tanggal=selasa_tgl,
        now=datetime(2026, 11, 24, 8, 10, tzinfo=WIB),
    )
    with pytest.raises(AttendanceValidationError):
        svc.scan_qr(
            qr_selasa_palsu.token,
            nim_peserta,
            now=datetime(2026, 11, 24, 8, 12, tzinfo=WIB),
        )

    # Scan pukul 08:20 WIB (menit 20 dari 08:00, sebelum exp 08:25) -> 'terlambat'
    scan_telat = svc.scan_qr(
        qr_sesi2.token,
        nim_peserta,
        now=datetime(2026, 11, 30, 8, 20, tzinfo=WIB),
    )
    assert scan_telat.status == "terlambat"

    # Pertemuan ke-3 lewat batas 30 menit (08:35 WIB dengan QR masih valid dibuat 08:25) -> 400
    qr_sesi3 = svc.create_or_rotate_qr(
        j1.id,
        valid_minutes=15,
        tanggal=date(2026, 12, 7),
        now=datetime(2026, 12, 7, 8, 25, tzinfo=WIB),
    )
    with pytest.raises(AttendanceValidationError):
        svc.scan_qr(
            qr_sesi3.token,
            nim_peserta,
            now=datetime(2026, 12, 7, 8, 35, tzinfo=WIB),
        )

    # 9. Rate limiting (5 req/menit) -> request ke-6 mengembalikan 429 Too Many Requests
    limiter = get_scan_rate_limiter()
    limiter.reset()
    for _ in range(5):
        r = client.post(
            "/api/presensi/scan",
            json={"token": token_baru, "nim": "2025001-9999"},
        )
        assert r.status_code == 404
    r_429 = client.post(
        "/api/presensi/scan",
        json={"token": token_baru, "nim": "2025001-9999"},
    )
    assert r_429.status_code == 429
    with pytest.raises(AttendanceNotFoundError):
        PresensiService(db_session).get_kelas_report(999999)
    with pytest.raises(AttendanceNotFoundError):
        PresensiService(db_session).get_mahasiswa_report("0000000-0000")


def test_integrasi_db_presensi_adapter_dengan_grade_service_minggu_9(
    client: TestClient, db_session: Session
) -> None:
    """Integrasi nyata PresensiPort (Minggu 9): <75% presensi DB ditolak input nilai, >=75% diizinkan."""
    d1, _d2, k1, j1, _j2, nim_peserta, _nim_lain = _siapkan_kelas_presensi(db_session)
    svc = PresensiService(db_session, rate_limiter=SlidingWindowRateLimiter(100, 60.0))

    # Buat 3 sesi: hadir di sesi 1 & 2, absen di sesi 3 -> 2/3 = 66.67% (< 75%)
    for week in range(3):
        tgl = date(2026, 9, 7) + timedelta(days=7 * week)
        qr = svc.create_or_rotate_qr(
            j1.id, tanggal=tgl, now=datetime.combine(tgl, time(8, 2), tzinfo=WIB)
        )
        if week < 2:
            svc.scan_qr(
                qr.token,
                nim_peserta,
                now=datetime.combine(tgl, time(8, 5), tzinfo=WIB),
            )

    # Tanpa override PresensiStub, DBPresensiAdapter membaca DB nyata: 66.67% -> 400 ditolak!
    res_block = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim_peserta}",
        json={"huruf": "A"},
        headers={"X-Dosen-Id": str(d1.id)},
    )
    assert res_block.status_code == 400
    assert "75%" in res_block.json()["detail"]

    # Tambah sesi ke-4 dan mahasiswa hadir -> 3/4 = 75.00% -> input nilai berhasil 200 OK!
    tgl4 = date(2026, 9, 28)
    qr4 = svc.create_or_rotate_qr(
        j1.id, tanggal=tgl4, now=datetime.combine(tgl4, time(8, 1), tzinfo=WIB)
    )
    svc.scan_qr(
        qr4.token, nim_peserta, now=datetime.combine(tgl4, time(8, 4), tzinfo=WIB)
    )

    res_ok = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim_peserta}",
        json={"huruf": "A"},
        headers={"X-Dosen-Id": str(d1.id)},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["huruf"] == "A"


def test_laporan_excel_ai_insights_dashboard_dan_seed_idempotent(
    client: TestClient, db_session: Session
) -> None:
    """Uji report per mahasiswa/kelas, ekspor Excel openpyxl, AI Insights JSON & live DB, & seed 2x."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    seed_transkrip_demo_data(db_session)
    seed_keuangan_data(db_session)
    seed_presensi_data(db_session)

    # Idempotency seed_presensi_data
    cnt_sess_1 = db_session.query(AttendanceSession).count()
    cnt_rec_1 = db_session.query(AttendanceRecord).count()
    seed_presensi_data(db_session)
    assert db_session.query(AttendanceSession).count() == cnt_sess_1 == 22
    assert db_session.query(AttendanceRecord).count() == cnt_rec_1 == 66

    # Dashboard HTML & daftar jadwal
    res_dash = client.get("/api/presensi/dashboard")
    assert res_dash.status_code == 200
    assert "Presensi QR Code" in res_dash.text
    res_sched = client.get("/api/presensi/schedules")
    assert res_sched.status_code == 200
    assert len(res_sched.json()) == 44

    # Report per mahasiswa (Budi: IF204-A 70%, IF102-A 33.33%, IF201-B 100%)
    res_budi = client.get("/api/presensi/mahasiswa/2025001-0001/report")
    assert res_budi.status_code == 200
    by_mk = {m["kode_mk"]: m for m in res_budi.json()["mata_kuliah"]}
    assert by_mk["IF204"]["persentase"] == "70.00"
    assert by_mk["IF204"]["warning"] is True
    assert by_mk["IF102"]["persentase"] == "33.33"
    assert by_mk["IF102"]["warning"] is True
    assert by_mk["IF201"]["persentase"] == "100.00"
    assert by_mk["IF201"]["warning"] is False

    # Report kelas IF102-A & Excel export verification via openpyxl
    k_if102 = db_session.execute(
        select(Kelas).where(
            Kelas.kode_mk == "IF102", Kelas.nama == "A", Kelas.semester == "20251"
        )
    ).scalar_one()
    res_k = client.get(f"/api/presensi/kelas/{k_if102.id}/report")
    assert res_k.status_code == 200
    assert len(res_k.json()["mahasiswa_berisiko"]) == 3

    res_xlsx = client.get(f"/api/presensi/kelas/{k_if102.id}/export.xlsx")
    assert res_xlsx.status_code == 200
    assert (
        res_xlsx.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    wb = load_workbook(io.BytesIO(res_xlsx.content))
    assert wb.sheetnames == ["Rekap Presensi", "Log Kehadiran"]
    ws_rekap = wb["Rekap Presensi"]
    assert "WARNING (<75%)" in [
        ws_rekap.cell(row=r, column=10).value for r in range(6, 9)
    ]

    # Live AI Attendance Insights dari DB seed
    res_ai_live = client.get("/api/presensi/ai-insights")
    assert res_ai_live.status_code == 200
    live = res_ai_live.json()
    assert live["summary"]["jumlah_warning"] >= 3
    assert any("Senin pagi" in act for act in live["actions"])
    assert any("IF102-A di jam 08:00" in act for act in live["actions"])

    # AI Attendance Analyzer endpoint POST dengan JSON array eksternal
    res_ai_custom = client.post(
        "/api/presensi/ai-insights/analyze",
        json={
            "attendance_records": [
                {"nim": "2025001-0001", "nama": "Mahasiswa X", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "hadir"},
                {"nim": "2025001-0001", "nama": "Mahasiswa X", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "alpha"},
                {"nim": "2025001-0001", "nama": "Mahasiswa X", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "alpha"},
                {"nim": "2025001-0001", "nama": "Mahasiswa X", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "alpha"},
                {"nim": "2025001-0002", "nama": "Mahasiswa Y", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "hadir"},
                {"nim": "2025001-0002", "nama": "Mahasiswa Y", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "hadir"},
                {"nim": "2025001-0002", "nama": "Mahasiswa Y", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "hadir"},
                {"nim": "2025001-0002", "nama": "Mahasiswa Y", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "hadir"},
                {"nim": "2025001-0003", "nama": "Mahasiswa Z", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "hadir"},
                {"nim": "2025001-0003", "nama": "Mahasiswa Z", "kelas": "Y", "hari": "Senin", "jam_mulai": "07:00", "status": "alpha"},
            ]
        },
    )
    assert res_ai_custom.status_code == 200
    custom = res_ai_custom.json()
    assert any("Y di jam 07:00 absen rate 40.00%" in a for a in custom["actions"])

    # Payload JSON tidak lengkap -> 400
    bad_ai = client.post(
        "/api/presensi/ai-insights/analyze",
        json={"attendance_records": [{"nim": "2025001-0001"}]},
    )
    assert bad_ai.status_code == 400

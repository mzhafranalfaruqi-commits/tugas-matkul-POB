"""Integration, security guard, atomicity, audit view, SQL CTE, & UI tests Modul Nilai."""

from datetime import date, time
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    CalonMahasiswa,
    Dosen,
    GradeHistory,
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
from app.services.gpa_calculator import GPACalculator, NilaiRepo
from app.services.grade_service import (
    GradeService,
    PresensiStub,
    get_presensi_port,
    is_pengampu,
)
from seed import (
    seed_data,
    seed_jadwal_data,
    seed_krs_data,
    seed_nilai_demo_data,
)


def _siapkan_nilai_fixture(
    db: Session,
) -> tuple[Dosen, Dosen, Kelas, Kelas, str, str, str]:
    """Menyiapkan skala nilai, 2 MK, 2 kelas + jadwal pengampu berbeda, & 3 mahasiswa."""
    for h, b, lulus in (
        ("A", Decimal("4.00"), True),
        ("B", Decimal("3.00"), True),
        ("C", Decimal("2.00"), True),
        ("D", Decimal("1.00"), False),
        ("E", Decimal("0.00"), False),
    ):
        if db.get(SkalaNilai, h) is None:
            db.add(SkalaNilai(huruf=h, bobot=b, lulus=lulus))

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
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
    )
    r1 = Ruangan(kode="A101", kapasitas=40)
    r2 = Ruangan(kode="A102", kapasitas=40)
    d1 = Dosen(nidn="0007018501", nama="Dr. Andi Pengampu")
    d2 = Dosen(nidn="0007018502", nama="Dr. Budi Lain")
    db.add_all([mk1, mk2, r1, r2, d1, d2])
    db.flush()

    k1 = Kelas(kode_mk="IF101", nama="A", kuota=40, semester="20251")
    k2 = Kelas(kode_mk="IF201", nama="A", kuota=40, semester="20251")
    db.add_all([k1, k2])
    db.flush()

    db.add_all(
        [
            Jadwal(
                kelas_id=k1.id,
                hari=1,
                jam_mulai=time(8, 0),
                jam_selesai=time(9, 40),
                ruangan_kode=r1.kode,
                dosen_id=d1.id,
            ),
            Jadwal(
                kelas_id=k2.id,
                hari=2,
                jam_mulai=time(8, 0),
                jam_selesai=time(9, 40),
                ruangan_kode=r2.kode,
                dosen_id=d2.id,
            ),
        ]
    )

    prodi = db.execute(select(ProgramStudi).limit(1)).scalar_one()
    jalur = db.execute(select(JalurMasuk).limit(1)).scalar_one()
    nims = ("2025001-0101", "2025001-0102", "2025001-0103")
    for idx, nim in enumerate(nims, start=1):
        db.add(
            CalonMahasiswa(
                nama_lengkap=f"Dummy Nilai {idx}",
                email=f"nilai{idx}@example.com",
                phone="081234567890",
                tanggal_lahir=date(2006, 1, 1),
                alamat="Bandung",
                program_studi_id=prodi.id,
                jalur_masuk_id=jalur.id,
                status=StatusPMB.approved,
                nim=nim,
            )
        )
        db.flush()
        db.add(
            KRS(
                nim=nim,
                semester="20251",
                status=KRSStatus.APPROVED,
                dosen_pa_id=101,
                details=[KRSDetail(kode_mk="IF101", kelas_id=k1.id)],
            )
        )

    db.commit()
    return d1, d2, k1, k2, nims[0], nims[1], nims[2]


def test_otorisasi_pengampu_401_403_dan_404(
    client: TestClient, db_session: Session
) -> None:
    """Hanya dosen pengampu kelas yang sah boleh melihat daftar peserta dan menginput nilai."""
    d1, d2, k1, k2, nim1, _, _ = _siapkan_nilai_fixture(db_session)

    assert is_pengampu(db_session, d1.id, k1.id) is True
    assert is_pengampu(db_session, d2.id, k1.id) is False
    assert is_pengampu(db_session, d2.id, k2.id) is True

    # Tanpa header X-Dosen-Id -> 401
    assert (
        client.put(
            f"/api/kelas/{k1.id}/nilai/{nim1}",
            json={"huruf": "A"},
        ).status_code
        == 401
    )

    # Dosen lain (bukan pengampu k1) -> 403 Forbidden
    res_403 = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim1}",
        headers={"X-Dosen-Id": str(d2.id)},
        json={"huruf": "A"},
    )
    assert res_403.status_code == 403
    assert (
        client.get(
            f"/api/kelas/{k1.id}/peserta",
            headers={"X-Dosen-Id": str(d2.id)},
        ).status_code
        == 403
    )

    # Kelas tidak ada -> 404; NIM tidak terdaftar di kelas k2 -> 404
    assert (
        client.get(
            "/api/kelas/9999/peserta",
            headers={"X-Dosen-Id": str(d1.id)},
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/kelas/{k2.id}/nilai/{nim1}",
            headers={"X-Dosen-Id": str(d2.id)},
            json={"huruf": "A"},
        ).status_code
        == 404
    )


def test_penjaga_presensi_batas_75_dan_validasi_huruf_422(
    client: TestClient, db_session: Session
) -> None:
    """Presensi < 75% ditolak 400, tepat 75% diizinkan, huruf invalid 422 (PMB tetap 400)."""
    d1, _, k1, _, nim1, nim2, nim3 = _siapkan_nilai_fixture(db_session)

    stub = PresensiStub(
        {
            (nim1, k1.id): Decimal("74.99"),
            (nim2, k1.id): Decimal("75"),
            (nim3, k1.id): Decimal("70"),
        }
    )
    app.dependency_overrides[get_presensi_port] = lambda: stub

    # 74.99% dan 70% ditolak 400
    for nim_gagal in (nim1, nim3):
        res_400 = client.put(
            f"/api/kelas/{k1.id}/nilai/{nim_gagal}",
            headers={"X-Dosen-Id": str(d1.id)},
            json={"huruf": "B"},
        )
        assert res_400.status_code == 400
        assert "75%" in res_400.json()["detail"]

    # Tepat 75% masih boleh!
    res_75 = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim2}",
        headers={"X-Dosen-Id": str(d1.id)},
        json={"huruf": "A"},
    )
    assert res_75.status_code == 200
    assert res_75.json() == {"nim": nim2, "kode_mk": "IF101", "huruf": "A"}

    # Huruf tidak valid pada endpoint nilai -> 422, sementara PMB tetap 400 (ADR-003)
    for bad in ("A+", "a", "F", "AB"):
        assert (
            client.put(
                f"/api/kelas/{k1.id}/nilai/{nim2}",
                headers={"X-Dosen-Id": str(d1.id)},
                json={"huruf": bad},
            ).status_code
            == 422
        )
    assert client.post("/api/pmb/register", json={}).status_code == 400


def test_input_idempoten_edit_wajib_alasan_dan_audit_view(
    client: TestClient, db_session: Session
) -> None:
    """Uji input awal, PUT idempoten, edit tanpa alasan 400, edit dengan alasan + v_riwayat_nilai."""
    d1, _, k1, _, nim1, _, _ = _siapkan_nilai_fixture(db_session)
    app.dependency_overrides[get_presensi_port] = lambda: PresensiStub(default=Decimal("100"))

    # Input pertama (alasan boleh kosong) -> old_value=None
    res1 = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim1}",
        headers={"X-Dosen-Id": str(d1.id)},
        json={"huruf": "B"},
    )
    assert res1.status_code == 200
    assert db_session.query(GradeHistory).count() == 1

    # PUT huruf sama berulang (idempoten) -> tidak menambah baris grade_history
    res_idem = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim1}",
        headers={"X-Dosen-Id": str(d1.id)},
        json={"huruf": "B"},
    )
    assert res_idem.status_code == 200
    assert db_session.query(GradeHistory).count() == 1

    # Edit nilai tanpa alasan atau hanya spasi -> 400
    for alasan_kosong in (None, "", "   "):
        res_bad = client.put(
            f"/api/kelas/{k1.id}/nilai/{nim1}",
            headers={"X-Dosen-Id": str(d1.id)},
            json={"huruf": "A", "alasan": alasan_kosong},
        )
        assert res_bad.status_code == 400
        assert "alasan" in res_bad.json()["detail"].lower()
    assert db_session.query(GradeHistory).count() == 1

    # Edit dengan alasan valid -> 200 + baris GradeHistory kedua
    res_edit = client.put(
        f"/api/kelas/{k1.id}/nilai/{nim1}",
        headers={"X-Dosen-Id": str(d1.id)},
        json={"huruf": "A", "alasan": "Koreksi rekap nilai UAS"},
    )
    assert res_edit.status_code == 200
    assert db_session.query(GradeHistory).count() == 2

    # Cek endpoint audit trail & query langsung ke view v_riwayat_nilai
    res_hist = client.get(f"/api/mahasiswa/{nim1}/nilai/riwayat")
    assert res_hist.status_code == 200
    rows = res_hist.json()
    assert len(rows) == 2
    assert rows[0]["old_value"] == "B"
    assert rows[0]["new_value"] == "A"
    assert rows[0]["pengubah"] == d1.nama
    assert rows[0]["reason"] == "Koreksi rekap nilai UAS"
    assert rows[1]["old_value"] is None
    assert rows[1]["new_value"] == "B"

    view_rows = db_session.execute(
        text("SELECT old_value, new_value, pengubah FROM v_riwayat_nilai WHERE nim = :nim ORDER BY id"),
        {"nim": nim1},
    ).all()
    assert len(view_rows) == 2
    assert tuple(view_rows[0]) == (None, "B", d1.nama)
    assert tuple(view_rows[1]) == ("B", "A", d1.nama)

    # Mahasiswa tidak ditemukan -> 404
    assert client.get("/api/mahasiswa/TIDAK-ADA/nilai/riwayat").status_code == 404


def test_atomicity_rollback_saat_commit_gagal(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jika commit gagal, perubahan nilai di krs_detail dan baris grade_history batal bersama."""
    d1, _, k1, _, nim1, _, _ = _siapkan_nilai_fixture(db_session)
    svc = GradeService(db_session, PresensiStub(default=Decimal("100")))

    def _gagal_commit() -> None:
        raise RuntimeError("Simulasi I/O disk penuh")

    monkeypatch.setattr(db_session, "commit", _gagal_commit)
    with pytest.raises(RuntimeError, match="Simulasi"):
        svc.input_nilai(d1.id, k1.id, nim1, "A", "Input awal")

    monkeypatch.undo()
    detail = db_session.execute(
        select(KRSDetail).join(KRS).where(KRS.nim == nim1, KRSDetail.kelas_id == k1.id)
    ).scalar_one()
    assert detail.nilai is None
    assert db_session.query(GradeHistory).count() == 0


def test_api_ipk_ips_auto_update_string_dan_differential_sql_cte(
    client: TestClient, db_session: Session
) -> None:
    """IPK & IPS dihitung compute-on-read sebagai string Decimal dan cocok dengan SQL CTE."""
    d1, _, k1, _, nim1, _, _ = _siapkan_nilai_fixture(db_session)

    # Tambah MK & riwayat multi-semester untuk nim1 (sama dengan contoh Rina)
    mk_if205 = MataKuliah(
        kode_mk="IF205", nama="Sistem Operasi", sks=4, hari=3,
        jam_mulai=time(8, 0), jam_selesai=time(11, 0),
    )
    mk_if208 = MataKuliah(
        kode_mk="IF208", nama="Etika Profesi", sks=2, hari=4,
        jam_mulai=time(8, 0), jam_selesai=time(10, 0),
    )
    mk_if102 = MataKuliah(
        kode_mk="IF102", nama="Struktur Data", sks=3, hari=5,
        jam_mulai=time(8, 0), jam_selesai=time(10, 30),
    )
    db_session.add_all([mk_if205, mk_if208, mk_if102])
    db_session.flush()

    db_session.add_all(
        [
            KRS(
                nim=nim1,
                semester="20241",
                status=KRSStatus.APPROVED,
                details=[
                    KRSDetail(kode_mk="IF101", nilai="E"),
                    KRSDetail(kode_mk="IF205", nilai="A"),
                    KRSDetail(kode_mk="IF208", nilai="B"),
                ],
            ),
            KRS(
                nim=nim1,
                semester="20242",
                status=KRSStatus.APPROVED,
                details=[
                    KRSDetail(kode_mk="IF101", nilai="B"),
                    KRSDetail(kode_mk="IF102", nilai="C"),
                    KRSDetail(kode_mk="IF201", nilai="D"),
                ],
            ),
        ]
    )
    db_session.commit()

    res_ipk_1 = client.get(f"/api/mahasiswa/{nim1}/ipk")
    assert res_ipk_1.status_code == 200
    assert res_ipk_1.json() == {"nim": nim1, "ipk": "3.08"}
    assert isinstance(res_ipk_1.json()["ipk"], str)

    assert client.get(f"/api/mahasiswa/{nim1}/ips/20241").json()["ips"] == "2.44"
    assert client.get(f"/api/mahasiswa/{nim1}/ips/20242").json()["ips"] == "2.00"

    # Differential check: Python == SQL Window Function CTE
    repo = NilaiRepo(db_session)
    assert GPACalculator(repo).calculate_ipk(nim1) == repo.calculate_ipk_sql(nim1) == Decimal("3.08")

    # Input nilai A untuk IF101 di semester 20251 (mengulang B -> A) -> IPK otomatis naik ke 3.33
    app.dependency_overrides[get_presensi_port] = lambda: PresensiStub(default=Decimal("100"))
    assert (
        client.put(
            f"/api/kelas/{k1.id}/nilai/{nim1}",
            headers={"X-Dosen-Id": str(d1.id)},
            json={"huruf": "A"},
        ).status_code
        == 200
    )
    res_ipk_2 = client.get(f"/api/mahasiswa/{nim1}/ipk")
    assert res_ipk_2.status_code == 200
    # (4*4 + 2*3 + 3*4 + 3*2) / 12 = 40/12 = 3.33
    assert res_ipk_2.json()["ipk"] == "3.33"
    assert GPACalculator(repo).calculate_ipk(nim1) == repo.calculate_ipk_sql(nim1) == Decimal("3.33")

    # Mahasiswa tak ditemukan -> 404
    assert client.get("/api/mahasiswa/TIDAK-ADA/ipk").status_code == 404
    assert client.get("/api/mahasiswa/TIDAK-ADA/ips/20251").status_code == 404


def test_ui_nilai_form_dan_seed_demo_minggu_9_idempotent(
    client: TestClient, db_session: Session
) -> None:
    """Seed lengkap Minggu 9 idempotent dan UI/endpoint peserta memblokir Budi (< 75%)."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)

    count_1 = (
        db_session.query(CalonMahasiswa).count(),
        db_session.query(KRS).count(),
        db_session.query(KRSDetail).count(),
        db_session.query(SkalaNilai).count(),
    )
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    count_2 = (
        db_session.query(CalonMahasiswa).count(),
        db_session.query(KRS).count(),
        db_session.query(KRSDetail).count(),
        db_session.query(SkalaNilai).count(),
    )
    assert count_1 == count_2

    # Cek IPK seed Rina = 3.08
    res_rina = client.get("/api/mahasiswa/2025001-0002/ipk")
    assert res_rina.status_code == 200
    assert res_rina.json()["ipk"] == "3.08"

    # Cek UI form & endpoint daftar kelas / peserta (IF204-A mengunci Budi 70%)
    res_ui = client.get("/api/kelas/nilai-form")
    assert res_ui.status_code == 200
    assert "text/html" in res_ui.headers["content-type"]
    assert "Form Input Nilai Dosen" in res_ui.text

    res_kelas = client.get("/api/kelas")
    assert res_kelas.status_code == 200
    k_if204 = next(k for k in res_kelas.json() if k["kode_mk"] == "IF204" and k["nama_kelas"] == "A")
    dosen_id = k_if204["dosens"][0]["id"]

    res_peserta = client.get(
        f"/api/kelas/{k_if204['id']}/peserta",
        headers={"X-Dosen-Id": str(dosen_id)},
    )
    assert res_peserta.status_code == 200
    peserta_by_nim = {p["nim"]: p for p in res_peserta.json()}
    assert peserta_by_nim["2025001-0001"]["presensi"] == "70"
    assert peserta_by_nim["2025001-0001"]["boleh_input"] is False
    assert peserta_by_nim["2025001-0002"]["boleh_input"] is True
    assert peserta_by_nim["2025001-0003"]["boleh_input"] is True

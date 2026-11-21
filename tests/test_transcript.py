"""Pengujian API Transkrip, Preview HTML, Generator PDF ReportLab, & Acceptance Multi-Semester."""

from datetime import date, time
from decimal import Decimal
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest
from sqlalchemy import select
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
from app.services.grade_service import PresensiStub, get_presensi_port
from seed import (
    seed_data,
    seed_jadwal_data,
    seed_krs_data,
    seed_nilai_demo_data,
    seed_transkrip_demo_data,
)


def _isi_skala_baku(db: Session) -> None:
    """Mengisi SkalaNilai standar ke sesi uji."""
    for h, b, lulus in (
        ("A", Decimal("4.00"), True),
        ("B", Decimal("3.00"), True),
        ("C", Decimal("2.00"), True),
        ("D", Decimal("1.00"), False),
        ("E", Decimal("0.00"), False),
    ):
        if db.get(SkalaNilai, h) is None:
            db.add(SkalaNilai(huruf=h, bobot=b, lulus=lulus))


def _buat_mahasiswa(
    db: Session,
    nim: str,
    nama: str,
    email: str,
    prodi_kode: str = "001",
) -> CalonMahasiswa:
    """Membuat mahasiswa berstatus approved dengan NIM terdaftar."""
    prodi = db.execute(
        select(ProgramStudi).where(ProgramStudi.kode == prodi_kode)
    ).scalar_one()
    jalur = db.execute(select(JalurMasuk).limit(1)).scalar_one()
    mhs = CalonMahasiswa(
        nama_lengkap=nama,
        email=email,
        phone="081234567890",
        tanggal_lahir=date(2005, 5, 10),
        alamat="Bandung",
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status=StatusPMB.approved,
        nim=nim,
    )
    db.add(mhs)
    db.flush()
    return mhs


def _ekstrak_teks_pdf(pdf_bytes: bytes) -> str:
    """Menggabungkan seluruh teks tiap halaman PDF menggunakan pypdf.PdfReader."""
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_get_transcript_json_dan_404(
    client: TestClient, db_session: Session
) -> None:
    """GET /api/mahasiswa/{nim}/transkrip mengembalikan rekap lintas semester lengkap & 404."""
    _isi_skala_baku(db_session)
    _buat_mahasiswa(
        db_session,
        nim="2024001-0001",
        nama="Rina Transkrip",
        email="rina.tr@example.com",
    )
    mk1 = MataKuliah(
        kode_mk="IF101",
        nama="Algoritma",
        sks=3,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(10, 0),
    )
    mk2 = MataKuliah(
        kode_mk="IF205",
        nama="Sistem Operasi",
        sks=4,
        hari=2,
        jam_mulai=time(8, 0),
        jam_selesai=time(11, 0),
    )
    mk3 = MataKuliah(
        kode_mk="IF102",
        nama="Struktur Data",
        sks=3,
        hari=3,
        jam_mulai=time(8, 0),
        jam_selesai=time(10, 0),
    )
    db_session.add_all([mk1, mk2, mk3])
    db_session.flush()

    db_session.add_all(
        [
            KRS(
                nim="2024001-0001",
                semester="20242",
                status=KRSStatus.APPROVED,
                dosen_pa_id=101,
                details=[
                    KRSDetail(kode_mk="IF101", nilai="A"),
                    KRSDetail(kode_mk="IF102", nilai="B"),
                ],
            ),
            KRS(
                nim="2024001-0001",
                semester="20241",
                status=KRSStatus.APPROVED,
                dosen_pa_id=101,
                details=[
                    KRSDetail(kode_mk="IF101", nilai="E"),
                    KRSDetail(kode_mk="IF205", nilai="A"),
                ],
            ),
        ]
    )
    db_session.commit()

    res = client.get("/api/mahasiswa/2024001-0001/transkrip")
    assert res.status_code == 200
    data = res.json()

    assert data["biodata"]["nim"] == "2024001-0001"
    assert data["biodata"]["nama"] == "Rina Transkrip"
    assert data["biodata"]["program_studi"] == "Teknik Informatika"
    assert data["biodata"]["fakultas"] == "Fakultas Teknik"
    assert data["biodata"]["angkatan"] == "2024"

    # Urutan semester menaik (20241 lalu 20242)
    assert [s["semester"] for s in data["semesters"]] == ["20241", "20242"]
    sem1, sem2 = data["semesters"]
    assert sem1["label_semester"] == "2024/2025 Ganjil"
    assert sem1["ips"] == "2.29"  # (0 + 16) / 7 = 2.2857 -> 2.29
    assert sem2["ips"] == "3.50"  # (12 + 9) / 6 = 3.50

    # IF101 di 20241 (E) tidak dipakai IPK; IF101 di 20242 (A) dipakai IPK
    items_s1 = {i["kode_mk"]: i for i in sem1["items"]}
    items_s2 = {i["kode_mk"]: i for i in sem2["items"]}
    assert items_s1["IF101"]["dipakai_ipk"] is False
    assert items_s1["IF205"]["dipakai_ipk"] is True
    assert items_s2["IF101"]["dipakai_ipk"] is True

    # Total lulus unik: IF205(4,A=16) + IF101(3,A=12) + IF102(3,B=9) -> 10 SKS, 37.00, 3.70
    assert data["summary"]["total_sks_tempuh"] == 13
    assert data["summary"]["total_sks_lulus"] == 10
    assert data["summary"]["total_mutu_lulus"] == "37.00"
    assert data["summary"]["ipk"] == "3.70"
    assert data["summary"]["predikat"] == "Cum Laude"

    assert client.get("/api/mahasiswa/TIDAK-ADA/transkrip").status_code == 404
    assert client.get("/api/mahasiswa/TIDAK-ADA/transkrip/preview").status_code == 404
    assert client.get("/api/mahasiswa/TIDAK-ADA/transkrip.pdf").status_code == 404


def test_transkrip_mahasiswa_belum_ada_nilai(
    client: TestClient, db_session: Session
) -> None:
    """Mahasiswa baru tanpa nilai tetap mendapat transkrip IPK 0.00 & PDF valid."""
    _isi_skala_baku(db_session)
    _buat_mahasiswa(
        db_session,
        nim="2025001-0999",
        nama="Mahasiswa Baru",
        email="maba@example.com",
    )
    db_session.commit()

    res_json = client.get("/api/mahasiswa/2025001-0999/transkrip")
    assert res_json.status_code == 200
    body = res_json.json()
    assert body["semesters"] == []
    assert body["summary"]["total_sks_tempuh"] == 0
    assert body["summary"]["total_sks_lulus"] == 0
    assert body["summary"]["ipk"] == "0.00"
    assert body["summary"]["predikat"] == "Belum Memenuhi Predikat"

    res_html = client.get("/api/mahasiswa/2025001-0999/transkrip/preview")
    assert res_html.status_code == 200
    assert "Belum ada mata kuliah yang memiliki nilai." in res_html.text

    res_pdf = client.get("/api/mahasiswa/2025001-0999/transkrip.pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.content.startswith(b"%PDF-")
    teks = _ekstrak_teks_pdf(res_pdf.content)
    assert "TRANSKRIP AKADEMIK" in teks
    assert "2025001-0999" in teks
    assert "Belum ada mata kuliah yang memiliki nilai." in teks


def test_escaping_karakter_khusus_html_dan_pdf(
    client: TestClient, db_session: Session
) -> None:
    """Nama & MK berisi '&' dan '<script>' di-escape aman di Jinja2 maupun ReportLab."""
    _isi_skala_baku(db_session)
    _buat_mahasiswa(
        db_session,
        nim="2025002-0001",
        nama='Andi & Budi <script>alert("xss")</script>',
        email="andi.xss@example.com",
        prodi_kode="002",
    )
    db_session.add(
        MataKuliah(
            kode_mk="SI101",
            nama="Analisis & Desain <Sistem>",
            sks=3,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
        )
    )
    db_session.flush()
    db_session.add(
        KRS(
            nim="2025002-0001",
            semester="20251",
            status=KRSStatus.APPROVED,
            dosen_pa_id=101,
            details=[KRSDetail(kode_mk="SI101", nilai="A")],
        )
    )
    db_session.commit()

    res_html = client.get("/api/mahasiswa/2025002-0001/transkrip/preview")
    assert res_html.status_code == 200
    assert "<script>" not in res_html.text
    assert "&lt;script&gt;" in res_html.text
    assert "Analisis &amp; Desain &lt;Sistem&gt;" in res_html.text

    res_pdf = client.get("/api/mahasiswa/2025002-0001/transkrip.pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.content.startswith(b"%PDF-")
    teks = _ekstrak_teks_pdf(res_pdf.content)
    assert "Andi & Budi" in teks
    assert "Analisis & Desain <Sistem>" in teks


def test_download_transcript_pdf_konten_dan_disposition(
    client: TestClient, db_session: Session
) -> None:
    """Endpoint PDF mengirim header attachment/inline dan memuat seluruh komponen resmi."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    seed_transkrip_demo_data(db_session)

    res_att = client.get("/api/mahasiswa/2025001-0004/transkrip.pdf")
    assert res_att.status_code == 200
    assert res_att.headers["content-type"].startswith("application/pdf")
    assert (
        res_att.headers["content-disposition"]
        == 'attachment; filename="transkrip_2025001-0004.pdf"'
    )
    assert res_att.content.startswith(b"%PDF-")

    teks = _ekstrak_teks_pdf(res_att.content)
    for wajib in (
        "UNIVERSITAS SEVIMA-MINI",
        "TRANSKRIP AKADEMIK",
        "2025001-0004",
        "Dina Kartika",
        "Teknik Informatika",
        "2025",
        "IF101",
        "IF206",
        "28 SKS",
        "3.82",
        "Cum Laude",
        "Dekan Fakultas Teknik",
    ):
        assert wajib in teks

    res_inl = client.get("/api/mahasiswa/2025001-0004/transkrip.pdf?inline=true")
    assert res_inl.status_code == 200
    assert (
        res_inl.headers["content-disposition"]
        == 'inline; filename="transkrip_2025001-0004.pdf"'
    )


def test_acceptance_multi_semester_pengulangan_edit_nilai_dan_pdf_multihalaman(
    client: TestClient, db_session: Session
) -> None:
    """Acceptance test: 4 semester, input/edit nilai -> audit + IPK/PDF update + PDF >= 2 hal."""
    _isi_skala_baku(db_session)
    dosen = Dosen(nidn="0099018501", nama="Prof. Pengampu Transkrip")
    ruang = Ruangan(kode="R901", kapasitas=40)
    db_session.add_all([dosen, ruang])

    # Buat 24 MK across 4 semester agar transkrip PDF otomatis melintasi >= 2 halaman
    mk_list: list[MataKuliah] = []
    for idx in range(1, 25):
        mk_list.append(
            MataKuliah(
                kode_mk=f"IF3{idx:02d}",
                nama=f"Mata Kuliah Pemrograman Lanjut Bagian {idx}",
                sks=3,
                hari=(idx % 5) + 1,
                jam_mulai=time(8, 0),
                jam_selesai=time(10, 0),
            )
        )
    db_session.add_all(mk_list)
    db_session.flush()

    mhs = _buat_mahasiswa(
        db_session,
        nim="2023001-0077",
        nama="Citra Multi Semester",
        email="citra.multi@example.com",
    )

    # MK IF301 mendapat D di semester 20231 lalu diambil ulang di kelas aktif 20242
    kelas_ulang = Kelas(kode_mk="IF301", nama="A", kuota=40, semester="20242")
    db_session.add(kelas_ulang)
    db_session.flush()
    db_session.add(
        Jadwal(
            kelas_id=kelas_ulang.id,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
            ruangan_kode=ruang.kode,
            dosen_id=dosen.id,
        )
    )

    krs_20231 = KRS(
        nim=mhs.nim,
        semester="20231",
        status=KRSStatus.APPROVED,
        dosen_pa_id=101,
        details=[
            KRSDetail(kode_mk="IF301", nilai="D"),
            *[KRSDetail(kode_mk=f"IF3{i:02d}", nilai="B") for i in range(2, 9)],
        ],
    )
    krs_20232 = KRS(
        nim=mhs.nim,
        semester="20232",
        status=KRSStatus.APPROVED,
        dosen_pa_id=101,
        details=[KRSDetail(kode_mk=f"IF3{i:02d}", nilai="B") for i in range(9, 17)],
    )
    krs_20241 = KRS(
        nim=mhs.nim,
        semester="20241",
        status=KRSStatus.APPROVED,
        dosen_pa_id=101,
        details=[KRSDetail(kode_mk=f"IF3{i:02d}", nilai="A") for i in range(17, 25)],
    )
    krs_20242 = KRS(
        nim=mhs.nim,
        semester="20242",
        status=KRSStatus.APPROVED,
        dosen_pa_id=101,
        details=[KRSDetail(kode_mk="IF301", kelas_id=kelas_ulang.id, nilai=None)],
    )
    db_session.add_all([krs_20231, krs_20232, krs_20241, krs_20242])
    db_session.commit()

    # Sebelum IF301 dinilai ulang: 15 MK B (135) + 8 MK A (96) = 231 / 69 = 3.35 (Sangat Memuaskan)
    sebelum = client.get(f"/api/mahasiswa/{mhs.nim}/transkrip").json()
    assert sebelum["summary"]["ipk"] == "3.35"
    assert sebelum["summary"]["predikat"] == "Sangat Memuaskan"

    app.dependency_overrides[get_presensi_port] = lambda: PresensiStub(default=Decimal("90"))
    try:
        # 1. Dosen input nilai B untuk IF301 di 20242
        r_put1 = client.put(
            f"/api/kelas/{kelas_ulang.id}/nilai/{mhs.nim}",
            headers={"X-Dosen-Id": str(dosen.id)},
            json={"huruf": "B"},
        )
        assert r_put1.status_code == 200

        # 2. Dosen koreksi nilai B -> A dengan alasan resmi -> audit tercatat
        r_put2 = client.put(
            f"/api/kelas/{kelas_ulang.id}/nilai/{mhs.nim}",
            headers={"X-Dosen-Id": str(dosen.id)},
            json={"huruf": "A", "alasan": "Koreksi UAS semester 20242"},
        )
        assert r_put2.status_code == 200
    finally:
        app.dependency_overrides.pop(get_presensi_port, None)

    riwayat = db_session.scalars(select(GradeHistory).order_by(GradeHistory.id)).all()
    assert len(riwayat) == 2
    assert (riwayat[0].old_value, riwayat[0].new_value) == (None, "B")
    assert (riwayat[1].old_value, riwayat[1].new_value, riwayat[1].reason) == (
        "B",
        "A",
        "Koreksi UAS semester 20242",
    )

    # Setelah IF301 = A: 24 MK x 3 = 72 SKS, mutu = 231 + 12 = 243 -> 243 / 72 = 3.375 -> 3.38
    sesudah = client.get(f"/api/mahasiswa/{mhs.nim}/transkrip").json()
    assert [s["semester"] for s in sesudah["semesters"]] == [
        "20231",
        "20232",
        "20241",
        "20242",
    ]
    assert sesudah["summary"]["total_sks_lulus"] == 72
    assert sesudah["summary"]["ipk"] == "3.38"
    assert sesudah["summary"]["predikat"] == "Sangat Memuaskan"

    # Pastikan PDF multi-halaman valid (>= 2 halaman) dan memuat data terbaru
    res_pdf = client.get(f"/api/mahasiswa/{mhs.nim}/transkrip.pdf")
    assert res_pdf.status_code == 200
    reader = PdfReader(BytesIO(res_pdf.content))
    assert len(reader.pages) >= 2
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Halaman 1" in full_text
    assert "Halaman 2" in full_text
    assert "3.38" in full_text
    assert "Sangat Memuaskan" in full_text
    assert "Citra Multi Semester" in full_text


def test_seed_transkrip_demo_data_idempotent(
    client: TestClient, db_session: Session
) -> None:
    """Seeding transkrip Dina Kartika (2025001-0004) idempotent 2x dan hasil IPK 3.82."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    seed_transkrip_demo_data(db_session)

    hitung_1 = (
        db_session.query(CalonMahasiswa).count(),
        db_session.query(KRS).count(),
        db_session.query(KRSDetail).count(),
    )
    seed_transkrip_demo_data(db_session)
    hitung_2 = (
        db_session.query(CalonMahasiswa).count(),
        db_session.query(KRS).count(),
        db_session.query(KRSDetail).count(),
    )
    assert hitung_1 == hitung_2

    res = client.get("/api/mahasiswa/2025001-0004/transkrip")
    assert res.status_code == 200
    data = res.json()
    assert len(data["semesters"]) == 3
    assert data["summary"]["total_sks_lulus"] == 28
    assert data["summary"]["total_mutu_lulus"] == "107.00"
    assert data["summary"]["ipk"] == "3.82"
    assert data["summary"]["predikat"] == "Cum Laude"

"""Script seeding data referensi PMB, KRS, Jadwal, Nilai, Transkrip, Keuangan, dan Presensi secara idempotent."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
    Billing,
    BillingStatus,
    CalonMahasiswa,
    Dosen,
    Jadwal,
    JalurMasuk,
    Kelas,
    KRS,
    KRSDetail,
    KRSStatus,
    MataKuliah,
    NimCounter,
    Payment,
    PaymentMethod,
    PaymentStatus,
    ProgramStudi,
    Ruangan,
    SkalaNilai,
    StatusPMB,
    prerequisite,
)

DEFAULT_PRODI = [
    {
        "kode": "001",
        "nama": "Teknik Informatika",
        "fakultas": "Fakultas Teknik",
    },
    {
        "kode": "002",
        "nama": "Sistem Informasi",
        "fakultas": "Fakultas Ilmu Komputer",
    },
    {
        "kode": "003",
        "nama": "Teknik Elektro",
        "fakultas": "Fakultas Teknik",
    },
]

DEFAULT_JALUR = ["SNBP", "SNBT", "Mandiri"]

DEFAULT_SKALA_NILAI = [
    ("A", Decimal("4.00"), True),
    ("B", Decimal("3.00"), True),
    ("C", Decimal("2.00"), True),
    ("D", Decimal("1.00"), False),
    ("E", Decimal("0.00"), False),
]

DEFAULT_MATAKULIAH = [
    {
        "kode_mk": "IF101",
        "nama": "Algoritma dan Pemrograman",
        "sks": 3,
        "hari": 1,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 30),
    },
    {
        "kode_mk": "MA101",
        "nama": "Kalkulus I",
        "sks": 3,
        "hari": 2,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 30),
    },
    {
        "kode_mk": "IF102",
        "nama": "Struktur Data",
        "sks": 3,
        "hari": 3,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 30),
    },
    {
        "kode_mk": "MA102",
        "nama": "Kalkulus II",
        "sks": 3,
        "hari": 4,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 30),
    },
    {
        "kode_mk": "IF201",
        "nama": "Basis Data",
        "sks": 3,
        "hari": 1,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 30),
    },
    {
        "kode_mk": "IF202",
        "nama": "Statistika",
        "sks": 3,
        "hari": 1,
        "jam_mulai": time(9, 0),
        "jam_selesai": time(11, 0),
    },
    {
        "kode_mk": "IF203",
        "nama": "Pemrograman Berorientasi Objek",
        "sks": 3,
        "hari": 1,
        "jam_mulai": time(10, 30),
        "jam_selesai": time(12, 30),
    },
    {
        "kode_mk": "IF204",
        "nama": "Jaringan Komputer",
        "sks": 3,
        "hari": 2,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 30),
    },
    {
        "kode_mk": "IF205",
        "nama": "Sistem Operasi",
        "sks": 4,
        "hari": 3,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(11, 0),
    },
    {
        "kode_mk": "IF206",
        "nama": "Rekayasa Perangkat Lunak",
        "sks": 4,
        "hari": 4,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(11, 0),
    },
    {
        "kode_mk": "IF207",
        "nama": "Kecerdasan Buatan",
        "sks": 4,
        "hari": 5,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(11, 0),
    },
    {
        "kode_mk": "IF208",
        "nama": "Etika Profesi",
        "sks": 2,
        "hari": 6,
        "jam_mulai": time(8, 0),
        "jam_selesai": time(10, 0),
    },
]

DEFAULT_PREREQUISITE = [
    ("IF102", "IF101"),
    ("MA102", "MA101"),
    ("IF203", "IF102"),
]

DEFAULT_RUANGAN = [
    {"kode": "A101", "kapasitas": 40},
    {"kode": "A102", "kapasitas": 40},
    {"kode": "A103", "kapasitas": 35},
    {"kode": "A104", "kapasitas": 30},
    {"kode": "B201", "kapasitas": 50},
    {"kode": "B202", "kapasitas": 50},
    {"kode": "B203", "kapasitas": 45},
    {"kode": "B204", "kapasitas": 60},
    {"kode": "LAB1", "kapasitas": 30},
    {"kode": "LAB2", "kapasitas": 30},
    {"kode": "LAB3", "kapasitas": 25},
    {"kode": "LAB4", "kapasitas": 35},
]

DEFAULT_DOSEN = [
    {"nidn": "0001018501", "nama": "Dr. Ahmad Fauzi, M.Kom."},
    {"nidn": "0001018502", "nama": "Dr. Siti Rahmawati, M.T."},
    {"nidn": "0001018503", "nama": "Ir. Hendra Wijaya, M.Sc."},
    {"nidn": "0001018504", "nama": "Dr. Rina Kusuma, M.Kom."},
    {"nidn": "0001018505", "nama": "Bambang Pratama, M.T."},
    {"nidn": "0001018506", "nama": "Dr. Dewi Kartika, M.Si."},
    {"nidn": "0001018507", "nama": "Agus Setiawan, M.Kom."},
    {"nidn": "0001018508", "nama": "Dr. Lestari Putri, M.T."},
    {"nidn": "0001018509", "nama": "Yusuf Hidayat, M.Sc."},
    {"nidn": "0001018510", "nama": "Dr. Nurul Aini, M.Kom."},
    {"nidn": "0001018511", "nama": "Eko Prasetyo, M.T."},
    {"nidn": "0001018512", "nama": "Dr. Maya Sari, M.Si."},
    {"nidn": "0001018513", "nama": "Fajar Nugroho, M.Kom."},
    {"nidn": "0001018514", "nama": "Dr. Indah Permata, M.T."},
    {"nidn": "0001018515", "nama": "Rizki Ramadhan, M.Sc."},
    {"nidn": "0001018516", "nama": "Dr. Ratna Dewi, M.Kom."},
]


def seed_data(db: Session) -> None:
    """Mengisi data awal program_studi dan jalur_masuk tanpa menduplikasi data."""
    for item in DEFAULT_PRODI:
        exists = db.execute(
            select(ProgramStudi).where(ProgramStudi.kode == item["kode"])
        ).scalar_one_or_none()
        if exists is None:
            db.add(ProgramStudi(**item))

    for nama_jalur in DEFAULT_JALUR:
        exists = db.execute(
            select(JalurMasuk).where(JalurMasuk.nama == nama_jalur)
        ).scalar_one_or_none()
        if exists is None:
            db.add(JalurMasuk(nama=nama_jalur))

    db.commit()


def seed_krs_data(db: Session) -> None:
    """Mengisi data dummy skala nilai, mata kuliah, prasyarat, dan riwayat KRS Budi."""
    for huruf, bobot, lulus in DEFAULT_SKALA_NILAI:
        skala = db.get(SkalaNilai, huruf)
        if skala is None:
            db.add(SkalaNilai(huruf=huruf, bobot=bobot, lulus=lulus))
        else:
            skala.bobot = bobot
            skala.lulus = lulus

    for mk_data in DEFAULT_MATAKULIAH:
        if db.get(MataKuliah, mk_data["kode_mk"]) is None:
            db.add(MataKuliah(**mk_data))

    db.flush()

    for kode_mk, kode_prasyarat in DEFAULT_PREREQUISITE:
        existing_pair = db.execute(
            select(prerequisite).where(
                prerequisite.c.kode_mk == kode_mk,
                prerequisite.c.kode_prasyarat == kode_prasyarat,
            )
        ).first()
        if existing_pair is None:
            db.execute(
                prerequisite.insert().values(
                    kode_mk=kode_mk, kode_prasyarat=kode_prasyarat
                )
            )

    # Dummy mahasiswa ber-NIM ("2025001-0001") untuk simulasi KRS & riwayat nilai semester lalu.
    dummy_nim = "2025001-0001"
    mahasiswa = db.execute(
        select(CalonMahasiswa).where(CalonMahasiswa.nim == dummy_nim)
    ).scalar_one_or_none()
    if mahasiswa is None:
        prodi_ti = db.execute(
            select(ProgramStudi).where(ProgramStudi.kode == "001")
        ).scalar_one()
        jalur_snbp = db.execute(
            select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
        ).scalar_one()
        mahasiswa = CalonMahasiswa(
            nama_lengkap="Budi Santoso",
            email="budi1@example.com",
            phone="081234567890",
            tanggal_lahir=date(2006, 5, 14),
            alamat="Jl. Merdeka No. 10, Bandung",
            program_studi_id=prodi_ti.id,
            jalur_masuk_id=jalur_snbp.id,
            status=StatusPMB.approved,
            nim=dummy_nim,
            approved_at=datetime.now(timezone.utc),
        )
        db.add(mahasiswa)
        counter = db.get(NimCounter, (2025, "001"))
        if counter is None:
            db.add(NimCounter(tahun=2025, kode_prodi="001", last_number=1))
        elif counter.last_number < 1:
            counter.last_number = 1
        db.flush()

    hist_krs = db.execute(
        select(KRS).where(KRS.nim == dummy_nim, KRS.semester == "20242")
    ).scalar_one_or_none()
    if hist_krs is None:
        hist_krs = KRS(
            nim=dummy_nim,
            semester="20242",
            status=KRSStatus.APPROVED,
            dosen_pa_id=101,
            details=[
                KRSDetail(kode_mk="IF101", nilai="B"),
                KRSDetail(kode_mk="MA101", nilai="D"),
            ],
        )
        db.add(hist_krs)

    db.commit()


def seed_jadwal_data(db: Session) -> None:
    """Mengisi data ruangan, dosen, kelas paralel, serta 44 jadwal (termasuk 6 bentrok sengaja)."""
    for mk_data in DEFAULT_MATAKULIAH:
        if db.get(MataKuliah, mk_data["kode_mk"]) is None:
            db.add(MataKuliah(**mk_data))

    for ruang_data in DEFAULT_RUANGAN:
        if db.get(Ruangan, ruang_data["kode"]) is None:
            db.add(Ruangan(**ruang_data))

    dosen_by_nidn: dict[str, Dosen] = {}
    for dosen_data in DEFAULT_DOSEN:
        dosen = db.execute(
            select(Dosen).where(Dosen.nidn == dosen_data["nidn"])
        ).scalar_one_or_none()
        if dosen is None:
            dosen = Dosen(**dosen_data)
            db.add(dosen)
        dosen_by_nidn[dosen_data["nidn"]] = dosen

    db.flush()

    kelas_by_key: dict[tuple[str, str], Kelas] = {}
    kuota_mk = [40, 40, 35, 30, 50, 50, 45, 35, 30, 30, 25, 35]
    for idx, mk_data in enumerate(DEFAULT_MATAKULIAH):
        kode_mk = str(mk_data["kode_mk"])
        for suffix, kuota_offset in (("A", 0), ("B", -5)):
            kuota = max(25, kuota_mk[idx] + kuota_offset)
            kelas = db.execute(
                select(Kelas).where(
                    Kelas.kode_mk == kode_mk,
                    Kelas.nama == suffix,
                    Kelas.semester == "20251",
                )
            ).scalar_one_or_none()
            if kelas is None:
                kelas = Kelas(
                    kode_mk=kode_mk,
                    nama=suffix,
                    kuota=kuota,
                    semester="20251",
                )
                db.add(kelas)
            kelas_by_key[(kode_mk, suffix)] = kelas

    db.flush()

    def _nidn(nomor: int) -> str:
        return f"00010185{nomor:02d}"

    # 39 jadwal bersih (termasuk sesi bersambung 08:00-09:40 & 09:40-11:20) + 5 jadwal bentrok sengaja.
    spesifikasi_jadwal: list[tuple[str, str, int, time, time, str, int]] = [
        # Senin (hari 1): Slot 1 (08:00-09:40) & Slot 2 (09:40-11:20) bersambung sah
        ("IF101", "A", 1, time(8, 0), time(9, 40), "A101", 1),
        ("MA101", "A", 1, time(8, 0), time(9, 40), "A102", 2),
        ("IF102", "A", 1, time(8, 0), time(9, 40), "A103", 3),
        ("MA102", "A", 1, time(8, 0), time(9, 40), "A104", 4),
        ("IF101", "B", 1, time(9, 40), time(11, 20), "A101", 1),
        ("MA101", "B", 1, time(9, 40), time(11, 20), "A102", 2),
        ("IF102", "B", 1, time(9, 40), time(11, 20), "A103", 3),
        ("MA102", "B", 1, time(9, 40), time(11, 20), "A104", 4),
        # Senin (hari 1): Slot 3 (13:00-14:40) & Slot 4 (14:40-16:20) bersambung sah
        ("IF201", "A", 1, time(13, 0), time(14, 40), "B201", 5),
        ("IF202", "A", 1, time(13, 0), time(14, 40), "B202", 6),
        ("IF203", "A", 1, time(13, 0), time(14, 40), "B203", 7),
        ("IF201", "B", 1, time(14, 40), time(16, 20), "B201", 5),
        ("IF202", "B", 1, time(14, 40), time(16, 20), "B202", 6),
        ("IF203", "B", 1, time(14, 40), time(16, 20), "B203", 7),
        # Selasa (hari 2): Praktikum Lab Slot 1 & Slot 2 bersambung sah
        ("IF101", "A", 2, time(8, 0), time(9, 40), "LAB1", 8),
        ("IF102", "A", 2, time(8, 0), time(9, 40), "LAB2", 9),
        ("IF205", "A", 2, time(8, 0), time(9, 40), "LAB3", 10),
        ("IF204", "A", 2, time(8, 0), time(9, 40), "LAB4", 11),
        ("IF101", "B", 2, time(9, 40), time(11, 20), "LAB1", 8),
        ("IF102", "B", 2, time(9, 40), time(11, 20), "LAB2", 9),
        ("IF205", "B", 2, time(9, 40), time(11, 20), "LAB3", 10),
        ("IF204", "B", 2, time(9, 40), time(11, 20), "LAB4", 11),
        # Rabu (hari 3)
        ("IF204", "A", 3, time(8, 0), time(9, 40), "A101", 12),
        ("IF205", "A", 3, time(8, 0), time(9, 40), "A102", 13),
        ("IF206", "A", 3, time(8, 0), time(9, 40), "B201", 14),
        ("IF207", "A", 3, time(8, 0), time(9, 40), "B202", 15),
        ("IF206", "B", 3, time(13, 0), time(14, 40), "A103", 16),
        ("IF207", "B", 3, time(13, 0), time(14, 40), "A104", 1),
        ("IF208", "A", 3, time(13, 0), time(14, 40), "B204", 2),
        # Kamis (hari 4)
        ("IF201", "A", 4, time(8, 0), time(9, 40), "B201", 3),
        ("IF202", "A", 4, time(8, 0), time(9, 40), "B202", 4),
        ("IF203", "A", 4, time(8, 0), time(9, 40), "B203", 5),
        ("IF208", "B", 4, time(8, 0), time(9, 40), "B204", 6),
        ("IF206", "A", 4, time(13, 0), time(14, 40), "LAB1", 7),
        # Jumat (hari 5): 4 jadwal bersih di Slot 1
        ("MA101", "A", 5, time(8, 0), time(9, 40), "A101", 9),
        ("MA102", "A", 5, time(8, 0), time(9, 40), "A102", 10),
        ("IF204", "B", 5, time(8, 0), time(9, 40), "A103", 11),
        ("IF205", "B", 5, time(8, 0), time(9, 40), "A104", 12),
        # Sabtu (hari 6): 1 jadwal bersih
        ("IF207", "A", 6, time(8, 0), time(9, 40), "B204", 15),
        # --- 5 jadwal bentrok sengaja (impor historis melewati SchedulingService -> 6 konflik) ---
        # 2 room_conflict (Jumat A101 & Jumat A102)
        ("IF201", "B", 5, time(8, 30), time(10, 0), "A101", 13),
        ("IF202", "B", 5, time(9, 0), time(10, 30), "A102", 14),
        # 2 lecturer_conflict (Jumat dosen 11 & dosen 12)
        ("IF203", "B", 5, time(8, 30), time(10, 0), "B201", 11),
        ("IF206", "B", 5, time(9, 0), time(10, 30), "B202", 12),
        # 1 bentrok ganda room_conflict + lecturer_conflict (Sabtu B204 + dosen 15)
        ("IF208", "A", 6, time(8, 30), time(10, 0), "B204", 15),
    ]

    for kode_mk, nama_kelas, hari, jam_mulai, jam_selesai, ruangan_kode, dosen_no in spesifikasi_jadwal:
        kelas = kelas_by_key[(kode_mk, nama_kelas)]
        dosen = dosen_by_nidn[_nidn(dosen_no)]
        exists = db.execute(
            select(Jadwal).where(
                Jadwal.kelas_id == kelas.id,
                Jadwal.hari == hari,
                Jadwal.jam_mulai == jam_mulai,
                Jadwal.jam_selesai == jam_selesai,
                Jadwal.ruangan_kode == ruangan_kode,
                Jadwal.dosen_id == dosen.id,
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                Jadwal(
                    kelas_id=kelas.id,
                    hari=hari,
                    jam_mulai=jam_mulai,
                    jam_selesai=jam_selesai,
                    ruangan_kode=ruangan_kode,
                    dosen_id=dosen.id,
                )
            )

    # Tautkan KRS semester aktif 20251 untuk dummy mahasiswa 2025001-0001 (jika ada)
    # agar demo ekspor .ics dan invalidasi otomatis KRS saat rescheduling langsung jalan.
    dummy_mhs = db.execute(
        select(CalonMahasiswa).where(CalonMahasiswa.nim == "2025001-0001")
    ).scalar_one_or_none()
    if dummy_mhs is not None:
        target_kelas = [
            ("IF201", "B"),
            ("IF102", "A"),
            ("IF204", "A"),
        ]
        krs_aktif = db.execute(
            select(KRS).where(KRS.nim == dummy_mhs.nim, KRS.semester == "20251")
        ).scalar_one_or_none()
        if krs_aktif is None:
            krs_aktif = KRS(
                nim=dummy_mhs.nim,
                semester="20251",
                status=KRSStatus.APPROVED,
                dosen_pa_id=101,
                approved_at=datetime.now(timezone.utc),
                details=[
                    KRSDetail(
                        kode_mk=kode_mk,
                        kelas_id=kelas_by_key[(kode_mk, nama_kelas)].id,
                    )
                    for kode_mk, nama_kelas in target_kelas
                ],
            )
            db.add(krs_aktif)
        else:
            existing_by_mk = {d.kode_mk: d for d in krs_aktif.details}
            for kode_mk, nama_kelas in target_kelas:
                target_kid = kelas_by_key[(kode_mk, nama_kelas)].id
                if kode_mk in existing_by_mk:
                    if existing_by_mk[kode_mk].kelas_id is None:
                        existing_by_mk[kode_mk].kelas_id = target_kid
                else:
                    krs_aktif.details.append(
                        KRSDetail(kode_mk=kode_mk, kelas_id=target_kid)
                    )

    db.commit()


def seed_nilai_demo_data(db: Session) -> None:
    """Menyiapkan dummy mahasiswa Rina & Sari beserta KRS aktif untuk demo form nilai."""
    prodi_ti = db.execute(
        select(ProgramStudi).where(ProgramStudi.kode == "001")
    ).scalar_one()
    jalur_snbp = db.execute(
        select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
    ).scalar_one()

    k_if201_b = db.execute(
        select(Kelas).where(
            Kelas.kode_mk == "IF201", Kelas.nama == "B", Kelas.semester == "20251"
        )
    ).scalar_one()
    k_if204_a = db.execute(
        select(Kelas).where(
            Kelas.kode_mk == "IF204", Kelas.nama == "A", Kelas.semester == "20251"
        )
    ).scalar_one()

    demo_mhs = [
        ("2025001-0002", "Rina Pratama", "rina.demo@example.com", "081234567891"),
        ("2025001-0003", "Sari Wulandari", "sari.demo@example.com", "081234567892"),
    ]
    for nim, nama, email, phone in demo_mhs:
        mhs = db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mhs is None:
            db.add(
                CalonMahasiswa(
                    nama_lengkap=nama,
                    email=email,
                    phone=phone,
                    tanggal_lahir=date(2006, 8, 20),
                    alamat="Jl. Ganesha No. 5, Bandung",
                    program_studi_id=prodi_ti.id,
                    jalur_masuk_id=jalur_snbp.id,
                    status=StatusPMB.approved,
                    nim=nim,
                    approved_at=datetime.now(timezone.utc),
                )
            )
    counter = db.get(NimCounter, (2025, "001"))
    if counter is None:
        db.add(NimCounter(tahun=2025, kode_prodi="001", last_number=3))
    elif counter.last_number < 3:
        counter.last_number = 3
    db.flush()

    # Riwayat nilai Rina (contoh perhitungan materi Minggu 9 -> 20241=2.44, 20242=2.00, IPK=3.08)
    rina_riwayat: dict[str, list[tuple[str, str]]] = {
        "20241": [("IF101", "E"), ("IF205", "A"), ("IF208", "B")],
        "20242": [("IF101", "B"), ("IF102", "C"), ("IF201", "D")],
    }
    for sem, items in rina_riwayat.items():
        krs_sem = db.execute(
            select(KRS).where(KRS.nim == "2025001-0002", KRS.semester == sem)
        ).scalar_one_or_none()
        if krs_sem is None:
            db.add(
                KRS(
                    nim="2025001-0002",
                    semester=sem,
                    status=KRSStatus.APPROVED,
                    dosen_pa_id=101,
                    details=[KRSDetail(kode_mk=mk, nilai=h) for mk, h in items],
                )
            )

    # Enrol Rina & Sari ke kelas 20251 (IF201-B dan IF204-A) untuk demo form dosen
    # Rina belum dinilai di 20251 (IPK tetap 3.08 dari 20241-20242); Sari sudah C di IF201/IF204 (untuk demo wajib alasan edit).
    demo_aktif = {
        "2025001-0002": [("IF201", k_if201_b.id, None), ("IF204", k_if204_a.id, None)],
        "2025001-0003": [("IF201", k_if201_b.id, "C"), ("IF204", k_if204_a.id, "C")],
    }
    for nim, kelas_items in demo_aktif.items():
        krs_aktif = db.execute(
            select(KRS).where(KRS.nim == nim, KRS.semester == "20251")
        ).scalar_one_or_none()
        if krs_aktif is None:
            db.add(
                KRS(
                    nim=nim,
                    semester="20251",
                    status=KRSStatus.APPROVED,
                    dosen_pa_id=101,
                    details=[
                        KRSDetail(kode_mk=mk, kelas_id=kid, nilai=h)
                        for mk, kid, h in kelas_items
                    ],
                )
            )

    db.commit()


def seed_transkrip_demo_data(db: Session) -> None:
    """Menyiapkan dummy mahasiswa multi-semester (Dina) untuk demo Transkrip & PDF."""
    prodi_ti = db.execute(
        select(ProgramStudi).where(ProgramStudi.kode == "001")
    ).scalar_one()
    jalur_snbp = db.execute(
        select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
    ).scalar_one()

    dina_nim = "2025001-0004"
    dina = db.execute(
        select(CalonMahasiswa).where(CalonMahasiswa.nim == dina_nim)
    ).scalar_one_or_none()
    if dina is None:
        db.add(
            CalonMahasiswa(
                nama_lengkap="Dina Kartika",
                email="dina.demo@example.com",
                phone="081234567893",
                tanggal_lahir=date(2005, 11, 12),
                alamat="Jl. Dago No. 18, Bandung",
                program_studi_id=prodi_ti.id,
                jalur_masuk_id=jalur_snbp.id,
                status=StatusPMB.approved,
                nim=dina_nim,
                approved_at=datetime.now(timezone.utc),
            )
        )

    counter = db.get(NimCounter, (2025, "001"))
    if counter is None:
        db.add(NimCounter(tahun=2025, kode_prodi="001", last_number=4))
    elif counter.last_number < 4:
        counter.last_number = 4
    db.flush()

    # 3 semester lengkap: 28 SKS lulus, 107.00 mutu -> IPK 3.82 ("Cum Laude")
    dina_riwayat: dict[str, list[tuple[str, str]]] = {
        "20241": [("IF101", "A"), ("MA101", "A"), ("IF208", "B")],
        "20242": [("IF102", "A"), ("MA102", "B"), ("IF201", "A")],
        "20251": [("IF203", "A"), ("IF205", "A"), ("IF206", "A")],
    }
    for sem, items in dina_riwayat.items():
        krs_sem = db.execute(
            select(KRS).where(KRS.nim == dina_nim, KRS.semester == sem)
        ).scalar_one_or_none()
        if krs_sem is None:
            db.add(
                KRS(
                    nim=dina_nim,
                    semester=sem,
                    status=KRSStatus.APPROVED,
                    dosen_pa_id=101,
                    approved_at=datetime.now(timezone.utc),
                    details=[KRSDetail(kode_mk=mk, nilai=h) for mk, h in items],
                )
            )

    db.commit()


def seed_keuangan_data(db: Session) -> None:
    """Mengisi data prodi Ekonomi, metode bayar, mahasiswa lintas prodi, dan simulasi SPP 20261."""
    prodi_ekonomi = db.execute(
        select(ProgramStudi).where(ProgramStudi.kode == "004")
    ).scalar_one_or_none()
    if prodi_ekonomi is None:
        prodi_ekonomi = ProgramStudi(
            kode="004",
            nama="Ekonomi Pembangunan",
            fakultas="Fakultas Ekonomi dan Bisnis",
        )
        db.add(prodi_ekonomi)
        db.flush()

    prodi_by_kode = {
        p.kode: p for p in db.scalars(select(ProgramStudi)).all()
    }
    jalur_snbp = db.execute(
        select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
    ).scalar_one()

    metode_list = [
        ("VA_BCA", "Virtual Account BCA", "gateway_va"),
        ("VA_BNI", "Virtual Account BNI", "gateway_va"),
        ("QRIS", "QRIS Nasional", "gateway_qris"),
        ("TRANSFER_BANK", "Transfer Bank Manual", "manual"),
        ("TUNAI", "Loket Keuangan Kampus", "manual"),
    ]
    method_by_code: dict[str, PaymentMethod] = {}
    for code, name, provider in metode_list:
        pm = db.execute(
            select(PaymentMethod).where(PaymentMethod.code == code)
        ).scalar_one_or_none()
        if pm is None:
            pm = PaymentMethod(
                code=code, name=name, provider=provider, is_active=True
            )
            db.add(pm)
        method_by_code[code] = pm
    db.flush()

    # Tambah mahasiswa lintas prodi (SI, Teknik Elektro, Ekonomi Pembangunan) secara idempoten.
    tambahan_mhs = [
        ("2025004-0001", "Andi Wijaya", "andi.ekonomi@example.com", "081234567894", "004", 1),
        ("2025004-0002", "Maya Putri", "maya.ekonomi@example.com", "081234567895", "004", 2),
        ("2025004-0003", "Doni Pratama", "doni.ekonomi@example.com", "081234567896", "004", 3),
        ("2025002-0001", "Citra Lestari", "citra.si@example.com", "081234567897", "002", 1),
        ("2025003-0001", "Fajar Santoso", "fajar.te@example.com", "081234567898", "003", 1),
        ("2025003-0002", "Hendra Gunawan", "hendra.te@example.com", "081234567899", "003", 2),
    ]
    max_nomor_per_prodi: dict[str, int] = {}
    for nim, nama, email, phone, kode_prodi, nomor in tambahan_mhs:
        mhs = db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mhs is None:
            db.add(
                CalonMahasiswa(
                    nama_lengkap=nama,
                    email=email,
                    phone=phone,
                    tanggal_lahir=date(2006, 3, 15),
                    alamat="Jl. Dipatiukur No. 25, Bandung",
                    program_studi_id=prodi_by_kode[kode_prodi].id,
                    jalur_masuk_id=jalur_snbp.id,
                    status=StatusPMB.approved,
                    nim=nim,
                    approved_at=datetime.now(timezone.utc),
                )
            )
        prev_max = max_nomor_per_prodi.get(kode_prodi, 0)
        if nomor > prev_max:
            max_nomor_per_prodi[kode_prodi] = nomor

    for kode_prodi, max_nomor in max_nomor_per_prodi.items():
        counter = db.get(NimCounter, (2025, kode_prodi))
        if counter is None:
            db.add(NimCounter(tahun=2025, kode_prodi=kode_prodi, last_number=max_nomor))
        elif counter.last_number < max_nomor:
            counter.last_number = max_nomor
    db.flush()

    # Skenario tagihan semester 20261 mencakup seluruh status (paid, partial, unpaid, overdue)
    # serta sebaran pembayaran bulanan (Agustus-November 2026).
    skenario_billing: list[
        tuple[
            str,
            Decimal,
            Decimal,
            Decimal,
            date,
            BillingStatus,
            list[tuple[str, str, Decimal, datetime, str, bool]],
        ]
    ] = [
        (
            "2025001-0001",
            Decimal("5000000.00"),
            Decimal("0.00"),
            Decimal("5000000.00"),
            date(2026, 8, 25),
            BillingStatus.paid,
            [
                (
                    "SEED-20261-2025001-0001-1",
                    "VA_BCA",
                    Decimal("5000000.00"),
                    datetime(2026, 8, 10, 9, 15, tzinfo=timezone.utc),
                    "webhook",
                    True,
                )
            ],
        ),
        (
            "2025001-0004",
            Decimal("5000000.00"),
            Decimal("0.00"),
            Decimal("5000000.00"),
            date(2026, 11, 25),
            BillingStatus.paid,
            [
                (
                    "SEED-20261-2025001-0004-1",
                    "QRIS",
                    Decimal("5000000.00"),
                    datetime(2026, 11, 5, 10, 30, tzinfo=timezone.utc),
                    "webhook",
                    True,
                )
            ],
        ),
        (
            "2025004-0001",
            Decimal("4000000.00"),
            Decimal("0.00"),
            Decimal("4000000.00"),
            date(2026, 11, 25),
            BillingStatus.paid,
            [
                (
                    "SEED-20261-2025004-0001-1",
                    "VA_BNI",
                    Decimal("4000000.00"),
                    datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc),
                    "webhook",
                    True,
                )
            ],
        ),
        (
            "2025002-0001",
            Decimal("4500000.00"),
            Decimal("0.00"),
            Decimal("4500000.00"),
            date(2026, 10, 30),
            BillingStatus.paid,
            [
                (
                    "SEED-20261-2025002-0001-1",
                    "TRANSFER_BANK",
                    Decimal("4500000.00"),
                    datetime(2026, 10, 15, 11, 20, tzinfo=timezone.utc),
                    "manual",
                    True,
                )
            ],
        ),
        (
            "2025001-0002",
            Decimal("5000000.00"),
            Decimal("0.00"),
            Decimal("2500000.00"),
            date(2026, 12, 5),
            BillingStatus.partial,
            [
                (
                    "SEED-20261-2025001-0002-1",
                    "VA_BCA",
                    Decimal("2500000.00"),
                    datetime(2026, 10, 20, 8, 45, tzinfo=timezone.utc),
                    "webhook",
                    True,
                )
            ],
        ),
        (
            "2025003-0001",
            Decimal("5000000.00"),
            Decimal("0.00"),
            Decimal("3000000.00"),
            date(2026, 12, 5),
            BillingStatus.partial,
            [
                (
                    "SEED-20261-2025003-0001-1",
                    "TUNAI",
                    Decimal("2000000.00"),
                    datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc),
                    "manual",
                    True,
                ),
                (
                    "SEED-20261-2025003-0001-2",
                    "QRIS",
                    Decimal("1000000.00"),
                    datetime(2026, 11, 10, 15, 10, tzinfo=timezone.utc),
                    "webhook",
                    True,
                ),
            ],
        ),
        (
            "2025004-0002",
            Decimal("4000000.00"),
            Decimal("0.00"),
            Decimal("0.00"),
            date(2026, 12, 5),
            BillingStatus.unpaid,
            [],
        ),
        (
            "2025001-0003",
            Decimal("5000000.00"),
            Decimal("500000.00"),
            Decimal("0.00"),
            date(2026, 8, 15),
            BillingStatus.overdue,
            [],
        ),
        (
            "2025004-0003",
            Decimal("4000000.00"),
            Decimal("400000.00"),
            Decimal("0.00"),
            date(2026, 8, 20),
            BillingStatus.overdue,
            [],
        ),
        (
            "2025003-0002",
            Decimal("5000000.00"),
            Decimal("500000.00"),
            Decimal("0.00"),
            date(2026, 9, 1),
            BillingStatus.overdue,
            [],
        ),
    ]

    for nim, amount, denda, paid_amount, due_dt, st, payment_items in skenario_billing:
        billing = db.execute(
            select(Billing).where(Billing.nim == nim, Billing.semester == "20261")
        ).scalar_one_or_none()
        if billing is None:
            billing = Billing(
                nim=nim,
                semester="20261",
                amount=amount,
                denda=denda,
                paid_amount=paid_amount,
                due_date=due_dt,
                status=st,
            )
            db.add(billing)
            db.flush()

        for tx_id, m_code, p_amt, p_at, src, r_sent in payment_items:
            exists_tx = db.execute(
                select(Payment).where(Payment.transaction_id == tx_id)
            ).scalar_one_or_none()
            if exists_tx is None:
                db.add(
                    Payment(
                        billing_id=billing.id,
                        payment_method_id=method_by_code[m_code].id,
                        transaction_id=tx_id,
                        amount=p_amt,
                        status=PaymentStatus.success,
                        source=src,
                        paid_at=p_at,
                        notes="Seed demo Modul Keuangan SPP",
                        receipt_sent=r_sent,
                    )
                )

    db.commit()


def seed_presensi_data(db: Session) -> None:
    """Mengisi data sesi QR presensi dan catatan kehadiran mahasiswa secara idempoten."""
    k_if102_a = db.execute(
        select(Kelas).where(
            Kelas.kode_mk == "IF102", Kelas.nama == "A", Kelas.semester == "20251"
        )
    ).scalar_one()
    k_if201_b = db.execute(
        select(Kelas).where(
            Kelas.kode_mk == "IF201", Kelas.nama == "B", Kelas.semester == "20251"
        )
    ).scalar_one()
    k_if204_a = db.execute(
        select(Kelas).where(
            Kelas.kode_mk == "IF204", Kelas.nama == "A", Kelas.semester == "20251"
        )
    ).scalar_one()

    # Tambah kepesertaan Andi & Maya di IF102-A (Senin pagi) tanpa menyentuh data Rina/Sari/Dina.
    for nim in ("2025004-0001", "2025004-0002"):
        krs_20251 = db.execute(
            select(KRS).where(KRS.nim == nim, KRS.semester == "20251")
        ).scalar_one_or_none()
        if krs_20251 is None:
            db.add(
                KRS(
                    nim=nim,
                    semester="20251",
                    status=KRSStatus.APPROVED,
                    dosen_pa_id=101,
                    approved_at=datetime.now(timezone.utc),
                    details=[KRSDetail(kode_mk="IF102", kelas_id=k_if102_a.id)],
                )
            )
    db.flush()

    j_if204_a = db.execute(
        select(Jadwal).where(Jadwal.kelas_id == k_if204_a.id, Jadwal.hari == 3)
    ).scalar_one()
    j_if102_a = db.execute(
        select(Jadwal).where(Jadwal.kelas_id == k_if102_a.id, Jadwal.hari == 1)
    ).scalar_one()
    j_if201_b = db.execute(
        select(Jadwal).where(Jadwal.kelas_id == k_if201_b.id, Jadwal.hari == 1)
    ).scalar_one()

    def _seed_kelas_sessions(
        jadwal: Jadwal,
        start_date: date,
        total_pertemuan: int,
        status_matrix: dict[str, list[AttendanceStatus]],
        prefix: str,
    ) -> None:
        for idx in range(total_pertemuan):
            tgl = start_date + timedelta(days=7 * idx)
            pertemuan_no = idx + 1
            jti = f"SEED-{prefix}-P{pertemuan_no:02d}"
            sess = db.execute(
                select(AttendanceSession).where(
                    AttendanceSession.jadwal_id == jadwal.id,
                    AttendanceSession.tanggal == tgl,
                )
            ).scalar_one_or_none()
            gen_utc = datetime.combine(
                tgl, jadwal.jam_mulai, tzinfo=timezone(timedelta(hours=7))
            ).astimezone(timezone.utc)
            if sess is None:
                sess = AttendanceSession(
                    jadwal_id=jadwal.id,
                    pertemuan_ke=pertemuan_no,
                    tanggal=tgl,
                    dosen_id=jadwal.dosen_id,
                    active_jti=jti,
                    generated_at=gen_utc,
                    expires_at=gen_utc + timedelta(minutes=15),
                    valid_minutes=15,
                    is_active=True,
                )
                db.add(sess)
                db.flush()

            for nim, daftar_st in status_matrix.items():
                st = daftar_st[idx]
                exists_rec = db.execute(
                    select(AttendanceRecord).where(
                        AttendanceRecord.session_id == sess.id,
                        AttendanceRecord.nim == nim,
                    )
                ).scalar_one_or_none()
                if exists_rec is None:
                    menit_offset = 18 if st == AttendanceStatus.terlambat else 4
                    db.add(
                        AttendanceRecord(
                            session_id=sess.id,
                            nim=nim,
                            status=st,
                            scanned_at=gen_utc + timedelta(minutes=menit_offset),
                            token_jti=jti,
                            notes=f"Seed pertemuan #{pertemuan_no}",
                        )
                    )

    # 1. IF204-A (Rabu 08:00, 10 pertemuan): Budi 70%, Rina 90%, Sari 80%
    _seed_kelas_sessions(
        j_if204_a,
        date(2026, 9, 2),
        10,
        {
            "2025001-0001": [AttendanceStatus.hadir] * 7 + [AttendanceStatus.alpha] * 3,
            "2025001-0002": [AttendanceStatus.hadir] * 9 + [AttendanceStatus.alpha],
            "2025001-0003": [AttendanceStatus.hadir] * 8 + [AttendanceStatus.alpha] * 2,
        },
        "IF204A",
    )

    # 2. IF102-A (Senin pagi 08:00, 6 pertemuan): Budi, Andi, & Maya sering absent Senin pagi
    _seed_kelas_sessions(
        j_if102_a,
        date(2026, 9, 7),
        6,
        {
            "2025001-0001": [AttendanceStatus.hadir] * 2 + [AttendanceStatus.alpha] * 4,
            "2025004-0001": [AttendanceStatus.hadir] * 3 + [AttendanceStatus.alpha] * 3,
            "2025004-0002": [AttendanceStatus.hadir] * 3 + [AttendanceStatus.alpha] * 3,
        },
        "IF102A",
    )

    # 3. IF201-B (Senin siang 14:40, 6 pertemuan): Budi 100%, Rina 100%, Sari 100% (1 telat)
    _seed_kelas_sessions(
        j_if201_b,
        date(2026, 9, 7),
        6,
        {
            "2025001-0001": [AttendanceStatus.hadir] * 6,
            "2025001-0002": [AttendanceStatus.hadir] * 6,
            "2025001-0003": [AttendanceStatus.hadir] * 5 + [AttendanceStatus.terlambat],
        },
        "IF201B",
    )

    db.commit()


def main() -> None:
    """Menjalankan proses seeding PMB, KRS, Jadwal, Nilai, Transkrip, Keuangan, & Presensi secara idempotent."""
    with SessionLocal() as db:
        seed_data(db)
        seed_krs_data(db)
        seed_jadwal_data(db)
        seed_nilai_demo_data(db)
        seed_transkrip_demo_data(db)
        seed_keuangan_data(db)
        seed_presensi_data(db)
    print("Seeding data PMB, KRS, Jadwal, Nilai, Transkrip, Keuangan, dan Presensi selesai.")


if __name__ == "__main__":
    main()

"""Script seeding data referensi PMB dan data dummy Modul KRS secara idempotent."""

from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
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
    ("A", 4.0),
    ("B", 3.0),
    ("C", 2.0),
    ("D", 1.0),
    ("E", 0.0),
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
    for huruf, bobot in DEFAULT_SKALA_NILAI:
        if db.get(SkalaNilai, huruf) is None:
            db.add(SkalaNilai(huruf=huruf, bobot=bobot))

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


def main() -> None:
    """Menjalankan proses seeding PMB, KRS, dan Jadwal secara idempotent."""
    with SessionLocal() as db:
        seed_data(db)
        seed_krs_data(db)
        seed_jadwal_data(db)
    print("Seeding data PMB, KRS, dan Jadwal selesai.")


if __name__ == "__main__":
    main()

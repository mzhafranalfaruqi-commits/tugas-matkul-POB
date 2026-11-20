"""Script seeding data referensi PMB dan data dummy Modul KRS secara idempotent."""

from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    CalonMahasiswa,
    JalurMasuk,
    KRS,
    KRSDetail,
    KRSStatus,
    MataKuliah,
    NimCounter,
    ProgramStudi,
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


def main() -> None:
    """Menjalankan proses seeding PMB dan KRS secara idempotent."""
    with SessionLocal() as db:
        seed_data(db)
        seed_krs_data(db)
    print("Seeding data PMB dan KRS selesai.")


if __name__ == "__main__":
    main()

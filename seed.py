"""Script seeding data referensi program_studi dan jalur_masuk secara idempotent."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pmb import JalurMasuk, ProgramStudi

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


def main() -> None:
    """Menjalankan proses seeding ke database yang terkonfigurasi."""
    with SessionLocal() as db:
        seed_data(db)
    print("Seeding data program_studi dan jalur_masuk selesai.")


if __name__ == "__main__":
    main()

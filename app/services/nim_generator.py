"""Generator NIM otomatis yang thread-safe dengan format [Tahun:4][Kode Prodi:3]-[Running Number:4]."""

import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pmb import CalonMahasiswa, ProgramStudi

_nim_lock = threading.RLock()


def generate_nim(tahun: int, kode_prodi: str, db: Session) -> str:
    """Generate NIM format YYYY[KODE]-XXXX secara sequential dan thread-safe.

    Contoh: 2025001-0001 untuk Teknik Informatika (kode 001), pendaftar pertama tahun 2025.
    """
    if isinstance(tahun, bool) or not isinstance(tahun, int) or not (2000 <= tahun <= 9999):
        raise ValueError("tahun harus berupa bilangan bulat 4 digit antara 2000 hingga 9999")

    if not isinstance(kode_prodi, str):
        raise ValueError("kode_prodi harus berupa string 3 karakter")

    kode_clean = kode_prodi.strip()
    if len(kode_clean) != 3:
        raise ValueError("kode_prodi harus tepat 3 karakter non-kosong")

    prefix = f"{tahun:04d}{kode_clean}-"

    with _nim_lock:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name and dialect_name != "sqlite":
            # Pada database client-server (MySQL/PostgreSQL), kunci baris program_studi
            # agar dua transaksi bersamaan tidak membaca max running number yang sama.
            db.execute(
                select(ProgramStudi)
                .where(ProgramStudi.kode == kode_clean)
                .with_for_update()
            ).scalar_one_or_none()

        last_nim = db.execute(
            select(CalonMahasiswa.nim)
            .where(CalonMahasiswa.nim.like(f"{prefix}%"))
            .order_by(CalonMahasiswa.nim.desc())
            .limit(1)
        ).scalar_one_or_none()

        if last_nim:
            last_seq = int(last_nim.split("-")[-1])
            next_seq = last_seq + 1
        else:
            next_seq = 1

        return f"{prefix}{next_seq:04d}"

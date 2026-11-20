"""Generator NIM otomatis berbasis database counter atomik [Tahun:4][Kode Prodi:3]-[Running Number:4]."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pmb import NimCounter


def _validate_tahun_dan_kode(tahun: int, kode_prodi: str) -> str:
    """Memvalidasi parameter tahun (4 digit) dan kode program studi (3 digit angka)."""
    if isinstance(tahun, bool) or not isinstance(tahun, int) or not (2000 <= tahun <= 9999):
        raise ValueError("tahun harus berupa bilangan bulat 4 digit antara 2000 hingga 9999")

    if not isinstance(kode_prodi, str):
        raise ValueError("kode_prodi harus berupa string 3 digit angka")

    kode_clean = kode_prodi.strip()
    if len(kode_clean) != 3 or not kode_clean.isdigit():
        raise ValueError("kode_prodi harus tepat 3 digit angka")

    return kode_clean


def format_nim(tahun: int, kode_prodi: str, nomor_urut: int) -> str:
    """Memformat NIM murni tanpa ketergantungan database: YYYY[KODE]-XXXX.

    Contoh: format_nim(2025, "001", 7) -> "2025001-0007".
    """
    kode_clean = _validate_tahun_dan_kode(tahun, kode_prodi)

    if isinstance(nomor_urut, bool) or not isinstance(nomor_urut, int):
        raise ValueError("nomor_urut harus berupa bilangan bulat")
    if nomor_urut > 9999:
        raise ValueError("Nomor urut habis")
    if nomor_urut < 1:
        raise ValueError("nomor_urut harus antara 1 hingga 9999")

    return f"{tahun:04d}{kode_clean}-{nomor_urut:04d}"


def generate_nim(tahun: int, kode_prodi: str, db: Session) -> str:
    """Mengambil dan menaikkan counter NIM atomik di tabel nim_counter dalam transaksi DB.

    Fungsi ini sengaja hanya memanggil db.flush() (bukan db.commit()) agar kenaikan
    counter dan pembaruan status calon mahasiswa selalu atomik dalam satu transaksi.
    """
    kode_clean = _validate_tahun_dan_kode(tahun, kode_prodi)

    counter = db.execute(
        select(NimCounter)
        .where(NimCounter.tahun == tahun, NimCounter.kode_prodi == kode_clean)
        .with_for_update()
    ).scalar_one_or_none()

    if counter is None:
        counter = NimCounter(tahun=tahun, kode_prodi=kode_clean, last_number=0)
        db.add(counter)

    counter.last_number += 1
    if counter.last_number > 9999:
        raise ValueError("Nomor urut habis")

    db.flush()
    return format_nim(tahun, kode_clean, counter.last_number)

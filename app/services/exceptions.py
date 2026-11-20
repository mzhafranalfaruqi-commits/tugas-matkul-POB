"""Domain exception untuk alur bisnis Modul PMB, Modul KRS, dan Modul Jadwal."""

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.conflict import Conflict


class EmailSudahTerdaftar(Exception):
    """Dilempar ketika email calon mahasiswa sudah terdaftar sebelumnya (HTTP 409)."""


class ReferensiTidakValid(Exception):
    """Dilempar ketika program_studi_id atau jalur_masuk_id tidak ditemukan (HTTP 400)."""


class PendaftarTidakDitemukan(Exception):
    """Dilempar ketika ID calon mahasiswa tidak ditemukan di database (HTTP 404)."""


class StatusTidakValid(Exception):
    """Dilempar ketika konflik transisi status pendaftaran melanggar aturan bisnis (HTTP 409)."""


class DataNIMTidakValid(Exception):
    """Dilempar ketika data pendaftar/prodi tidak memenuhi syarat pembuatan NIM (HTTP 400)."""


class KRSError(Exception):
    """Base domain exception untuk seluruh pelanggaran aturan pada Modul KRS."""

    status_code: int = 400


class KRSTidakDitemukan(KRSError):
    """Dilempar ketika mahasiswa ber-NIM, KRS, atau mata kuliah tidak ditemukan (HTTP 404)."""

    status_code = 404


class KRSValidasiGagal(KRSError):
    """Dilempar ketika pengisian atau pengajuan KRS gagal validasi bisnis (HTTP 400)."""

    status_code = 400


class ForbiddenError(KRSError):
    """Dilempar ketika aktor bukan pemilik sah resource, misalnya bukan Dosen PA mahasiswa (HTTP 403)."""

    status_code = 403


class TransitionError(KRSError):
    """Dilempar ketika transisi status state machine KRS tidak diizinkan (HTTP 409)."""

    status_code = 409


class KRSLockedError(KRSError):
    """Dilempar ketika KRS berada pada status terkunci (SUBMITTED/APPROVED) saat hendak diubah (HTTP 409)."""

    status_code = 409


class StaleVersionError(KRSError):
    """Dilempar ketika versi KRS sudah berubah oleh proses lain (optimistic locking conflict, HTTP 409)."""

    status_code = 409


# Alias kompatibilitas untuk modul/pengujian Minggu 5
KRSStatusTidakValid = KRSLockedError


class ScheduleError(Exception):
    """Base domain exception untuk pelanggaran aturan pada Modul Jadwal & Ruangan."""

    status_code: int = 400

    def body(self) -> dict[str, Any]:
        """Mengembalikan payload JSON standar untuk handler exception FastAPI."""
        return {"detail": str(self)}


class NotFoundError(ScheduleError):
    """Dilempar ketika ruangan, kelas, dosen, atau jadwal tidak ditemukan (HTTP 404)."""

    status_code = 404


class CapacityError(ScheduleError):
    """Dilempar ketika kuota/peserta kelas melebihi kapasitas ruangan (HTTP 409)."""

    status_code = 409


class ScheduleConflictError(ScheduleError):
    """Dilempar ketika jadwal yang disimpan bentrok ruangan atau dosen (HTTP 409)."""

    status_code = 409

    def __init__(self, konflik: list["Conflict"]) -> None:
        super().__init__(f"Jadwal bentrok ({len(konflik)} konflik)")
        self.konflik = konflik

    def body(self) -> dict[str, Any]:
        """Menyertakan daftar detail konflik agar frontend/admin dapat menindaklanjuti."""
        return super().body() | {"conflicts": [asdict(k) for k in self.konflik]}

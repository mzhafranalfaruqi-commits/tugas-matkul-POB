"""Domain exception untuk alur bisnis Modul PMB dan Modul KRS."""


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

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


class KRSTidakDitemukan(KRSError):
    """Dilempar ketika mahasiswa ber-NIM, KRS, atau mata kuliah tidak ditemukan (HTTP 404)."""


class KRSStatusTidakValid(KRSError):
    """Dilempar ketika KRS berada pada status yang tidak dapat diubah (HTTP 409)."""


class KRSValidasiGagal(KRSError):
    """Dilempar ketika pengisian KRS gagal pada rantai validator (HTTP 400)."""

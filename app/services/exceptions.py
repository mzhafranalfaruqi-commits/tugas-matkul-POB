"""Domain exception untuk alur bisnis Modul PMB."""


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

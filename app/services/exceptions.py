"""Domain exception untuk alur bisnis Modul PMB."""


class EmailSudahTerdaftar(Exception):
    """Dilempar ketika email calon mahasiswa sudah terdaftar sebelumnya."""


class ReferensiTidakValid(Exception):
    """Dilempar ketika program_studi_id atau jalur_masuk_id tidak ditemukan."""


class PendaftarTidakDitemukan(Exception):
    """Dilempar ketika ID calon mahasiswa tidak ditemukan di database."""


class StatusTidakValid(Exception):
    """Dilempar ketika transisi status pendaftaran melanggar aturan bisnis."""

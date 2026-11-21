"""Skema Pydantic v2 untuk Modul Nilai, Perhitungan IPS/IPK, dan Audit Trail."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class NilaiIn(BaseModel):
    """Payload input atau pembaruan nilai huruf oleh dosen pengampu."""

    huruf: str = Field(pattern=r"^[A-E]$")
    alasan: str | None = Field(default=None, max_length=500)


class NilaiOut(BaseModel):
    """Response hasil penyimpanan atau pembaruan nilai mahasiswa."""

    nim: str
    kode_mk: str
    huruf: str


class IPKOut(BaseModel):
    """Response IPK mahasiswa dalam format string 2 desimal (mencegah float)."""

    nim: str
    ipk: str


class IPSOut(BaseModel):
    """Response IPS mahasiswa untuk satu semester dalam format string 2 desimal."""

    nim: str
    semester: str
    ips: str


class GradeHistoryOut(BaseModel):
    """Response satu baris jejak audit perubahan nilai dari SQL view v_riwayat_nilai."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    grade_id: int
    nim: str
    semester: str
    kode_mk: str
    old_value: str | None
    new_value: str
    pengubah: str
    changed_at: datetime
    reason: str | None


class DosenRingkasOut(BaseModel):
    """Identitas ringkas dosen pengampu pada satu kelas."""

    id: int
    nama: str


class KelasNilaiRingkasOut(BaseModel):
    """Ringkasan kelas dan dosen pengampunya untuk pemilih kelas di form nilai."""

    id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    dosens: list[DosenRingkasOut]


class PesertaNilaiOut(BaseModel):
    """Baris peserta kelas pada form input nilai dosen."""

    grade_id: int
    nim: str
    nama: str
    semester: str
    kode_mk: str
    presensi: str
    boleh_input: bool
    nilai: str | None
    ipk: str


class TranskripBiodataOut(BaseModel):
    """Biodata resmi mahasiswa pada header transkrip akademik."""

    nim: str
    nama: str
    program_studi: str
    fakultas: str
    angkatan: str


class TranskripItemOut(BaseModel):
    """Satu baris mata kuliah dalam satu semester pada transkrip akademik."""

    kode_mk: str
    nama_mk: str
    semester: str
    sks: int
    huruf: str
    bobot: str
    mutu: str
    lulus: bool
    dipakai_ipk: bool


class TranskripSemesterOut(BaseModel):
    """Rekap satu semester berisi daftar MK dan IPS semester terkait."""

    semester: str
    label_semester: str
    items: list[TranskripItemOut]
    total_sks: int
    total_mutu: str
    ips: str


class TranskripSummaryOut(BaseModel):
    """Ringkasan total SKS, mutu, IPK kumulatif, dan predikat kelulusan."""

    total_sks_tempuh: int
    total_sks_lulus: int
    total_mutu_lulus: str
    ipk: str
    predikat: str


class TranskripOut(BaseModel):
    """Payload JSON lengkap catatan akademik lintas semester mahasiswa."""

    biodata: TranskripBiodataOut
    semesters: list[TranskripSemesterOut]
    summary: TranskripSummaryOut
    tanggal_cetak: date

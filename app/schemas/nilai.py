"""Skema Pydantic v2 untuk Modul Nilai, Perhitungan IPS/IPK, dan Audit Trail."""

from datetime import datetime

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

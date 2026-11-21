"""Skema Pydantic v2 untuk validasi request dan serialisasi response Modul Jadwal."""

from datetime import time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.conflict import ConflictType


class JadwalIn(BaseModel):
    """Payload pembuatan atau pembaruan satu slot pertemuan jadwal kuliah."""

    kelas_id: int = Field(ge=1)
    hari: int = Field(ge=1, le=6)
    jam_mulai: time
    jam_selesai: time
    ruangan_kode: str = Field(min_length=1, max_length=20)
    dosen_id: int = Field(ge=1)

    @field_validator("ruangan_kode", mode="after")
    @classmethod
    def strip_ruangan_kode(cls, value: str) -> str:
        """Menghapus spasi di pinggir kode ruangan dan menolak string kosong."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("ruangan_kode tidak boleh kosong")
        return cleaned

    @model_validator(mode="after")
    def cek_urutan(self) -> "JadwalIn":
        """Memastikan jam_mulai selalu lebih awal daripada jam_selesai."""
        if self.jam_mulai >= self.jam_selesai:
            raise ValueError("jam_mulai harus sebelum jam_selesai")
        return self


class JadwalOut(BaseModel):
    """Response representasi jadwal kuliah tersimpan."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kelas_id: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan_kode: str
    dosen_id: int
    sequence: int = 0


class JadwalDetailOut(JadwalOut):
    """Response jadwal lengkap dengan metadata MK, kelas, kapasitas, dan dosen untuk UI."""

    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    kuota: int
    peserta: int
    ruangan_kapasitas: int
    dosen_nama: str


class ConflictOut(BaseModel):
    """Response satu pelanggaran bentrok jadwal (room_conflict atau lecturer_conflict)."""

    model_config = ConfigDict(from_attributes=True)

    type: ConflictType
    affected: list[int]


class SaranOut(BaseModel):
    """Response satu alternatif jadwal hasil penyaringan AI rescheduler."""

    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan: str
    reason: str = ""


class ApplySaranIn(BaseModel):
    """Payload penerapan salah satu saran jadwal alternatif oleh admin."""

    hari: int = Field(ge=1, le=6)
    jam_mulai: time
    ruangan: str = Field(min_length=1, max_length=20)
    reason: str = ""

    @field_validator("ruangan", mode="after")
    @classmethod
    def strip_ruangan(cls, value: str) -> str:
        """Membersihkan spasi di pinggir kode ruangan dan menolak string kosong."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("ruangan tidak boleh kosong")
        return cleaned

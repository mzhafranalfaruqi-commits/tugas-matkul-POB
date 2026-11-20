"""Skema Pydantic v2 untuk validasi request dan serialisasi response Modul KRS."""

from datetime import time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.krs import KRSStatus


class AddCourseRequest(BaseModel):
    """Payload penambahan mata kuliah ke dalam KRS."""

    kode_mk: str = Field(min_length=2, max_length=10)

    @field_validator("kode_mk", mode="after")
    @classmethod
    def strip_kode_mk(cls, value: str) -> str:
        """Menghapus spasi berlebih dan menolak string kode kosong."""
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("kode_mk minimal 2 karakter (tidak termasuk spasi)")
        return cleaned


class MataKuliahOut(BaseModel):
    """Representasi mata kuliah pada endpoint atau detail KRS."""

    model_config = ConfigDict(from_attributes=True)

    kode_mk: str
    nama: str
    sks: int
    hari: int
    jam_mulai: time
    jam_selesai: time


class KRSDetailOut(BaseModel):
    """Response item mata kuliah yang berhasil ditambahkan/tersimpan di KRS."""

    id: int
    kode_mk: str
    nama_mk: str
    sks: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    nilai: str | None = None


class KRSOut(BaseModel):
    """Response lengkap Kartu Rencana Studi mahasiswa dalam satu semester."""

    id: int
    nim: str
    semester: str
    status: KRSStatus
    dosen_pa_id: int | None
    total_sks: int
    details: list[KRSDetailOut]


class RemoveCourseOut(BaseModel):
    """Response penghapusan mata kuliah dari KRS."""

    message: str
    nim: str
    semester: str
    kode_mk: str


class ValidationIssueOut(BaseModel):
    """Representasi satu hasil pelanggaran aturan dari rantai validator."""

    ok: bool
    message: str


class KRSValidationOut(BaseModel):
    """Response agregat validasi menyeluruh terhadap KRS mahasiswa."""

    nim: str
    semester: str
    valid: bool
    errors: list[ValidationIssueOut]

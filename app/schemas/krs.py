"""Skema Pydantic v2 untuk validasi request dan serialisasi response Modul KRS."""

from datetime import datetime, time

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


class ApproveKRSRequest(BaseModel):
    """Payload persetujuan KRS oleh Dosen Pembimbing Akademik."""

    dosen_pa_id: int = Field(ge=1)
    expected_version: int | None = Field(default=None, ge=1)


class ReviseKRSRequest(BaseModel):
    """Payload pengembalian KRS ke status REVISION dengan catatan wajib Dosen PA."""

    dosen_pa_id: int = Field(ge=1)
    catatan: str = Field(min_length=1, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("catatan", mode="after")
    @classmethod
    def strip_catatan(cls, value: str) -> str:
        """Memastikan catatan revisi tidak hanya berisi spasi."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("catatan revisi tidak boleh kosong")
        return cleaned


class RecommendKRSRequest(BaseModel):
    """Payload permintaan rekomendasi paket KRS berbasis CSP."""

    wajib: list[str] = Field(default_factory=list)
    pilihan: list[str] = Field(default_factory=list)
    max_sks: int = Field(default=24, ge=1, le=24)


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
    version: int
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    catatan_revisi: str | None = None
    total_sks: int
    details: list[KRSDetailOut]


class RecommendKRSOut(BaseModel):
    """Response rekomendasi jadwal KRS optimal hasil solver CSP + guardrail validator."""

    nim: str
    semester: str
    total_sks: int
    max_sks: int
    selected: list[MataKuliahOut]
    wajib_terpilih: list[str]
    ditolak: dict[str, str]


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

"""Skema Pydantic v2 untuk validasi input dan serialisasi output Modul PMB."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationInfo, field_validator

from app.models.pmb import StatusPMB

PHONE_ID = r"^(\+62|62|0)8[1-9][0-9]{6,10}$"


class RegisterRequest(BaseModel):
    """Payload JSON pendaftaran calon mahasiswa baru."""

    nama_lengkap: str = Field(min_length=3, max_length=150)
    email: EmailStr
    phone: str = Field(pattern=PHONE_ID)
    tanggal_lahir: date
    alamat: str = Field(min_length=5)
    program_studi_id: int = Field(gt=0)
    jalur_masuk_id: int = Field(gt=0)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        """Menormalisasi email ke huruf kecil agar konsisten saat cek duplikat."""
        return str(v).lower()

    @field_validator("nama_lengkap", "alamat", mode="after")
    @classmethod
    def strip_and_validate_non_blank(cls, v: str, info: ValidationInfo) -> str:
        """Menghapus spasi berlebih dan memastikan teks tidak kosong."""
        cleaned = v.strip()
        min_len = 3 if info.field_name == "nama_lengkap" else 5
        if len(cleaned) < min_len:
            raise ValueError(
                f"{info.field_name} minimal {min_len} karakter (tidak termasuk spasi)"
            )
        return cleaned

    @field_validator("tanggal_lahir", mode="after")
    @classmethod
    def validate_birth_date(cls, v: date) -> date:
        """Menolak tanggal lahir di hari ini atau masa depan."""
        if v >= date.today():
            raise ValueError("tanggal_lahir harus sebelum hari ini")
        return v


class PendaftarOut(BaseModel):
    """Response ringkas setelah pendaftaran (tidak membocorkan alamat/tanggal lahir)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nama_lengkap: str
    email: str
    status: StatusPMB


class StatusPendaftaranOut(BaseModel):
    """Response detail status pendaftaran calon mahasiswa."""

    id: int
    nama_lengkap: str
    email: str
    program_studi_kode: str
    program_studi_nama: str
    jalur_masuk: str
    status: StatusPMB
    nim: str | None
    created_at: datetime
    approved_at: datetime | None


class ApproveOut(BaseModel):
    """Response endpoint approve pendaftaran yang menyertakan NIM hasil generate."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nama_lengkap: str
    status: StatusPMB
    nim: str
    approved_at: datetime
    already_approved: bool = False


class RejectOut(BaseModel):
    """Response endpoint reject pendaftaran calon mahasiswa."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nama_lengkap: str
    status: StatusPMB


class ProdiStat(BaseModel):
    """Statistik pendaftar per program studi."""

    kode: str
    nama: str
    total: int
    pending: int
    approved: int
    rejected: int


class JalurStat(BaseModel):
    """Statistik pendaftar per jalur masuk."""

    nama: str
    total: int


class StatsOut(BaseModel):
    """Response dashboard statistik keseluruhan Modul PMB."""

    total_pendaftar: int
    per_status: dict[str, int]
    per_program_studi: list[ProdiStat]
    per_jalur_masuk: list[JalurStat]

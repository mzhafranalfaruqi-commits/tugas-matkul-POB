"""Model ORM SQLAlchemy 2.0 untuk modul Penerimaan Mahasiswa Baru (PMB)."""

from datetime import date, datetime
import enum

from sqlalchemy import CheckConstraint, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class deklaratif SQLAlchemy 2.0 untuk seluruh model ORM."""


class StatusPMB(str, enum.Enum):
    """Enum status pendaftaran calon mahasiswa yang sah."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


status_enum = SAEnum(StatusPMB, name="status_pmb", create_constraint=True)


class ProgramStudi(Base):
    """Representasi tabel program_studi sebagai referensi prodi institusi."""

    __tablename__ = "program_studi"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(3), unique=True)
    nama: Mapped[str] = mapped_column(String(100))
    fakultas: Mapped[str] = mapped_column(String(100))

    calon_mahasiswa: Mapped[list["CalonMahasiswa"]] = relationship(
        back_populates="program_studi"
    )


class JalurMasuk(Base):
    """Representasi tabel jalur_masuk (SNBP, SNBT, Mandiri)."""

    __tablename__ = "jalur_masuk"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(30), unique=True)

    calon_mahasiswa: Mapped[list["CalonMahasiswa"]] = relationship(
        back_populates="jalur_masuk"
    )


class CalonMahasiswa(Base):
    """Representasi tabel calon_mahasiswa lengkap dengan constraint dan relasi."""

    __tablename__ = "calon_mahasiswa"
    __table_args__ = (
        CheckConstraint(
            "length(phone) >= 9 AND length(phone) <= 15",
            name="ck_calon_phone_length",
        ),
        CheckConstraint(
            "email LIKE '%_@%_._%'",
            name="ck_calon_email_format",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_lengkap: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(15))
    tanggal_lahir: Mapped[date]
    alamat: Mapped[str] = mapped_column(Text)
    program_studi_id: Mapped[int] = mapped_column(ForeignKey("program_studi.id"))
    jalur_masuk_id: Mapped[int] = mapped_column(ForeignKey("jalur_masuk.id"))
    status: Mapped[StatusPMB] = mapped_column(status_enum, default=StatusPMB.pending)
    nim: Mapped[str | None] = mapped_column(String(15), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(default=None)

    program_studi: Mapped["ProgramStudi"] = relationship(
        back_populates="calon_mahasiswa"
    )
    jalur_masuk: Mapped["JalurMasuk"] = relationship(
        back_populates="calon_mahasiswa"
    )


class NimCounter(Base):
    """Tabel counter atomik untuk menjaga urutan NIM per tahun dan kode prodi."""

    __tablename__ = "nim_counter"

    tahun: Mapped[int] = mapped_column(primary_key=True)
    kode_prodi: Mapped[str] = mapped_column(String(3), primary_key=True)
    last_number: Mapped[int] = mapped_column(default=0)

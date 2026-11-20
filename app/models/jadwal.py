"""Model ORM SQLAlchemy 2.0 untuk modul Penjadwalan Kuliah & Ruangan."""

from datetime import time

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.krs import MataKuliah
from app.models.pmb import Base


class Ruangan(Base):
    """Representasi ruang kuliah beserta kapasitas kursinya."""

    __tablename__ = "ruangan"
    __table_args__ = (
        CheckConstraint("kapasitas >= 1", name="ck_ruangan_kapasitas_positif"),
    )

    kode: Mapped[str] = mapped_column(String(20), primary_key=True)
    kapasitas: Mapped[int]


class Dosen(Base):
    """Representasi dosen pengampu kelas kuliah."""

    __tablename__ = "dosen"

    id: Mapped[int] = mapped_column(primary_key=True)
    nidn: Mapped[str] = mapped_column(String(20), unique=True)
    nama: Mapped[str] = mapped_column(String(100))


class Kelas(Base):
    """Representasi kelas paralel dari suatu mata kuliah pada semester tertentu."""

    __tablename__ = "kelas"
    __table_args__ = (
        CheckConstraint("kuota >= 1", name="ck_kelas_kuota_positif"),
        UniqueConstraint("kode_mk", "nama", "semester", name="uq_kelas_mk_nama_semester"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_mk: Mapped[str] = mapped_column(String(10), ForeignKey("matakuliah.kode_mk"))
    nama: Mapped[str] = mapped_column(String(50))
    kuota: Mapped[int]
    semester: Mapped[str] = mapped_column(String(5))

    matakuliah: Mapped["MataKuliah"] = relationship()
    jadwals: Mapped[list["Jadwal"]] = relationship(
        back_populates="kelas", cascade="all, delete-orphan"
    )


class Jadwal(Base):
    """Satu pertemuan mingguan kelas di ruangan dan dosen pengampu tertentu."""

    __tablename__ = "jadwal"
    __table_args__ = (
        CheckConstraint("jam_mulai < jam_selesai", name="ck_jadwal_jam_valid"),
        CheckConstraint("hari >= 1 AND hari <= 6", name="ck_jadwal_hari_range"),
        Index("ix_jadwal_ruang", "hari", "ruangan_kode"),
        Index("ix_jadwal_dosen", "hari", "dosen_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kelas_id: Mapped[int] = mapped_column(ForeignKey("kelas.id"))
    hari: Mapped[int]
    jam_mulai: Mapped[time]
    jam_selesai: Mapped[time]
    ruangan_kode: Mapped[str] = mapped_column(String(20), ForeignKey("ruangan.kode"))
    dosen_id: Mapped[int] = mapped_column(ForeignKey("dosen.id"))

    kelas: Mapped["Kelas"] = relationship(back_populates="jadwals")
    ruangan: Mapped["Ruangan"] = relationship()
    dosen: Mapped["Dosen"] = relationship()

"""Model ORM SQLAlchemy 2.0 untuk modul Penjadwalan Kuliah, Ruangan, & Transactional Outbox."""

from datetime import datetime, time, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.krs import MataKuliah
from app.models.pmb import Base

if TYPE_CHECKING:
    from app.services.observer import ScheduleEvent


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
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa_text("0")
    )

    kelas: Mapped["Kelas"] = relationship(back_populates="jadwals")
    ruangan: Mapped["Ruangan"] = relationship()
    dosen: Mapped["Dosen"] = relationship()


class Outbox(Base):
    """Tabel Transactional Outbox untuk memastikan event jadwal hanya dikirim pasca-commit."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')",
            name="ck_outbox_status_valid",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts_non_neg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
        server_default=sa_text("'PENDING'"),
        index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa_text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    @classmethod
    def dari_event(cls, event: "ScheduleEvent") -> "Outbox":
        """Mengonversi ScheduleEvent menjadi baris Outbox siap simpan dalam transaksi."""
        return cls(
            event_id=event.event_id,
            payload=event.to_dict(),
        )

    def ke_event(self) -> "ScheduleEvent":
        """Merekonstruksi ScheduleEvent dari payload JSON tersimpan."""
        from app.services.observer import ScheduleEvent

        return ScheduleEvent.from_dict(self.payload)

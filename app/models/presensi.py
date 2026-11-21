"""Model ORM SQLAlchemy 2.0 untuk Modul Presensi (QR Code): attendance_session dan attendance_record."""

from datetime import date, datetime, timezone
import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.jadwal import Dosen, Jadwal
from app.models.pmb import Base, CalonMahasiswa


class AttendanceStatus(str, enum.Enum):
    """Enum status kehadiran mahasiswa pada satu sesi pertemuan kuliah."""

    hadir = "hadir"
    terlambat = "terlambat"
    izin = "izin"
    alpha = "alpha"


attendance_status_enum = SAEnum(
    AttendanceStatus, name="attendance_status", create_constraint=True
)


class AttendanceSession(Base):
    """Sesi presensi per pertemuan jadwal kuliah beserta token JWT unik (anti-replay) dan geofence."""

    __tablename__ = "attendance_session"
    __table_args__ = (
        UniqueConstraint(
            "jadwal_id", "tanggal", name="uq_attendance_session_jadwal_tgl"
        ),
        CheckConstraint("pertemuan_ke >= 1", name="ck_attendance_session_pertemuan_pos"),
        CheckConstraint(
            "valid_minutes >= 1 AND valid_minutes <= 30",
            name="ck_attendance_session_valid_minutes",
        ),
        CheckConstraint(
            "max_radius_meters IS NULL OR max_radius_meters >= 10",
            name="ck_attendance_session_radius_pos",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    jadwal_id: Mapped[int] = mapped_column(
        ForeignKey("jadwal.id", ondelete="CASCADE"), index=True
    )
    pertemuan_ke: Mapped[int] = mapped_column(Integer, nullable=False)
    tanggal: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    dosen_id: Mapped[int] = mapped_column(ForeignKey("dosen.id"), index=True)
    active_jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default=sa_text("15")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_text("1")
    )
    latitude: Mapped[float | None] = mapped_column(Float, default=None)
    longitude: Mapped[float | None] = mapped_column(Float, default=None)
    max_radius_meters: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    jadwal: Mapped["Jadwal"] = relationship()
    dosen: Mapped["Dosen"] = relationship()
    records: Mapped[list["AttendanceRecord"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AttendanceRecord.scanned_at, AttendanceRecord.id",
    )


class AttendanceRecord(Base):
    """Catatan hasil scan QR presensi mahasiswa per sesi kuliah (maksimal 1 per sesi)."""

    __tablename__ = "attendance_record"
    __table_args__ = (
        UniqueConstraint("session_id", "nim", name="uq_attendance_session_nim"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_session.id", ondelete="CASCADE"), index=True
    )
    nim: Mapped[str] = mapped_column(
        String(15), ForeignKey("calon_mahasiswa.nim"), index=True
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        attendance_status_enum, nullable=False, index=True
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    latitude: Mapped[float | None] = mapped_column(Float, default=None)
    longitude: Mapped[float | None] = mapped_column(Float, default=None)
    distance_meters: Mapped[float | None] = mapped_column(Float, default=None)
    token_jti: Mapped[str | None] = mapped_column(String(64), default=None)
    notes: Mapped[str | None] = mapped_column(String(300), default=None)

    session: Mapped["AttendanceSession"] = relationship(back_populates="records")
    mahasiswa: Mapped["CalonMahasiswa"] = relationship()

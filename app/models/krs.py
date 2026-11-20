"""Model ORM SQLAlchemy 2.0 untuk modul Kartu Rencana Studi (KRS)."""

from datetime import datetime, time, timezone
import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pmb import Base
from app.services.exceptions import TransitionError


class KRSStatus(str, enum.Enum):
    """Status siklus pengisian KRS mahasiswa (state machine lengkap di Minggu 6)."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION = "REVISION"


class Actor(str, enum.Enum):
    """Aktor yang berhak memicu transisi pada state machine KRS."""

    MAHASISWA = "MAHASISWA"
    DOSEN_PA = "DOSEN_PA"


# Tabel transisi eksplisit state machine KRS: (status_awal, aktor) -> {status_tujuan}
TRANSITIONS: dict[tuple[KRSStatus, Actor], set[KRSStatus]] = {
    (KRSStatus.DRAFT, Actor.MAHASISWA): {KRSStatus.SUBMITTED},
    (KRSStatus.SUBMITTED, Actor.DOSEN_PA): {KRSStatus.APPROVED, KRSStatus.REVISION},
    (KRSStatus.REVISION, Actor.MAHASISWA): {KRSStatus.SUBMITTED},
}


krs_status_enum = SAEnum(KRSStatus, name="krs_status", create_constraint=True)

# Tabel asosiasi self-referencing many-to-many untuk prasyarat antar mata kuliah.
prerequisite = Table(
    "prerequisite",
    Base.metadata,
    Column("kode_mk", String(10), ForeignKey("matakuliah.kode_mk"), primary_key=True),
    Column(
        "kode_prasyarat",
        String(10),
        ForeignKey("matakuliah.kode_mk"),
        primary_key=True,
    ),
    CheckConstraint("kode_mk <> kode_prasyarat", name="ck_prerequisite_not_self"),
)


class SkalaNilai(Base):
    """Tabel pemetaan nilai huruf ke bobot numerik agar perbandingan kelulusan akurat."""

    __tablename__ = "skala_nilai"

    huruf: Mapped[str] = mapped_column(String(2), primary_key=True)
    bobot: Mapped[float]


class MataKuliah(Base):
    """Representasi mata kuliah lengkap dengan bobot SKS, jadwal, dan daftar prasyarat."""

    __tablename__ = "matakuliah"
    __table_args__ = (
        CheckConstraint("sks >= 1 AND sks <= 4", name="ck_matakuliah_sks_range"),
        CheckConstraint("hari >= 1 AND hari <= 6", name="ck_matakuliah_hari_range"),
        CheckConstraint("jam_mulai < jam_selesai", name="ck_matakuliah_jam_valid"),
    )

    kode_mk: Mapped[str] = mapped_column(String(10), primary_key=True)
    nama: Mapped[str] = mapped_column(String(100))
    sks: Mapped[int]
    hari: Mapped[int]
    jam_mulai: Mapped[time]
    jam_selesai: Mapped[time]

    prasyarat: Mapped[list["MataKuliah"]] = relationship(
        "MataKuliah",
        secondary=prerequisite,
        primaryjoin=kode_mk == prerequisite.c.kode_mk,
        secondaryjoin=kode_mk == prerequisite.c.kode_prasyarat,
    )


class KRS(Base):
    """Header Kartu Rencana Studi per mahasiswa (NIM) per semester."""

    __tablename__ = "krs"
    __table_args__ = (
        UniqueConstraint("nim", "semester", name="uq_krs_nim_semester"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nim: Mapped[str] = mapped_column(String(15), ForeignKey("calon_mahasiswa.nim"))
    semester: Mapped[str] = mapped_column(String(5))
    status: Mapped[KRSStatus] = mapped_column(krs_status_enum, default=KRSStatus.DRAFT)
    dosen_pa_id: Mapped[int | None] = mapped_column(default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    catatan_revisi: Mapped[str | None] = mapped_column(String(500), default=None)
    diubah_pada: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=sa_text("1")
    )

    __mapper_args__ = {"version_id_col": version}

    details: Mapped[list["KRSDetail"]] = relationship(
        back_populates="krs", cascade="all, delete-orphan"
    )
    logs: Mapped[list["KRSLog"]] = relationship(
        back_populates="krs", cascade="all, delete-orphan"
    )

    def cek_transisi(self, target: KRSStatus, actor: Actor) -> None:
        """Memvalidasi apakah transisi state dari status saat ini oleh aktor diizinkan."""
        if target not in TRANSITIONS.get((self.status, actor), set()):
            raise TransitionError(
                f"Transisi tidak diizinkan: {self.status.name} ke {target.name} oleh {actor.name}"
            )

    def transition(self, target: KRSStatus, actor: Actor) -> None:
        """Mengubah status KRS setelah memvalidasi aturan transisi state machine."""
        self.cek_transisi(target, actor)
        self.status = target


class KRSDetail(Base):
    """Baris mata kuliah di dalam satu KRS (termasuk nilai huruf setelah semester usai)."""

    __tablename__ = "krs_detail"
    __table_args__ = (
        UniqueConstraint("krs_id", "kode_mk", name="uq_krs_detail_krs_mk"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    krs_id: Mapped[int] = mapped_column(ForeignKey("krs.id", ondelete="CASCADE"))
    kode_mk: Mapped[str] = mapped_column(String(10), ForeignKey("matakuliah.kode_mk"))
    kelas_id: Mapped[int | None] = mapped_column(
        ForeignKey("kelas.id"), default=None, index=True
    )
    nilai: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("skala_nilai.huruf"), default=None
    )

    krs: Mapped["KRS"] = relationship(back_populates="details")
    matakuliah: Mapped["MataKuliah"] = relationship()


class KRSLog(Base):
    """Jejak audit setiap transisi atau peristiwa penting pada siklus KRS."""

    __tablename__ = "krs_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    krs_id: Mapped[int] = mapped_column(
        ForeignKey("krs.id", ondelete="CASCADE"), index=True
    )
    aksi: Mapped[str] = mapped_column(String(30))
    aktor_id: Mapped[str] = mapped_column(String(50))
    catatan: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    krs: Mapped["KRS"] = relationship(back_populates="logs")


class Notifikasi(Base):
    """Notifikasi hasil persetujuan atau permintaan revisi KRS untuk mahasiswa."""

    __tablename__ = "notifikasi"

    id: Mapped[int] = mapped_column(primary_key=True)
    nim: Mapped[str] = mapped_column(
        String(15), ForeignKey("calon_mahasiswa.nim"), index=True
    )
    pesan: Mapped[str] = mapped_column(String(500))
    terbaca: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

"""Membuat tabel attendance_session dan attendance_record untuk Modul Presensi (QR Code).

Revision ID: 0009_modul_presensi_qr
Revises: 0008_modul_keuangan_spp
Create Date: 2026-11-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_modul_presensi_qr"
down_revision: Union[str, None] = "0008_modul_keuangan_spp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel sesi QR presensi dan catatan scan kehadiran mahasiswa."""
    op.create_table(
        "attendance_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jadwal_id", sa.Integer(), nullable=False),
        sa.Column("pertemuan_ke", sa.Integer(), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("dosen_id", sa.Integer(), nullable=False),
        sa.Column("active_jti", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "valid_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("15"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("max_radius_meters", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pertemuan_ke >= 1", name="ck_attendance_session_pertemuan_pos"),
        sa.CheckConstraint(
            "valid_minutes >= 1 AND valid_minutes <= 30",
            name="ck_attendance_session_valid_minutes",
        ),
        sa.CheckConstraint(
            "max_radius_meters IS NULL OR max_radius_meters >= 10",
            name="ck_attendance_session_radius_pos",
        ),
        sa.ForeignKeyConstraint(
            ["jadwal_id"],
            ["jadwal.id"],
            name="fk_attendance_session_jadwal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dosen_id"],
            ["dosen.id"],
            name="fk_attendance_session_dosen_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attendance_session"),
        sa.UniqueConstraint(
            "jadwal_id", "tanggal", name="uq_attendance_session_jadwal_tgl"
        ),
    )
    op.create_index(
        "ix_attendance_session_jadwal_id",
        "attendance_session",
        ["jadwal_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_session_tanggal",
        "attendance_session",
        ["tanggal"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_session_dosen_id",
        "attendance_session",
        ["dosen_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_session_active_jti",
        "attendance_session",
        ["active_jti"],
        unique=True,
    )

    op.create_table(
        "attendance_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("nim", sa.String(length=15), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "hadir",
                "terlambat",
                "izin",
                "alpha",
                name="attendance_status",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("distance_meters", sa.Float(), nullable=True),
        sa.Column("token_jti", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["attendance_session.id"],
            name="fk_attendance_record_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["nim"],
            ["calon_mahasiswa.nim"],
            name="fk_attendance_record_nim",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attendance_record"),
        sa.UniqueConstraint("session_id", "nim", name="uq_attendance_session_nim"),
    )
    op.create_index(
        "ix_attendance_record_session_id",
        "attendance_record",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_record_nim", "attendance_record", ["nim"], unique=False
    )
    op.create_index(
        "ix_attendance_record_status", "attendance_record", ["status"], unique=False
    )
    op.create_index(
        "ix_attendance_record_scanned_at",
        "attendance_record",
        ["scanned_at"],
        unique=False,
    )


def downgrade() -> None:
    """Menghapus tabel attendance_record dan attendance_session sesuai urutan FK."""
    op.drop_index("ix_attendance_record_scanned_at", table_name="attendance_record")
    op.drop_index("ix_attendance_record_status", table_name="attendance_record")
    op.drop_index("ix_attendance_record_nim", table_name="attendance_record")
    op.drop_index("ix_attendance_record_session_id", table_name="attendance_record")
    op.drop_table("attendance_record")

    op.drop_index("ix_attendance_session_active_jti", table_name="attendance_session")
    op.drop_index("ix_attendance_session_dosen_id", table_name="attendance_session")
    op.drop_index("ix_attendance_session_tanggal", table_name="attendance_session")
    op.drop_index("ix_attendance_session_jadwal_id", table_name="attendance_session")
    op.drop_table("attendance_session")

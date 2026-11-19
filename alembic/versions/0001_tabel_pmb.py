"""Membuat tabel program_studi, jalur_masuk, dan calon_mahasiswa.

Revision ID: 0001_tabel_pmb
Revises:
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_tabel_pmb"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel referensi terlebih dahulu lalu tabel utama calon_mahasiswa."""
    op.create_table(
        "program_studi",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kode", sa.String(length=3), nullable=False),
        sa.Column("nama", sa.String(length=100), nullable=False),
        sa.Column("fakultas", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kode", name="uq_program_studi_kode"),
    )

    op.create_table(
        "jalur_masuk",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nama", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nama", name="uq_jalur_masuk_nama"),
    )

    op.create_table(
        "calon_mahasiswa",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nama_lengkap", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=15), nullable=False),
        sa.Column("tanggal_lahir", sa.Date(), nullable=False),
        sa.Column("alamat", sa.Text(), nullable=False),
        sa.Column("program_studi_id", sa.Integer(), nullable=False),
        sa.Column("jalur_masuk_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="status_pmb", create_constraint=True),
            nullable=False,
        ),
        sa.Column("nim", sa.String(length=15), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "length(phone) >= 9 AND length(phone) <= 15",
            name="ck_calon_phone_length",
        ),
        sa.CheckConstraint(
            "email LIKE '%_@%_._%'",
            name="ck_calon_email_format",
        ),
        sa.ForeignKeyConstraint(
            ["jalur_masuk_id"],
            ["jalur_masuk.id"],
            name="fk_calon_jalur_masuk_id",
        ),
        sa.ForeignKeyConstraint(
            ["program_studi_id"],
            ["program_studi.id"],
            name="fk_calon_program_studi_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nim", name="uq_calon_mahasiswa_nim"),
    )
    op.create_index(
        "ix_calon_mahasiswa_email",
        "calon_mahasiswa",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    """Menghapus tabel anak (calon_mahasiswa) terlebih dahulu sebelum tabel referensi."""
    op.drop_index("ix_calon_mahasiswa_email", table_name="calon_mahasiswa")
    op.drop_table("calon_mahasiswa")
    op.drop_table("jalur_masuk")
    op.drop_table("program_studi")

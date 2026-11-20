"""Menambah kolom state machine/optimistic lock pada krs serta tabel krs_log dan notifikasi.

Revision ID: 0004_krs_workflow_audit
Revises: 0003_tabel_krs
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_krs_workflow_audit"
down_revision: Union[str, None] = "0003_tabel_krs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Menambahkan metadata workflow & version ke krs serta membuat tabel audit dan notifikasi."""
    op.add_column("krs", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("krs", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("krs", sa.Column("catatan_revisi", sa.String(length=500), nullable=True))
    op.add_column("krs", sa.Column("diubah_pada", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "krs",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )

    op.create_table(
        "krs_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("krs_id", sa.Integer(), nullable=False),
        sa.Column("aksi", sa.String(length=30), nullable=False),
        sa.Column("aktor_id", sa.String(length=50), nullable=False),
        sa.Column("catatan", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["krs_id"],
            ["krs.id"],
            name="fk_krs_log_krs_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_krs_log"),
    )
    op.create_index("ix_krs_log_krs_id", "krs_log", ["krs_id"], unique=False)

    op.create_table(
        "notifikasi",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nim", sa.String(length=15), nullable=False),
        sa.Column("pesan", sa.String(length=500), nullable=False),
        sa.Column(
            "terbaca",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["nim"],
            ["calon_mahasiswa.nim"],
            name="fk_notifikasi_nim",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifikasi"),
    )
    op.create_index("ix_notifikasi_nim", "notifikasi", ["nim"], unique=False)


def downgrade() -> None:
    """Menghapus tabel notifikasi, krs_log, serta kolom tambahan krs dengan aman di SQLite."""
    op.drop_index("ix_notifikasi_nim", table_name="notifikasi")
    op.drop_table("notifikasi")

    op.drop_index("ix_krs_log_krs_id", table_name="krs_log")
    op.drop_table("krs_log")

    with op.batch_alter_table("krs") as batch_op:
        batch_op.drop_column("version")
        batch_op.drop_column("diubah_pada")
        batch_op.drop_column("catatan_revisi")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("submitted_at")

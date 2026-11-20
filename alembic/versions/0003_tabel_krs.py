"""Membuat tabel skala_nilai, matakuliah, prerequisite, krs, dan krs_detail.

Revision ID: 0003_tabel_krs
Revises: 0002_tabel_nim_counter
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_tabel_krs"
down_revision: Union[str, None] = "0002_tabel_nim_counter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel referensi nilai, mata kuliah, prasyarat, serta transaksi KRS."""
    op.create_table(
        "skala_nilai",
        sa.Column("huruf", sa.String(length=2), nullable=False),
        sa.Column("bobot", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("huruf", name="pk_skala_nilai"),
    )

    op.create_table(
        "matakuliah",
        sa.Column("kode_mk", sa.String(length=10), nullable=False),
        sa.Column("nama", sa.String(length=100), nullable=False),
        sa.Column("sks", sa.Integer(), nullable=False),
        sa.Column("hari", sa.Integer(), nullable=False),
        sa.Column("jam_mulai", sa.Time(), nullable=False),
        sa.Column("jam_selesai", sa.Time(), nullable=False),
        sa.CheckConstraint("sks >= 1 AND sks <= 4", name="ck_matakuliah_sks_range"),
        sa.CheckConstraint("hari >= 1 AND hari <= 6", name="ck_matakuliah_hari_range"),
        sa.CheckConstraint("jam_mulai < jam_selesai", name="ck_matakuliah_jam_valid"),
        sa.PrimaryKeyConstraint("kode_mk", name="pk_matakuliah"),
    )

    op.create_table(
        "prerequisite",
        sa.Column("kode_mk", sa.String(length=10), nullable=False),
        sa.Column("kode_prasyarat", sa.String(length=10), nullable=False),
        sa.CheckConstraint("kode_mk <> kode_prasyarat", name="ck_prerequisite_not_self"),
        sa.ForeignKeyConstraint(
            ["kode_mk"],
            ["matakuliah.kode_mk"],
            name="fk_prerequisite_kode_mk",
        ),
        sa.ForeignKeyConstraint(
            ["kode_prasyarat"],
            ["matakuliah.kode_mk"],
            name="fk_prerequisite_kode_prasyarat",
        ),
        sa.PrimaryKeyConstraint("kode_mk", "kode_prasyarat", name="pk_prerequisite"),
    )

    op.create_table(
        "krs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nim", sa.String(length=15), nullable=False),
        sa.Column("semester", sa.String(length=5), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "SUBMITTED",
                "APPROVED",
                "REVISION",
                name="krs_status",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("dosen_pa_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["nim"],
            ["calon_mahasiswa.nim"],
            name="fk_krs_nim",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_krs"),
        sa.UniqueConstraint("nim", "semester", name="uq_krs_nim_semester"),
    )

    op.create_table(
        "krs_detail",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("krs_id", sa.Integer(), nullable=False),
        sa.Column("kode_mk", sa.String(length=10), nullable=False),
        sa.Column("nilai", sa.String(length=2), nullable=True),
        sa.ForeignKeyConstraint(
            ["krs_id"],
            ["krs.id"],
            name="fk_krs_detail_krs_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kode_mk"],
            ["matakuliah.kode_mk"],
            name="fk_krs_detail_kode_mk",
        ),
        sa.ForeignKeyConstraint(
            ["nilai"],
            ["skala_nilai.huruf"],
            name="fk_krs_detail_nilai",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_krs_detail"),
        sa.UniqueConstraint("krs_id", "kode_mk", name="uq_krs_detail_krs_mk"),
    )


def downgrade() -> None:
    """Menghapus tabel anak KRS terlebih dahulu sebelum tabel referensi."""
    op.drop_table("krs_detail")
    op.drop_table("krs")
    op.drop_table("prerequisite")
    op.drop_table("matakuliah")
    op.drop_table("skala_nilai")

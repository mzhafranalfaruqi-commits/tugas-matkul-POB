"""Membuat tabel ruangan, dosen, kelas, jadwal, dan kolom krs_detail.kelas_id.

Revision ID: 0005_tabel_jadwal_ruangan
Revises: 0004_krs_workflow_audit
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_tabel_jadwal_ruangan"
down_revision: Union[str, None] = "0004_krs_workflow_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel penjadwalan & ruangan serta menambahkan FK kelas_id pada krs_detail."""
    op.create_table(
        "ruangan",
        sa.Column("kode", sa.String(length=20), nullable=False),
        sa.Column("kapasitas", sa.Integer(), nullable=False),
        sa.CheckConstraint("kapasitas >= 1", name="ck_ruangan_kapasitas_positif"),
        sa.PrimaryKeyConstraint("kode", name="pk_ruangan"),
    )

    op.create_table(
        "dosen",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nidn", sa.String(length=20), nullable=False),
        sa.Column("nama", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dosen"),
        sa.UniqueConstraint("nidn", name="uq_dosen_nidn"),
    )

    op.create_table(
        "kelas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kode_mk", sa.String(length=10), nullable=False),
        sa.Column("nama", sa.String(length=50), nullable=False),
        sa.Column("kuota", sa.Integer(), nullable=False),
        sa.Column("semester", sa.String(length=5), nullable=False),
        sa.CheckConstraint("kuota >= 1", name="ck_kelas_kuota_positif"),
        sa.ForeignKeyConstraint(
            ["kode_mk"],
            ["matakuliah.kode_mk"],
            name="fk_kelas_kode_mk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_kelas"),
        sa.UniqueConstraint("kode_mk", "nama", "semester", name="uq_kelas_mk_nama_semester"),
    )

    op.create_table(
        "jadwal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kelas_id", sa.Integer(), nullable=False),
        sa.Column("hari", sa.Integer(), nullable=False),
        sa.Column("jam_mulai", sa.Time(), nullable=False),
        sa.Column("jam_selesai", sa.Time(), nullable=False),
        sa.Column("ruangan_kode", sa.String(length=20), nullable=False),
        sa.Column("dosen_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("jam_mulai < jam_selesai", name="ck_jadwal_jam_valid"),
        sa.CheckConstraint("hari >= 1 AND hari <= 6", name="ck_jadwal_hari_range"),
        sa.ForeignKeyConstraint(
            ["kelas_id"],
            ["kelas.id"],
            name="fk_jadwal_kelas_id",
        ),
        sa.ForeignKeyConstraint(
            ["ruangan_kode"],
            ["ruangan.kode"],
            name="fk_jadwal_ruangan_kode",
        ),
        sa.ForeignKeyConstraint(
            ["dosen_id"],
            ["dosen.id"],
            name="fk_jadwal_dosen_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jadwal"),
    )
    op.create_index("ix_jadwal_ruang", "jadwal", ["hari", "ruangan_kode"], unique=False)
    op.create_index("ix_jadwal_dosen", "jadwal", ["hari", "dosen_id"], unique=False)

    with op.batch_alter_table("krs_detail") as batch_op:
        batch_op.add_column(sa.Column("kelas_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_krs_detail_kelas_id",
            "kelas",
            ["kelas_id"],
            ["id"],
        )
        batch_op.create_index("ix_krs_detail_kelas_id", ["kelas_id"], unique=False)


def downgrade() -> None:
    """Menghapus FK krs_detail.kelas_id dan seluruh tabel modul penjadwalan dengan aman."""
    with op.batch_alter_table("krs_detail") as batch_op:
        batch_op.drop_index("ix_krs_detail_kelas_id")
        batch_op.drop_constraint("fk_krs_detail_kelas_id", type_="foreignkey")
        batch_op.drop_column("kelas_id")

    op.drop_index("ix_jadwal_dosen", table_name="jadwal")
    op.drop_index("ix_jadwal_ruang", table_name="jadwal")
    op.drop_table("jadwal")
    op.drop_table("kelas")
    op.drop_table("dosen")
    op.drop_table("ruangan")

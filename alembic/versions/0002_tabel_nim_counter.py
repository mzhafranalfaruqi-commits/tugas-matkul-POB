"""Membuat tabel nim_counter untuk penomoran NIM atomik per tahun dan prodi.

Revision ID: 0002_tabel_nim_counter
Revises: 0001_tabel_pmb
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_tabel_nim_counter"
down_revision: Union[str, None] = "0001_tabel_pmb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel nim_counter dengan composite primary key (tahun, kode_prodi)."""
    op.create_table(
        "nim_counter",
        sa.Column("tahun", sa.Integer(), nullable=False),
        sa.Column("kode_prodi", sa.String(length=3), nullable=False),
        sa.Column(
            "last_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.PrimaryKeyConstraint("tahun", "kode_prodi", name="pk_nim_counter"),
    )


def downgrade() -> None:
    """Menghapus tabel nim_counter saat rollback migrasi."""
    op.drop_table("nim_counter")

"""Memperbarui skala_nilai (Numeric + lulus), menambah grade_history dan view v_riwayat_nilai.

Revision ID: 0007_nilai_grade_history_view
Revises: 0006_outbox_dan_jadwal_sequence
Create Date: 2026-11-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.nilai import (
    CREATE_VIEW_RIWAYAT_NILAI_SQL,
    DROP_VIEW_RIWAYAT_NILAI_SQL,
)

revision: str = "0007_nilai_grade_history_view"
down_revision: Union[str, None] = "0006_outbox_dan_jadwal_sequence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Mengubah bobot skala_nilai menjadi Numeric(3,2) + kolom lulus, serta membuat audit trail."""
    with op.batch_alter_table("skala_nilai") as batch_op:
        batch_op.alter_column(
            "bobot",
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=3, scale=2),
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                "lulus",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    # Set default kelulusan sementara (A/B/C = lulus, D/E = tidak lulus; terdokumentasi di ADR-016).
    op.execute(sa.text("UPDATE skala_nilai SET lulus = 1 WHERE huruf IN ('A', 'B', 'C')"))
    op.execute(sa.text("UPDATE skala_nilai SET lulus = 0 WHERE huruf IN ('D', 'E')"))

    op.create_table(
        "grade_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("old_value", sa.String(length=2), nullable=True),
        sa.Column("new_value", sa.String(length=2), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["grade_id"],
            ["krs_detail.id"],
            name="fk_grade_history_grade_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["old_value"],
            ["skala_nilai.huruf"],
            name="fk_grade_history_old_value",
        ),
        sa.ForeignKeyConstraint(
            ["new_value"],
            ["skala_nilai.huruf"],
            name="fk_grade_history_new_value",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["dosen.id"],
            name="fk_grade_history_changed_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_grade_history"),
    )
    op.create_index("ix_grade_history_grade_id", "grade_history", ["grade_id"], unique=False)
    op.create_index("ix_grade_history_changed_by", "grade_history", ["changed_by"], unique=False)

    op.execute(sa.text(CREATE_VIEW_RIWAYAT_NILAI_SQL))


def downgrade() -> None:
    """Menghapus view v_riwayat_nilai, tabel grade_history, dan mengembalikan skala_nilai."""
    op.execute(sa.text(DROP_VIEW_RIWAYAT_NILAI_SQL))
    op.drop_index("ix_grade_history_changed_by", table_name="grade_history")
    op.drop_index("ix_grade_history_grade_id", table_name="grade_history")
    op.drop_table("grade_history")

    with op.batch_alter_table("skala_nilai") as batch_op:
        batch_op.drop_column("lulus")
        batch_op.alter_column(
            "bobot",
            existing_type=sa.Numeric(precision=3, scale=2),
            type_=sa.Float(),
            existing_nullable=False,
        )

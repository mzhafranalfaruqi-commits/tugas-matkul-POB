"""Menambahkan kolom jadwal.sequence dan tabel outbox untuk Transactional Outbox.

Revision ID: 0006_outbox_dan_jadwal_sequence
Revises: 0005_tabel_jadwal_ruangan
Create Date: 2026-11-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_outbox_dan_jadwal_sequence"
down_revision: Union[str, None] = "0005_tabel_jadwal_ruangan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Menambahkan jadwal.sequence serta membuat tabel outbox dan indeks status."""
    with op.batch_alter_table("jadwal") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sequence",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')",
            name="ck_outbox_status_valid",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_non_neg"),
        sa.PrimaryKeyConstraint("id", name="pk_outbox"),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
    )
    op.create_index("ix_outbox_status", "outbox", ["status"], unique=False)


def downgrade() -> None:
    """Menghapus tabel outbox dan mengembalikan skema jadwal ke revisi 0005."""
    op.drop_index("ix_outbox_status", table_name="outbox")
    op.drop_table("outbox")

    with op.batch_alter_table("jadwal") as batch_op:
        batch_op.drop_column("sequence")

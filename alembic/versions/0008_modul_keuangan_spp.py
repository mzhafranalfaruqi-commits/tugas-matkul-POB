"""Membuat tabel payment_method, billing, dan payment untuk Modul Keuangan (SPP).

Revision ID: 0008_modul_keuangan_spp
Revises: 0007_nilai_grade_history_view
Create Date: 2026-11-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_modul_keuangan_spp"
down_revision: Union[str, None] = "0007_nilai_grade_history_view"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat skema tabel metode pembayaran, tagihan SPP, dan transaksi pembayaran."""
    op.create_table(
        "payment_method",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_payment_method"),
    )
    op.create_index("ix_payment_method_code", "payment_method", ["code"], unique=True)

    op.create_table(
        "billing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nim", sa.String(length=15), nullable=False),
        sa.Column("semester", sa.String(length=5), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "denda",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "unpaid",
                "partial",
                "paid",
                "overdue",
                name="billing_status",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "reminder_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_billing_amount_pos"),
        sa.CheckConstraint("denda >= 0", name="ck_billing_denda_nonneg"),
        sa.CheckConstraint("paid_amount >= 0", name="ck_billing_paid_nonneg"),
        sa.ForeignKeyConstraint(
            ["nim"],
            ["calon_mahasiswa.nim"],
            name="fk_billing_nim",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing"),
        sa.UniqueConstraint("nim", "semester", name="uq_billing_nim_semester"),
    )
    op.create_index("ix_billing_nim", "billing", ["nim"], unique=False)
    op.create_index("ix_billing_semester", "billing", ["semester"], unique=False)
    op.create_index("ix_billing_due_date", "billing", ["due_date"], unique=False)
    op.create_index("ix_billing_status", "billing", ["status"], unique=False)

    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("billing_id", sa.Integer(), nullable=False),
        sa.Column("payment_method_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "success",
                "pending",
                "failed",
                name="payment_status",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "receipt_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_pos"),
        sa.CheckConstraint(
            "source IN ('manual', 'webhook')", name="ck_payment_source_valid"
        ),
        sa.ForeignKeyConstraint(
            ["billing_id"],
            ["billing.id"],
            name="fk_payment_billing_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["payment_method.id"],
            name="fk_payment_method_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment"),
    )
    op.create_index("ix_payment_billing_id", "payment", ["billing_id"], unique=False)
    op.create_index(
        "ix_payment_payment_method_id", "payment", ["payment_method_id"], unique=False
    )
    op.create_index(
        "ix_payment_transaction_id", "payment", ["transaction_id"], unique=True
    )
    op.create_index("ix_payment_paid_at", "payment", ["paid_at"], unique=False)


def downgrade() -> None:
    """Menghapus tabel payment, billing, dan payment_method sesuai urutan FK."""
    op.drop_index("ix_payment_paid_at", table_name="payment")
    op.drop_index("ix_payment_transaction_id", table_name="payment")
    op.drop_index("ix_payment_payment_method_id", table_name="payment")
    op.drop_index("ix_payment_billing_id", table_name="payment")
    op.drop_table("payment")

    op.drop_index("ix_billing_status", table_name="billing")
    op.drop_index("ix_billing_due_date", table_name="billing")
    op.drop_index("ix_billing_semester", table_name="billing")
    op.drop_index("ix_billing_nim", table_name="billing")
    op.drop_table("billing")

    op.drop_index("ix_payment_method_code", table_name="payment_method")
    op.drop_table("payment_method")

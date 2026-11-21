"""Model ORM SQLAlchemy 2.0 untuk Modul Keuangan (SPP): billing, payment, dan payment_method."""

from datetime import date, datetime, timezone
from decimal import Decimal
import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.keuangan import bulatkan_uang
from app.models.pmb import Base, CalonMahasiswa


class BillingStatus(str, enum.Enum):
    """Status pembayaran tagihan SPP mahasiswa."""

    unpaid = "unpaid"
    partial = "partial"
    paid = "paid"
    overdue = "overdue"


class PaymentStatus(str, enum.Enum):
    """Status pencatatan transaksi pembayaran."""

    success = "success"
    pending = "pending"
    failed = "failed"


billing_status_enum = SAEnum(
    BillingStatus, name="billing_status", create_constraint=True
)
payment_status_enum = SAEnum(
    PaymentStatus, name="payment_status", create_constraint=True
)


class PaymentMethod(Base):
    """Master metode pembayaran SPP (Virtual Account, QRIS, Transfer Bank, Tunai)."""

    __tablename__ = "payment_method"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50), default="manual")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    payments: Mapped[list["Payment"]] = relationship(back_populates="payment_method")


class Billing(Base):
    """Tagihan SPP mahasiswa per semester lengkap dengan denda, cicilan, dan status."""

    __tablename__ = "billing"
    __table_args__ = (
        UniqueConstraint("nim", "semester", name="uq_billing_nim_semester"),
        CheckConstraint("amount > 0", name="ck_billing_amount_pos"),
        CheckConstraint("denda >= 0", name="ck_billing_denda_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_billing_paid_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nim: Mapped[str] = mapped_column(
        String(15), ForeignKey("calon_mahasiswa.nim"), index=True
    )
    semester: Mapped[str] = mapped_column(String(5), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    denda: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default=sa_text("0")
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default=sa_text("0")
    )
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[BillingStatus] = mapped_column(
        billing_status_enum, default=BillingStatus.unpaid, index=True
    )
    reminder_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa_text("0")
    )
    last_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    mahasiswa: Mapped["CalonMahasiswa"] = relationship()
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="billing",
        cascade="all, delete-orphan",
        order_by="Payment.paid_at, Payment.id",
    )

    @property
    def total(self) -> Decimal:
        """Total tagihan gabungan pokok SPP dan denda keterlambatan."""
        return bulatkan_uang(Decimal(self.amount) + Decimal(self.denda))

    @property
    def remaining(self) -> Decimal:
        """Sisa tagihan yang masih harus dibayar mahasiswa."""
        sisa = self.total - Decimal(self.paid_amount)
        return bulatkan_uang(sisa if sisa > Decimal("0.00") else Decimal("0.00"))


class Payment(Base):
    """Catatan transaksi pembayaran SPP (manual maupun otomatis via payment gateway webhook)."""

    __tablename__ = "payment"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_pos"),
        CheckConstraint("source IN ('manual', 'webhook')", name="ck_payment_source_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    billing_id: Mapped[int] = mapped_column(
        ForeignKey("billing.id", ondelete="CASCADE"), index=True
    )
    payment_method_id: Mapped[int] = mapped_column(
        ForeignKey("payment_method.id"), index=True
    )
    transaction_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum, default=PaymentStatus.success
    )
    source: Mapped[str] = mapped_column(String(20), default="manual")
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    notes: Mapped[str | None] = mapped_column(String(500), default=None)
    receipt_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    billing: Mapped["Billing"] = relationship(back_populates="payments")
    payment_method: Mapped["PaymentMethod"] = relationship(back_populates="payments")

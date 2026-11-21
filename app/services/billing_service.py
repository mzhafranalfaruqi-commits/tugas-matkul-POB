"""Service layer Modul Keuangan (SPP): billing generator, payment, webhook HMAC, denda, & dashboard."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hmac
import hashlib
import csv
import io
import json
import logging
import os
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.keuangan import (
    bulatkan_uang,
    format_rupiah,
    hitung_denda_keterlambatan,
    hitung_due_date,
    hitung_persentase,
    tentukan_status_pembayaran,
    tentukan_tarif_spp,
)
from app.models.keuangan import (
    Billing,
    BillingStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.models.krs import Notifikasi
from app.models.pmb import CalonMahasiswa, ProgramStudi, StatusPMB
from app.schemas.keuangan import WebhookPaymentIn
from app.services.exceptions import (
    BillingNotFoundError,
    BillingValidationError,
    PaymentConflictError,
    WebhookSignatureError,
)

logger = logging.getLogger("sevima.billing")
receipt_logger = logging.getLogger("sevima.email_receipt")

DEFAULT_WEBHOOK_SECRET = "sevima-webhook-secret-dev"
_WEBHOOK_PAID_STATUSES = frozenset({"paid", "settlement", "capture", "success"})
_WEBHOOK_IGNORED_STATUSES = frozenset(
    {"pending", "failed", "expire", "expired", "cancel", "cancelled", "deny"}
)
_STATUS_TUNGGAKAN = (
    BillingStatus.unpaid,
    BillingStatus.partial,
    BillingStatus.overdue,
)


def get_webhook_secret() -> str:
    """Membaca secret HMAC webhook payment gateway dari environment variable."""
    return os.getenv("PAYMENT_WEBHOOK_SECRET", DEFAULT_WEBHOOK_SECRET)


def compute_webhook_signature(raw_body: bytes, secret: str | None = None) -> str:
    """Menghitung HMAC-SHA256 hex digest atas payload mentah webhook."""
    kunci = (secret if secret is not None else get_webhook_secret()).encode("utf-8")
    return hmac.new(kunci, raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    raw_body: bytes,
    signature: str | None,
    secret: str | None = None,
) -> bool:
    """Memverifikasi header signature webhook secara constant-time."""
    if not signature or not signature.strip():
        return False
    sig_clean = signature.strip()
    if sig_clean.lower().startswith("sha256="):
        sig_clean = sig_clean[7:].strip()
    if not sig_clean:
        return False
    expected = compute_webhook_signature(raw_body, secret=secret)
    return hmac.compare_digest(expected.lower(), sig_clean.lower())


@dataclass(frozen=True)
class EmailReceiptRecord:
    """Rekam jejak email receipt atau pengingat tunggakan SPP (simulasi)."""

    id: str
    jenis: str
    nim: str
    penerima_email: str
    subjek: str
    isi_ringkas: str
    sent_at: datetime


class EmailReceiptPort(Protocol):
    """Port pengiriman email receipt dan reminder pembayaran (Dependency Inversion)."""

    def send_receipt(
        self,
        *,
        nim: str,
        penerima_email: str,
        transaction_id: str,
        semester: str,
        amount: Decimal,
        status: str,
    ) -> EmailReceiptRecord:
        """Mengirim kuitansi pembayaran resmi via email secara idempoten."""

    def send_reminder(
        self,
        *,
        nim: str,
        penerima_email: str,
        semester: str,
        remaining: Decimal,
        due_date: date,
    ) -> EmailReceiptRecord:
        """Mengirim notifikasi pengingat tagihan jatuh tempo / menunggak."""

    def list_records(self) -> list[EmailReceiptRecord]:
        """Mengembalikan daftar seluruh email yang pernah dikirim."""


class LogEmailReceiptSender:
    """Implementasi EmailReceiptPort berbasis logger Python dan riwayat memori."""

    def __init__(self) -> None:
        self._records: list[EmailReceiptRecord] = []
        self._by_key: dict[str, EmailReceiptRecord] = {}

    def send_receipt(
        self,
        *,
        nim: str,
        penerima_email: str,
        transaction_id: str,
        semester: str,
        amount: Decimal,
        status: str,
    ) -> EmailReceiptRecord:
        key = f"receipt:{transaction_id}"
        if key in self._by_key:
            return self._by_key[key]

        rec = EmailReceiptRecord(
            id=uuid4().hex[:12],
            jenis="receipt",
            nim=nim,
            penerima_email=penerima_email,
            subjek=f"[SEVIMA-Mini] Kuitansi Pembayaran SPP Semester {semester}",
            isi_ringkas=(
                f"Pembayaran {format_rupiah(amount)} (Ref: {transaction_id}) "
                f"diterima. Status tagihan: {status}."
            ),
            sent_at=datetime.now(timezone.utc),
        )
        receipt_logger.info(
            "EMAIL RECEIPT ke %s (%s): %s", penerima_email, nim, rec.isi_ringkas
        )
        self._by_key[key] = rec
        self._records.append(rec)
        return rec

    def send_reminder(
        self,
        *,
        nim: str,
        penerima_email: str,
        semester: str,
        remaining: Decimal,
        due_date: date,
    ) -> EmailReceiptRecord:
        rec = EmailReceiptRecord(
            id=uuid4().hex[:12],
            jenis="reminder",
            nim=nim,
            penerima_email=penerima_email,
            subjek=f"[SEVIMA-Mini] Pengingat Tunggakan SPP Semester {semester}",
            isi_ringkas=(
                f"Sisa tagihan SPP sebesar {format_rupiah(remaining)} "
                f"(jatuh tempo {due_date.isoformat()}). Segera lunasi agar KRS tidak diblokir."
            ),
            sent_at=datetime.now(timezone.utc),
        )
        receipt_logger.info(
            "EMAIL REMINDER ke %s (%s): %s", penerima_email, nim, rec.isi_ringkas
        )
        self._records.append(rec)
        return rec

    def list_records(self) -> list[EmailReceiptRecord]:
        return list(reversed(self._records))

    def reset(self) -> None:
        """Mengosongkan riwayat email (berguna untuk isolasi pengujian)."""
        self._records.clear()
        self._by_key.clear()


_default_email_sender = LogEmailReceiptSender()


def get_email_receipt_sender() -> LogEmailReceiptSender:
    """Mengembalikan singleton pengirim email receipt/reminder aplikasi."""
    return _default_email_sender


@dataclass(frozen=True)
class GenerateBillingResult:
    """Ringkasan hasil pembuatan tagihan SPP per semester."""

    semester: str
    due_date: date
    created_count: int
    skipped_count: int
    billings: list[Billing]


@dataclass(frozen=True)
class PaymentResult:
    """Hasil pemrosesan satu transaksi pembayaran SPP."""

    idempotent: bool
    payment: Payment
    billing: Billing
    receipt_sent: bool


@dataclass(frozen=True)
class WebhookResult:
    """Hasil pemrosesan notifikasi webhook dari payment gateway."""

    ok: bool
    action: str
    transaction_id: str
    billing_id: int
    billing_status: BillingStatus
    paid_amount: Decimal
    remaining: Decimal
    receipt_sent: bool


@dataclass(frozen=True)
class LateFeeResult:
    """Hasil kalkulasi denda keterlambatan tagihan SPP."""

    as_of: date
    updated_count: int
    total_denda_ditambahkan: Decimal


@dataclass(frozen=True)
class ReminderResult:
    """Hasil pengiriman pengingat tagihan jatuh tempo / menunggak."""

    as_of: date
    reminded_count: int
    nims: list[str]


class BillingService:
    """Mengelola siklus tagihan SPP, pembayaran manual/webhook, denda, reminder, & dashboard."""

    def __init__(
        self,
        db: Session,
        email_sender: EmailReceiptPort | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self.db = db
        self.email_sender = email_sender or get_email_receipt_sender()
        self.webhook_secret = webhook_secret

    def _mulai_transaksi_terkunci(self) -> bool:
        """Membuka BEGIN IMMEDIATE pada SQLite sebelum SELECT agar transaksi atomik."""
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "sqlite" and not self.db.in_transaction():
            self.db.execute(text("BEGIN IMMEDIATE"))
            return True
        return False

    def _query_billing_lengkap(self, billing_id: int) -> Billing | None:
        """Memuat satu Billing beserta relasi mahasiswa, prodi, dan riwayat pembayarannya."""
        return self.db.execute(
            select(Billing)
            .options(
                joinedload(Billing.mahasiswa).joinedload(CalonMahasiswa.program_studi),
                selectinload(Billing.payments).joinedload(Payment.payment_method),
            )
            .where(Billing.id == billing_id)
        ).scalar_one_or_none()

    def generate_billing(
        self, semester: str, semester_start: date | None = None
    ) -> GenerateBillingResult:
        """Membuat tagihan SPP awal semester secara idempoten untuk seluruh mahasiswa aktif."""
        sem = semester.strip()
        if len(sem) != 5 or not sem.isdigit():
            raise BillingValidationError(
                "Format semester harus 5 digit angka (misalnya '20261')"
            )

        tgl_mulai = semester_start or date.today()
        due_date = hitung_due_date(tgl_mulai)
        started_immediate = False
        created_count = 0
        skipped_count = 0

        try:
            started_immediate = self._mulai_transaksi_terkunci()
            mahasiswa_aktif = self.db.scalars(
                select(CalonMahasiswa)
                .options(joinedload(CalonMahasiswa.program_studi))
                .where(
                    CalonMahasiswa.status == StatusPMB.approved,
                    CalonMahasiswa.nim.is_not(None),
                )
                .order_by(CalonMahasiswa.nim)
            ).all()

            sudah_ada = {
                b.nim: b
                for b in self.db.scalars(
                    select(Billing).where(Billing.semester == sem)
                ).all()
            }

            for mhs in mahasiswa_aktif:
                assert mhs.nim is not None
                if mhs.nim in sudah_ada:
                    skipped_count += 1
                    continue

                prodi_nama = mhs.program_studi.nama if mhs.program_studi else ""
                fakultas = mhs.program_studi.fakultas if mhs.program_studi else ""
                nominal = tentukan_tarif_spp(prodi_nama, fakultas)
                self.db.add(
                    Billing(
                        nim=mhs.nim,
                        semester=sem,
                        amount=nominal,
                        denda=Decimal("0.00"),
                        paid_amount=Decimal("0.00"),
                        due_date=due_date,
                        status=BillingStatus.unpaid,
                    )
                )
                created_count += 1

            self.db.commit()
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

        billings = self.list_billings(semester=sem)
        return GenerateBillingResult(
            semester=sem,
            due_date=due_date,
            created_count=created_count,
            skipped_count=skipped_count,
            billings=billings,
        )

    def process_payment(
        self,
        billing_id: int,
        amount: Decimal | int | float | str,
        method_code: str,
        *,
        transaction_id: str | None = None,
        source: str = "manual",
        notes: str | None = None,
        paid_at: datetime | None = None,
        send_receipt: bool = True,
    ) -> PaymentResult:
        """Mencatat pembayaran SPP (penuh atau cicilan) secara atomik dan idempoten."""
        try:
            nominal = bulatkan_uang(
                amount if isinstance(amount, Decimal) else Decimal(str(amount))
            )
        except Exception as exc:
            raise BillingValidationError("Nominal pembayaran tidak valid") from exc

        if not nominal.is_finite() or nominal <= Decimal("0.00"):
            raise BillingValidationError("Nominal pembayaran harus lebih besar dari nol")

        sumber = source.strip().lower()
        if sumber not in ("manual", "webhook"):
            raise BillingValidationError("Sumber pembayaran harus 'manual' atau 'webhook'")

        method_key = method_code.strip().upper()
        if not method_key:
            raise BillingValidationError("Kode metode pembayaran wajib diisi")

        tx_id = (
            transaction_id.strip()
            if transaction_id and transaction_id.strip()
            else f"PAY-{uuid4().hex[:16].upper()}"
        )

        started_immediate = False
        payment: Payment | None = None
        billing: Billing | None = None
        is_idempotent = False

        try:
            started_immediate = self._mulai_transaksi_terkunci()

            existing = self.db.execute(
                select(Payment)
                .options(
                    joinedload(Payment.payment_method),
                    joinedload(Payment.billing)
                    .joinedload(Billing.mahasiswa)
                    .joinedload(CalonMahasiswa.program_studi),
                    joinedload(Payment.billing)
                    .selectinload(Billing.payments)
                    .joinedload(Payment.payment_method),
                )
                .where(Payment.transaction_id == tx_id)
            ).scalar_one_or_none()
            if existing is not None:
                if (
                    existing.billing_id == billing_id
                    and bulatkan_uang(Decimal(existing.amount)) == nominal
                ):
                    if started_immediate:
                        self.db.rollback()
                    return PaymentResult(
                        idempotent=True,
                        payment=existing,
                        billing=existing.billing,
                        receipt_sent=existing.receipt_sent,
                    )
                raise PaymentConflictError(
                    f"transaction_id '{tx_id}' sudah tercatat untuk tagihan atau nominal berbeda"
                )

            billing = self.db.execute(
                select(Billing)
                .options(
                    joinedload(Billing.mahasiswa).joinedload(
                        CalonMahasiswa.program_studi
                    ),
                    selectinload(Billing.payments).joinedload(Payment.payment_method),
                )
                .where(Billing.id == billing_id)
                .with_for_update()
            ).scalar_one_or_none()
            if billing is None:
                raise BillingNotFoundError(
                    f"Tagihan dengan ID {billing_id} tidak ditemukan"
                )

            if billing.status == BillingStatus.paid:
                raise PaymentConflictError(f"Tagihan #{billing_id} sudah berstatus lunas")

            method = self.db.execute(
                select(PaymentMethod).where(func.upper(PaymentMethod.code) == method_key)
            ).scalar_one_or_none()
            if method is None or not method.is_active:
                raise BillingValidationError(
                    f"Metode pembayaran '{method_code}' tidak ditemukan atau tidak aktif"
                )

            total_terbayar_baru = bulatkan_uang(Decimal(billing.paid_amount) + nominal)
            status_baru_str = tentukan_status_pembayaran(
                billing.total, total_terbayar_baru
            )
            billing.paid_amount = total_terbayar_baru
            billing.status = BillingStatus(status_baru_str)
            billing.updated_at = datetime.now(timezone.utc)

            payment = Payment(
                billing_id=billing.id,
                payment_method_id=method.id,
                transaction_id=tx_id,
                amount=nominal,
                status=PaymentStatus.success,
                source=sumber,
                paid_at=paid_at or datetime.now(timezone.utc),
                notes=notes,
                receipt_sent=False,
            )
            self.db.add(payment)
            self.db.add(
                Notifikasi(
                    nim=billing.nim,
                    pesan=(
                        f"Pembayaran SPP semester {billing.semester} sebesar "
                        f"{format_rupiah(nominal)} ({method.code}) berhasil dicatat. "
                        f"Status tagihan: {billing.status.value}."
                    ),
                )
            )
            self.db.commit()
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

        assert payment is not None and billing is not None
        self.db.refresh(payment)
        _ = payment.payment_method
        billing = self._query_billing_lengkap(billing.id) or billing

        receipt_sent = payment.receipt_sent
        if send_receipt and not receipt_sent:
            try:
                penerima_email = (
                    billing.mahasiswa.email
                    if billing.mahasiswa is not None
                    else f"{billing.nim}@student.example.com"
                )
                self.email_sender.send_receipt(
                    nim=billing.nim,
                    penerima_email=penerima_email,
                    transaction_id=payment.transaction_id,
                    semester=billing.semester,
                    amount=nominal,
                    status=billing.status.value,
                )
                payment.receipt_sent = True
                self.db.commit()
                receipt_sent = True
            except Exception:
                logger.exception(
                    "Gagal mengirim email receipt pasca-commit untuk %s",
                    payment.transaction_id,
                )
                if self.db.in_transaction():
                    self.db.rollback()

        billing = self._query_billing_lengkap(billing.id) or billing
        return PaymentResult(
            idempotent=is_idempotent,
            payment=payment,
            billing=billing,
            receipt_sent=receipt_sent,
        )

    def handle_webhook(
        self, raw_body: bytes, signature: str | None
    ) -> WebhookResult:
        """Memverifikasi signature webhook payment gateway lalu memproses status transaksi."""
        if not verify_webhook_signature(
            raw_body, signature, secret=self.webhook_secret
        ):
            raise WebhookSignatureError(
                "Signature HMAC webhook payment gateway tidak valid atau hilang"
            )

        try:
            payload_dict = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BillingValidationError(
                "Payload webhook bukan JSON UTF-8 yang valid"
            ) from exc

        try:
            payload = WebhookPaymentIn.model_validate(payload_dict)
        except ValidationError as exc:
            raise BillingValidationError(
                f"Payload webhook tidak valid: {exc.errors()[0]['msg']}"
            ) from exc

        status_norm = payload.status.strip().lower()
        if status_norm in _WEBHOOK_PAID_STATUSES:
            res = self.process_payment(
                billing_id=payload.billing_id,
                amount=payload.amount,
                method_code=payload.method,
                transaction_id=payload.transaction_id,
                source="webhook",
                notes=payload.notes or f"Webhook payment gateway ({status_norm})",
                send_receipt=True,
            )
            return WebhookResult(
                ok=True,
                action="idempotent" if res.idempotent else "processed",
                transaction_id=res.payment.transaction_id,
                billing_id=res.billing.id,
                billing_status=res.billing.status,
                paid_amount=bulatkan_uang(Decimal(res.billing.paid_amount)),
                remaining=res.billing.remaining,
                receipt_sent=res.receipt_sent,
            )

        if status_norm in _WEBHOOK_IGNORED_STATUSES:
            billing = self.db.get(Billing, payload.billing_id)
            if billing is None:
                raise BillingNotFoundError(
                    f"Tagihan dengan ID {payload.billing_id} tidak ditemukan"
                )
            return WebhookResult(
                ok=True,
                action=f"ignored_{status_norm}",
                transaction_id=payload.transaction_id,
                billing_id=billing.id,
                billing_status=billing.status,
                paid_amount=bulatkan_uang(Decimal(billing.paid_amount)),
                remaining=billing.remaining,
                receipt_sent=False,
            )

        raise BillingValidationError(
            f"Status notifikasi webhook '{payload.status}' tidak dikenali"
        )

    def calculate_late_fees(
        self, as_of: date | None = None, semester: str | None = None
    ) -> LateFeeResult:
        """Menghitung denda keterlambatan dan menandai tagihan lewat jatuh tempo menjadi overdue."""
        ref_date = as_of or date.today()
        started_immediate = False
        updated_count = 0
        total_ditambahkan = Decimal("0.00")

        try:
            started_immediate = self._mulai_transaksi_terkunci()
            stmt = select(Billing).where(
                Billing.status != BillingStatus.paid,
                Billing.due_date < ref_date,
            )
            if semester:
                stmt = stmt.where(Billing.semester == semester)

            billings = self.db.scalars(stmt.order_by(Billing.id)).all()
            now_utc = datetime.now(timezone.utc)

            for b in billings:
                denda_baru = hitung_denda_keterlambatan(
                    Decimal(b.amount), b.due_date, ref_date
                )
                denda_lama = bulatkan_uang(Decimal(b.denda))
                berubah = False

                if denda_baru > denda_lama:
                    total_ditambahkan += denda_baru - denda_lama
                    b.denda = denda_baru
                    berubah = True

                if b.status != BillingStatus.overdue:
                    b.status = BillingStatus.overdue
                    berubah = True

                if berubah:
                    b.updated_at = now_utc
                    updated_count += 1

            self.db.commit()
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

        return LateFeeResult(
            as_of=ref_date,
            updated_count=updated_count,
            total_denda_ditambahkan=bulatkan_uang(total_ditambahkan),
        )

    def send_overdue_reminders(
        self, as_of: date | None = None
    ) -> ReminderResult:
        """Menghitung denda lalu mengirim notifikasi pengingat ke penunggak/mendekati jatuh tempo."""
        ref_date = as_of or date.today()
        self.calculate_late_fees(as_of=ref_date)

        batas_pengingat = ref_date + timedelta(days=3)
        started_immediate = False
        targets: list[tuple[str, str, str, Decimal, date]] = []

        try:
            started_immediate = self._mulai_transaksi_terkunci()
            billings = self.db.scalars(
                select(Billing)
                .options(joinedload(Billing.mahasiswa))
                .where(
                    Billing.status.in_(_STATUS_TUNGGAKAN),
                    (Billing.status == BillingStatus.overdue)
                    | (Billing.due_date <= batas_pengingat),
                )
                .order_by(Billing.nim, Billing.semester)
            ).all()

            now_utc = datetime.now(timezone.utc)
            for b in billings:
                email = (
                    b.mahasiswa.email
                    if b.mahasiswa is not None
                    else f"{b.nim}@student.example.com"
                )
                sisa = b.remaining
                self.db.add(
                    Notifikasi(
                        nim=b.nim,
                        pesan=(
                            f"Pengingat SPP semester {b.semester}: sisa tagihan "
                            f"{format_rupiah(sisa)} (jatuh tempo {b.due_date.isoformat()})."
                        ),
                    )
                )
                b.reminder_count += 1
                b.last_reminder_at = now_utc
                b.updated_at = now_utc
                targets.append((b.nim, email, b.semester, sisa, b.due_date))

            self.db.commit()
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

        for nim, email, sem, sisa, due in targets:
            try:
                self.email_sender.send_reminder(
                    nim=nim,
                    penerima_email=email,
                    semester=sem,
                    remaining=sisa,
                    due_date=due,
                )
            except Exception:
                logger.exception("Gagal mengirim email reminder ke %s", nim)

        return ReminderResult(
            as_of=ref_date,
            reminded_count=len(targets),
            nims=[t[0] for t in targets],
        )

    def get_billing(self, billing_id: int) -> Billing:
        """Mengambil detail satu tagihan SPP berdasarkan ID (404 jika tidak ada)."""
        billing = self._query_billing_lengkap(billing_id)
        if billing is None:
            raise BillingNotFoundError(
                f"Tagihan dengan ID {billing_id} tidak ditemukan"
            )
        return billing

    def list_billings(
        self,
        *,
        nim: str | None = None,
        semester: str | None = None,
        status: BillingStatus | None = None,
    ) -> list[Billing]:
        """Mengambil daftar tagihan SPP beserta detail pembayaran dan mahasiswa."""
        stmt = (
            select(Billing)
            .options(
                joinedload(Billing.mahasiswa).joinedload(CalonMahasiswa.program_studi),
                selectinload(Billing.payments).joinedload(Payment.payment_method),
            )
            .order_by(Billing.semester.desc(), Billing.nim, Billing.id)
        )
        if nim:
            stmt = stmt.where(Billing.nim == nim)
        if semester:
            stmt = stmt.where(Billing.semester == semester)
        if status is not None:
            stmt = stmt.where(Billing.status == status)
        return list(self.db.scalars(stmt).unique().all())

    def list_payment_methods(self) -> list[PaymentMethod]:
        """Mengembalikan daftar seluruh metode pembayaran terurut berdasarkan kode."""
        return list(
            self.db.scalars(select(PaymentMethod).order_by(PaymentMethod.code)).all()
        )

    def get_mahasiswa_summary(self, nim: str) -> dict[str, Any]:
        """Mengambil ringkasan total tagihan, sudah bayar, sisa, dan status blokir KRS per NIM."""
        mhs = self.db.execute(
            select(CalonMahasiswa)
            .options(joinedload(CalonMahasiswa.program_studi))
            .where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mhs is None:
            raise BillingNotFoundError(f"Mahasiswa dengan NIM {nim} tidak ditemukan")

        billings = self.list_billings(nim=nim)
        total_tagihan = bulatkan_uang(
            sum((b.total for b in billings), Decimal("0.00"))
        )
        sudah_bayar = bulatkan_uang(
            sum((Decimal(b.paid_amount) for b in billings), Decimal("0.00"))
        )
        sisa = bulatkan_uang(sum((b.remaining for b in billings), Decimal("0.00")))
        krs_blocked = any(b.status in _STATUS_TUNGGAKAN for b in billings)

        statuses = {b.status for b in billings}
        if BillingStatus.overdue in statuses:
            status_ringkas = "overdue"
        elif BillingStatus.partial in statuses:
            status_ringkas = "partial"
        elif BillingStatus.unpaid in statuses:
            status_ringkas = "unpaid"
        elif billings:
            status_ringkas = "paid"
        else:
            status_ringkas = "no_billing"

        return {
            "nim": nim,
            "nama_lengkap": mhs.nama_lengkap,
            "program_studi": (
                mhs.program_studi.nama if mhs.program_studi is not None else "-"
            ),
            "total_tagihan": f"{total_tagihan:.2f}",
            "sudah_bayar": f"{sudah_bayar:.2f}",
            "sisa": f"{sisa:.2f}",
            "status_ringkas": status_ringkas,
            "krs_blocked": krs_blocked,
            "billings": billings,
        }

    def get_dashboard_data(self, as_of: date | None = None) -> dict[str, Any]:
        """Menghitung seluruh agregasi dashboard keuangan secara real-time."""
        _ = as_of
        billings = self.list_billings()
        prodis = list(
            self.db.scalars(select(ProgramStudi).order_by(ProgramStudi.kode)).all()
        )
        students = list(
            self.db.scalars(
                select(CalonMahasiswa)
                .options(joinedload(CalonMahasiswa.program_studi))
                .where(
                    CalonMahasiswa.status == StatusPMB.approved,
                    CalonMahasiswa.nim.is_not(None),
                )
                .order_by(CalonMahasiswa.nim)
            ).all()
        )
        payments = list(
            self.db.scalars(
                select(Payment)
                .where(Payment.status == PaymentStatus.success)
                .order_by(Payment.paid_at, Payment.id)
            ).all()
        )

        billings_by_nim: dict[str, list[Billing]] = defaultdict(list)
        for b in billings:
            billings_by_nim[b.nim].append(b)

        per_mahasiswa: list[dict[str, Any]] = []
        prodi_students: dict[int, list[dict[str, Any]]] = defaultdict(list)

        for mhs in students:
            assert mhs.nim is not None
            mhs_bills = billings_by_nim.get(mhs.nim, [])
            tot = bulatkan_uang(sum((b.total for b in mhs_bills), Decimal("0.00")))
            bayar = bulatkan_uang(
                sum((Decimal(b.paid_amount) for b in mhs_bills), Decimal("0.00"))
            )
            sisa = bulatkan_uang(sum((b.remaining for b in mhs_bills), Decimal("0.00")))
            blocked = any(b.status in _STATUS_TUNGGAKAN for b in mhs_bills)
            statuses = {b.status for b in mhs_bills}
            if BillingStatus.overdue in statuses:
                ringkas = "overdue"
            elif BillingStatus.partial in statuses:
                ringkas = "partial"
            elif BillingStatus.unpaid in statuses:
                ringkas = "unpaid"
            elif mhs_bills:
                ringkas = "paid"
            else:
                ringkas = "no_billing"

            item = {
                "nim": mhs.nim,
                "nama_lengkap": mhs.nama_lengkap,
                "program_studi": (
                    mhs.program_studi.nama if mhs.program_studi is not None else "-"
                ),
                "total_tagihan": f"{tot:.2f}",
                "sudah_bayar": f"{bayar:.2f}",
                "sisa": f"{sisa:.2f}",
                "status_ringkas": ringkas,
                "krs_blocked": blocked,
                "billings": mhs_bills,
            }
            per_mahasiswa.append(item)
            if mhs_bills:
                prodi_students[mhs.program_studi_id].append(
                    {
                        "total": tot,
                        "bayar": bayar,
                        "lunas": not blocked,
                    }
                )

        per_prodi: list[dict[str, Any]] = []
        for prodi in prodis:
            entri = prodi_students.get(prodi.id, [])
            jml_mhs = len(entri)
            jml_lunas = sum(1 for e in entri if e["lunas"])
            tot_tag = bulatkan_uang(
                sum((e["total"] for e in entri), Decimal("0.00"))
            )
            tot_byr = bulatkan_uang(
                sum((e["bayar"] for e in entri), Decimal("0.00"))
            )
            rate = hitung_persentase(Decimal(jml_lunas), Decimal(jml_mhs))
            per_prodi.append(
                {
                    "kode_prodi": prodi.kode,
                    "nama_prodi": prodi.nama,
                    "total_mahasiswa": jml_mhs,
                    "mahasiswa_lunas": jml_lunas,
                    "total_tagihan": f"{tot_tag:.2f}",
                    "total_terbayar": f"{tot_byr:.2f}",
                    "collection_rate_persen": f"{rate:.2f}",
                }
            )

        bulanan_nominal: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        bulanan_count: dict[str, int] = defaultdict(int)
        for p in payments:
            key = f"{p.paid_at.year:04d}-{p.paid_at.month:02d}"
            bulanan_nominal[key] += Decimal(p.amount)
            bulanan_count[key] += 1

        grafik_bulanan = [
            {
                "bulan": bulan,
                "total_pembayaran": f"{bulatkan_uang(bulanan_nominal[bulan]):.2f}",
                "jumlah_transaksi": bulanan_count[bulan],
            }
            for bulan in sorted(bulanan_nominal.keys())
        ]

        total_tagihan_all = bulatkan_uang(
            sum((b.total for b in billings), Decimal("0.00"))
        )
        total_terbayar_all = bulatkan_uang(
            sum((Decimal(b.paid_amount) for b in billings), Decimal("0.00"))
        )
        total_tunggakan_all = bulatkan_uang(
            sum((b.remaining for b in billings), Decimal("0.00"))
        )

        mhs_bertagihan = [m for m in per_mahasiswa if m["billings"]]
        mhs_lunas_all = sum(1 for m in mhs_bertagihan if not m["krs_blocked"])
        overall_rate = hitung_persentase(
            Decimal(mhs_lunas_all), Decimal(len(mhs_bertagihan))
        )

        ringkasan = {
            "total_tagihan": f"{total_tagihan_all:.2f}",
            "total_terbayar": f"{total_terbayar_all:.2f}",
            "total_tunggakan": f"{total_tunggakan_all:.2f}",
            "collection_rate_persen": f"{overall_rate:.2f}",
            "jumlah_billing": len(billings),
            "jumlah_paid": sum(1 for b in billings if b.status == BillingStatus.paid),
            "jumlah_partial": sum(
                1 for b in billings if b.status == BillingStatus.partial
            ),
            "jumlah_unpaid": sum(
                1 for b in billings if b.status == BillingStatus.unpaid
            ),
            "jumlah_overdue": sum(
                1 for b in billings if b.status == BillingStatus.overdue
            ),
            "jumlah_krs_blocked": sum(1 for m in per_mahasiswa if m["krs_blocked"]),
        }

        return {
            "generated_at": datetime.now(timezone.utc),
            "ringkasan": ringkasan,
            "per_mahasiswa": per_mahasiswa,
            "per_program_studi": per_prodi,
            "grafik_bulanan": grafik_bulanan,
        }

    def export_payment_csv(self) -> str:
        """Mengekspor data pembayaran masuk dan sisa tunggakan ke format CSV (nim,jumlah,tanggal,status)."""
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["nim", "jumlah", "tanggal", "status"])

        billings = self.list_billings()
        for b in billings:
            for p in b.payments:
                if p.status == PaymentStatus.success:
                    writer.writerow(
                        [
                            b.nim,
                            f"{bulatkan_uang(Decimal(p.amount)):.2f}",
                            p.paid_at.date().isoformat(),
                            "paid",
                        ]
                    )
            sisa = b.remaining
            if sisa > Decimal("0.00"):
                status_sisa = (
                    "overdue"
                    if b.status == BillingStatus.overdue
                    else "unpaid"
                )
                writer.writerow(
                    [
                        b.nim,
                        f"{sisa:.2f}",
                        b.due_date.isoformat(),
                        status_sisa,
                    ]
                )

        return buf.getvalue()

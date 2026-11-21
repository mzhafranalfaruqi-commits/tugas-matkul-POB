"""Implementasi konkret lima validator aturan pengisian KRS termasuk blokir tunggakan SPP."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.keuangan import format_rupiah
from app.models.keuangan import Billing, BillingStatus
from app.models.krs import MataKuliah
from app.services.krs_queries import prasyarat_belum_lulus
from app.validators.base import KRSContext, ValidationResult, Validator

MAX_SKS = 24
STATUS_TUNGGAKAN_KRS = (
    BillingStatus.unpaid,
    BillingStatus.partial,
    BillingStatus.overdue,
)


def cek_tunggakan_krs(db: Session | None, nim: str) -> str | None:
    """Mengembalikan pesan blokir KRS bila mahasiswa masih memiliki tagihan SPP tertunggak."""
    if db is None:
        return None

    tunggakan = db.scalars(
        select(Billing)
        .where(Billing.nim == nim, Billing.status.in_(STATUS_TUNGGAKAN_KRS))
        .order_by(Billing.semester)
    ).all()
    if not tunggakan:
        return None

    total_sisa = sum((b.remaining for b in tunggakan), Decimal("0.00"))
    semesters = sorted({b.semester for b in tunggakan})
    return (
        f"KRS diblokir: mahasiswa memiliki tunggakan SPP sebesar "
        f"{format_rupiah(total_sisa)} (semester {', '.join(semesters)})"
    )


def bentrok(a: MataKuliah, b: MataKuliah) -> bool:
    """Mendeteksi irisan interval jadwal dua mata kuliah (kuliah bersambung diperbolehkan)."""
    return (
        a.hari == b.hari
        and a.jam_mulai < b.jam_selesai
        and b.jam_mulai < a.jam_selesai
    )


class BillingArrearsValidator(Validator):
    """Memblokir pengisian KRS bila mahasiswa masih memiliki tagihan SPP belum lunas."""

    def check(self, ctx: KRSContext) -> ValidationResult:
        pesan = cek_tunggakan_krs(ctx.db, ctx.nim)
        if pesan is not None:
            return ValidationResult(False, pesan)
        return ValidationResult(True)


class DuplicateValidator(Validator):
    """Menolak penambahan mata kuliah yang sudah terdaftar dalam KRS aktif."""

    def check(self, ctx: KRSContext) -> ValidationResult:
        if any(d.kode_mk == ctx.mk_baru.kode_mk for d in ctx.details):
            return ValidationResult(False, f"Sudah ada di KRS: {ctx.mk_baru.nama}")
        return ValidationResult(True)


class SKSValidator(Validator):
    """Menjaga total SKS dalam satu semester tidak melebihi batas MAX_SKS (24)."""

    def check(self, ctx: KRSContext) -> ValidationResult:
        total = sum(d.matakuliah.sks for d in ctx.details) + ctx.mk_baru.sks
        if total > MAX_SKS:
            return ValidationResult(
                False, f"Total SKS {total} melebihi batas {MAX_SKS}"
            )
        return ValidationResult(True)


class PrerequisiteValidator(Validator):
    """Memeriksa kelulusan seluruh mata kuliah prasyarat pada semester sebelumnya."""

    def check(self, ctx: KRSContext) -> ValidationResult:
        kurang = prasyarat_belum_lulus(
            ctx.db, ctx.nim, ctx.mk_baru.kode_mk, ctx.semester
        )
        if kurang:
            return ValidationResult(
                False, f"Prasyarat tidak terpenuhi: {', '.join(kurang)}"
            )
        return ValidationResult(True)


class ConflictValidator(Validator):
    """Memastikan mata kuliah baru tidak bertumpuk jadwal dengan MK lain di KRS."""

    def check(self, ctx: KRSContext) -> ValidationResult:
        for detail in ctx.details:
            if bentrok(detail.matakuliah, ctx.mk_baru):
                return ValidationResult(
                    False,
                    f"Jadwal bentrok: {ctx.mk_baru.nama} dengan {detail.matakuliah.nama}",
                )
        return ValidationResult(True)


def default_krs_validators() -> list[Validator]:
    """Mengembalikan urutan validator baku: blokir tunggakan & aturan tercepat di depan."""
    return [
        BillingArrearsValidator(),
        DuplicateValidator(),
        SKSValidator(),
        PrerequisiteValidator(),
        ConflictValidator(),
    ]

"""Implementasi konkret empat validator aturan pengisian KRS."""

from app.models.krs import MataKuliah
from app.services.krs_queries import prasyarat_belum_lulus
from app.validators.base import KRSContext, ValidationResult, Validator

MAX_SKS = 24


def bentrok(a: MataKuliah, b: MataKuliah) -> bool:
    """Mendeteksi irisan interval jadwal dua mata kuliah (kuliah bersambung diperbolehkan)."""
    return (
        a.hari == b.hari
        and a.jam_mulai < b.jam_selesai
        and b.jam_mulai < a.jam_selesai
    )


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
    """Mengembalikan urutan validator baku: paling murah & spesifik di depan."""
    return [
        DuplicateValidator(),
        SKSValidator(),
        PrerequisiteValidator(),
        ConflictValidator(),
    ]

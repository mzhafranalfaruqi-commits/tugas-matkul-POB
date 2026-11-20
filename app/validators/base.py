"""Abstraksi dasar pola Chain of Responsibility untuk validasi KRS."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.krs import KRSDetail, MataKuliah


@dataclass(frozen=True)
class ValidationResult:
    """Hasil immutabel dari satu langkah atau rantai validasi."""

    ok: bool
    message: str = ""


@dataclass
class KRSContext:
    """Objek konteks tunggal yang dibawa sepanjang rantai validator."""

    nim: str
    semester: str
    details: list[KRSDetail]
    mk_baru: MataKuliah
    db: Session


class Validator(ABC):
    """Abstract base class validator dengan Template Method untuk merantai aturan."""

    _next: "Validator | None" = None

    def set_next(self, nxt: "Validator") -> "Validator":
        """Menyambungkan validator berikutnya dalam rantai."""
        self._next = nxt
        return nxt

    def validate(self, ctx: KRSContext) -> ValidationResult:
        """Menjalankan aturan saat ini dan berhenti segera bila gagal (fail-fast)."""
        hasil = self.check(ctx)
        if not hasil.ok or self._next is None:
            return hasil
        return self._next.validate(ctx)

    @abstractmethod
    def check(self, ctx: KRSContext) -> ValidationResult:
        """Memeriksa satu aturan bisnis spesifik dan mengembalikan ValidationResult."""


def build_chain(validators: list[Validator]) -> Validator:
    """Merangkai daftar validator secara berurutan dan mengembalikan simpul awal."""
    if not validators:
        raise ValueError("Daftar validator tidak boleh kosong")

    for current, nxt in zip(validators, validators[1:]):
        current.set_next(nxt)
    return validators[0]

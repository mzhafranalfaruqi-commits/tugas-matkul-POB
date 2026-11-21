"""Fungsi murni perhitungan IPS dan IPK berbasis aritmetika Decimal presisi tinggi."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

DUA_DESIMAL = Decimal("0.01")


@dataclass(frozen=True)
class Skala:
    """Representasi aturan bobot dan status kelulusan untuk satu nilai huruf."""

    bobot: Decimal
    lulus: bool


@dataclass(frozen=True)
class NilaiRecord:
    """Representasi satu baris nilai mahasiswa yang sudah terisi."""

    kode_mk: str
    semester: str
    sks: int
    huruf: str


def _rata(records: Sequence[NilaiRecord], skala: Mapping[str, Skala]) -> Decimal:
    """Menghitung rata-rata tertimbang SKS dan membulatkan ONCE di akhir (ROUND_HALF_UP)."""
    total_sks = sum(r.sks for r in records)
    if total_sks == 0:
        return Decimal("0.00")

    mutu = sum((skala[r.huruf].bobot * r.sks for r in records), Decimal(0))
    return (mutu / Decimal(total_sks)).quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)


def hitung_ips(
    records: Sequence[NilaiRecord],
    semester: str,
    skala: Mapping[str, Skala],
) -> Decimal:
    """Menghitung IPS dari SELURUH MK ber-nilai pada `semester` tertentu (termasuk E & D)."""
    pada_semester = [r for r in records if r.semester == semester]
    return _rata(pada_semester, skala)


def hitung_ipk(
    records: Sequence[NilaiRecord],
    skala: Mapping[str, Skala],
) -> Decimal:
    """Menghitung IPK: ambil bobot terbaik per kode_mk dulu, lalu saring hanya yang lulus."""
    terbaik: dict[str, NilaiRecord] = {}
    for r in records:
        if (
            r.kode_mk not in terbaik
            or skala[r.huruf].bobot > skala[terbaik[r.kode_mk].huruf].bobot
        ):
            terbaik[r.kode_mk] = r

    hanya_lulus = [r for r in terbaik.values() if skala[r.huruf].lulus]
    return _rata(hanya_lulus, skala)

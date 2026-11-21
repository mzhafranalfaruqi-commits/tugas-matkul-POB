"""Fungsi murni perhitungan IPS, IPK, transkrip, dan predikat berbasis Decimal."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

DUA_DESIMAL = Decimal("0.01")

_LABEL_TIPE_SEMESTER = {
    "1": "Ganjil",
    "2": "Genap",
    "3": "Pendek",
}


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


@dataclass(frozen=True)
class RekordNilaiLengkap:
    """Representasi rekord nilai lengkap dengan nama mata kuliah untuk transkrip."""

    kode_mk: str
    nama_mk: str
    semester: str
    sks: int
    huruf: str
    record_id: int = 0


@dataclass(frozen=True)
class BarisNilaiTranskrip:
    """Satu baris mata kuliah yang ditampilkan pada tabel semester transkrip."""

    kode_mk: str
    nama_mk: str
    semester: str
    sks: int
    huruf: str
    bobot: Decimal
    mutu: Decimal
    lulus: bool
    dipakai_ipk: bool


@dataclass(frozen=True)
class SemesterTranskrip:
    """Kelompok mata kuliah dan rekap IPS untuk satu semester di transkrip."""

    semester: str
    label_semester: str
    items: tuple[BarisNilaiTranskrip, ...]
    total_sks: int
    total_mutu: Decimal
    ips: Decimal


@dataclass(frozen=True)
class RingkasanTranskrip:
    """Hasil agregasi seluruh semester, total SKS, IPK, dan predikat kelulusan."""

    semesters: tuple[SemesterTranskrip, ...]
    total_sks_tempuh: int
    total_sks_lulus: int
    total_mutu_lulus: Decimal
    ipk: Decimal
    predikat: str


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


def format_label_semester(semester: str) -> str:
    """Mengubah kode semester YYYYN (mis. '20241') menjadi label manusia yang terbaca."""
    if len(semester) == 5 and semester.isdigit():
        tipe = _LABEL_TIPE_SEMESTER.get(semester[4])
        if tipe is not None:
            tahun = int(semester[:4])
            return f"{tahun}/{tahun + 1} {tipe}"
    return semester


def tentukan_predikat(ipk: Decimal, total_sks_lulus: int) -> str:
    """Menentukan predikat kelulusan berdasarkan IPK kumulatif dan SKS lulus."""
    if total_sks_lulus <= 0:
        return "Belum Memenuhi Predikat"
    if ipk >= Decimal("3.50"):
        return "Cum Laude"
    if ipk >= Decimal("3.00"):
        return "Sangat Memuaskan"
    if ipk >= Decimal("2.50"):
        return "Memuaskan"
    if ipk >= Decimal("2.00"):
        return "Cukup"
    return "Belum Memenuhi Syarat Kelulusan"


def bangun_ringkasan_transkrip(
    records: Sequence[RekordNilaiLengkap],
    skala: Mapping[str, Skala],
) -> RingkasanTranskrip:
    """Menyusun catatan transkrip per semester, tanda MK dipakai IPK, total SKS, dan predikat."""
    terurut = sorted(records, key=lambda r: (r.semester, r.kode_mk, r.record_id))
    terbaik_idx: dict[str, int] = {}
    for idx, rec in enumerate(terurut):
        if (
            rec.kode_mk not in terbaik_idx
            or skala[rec.huruf].bobot > skala[terurut[terbaik_idx[rec.kode_mk]].huruf].bobot
        ):
            terbaik_idx[rec.kode_mk] = idx

    indeks_ipk = {
        idx for idx in terbaik_idx.values() if skala[terurut[idx].huruf].lulus
    }

    nilai_records = [
        NilaiRecord(
            kode_mk=rec.kode_mk,
            semester=rec.semester,
            sks=rec.sks,
            huruf=rec.huruf,
        )
        for rec in terurut
    ]

    baris_per_semester: dict[str, list[BarisNilaiTranskrip]] = defaultdict(list)
    semua_baris: list[BarisNilaiTranskrip] = []
    for idx, rec in enumerate(terurut):
        info_skala = skala[rec.huruf]
        bobot = info_skala.bobot.quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)
        mutu = (bobot * rec.sks).quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)
        baris = BarisNilaiTranskrip(
            kode_mk=rec.kode_mk,
            nama_mk=rec.nama_mk,
            semester=rec.semester,
            sks=rec.sks,
            huruf=rec.huruf,
            bobot=bobot,
            mutu=mutu,
            lulus=info_skala.lulus,
            dipakai_ipk=(idx in indeks_ipk),
        )
        baris_per_semester[rec.semester].append(baris)
        semua_baris.append(baris)

    semesters = tuple(
        SemesterTranskrip(
            semester=sem,
            label_semester=format_label_semester(sem),
            items=tuple(items),
            total_sks=sum(item.sks for item in items),
            total_mutu=sum((item.mutu for item in items), Decimal("0.00")).quantize(
                DUA_DESIMAL, rounding=ROUND_HALF_UP
            ),
            ips=hitung_ips(nilai_records, sem, skala),
        )
        for sem, items in baris_per_semester.items()
    )

    total_sks_tempuh = sum(item.sks for item in semua_baris)
    baris_lulus = [item for item in semua_baris if item.dipakai_ipk]
    total_sks_lulus = sum(item.sks for item in baris_lulus)
    total_mutu_lulus = sum(
        (item.mutu for item in baris_lulus), Decimal("0.00")
    ).quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)
    ipk = hitung_ipk(nilai_records, skala)
    predikat = tentukan_predikat(ipk, total_sks_lulus)

    return RingkasanTranskrip(
        semesters=semesters,
        total_sks_tempuh=total_sks_tempuh,
        total_sks_lulus=total_sks_lulus,
        total_mutu_lulus=total_mutu_lulus,
        ipk=ipk,
        predikat=predikat,
    )

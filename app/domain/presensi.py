"""Fungsi murni domain Presensi (QR Code), geofencing Haversine, dan AI Attendance Pattern Analyzer."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, ROUND_HALF_UP
import math

from app.domain.gpa import DUA_DESIMAL

MIN_PRESENSI_PERSEN = Decimal("75.00")
BATAS_HADIR_MENIT = 15
BATAS_TERLAMBAT_MENIT = 30
EARTH_RADIUS_METERS = 6_371_000.0

NAMA_HARI: dict[int, str] = {
    1: "Senin",
    2: "Selasa",
    3: "Rabu",
    4: "Kamis",
    5: "Jumat",
    6: "Sabtu",
    7: "Minggu",
}

_PETA_HARI_STR: dict[str, int] = {
    "1": 1,
    "senin": 1,
    "monday": 1,
    "mon": 1,
    "2": 2,
    "selasa": 2,
    "tuesday": 2,
    "tue": 2,
    "3": 3,
    "rabu": 3,
    "wednesday": 3,
    "wed": 3,
    "4": 4,
    "kamis": 4,
    "thursday": 4,
    "thu": 4,
    "5": 5,
    "jumat": 5,
    "jum'at": 5,
    "friday": 5,
    "fri": 5,
    "6": 6,
    "sabtu": 6,
    "saturday": 6,
    "sat": 6,
    "7": 7,
    "minggu": 7,
    "ahad": 7,
    "sunday": 7,
    "sun": 7,
}

_STATUS_HADIR = frozenset({"hadir", "present"})
_STATUS_TERLAMBAT = frozenset({"terlambat", "late"})
_STATUS_IZIN = frozenset({"izin", "excused", "sakit"})
_STATUS_ALPHA = frozenset({"alpha", "absent", "tidak_hadir", "mangkir"})


@dataclass(frozen=True)
class RekordPresensiInput:
    """Satu entri presensi mahasiswa pada sesi pertemuan kelas tertentu."""

    nim: str
    kelas: str
    hari: int
    jam_mulai: time
    status: str
    nama: str | None = None
    tanggal: date | None = None


@dataclass(frozen=True)
class RingkasanMahasiswaPresensi:
    """Rekap persentase kehadiran satu mahasiswa across seluruh sesi."""

    nim: str
    nama: str | None
    total_sesi: int
    hadir: int
    terlambat: int
    izin: int
    alpha: int
    persentase: Decimal
    warning: bool


@dataclass(frozen=True)
class PolaHariJamAbsen:
    """Temuan pola tingkat ketidakhadiran tinggi pada kelas, hari, dan jam tertentu."""

    kelas: str
    hari: int
    nama_hari: str
    jam_mulai: str
    slot_waktu: str
    total_rekord: int
    jumlah_absen: int
    absen_rate_persen: Decimal


@dataclass(frozen=True)
class HasilAnalisisPresensi:
    """Hasil analisis pola kehadiran mahasiswa dan kelas secara deterministik."""

    total_rekord: int
    total_mahasiswa: int
    per_mahasiswa: tuple[RingkasanMahasiswaPresensi, ...]
    warning_mahasiswa: tuple[RingkasanMahasiswaPresensi, ...]
    pola_hari_jam: tuple[PolaHariJamAbsen, ...]
    insights: tuple[str, ...]
    actions: tuple[str, ...]


def tentukan_status_kehadiran(menit_dari_mulai: float) -> str:
    """Menentukan status 'hadir' (<=15 mnt) atau 'terlambat' (<=30 mnt) dari awal kelas."""
    if not math.isfinite(menit_dari_mulai):
        raise ValueError("Selisih waktu tidak valid")
    if menit_dari_mulai < 0:
        raise ValueError("Scan belum dapat dilakukan sebelum sesi kelas dimulai")
    if menit_dari_mulai > BATAS_TERLAMBAT_MENIT:
        raise ValueError(
            f"Batas keterlambatan {BATAS_TERLAMBAT_MENIT} menit telah terlewati"
        )
    if menit_dari_mulai <= BATAS_HADIR_MENIT:
        return "hadir"
    return "terlambat"


def hitung_persentase_kehadiran(jumlah_hadir: int, total_sesi: int) -> Decimal:
    """Menghitung persentase kehadiran (0.00..100.00) dibulatkan ROUND_HALF_UP."""
    if total_sesi <= 0 or jumlah_hadir <= 0:
        return Decimal("0.00")
    if jumlah_hadir >= total_sesi:
        return Decimal("100.00")
    rasio = (Decimal(jumlah_hadir) / Decimal(total_sesi)) * Decimal("100")
    return rasio.quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)


def hitung_jarak_haversine_meter(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Menghitung jarak permukaan bumi (meter) antara dua koordinat GPS via Haversine."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_METERS * c


def normalisasi_hari(hari: int | str) -> int:
    """Menormalisasi kode hari (1..7) atau nama hari Indonesia/Inggris menjadi 1..7."""
    if isinstance(hari, bool):
        raise ValueError("Nilai hari tidak boleh boolean")
    if isinstance(hari, int):
        if 1 <= hari <= 7:
            return hari
        raise ValueError(f"Kode hari di luar rentang 1..7: {hari}")
    key = str(hari).strip().lower()
    if key in _PETA_HARI_STR:
        return _PETA_HARI_STR[key]
    raise ValueError(f"Nama hari tidak dikenali: {hari!r}")


def label_slot_waktu(jam: time) -> str:
    """Mengelompokkan jam mulai kuliah ke label slot waktu harian."""
    if jam < time(12, 0):
        return "pagi"
    if jam < time(15, 0):
        return "siang"
    if jam < time(18, 0):
        return "sore"
    return "malam"


def _normalisasi_status(status: str) -> str:
    """Menormalisasi status presensi ke salah satu dari hadir/terlambat/izin/alpha."""
    norm = status.strip().lower()
    if norm in _STATUS_HADIR:
        return "hadir"
    if norm in _STATUS_TERLAMBAT:
        return "terlambat"
    if norm in _STATUS_IZIN:
        return "izin"
    if norm in _STATUS_ALPHA:
        return "alpha"
    raise ValueError(f"Status presensi tidak dikenali: {status!r}")


def analisis_pola_presensi(
    records: Sequence[RekordPresensiInput],
    ambang_persen: Decimal = MIN_PRESENSI_PERSEN,
    ambang_absen_kelas: Decimal = Decimal("30.00"),
) -> HasilAnalisisPresensi:
    """Menganalisis data presensi untuk mendeteksi early warning dan pola hari/jam absen."""
    by_nim: dict[str, list[tuple[RekordPresensiInput, str]]] = defaultdict(list)
    by_kelas_slot: dict[tuple[str, int, time], list[str]] = defaultdict(list)
    nama_map: dict[str, str] = {}

    for rec in records:
        st_norm = _normalisasi_status(rec.status)
        hari_norm = normalisasi_hari(rec.hari)
        rec_clean = RekordPresensiInput(
            nim=rec.nim.strip(),
            kelas=rec.kelas.strip(),
            hari=hari_norm,
            jam_mulai=rec.jam_mulai,
            status=st_norm,
            nama=rec.nama.strip() if rec.nama and rec.nama.strip() else None,
            tanggal=rec.tanggal,
        )
        if not rec_clean.nim:
            raise ValueError("NIM pada rekord presensi tidak boleh kosong")
        if not rec_clean.kelas:
            raise ValueError("Nama kelas pada rekord presensi tidak boleh kosong")
        if rec_clean.nama and rec_clean.nim not in nama_map:
            nama_map[rec_clean.nim] = rec_clean.nama

        by_nim[rec_clean.nim].append((rec_clean, st_norm))
        by_kelas_slot[(rec_clean.kelas, hari_norm, rec_clean.jam_mulai)].append(
            st_norm
        )

    per_mahasiswa: list[RingkasanMahasiswaPresensi] = []
    for nim in sorted(by_nim.keys()):
        items = by_nim[nim]
        hadir_cnt = sum(1 for _, st in items if st == "hadir")
        telat_cnt = sum(1 for _, st in items if st == "terlambat")
        izin_cnt = sum(1 for _, st in items if st == "izin")
        alpha_cnt = sum(1 for _, st in items if st == "alpha")
        total_sesi = len(items)
        persen = hitung_persentase_kehadiran(hadir_cnt + telat_cnt, total_sesi)
        per_mahasiswa.append(
            RingkasanMahasiswaPresensi(
                nim=nim,
                nama=nama_map.get(nim),
                total_sesi=total_sesi,
                hadir=hadir_cnt,
                terlambat=telat_cnt,
                izin=izin_cnt,
                alpha=alpha_cnt,
                persentase=persen,
                warning=persen < ambang_persen,
            )
        )

    warning_mahasiswa = sorted(
        (m for m in per_mahasiswa if m.warning),
        key=lambda m: (m.persentase, m.nim),
    )

    insights: list[str] = [
        f"{len(warning_mahasiswa)} mahasiswa berisiko tidak memenuhi syarat presensi (<75%)"
    ]
    actions: list[str] = []
    nim_punya_aksi: set[str] = set()

    # Deteksi pola mahasiswa sering absent pada hari & slot waktu tertentu.
    for mhs in per_mahasiswa:
        by_hari: dict[int, list[tuple[RekordPresensiInput, str]]] = defaultdict(list)
        for rec, st in by_nim[mhs.nim]:
            by_hari[rec.hari].append((rec, st))

        for hari_idx in sorted(by_hari.keys()):
            entri_hari = by_hari[hari_idx]
            absen_hari = [
                rec for rec, st in entri_hari if st in ("alpha", "izin")
            ]
            if len(absen_hari) < 2:
                continue
            rate_absen_hari = hitung_persentase_kehadiran(
                len(absen_hari), len(entri_hari)
            )
            if rate_absen_hari < Decimal("50.00"):
                continue

            slot_counter = Counter(
                label_slot_waktu(rec.jam_mulai) for rec in absen_hari
            )
            slot_dominan = slot_counter.most_common(1)[0][0]
            nama_hari = NAMA_HARI[hari_idx]
            label_mhs = f"{mhs.nama} ({mhs.nim})" if mhs.nama else mhs.nim
            insights.append(
                f"Mahasiswa {label_mhs} sering absent hari {nama_hari} {slot_dominan}"
            )
            actions.append(
                f"Mahasiswa {label_mhs} sering absent hari {nama_hari} {slot_dominan} → hubungi untuk konseling"
            )
            nim_punya_aksi.add(mhs.nim)

    # Deteksi kelas & jam dengan absen rate tinggi (>= ambang_absen_kelas).
    pola_hari_jam: list[PolaHariJamAbsen] = []
    for kelas, hari_idx, jam_mulai in sorted(by_kelas_slot.keys()):
        statuses = by_kelas_slot[(kelas, hari_idx, jam_mulai)]
        total_rek = len(statuses)
        if total_rek < 2:
            continue
        jml_absen = sum(1 for st in statuses if st in ("alpha", "izin"))
        absen_rate = hitung_persentase_kehadiran(jml_absen, total_rek)
        if absen_rate < ambang_absen_kelas:
            continue

        nama_hari = NAMA_HARI[hari_idx]
        jam_str = jam_mulai.strftime("%H:%M")
        slot = label_slot_waktu(jam_mulai)
        pola = PolaHariJamAbsen(
            kelas=kelas,
            hari=hari_idx,
            nama_hari=nama_hari,
            jam_mulai=jam_str,
            slot_waktu=slot,
            total_rekord=total_rek,
            jumlah_absen=jml_absen,
            absen_rate_persen=absen_rate,
        )
        pola_hari_jam.append(pola)
        insights.append(
            f"Kelas {kelas} pada hari {nama_hari} jam {jam_str} memiliki absen rate {absen_rate}%"
        )
        actions.append(
            f"Kelas {kelas} di jam {jam_str} absen rate {absen_rate}% → pertimbangkan reschedule"
        )

    tanpa_aksi = [m for m in warning_mahasiswa if m.nim not in nim_punya_aksi]
    if tanpa_aksi:
        daftar_label = ", ".join(
            f"{m.nama} ({m.nim})" if m.nama else m.nim for m in tanpa_aksi[:5]
        )
        actions.append(
            f"Kirim peringatan dini presensi <75% kepada {len(tanpa_aksi)} mahasiswa: {daftar_label}"
        )

    return HasilAnalisisPresensi(
        total_rekord=len(records),
        total_mahasiswa=len(per_mahasiswa),
        per_mahasiswa=tuple(per_mahasiswa),
        warning_mahasiswa=tuple(warning_mahasiswa),
        pola_hari_jam=tuple(pola_hari_jam),
        insights=tuple(insights),
        actions=tuple(actions),
    )

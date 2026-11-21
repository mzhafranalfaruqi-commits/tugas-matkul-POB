"""Fungsi murni domain Keuangan (SPP), denda keterlambatan, dan analitik CSV berbasis Decimal."""

from collections import defaultdict
from collections.abc import Mapping
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io

from app.domain.gpa import DUA_DESIMAL

TARIF_TEKNIK = Decimal("5000000.00")
TARIF_EKONOMI = Decimal("4000000.00")
TARIF_DEFAULT = Decimal("4500000.00")
DEFAULT_TARIF_DENDA_HARIAN = Decimal("0.005")  # 0.5% per hari keterlambatan
DEFAULT_MAKS_DENDA_PERSEN = Decimal("0.10")  # Maksimal 10% dari pokok tagihan

_STATUS_PEMBAYARAN_MASUK = frozenset({"paid", "lunas", "success", "partial"})
_STATUS_LUNAS = frozenset({"paid", "lunas", "success"})
_STATUS_TUNGGAKAN = frozenset({"unpaid", "partial", "overdue"})
_STATUS_SAH = _STATUS_LUNAS | _STATUS_TUNGGAKAN


@dataclass(frozen=True)
class BarisPembayaranCSV:
    """Representasi satu baris valid dari input CSV data pembayaran mahasiswa."""

    nim: str
    jumlah: Decimal
    tanggal: date
    status: str


@dataclass(frozen=True)
class TunggakanMahasiswaItem:
    """Ringkasan tunggakan satu mahasiswa untuk daftar top tunggakan pada laporan AI."""

    nim: str
    nama: str | None
    total_tunggakan: Decimal
    tanggal_tertua: date
    hari_tunggakan: int


@dataclass(frozen=True)
class HasilAnalisisKeuangan:
    """Hasil agregasi deterministik data pembayaran mahasiswa untuk AI Financial Insights."""

    periode_bulan: str
    total_revenue_bulan_ini: Decimal
    total_mahasiswa: int
    mahasiswa_sudah_bayar: int
    collection_rate_persen: Decimal
    top_10_tunggakan: tuple[TunggakanMahasiswaItem, ...]
    tunggakan_lebih_2_bulan_count: int
    rekomendasi: tuple[str, ...]


def bulatkan_uang(val: Decimal) -> Decimal:
    """Membulatkan nominal Rupiah ke 2 angka di belakang koma dengan ROUND_HALF_UP."""
    return val.quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)


def format_rupiah(val: Decimal) -> str:
    """Memformat nominal Decimal menjadi string Rupiah berpemisah ribuan titik."""
    dibulatkan = bulatkan_uang(val)
    negatif = dibulatkan < 0
    absolut = abs(dibulatkan)
    bagian_bulat = int(absolut)
    sen = int((absolut - bagian_bulat) * 100)
    teks_ribuan = f"{bagian_bulat:,}".replace(",", ".")
    awalan = "-Rp " if negatif else "Rp "
    if sen == 0:
        return f"{awalan}{teks_ribuan}"
    return f"{awalan}{teks_ribuan},{sen:02d}"


def tentukan_tarif_spp(nama_prodi: str, fakultas: str = "") -> Decimal:
    """Menentukan tarif SPP semester berdasarkan nama program studi atau fakultas."""
    gabungan = f"{nama_prodi} {fakultas}".lower()
    if "teknik" in gabungan:
        return TARIF_TEKNIK
    if any(kata in gabungan for kata in ("ekonomi", "manajemen", "akuntansi")):
        return TARIF_EKONOMI
    return TARIF_DEFAULT


def hitung_due_date(semester_start: date) -> date:
    """Menghitung tanggal jatuh tempo tagihan SPP yaitu tepat 2 minggu (14 hari)."""
    return semester_start + timedelta(days=14)


def hitung_denda_keterlambatan(
    pokok: Decimal,
    due_date: date,
    as_of: date,
    tarif_harian_persen: Decimal = DEFAULT_TARIF_DENDA_HARIAN,
    maks_persen: Decimal = DEFAULT_MAKS_DENDA_PERSEN,
) -> Decimal:
    """Menghitung denda keterlambatan secara murni dengan batas maksimum persentase pokok."""
    if pokok <= 0:
        raise ValueError("Pokok tagihan SPP harus lebih besar dari nol")
    if tarif_harian_persen < 0 or maks_persen < 0:
        raise ValueError("Tarif dan batas maksimum denda tidak boleh negatif")
    if as_of <= due_date:
        return Decimal("0.00")

    hari_telat = (as_of - due_date).days
    denda_kotor = pokok * tarif_harian_persen * Decimal(hari_telat)
    denda_maks = pokok * maks_persen
    return bulatkan_uang(min(denda_kotor, denda_maks))


def tentukan_status_pembayaran(
    total_tagihan: Decimal, total_terbayar: Decimal
) -> str:
    """Menentukan status dasar tagihan berdasarkan rasio pembayaran terhadap total tagihan."""
    if total_terbayar >= total_tagihan:
        return "paid"
    if total_terbayar > Decimal("0.00"):
        return "partial"
    return "unpaid"


def tentukan_semester_aktif(tanggal: date) -> str:
    """Mengonversi tanggal kalender menjadi kode semester akademik 5 digit (mis. 20261)."""
    if tanggal.month >= 8:
        return f"{tanggal.year}1"
    if tanggal.month == 1:
        return f"{tanggal.year - 1}1"
    return f"{tanggal.year - 1}2"


def hitung_persentase(pembilang: Decimal, penyebut: Decimal) -> Decimal:
    """Menghitung persentase dengan aman terhadap pembagi nol dan pembulatan ROUND_HALF_UP."""
    if penyebut <= 0:
        return Decimal("0.00")
    return bulatkan_uang((pembilang / penyebut) * Decimal("100"))


def _parse_baris_csv(csv_text: str) -> list[BarisPembayaranCSV]:
    """Memvalidasi header dan mem-parsing seluruh baris CSV pembayaran."""
    teks = csv_text.strip()
    if not teks:
        raise ValueError("Input CSV data pembayaran tidak boleh kosong")

    reader = csv.DictReader(io.StringIO(teks))
    if not reader.fieldnames:
        raise ValueError("Header CSV tidak ditemukan")

    peta_kolom: dict[str, str] = {}
    for col in reader.fieldnames:
        norm = col.strip().lower()
        if norm:
            peta_kolom[norm] = col

    wajib = {"nim", "jumlah", "tanggal", "status"}
    kurang = sorted(wajib - set(peta_kolom.keys()))
    if kurang:
        raise ValueError(
            f"Kolom CSV wajib tidak lengkap, kurang: {', '.join(kurang)}"
        )

    hasil: list[BarisPembayaranCSV] = []
    for nomor, raw in enumerate(reader, start=2):
        nim = (raw.get(peta_kolom["nim"]) or "").strip()
        jumlah_str = (raw.get(peta_kolom["jumlah"]) or "").strip()
        tanggal_str = (raw.get(peta_kolom["tanggal"]) or "").strip()
        status_str = (raw.get(peta_kolom["status"]) or "").strip().lower()

        if not nim:
            raise ValueError(f"Baris {nomor}: kolom 'nim' tidak boleh kosong")
        try:
            jumlah = Decimal(jumlah_str)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f"Baris {nomor}: nominal 'jumlah' tidak valid ({jumlah_str!r})"
            ) from exc
        if not jumlah.is_finite() or jumlah < 0:
            raise ValueError(
                f"Baris {nomor}: nominal 'jumlah' tidak boleh negatif atau non-finit"
            )
        try:
            tanggal = date.fromisoformat(tanggal_str)
        except ValueError as exc:
            raise ValueError(
                f"Baris {nomor}: format 'tanggal' harus YYYY-MM-DD ({tanggal_str!r})"
            ) from exc
        if status_str not in _STATUS_SAH:
            raise ValueError(
                f"Baris {nomor}: status '{status_str}' tidak dikenali"
            )

        hasil.append(
            BarisPembayaranCSV(
                nim=nim,
                jumlah=bulatkan_uang(jumlah),
                tanggal=tanggal,
                status=status_str,
            )
        )

    return hasil


def analisis_keuangan_csv(
    csv_text: str,
    as_of: date | None = None,
    nama_by_nim: Mapping[str, str] | None = None,
) -> HasilAnalisisKeuangan:
    """Menganalisis data pembayaran CSV menjadi metrik ringkas dan rekomendasi penagihan."""
    ref_date = as_of or date.today()
    rows = _parse_baris_csv(csv_text)

    revenue_bulan_ini = Decimal("0.00")
    status_per_nim: dict[str, set[str]] = defaultdict(set)
    tunggakan_per_nim: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    tanggal_tertua_per_nim: dict[str, date] = {}

    for row in rows:
        status_per_nim[row.nim].add(row.status)
        if (
            row.status in _STATUS_PEMBAYARAN_MASUK
            and row.tanggal.year == ref_date.year
            and row.tanggal.month == ref_date.month
        ):
            revenue_bulan_ini += row.jumlah

        if row.status in _STATUS_TUNGGAKAN:
            tunggakan_per_nim[row.nim] += row.jumlah
            prev_tgl = tanggal_tertua_per_nim.get(row.nim)
            if prev_tgl is None or row.tanggal < prev_tgl:
                tanggal_tertua_per_nim[row.nim] = row.tanggal

    total_mahasiswa = len(status_per_nim)
    sudah_bayar = sum(
        1
        for statuses in status_per_nim.values()
        if statuses.isdisjoint(_STATUS_TUNGGAKAN) and not statuses.isdisjoint(_STATUS_LUNAS)
    )
    collection_rate = hitung_persentase(
        Decimal(sudah_bayar), Decimal(total_mahasiswa)
    )

    daftar_tunggakan: list[TunggakanMahasiswaItem] = []
    jumlah_lebih_2_bulan = 0
    for nim, total_sisa in tunggakan_per_nim.items():
        if total_sisa <= 0:
            continue
        tgl_tertua = tanggal_tertua_per_nim[nim]
        hari_tunggakan = max(0, (ref_date - tgl_tertua).days)
        if hari_tunggakan > 60:
            jumlah_lebih_2_bulan += 1
        daftar_tunggakan.append(
            TunggakanMahasiswaItem(
                nim=nim,
                nama=nama_by_nim.get(nim) if nama_by_nim else None,
                total_tunggakan=bulatkan_uang(total_sisa),
                tanggal_tertua=tgl_tertua,
                hari_tunggakan=hari_tunggakan,
            )
        )

    daftar_tunggakan.sort(key=lambda item: (-item.total_tunggakan, item.nim))
    top_10 = tuple(daftar_tunggakan[:10])

    rekomendasi: list[str] = [
        f"Kirim reminder ke {jumlah_lebih_2_bulan} mahasiswa dengan tunggakan >2 bulan"
    ]
    if total_mahasiswa > 0 and collection_rate < Decimal("80.00"):
        rekomendasi.append(
            f"Collection rate saat ini {collection_rate}% (< 80%); aktifkan pengingat berkala dan blokir pengisian KRS bagi penunggak"
        )
    jumlah_partial = sum(
        1 for statuses in status_per_nim.values() if "partial" in statuses
    )
    if jumlah_partial > 0:
        rekomendasi.append(
            f"Tindak lanjuti {jumlah_partial} mahasiswa berstatus cicilan (partial) agar melunasi sisa tagihan sebelum jatuh tempo"
        )

    return HasilAnalisisKeuangan(
        periode_bulan=f"{ref_date.year:04d}-{ref_date.month:02d}",
        total_revenue_bulan_ini=bulatkan_uang(revenue_bulan_ini),
        total_mahasiswa=total_mahasiswa,
        mahasiswa_sudah_bayar=sudah_bayar,
        collection_rate_persen=collection_rate,
        top_10_tunggakan=top_10,
        tunggakan_lebih_2_bulan_count=jumlah_lebih_2_bulan,
        rekomendasi=tuple(rekomendasi),
    )

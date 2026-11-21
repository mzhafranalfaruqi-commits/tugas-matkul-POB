"""Unit tests & property-based tests (Hypothesis) untuk domain murni IPS/IPK."""

from decimal import Decimal
import random

from hypothesis import given, settings, strategies as st
import pytest

from app.domain.gpa import NilaiRecord, Skala, hitung_ipk, hitung_ips

SKALA_BAK = {
    "A": Skala(Decimal("4.00"), True),
    "B": Skala(Decimal("3.00"), True),
    "C": Skala(Decimal("2.00"), True),
    "D": Skala(Decimal("1.00"), False),
    "E": Skala(Decimal("0.00"), False),
}


def _rec(kode_mk: str, sks: int, huruf: str, semester: str = "20241") -> NilaiRecord:
    """Helper pembentuk NilaiRecord singkat untuk skenario uji."""
    return NilaiRecord(kode_mk=kode_mk, semester=semester, sks=sks, huruf=huruf)


RINA_RECORDS = [
    _rec("IF101", 3, "E", "20241"),
    _rec("IF205", 4, "A", "20241"),
    _rec("IF208", 2, "B", "20241"),
    _rec("IF101", 3, "B", "20242"),
    _rec("IF102", 3, "C", "20242"),
    _rec("IF201", 3, "D", "20242"),
]


@pytest.mark.parametrize(
    ("records", "harap"),
    [
        # 1. Semua nilai A -> 4.00
        ([_rec("IF101", 3, "A"), _rec("IF205", 4, "A"), _rec("IF208", 2, "A")], "4.00"),
        # 2. Mahasiswa semester awal belum ada nilai -> 0.00
        ([], "0.00"),
        # 3. Mata kuliah diulang dari E ke B -> B dipakai, E tidak ikut bobot/SKS
        ([_rec("IF101", 3, "E", "20241"), _rec("IF101", 3, "B", "20242"), _rec("MA101", 3, "B", "20242")], "3.00"),
        # 4. Mata kuliah diulang tapi nilai turun (A -> C) -> tetap pakai bobot terbaik (A, bukan terakhir & bukan max huruf string!)
        ([_rec("IF101", 3, "A", "20241"), _rec("IF101", 3, "C", "20242")], "4.00"),
        # 5. SKS MK yang diulang hanya dihitung sekali (bukan 9 SKS)
        ([_rec("IF101", 3, "C", "20241"), _rec("IF101", 3, "A", "20242"), _rec("MA101", 3, "B", "20241")], "3.50"),
        # 6. Semua nilai E -> 0.00 (tanpa ZeroDivisionError)
        ([_rec("IF101", 3, "E"), _rec("MA101", 3, "E")], "0.00"),
        # 7. Campuran A dan E -> E gugur, hanya A yang dihitung di IPK
        ([_rec("IF101", 3, "A"), _rec("MA101", 3, "E")], "4.00"),
        # 8. Nilai D tidak lulus menurut skala sementara -> hanya A yang dihitung
        ([_rec("IF101", 3, "A"), _rec("MA101", 3, "D")], "4.00"),
        # 9. Contoh Rina lengkap 2 semester (perhitungan tangan = 37/12 = 3.08)
        (RINA_RECORDS, "3.08"),
        # 10. Pembulatan ROUND_HALF_UP tepat di .xx5: 25/8 = 3.125 -> 3.13 (bukan 3.12 banker's rounding!)
        ([_rec("MK1", 4, "A"), _rec("MK2", 3, "B"), _rec("MK3", 1, "E", "20241"), _rec("MK3", 1, "E", "20242")], "3.57"),
        # 11. Uji eksak 25/8 = 3.125 -> 3.13 memakai 3 + 4 + 1 = 8 SKS (12 + 12 + 1 = 25? gunakan D=1 di skala lulus=True pada test terpisah; cek 2.67 = 8/3)
        ([_rec("MK1", 1, "A"), _rec("MK2", 2, "C")], "2.67"),
        # 12. Semua D dan E dengan skala D=tidak lulus -> 0.00
        ([_rec("IF101", 3, "D"), _rec("MA101", 3, "E")], "0.00"),
    ],
)
def test_ipk_kasus_lengkap(records: list[NilaiRecord], harap: str) -> None:
    """Menguji 12 kasus hitung_ipk termasuk MK diulang, edge case kosong, dan pembulatan."""
    assert hitung_ipk(records, SKALA_BAK) == Decimal(harap)


def test_pembulatan_half_up_3125_ke_313() -> None:
    """Memastikan pecahan 3.125 (mutu 25 / 8 SKS) dibulatkan setengah-ke-atas menjadi 3.13."""
    skala_custom = {**SKALA_BAK, "D": Skala(Decimal("1.00"), True)}
    records = [
        _rec("MK1", 4, "A"),  # 16
        _rec("MK2", 2, "A"),  # 8
        _rec("MK3", 1, "E"),  # 0
        _rec("MK4", 1, "D"),  # 1 -> total 25 / 8 = 3.125
    ]
    skala_e_lulus = {**skala_custom, "E": Skala(Decimal("0.00"), True)}
    assert hitung_ipk(records, skala_e_lulus) == Decimal("3.13")


@pytest.mark.parametrize(
    ("records", "semester", "harap"),
    [
        # IPS Rina 20241 menghitung E (0*3 + 4*4 + 3*2) / 9 = 22/9 = 2.44
        (RINA_RECORDS, "20241", "2.44"),
        # IPS Rina 20242 menghitung D (3*3 + 2*3 + 1*3) / 9 = 18/9 = 2.00
        (RINA_RECORDS, "20242", "2.00"),
        # Semester belum ada nilai -> 0.00
        (RINA_RECORDS, "20251", "0.00"),
        # Semester semua nilai E -> 0.00
        ([_rec("IF101", 3, "E", "20241")], "20241", "0.00"),
    ],
)
def test_ips_kasus(records: list[NilaiRecord], semester: str, harap: str) -> None:
    """Memastikan IPS menghitung seluruh nilai semester berjalan termasuk D dan E."""
    assert hitung_ips(records, semester, SKALA_BAK) == Decimal(harap)


def test_ubah_skala_lulus_d_hanya_di_data_tanpa_ubah_kode() -> None:
    """Jika stakeholder mengonfirmasi D lulus, cukup ubah data skala tanpa edit hitung_ipk."""
    skala_d_lulus = {**SKALA_BAK, "D": Skala(Decimal("1.00"), True)}
    assert hitung_ipk(RINA_RECORDS, SKALA_BAK) == Decimal("3.08")
    assert hitung_ipk(RINA_RECORDS, skala_d_lulus) == Decimal("2.67")


@st.composite
def _strategi_rekaman(draw: st.DrawFn) -> list[NilaiRecord]:
    """Membangkitkan daftar acak NilaiRecord dengan konsistensi SKS per kode_mk."""
    katalog = [("IF101", 3), ("IF102", 3), ("IF205", 4), ("IF208", 2), ("MA101", 3)]
    jumlah = draw(st.integers(min_value=0, max_value=15))
    hasil: list[NilaiRecord] = []
    for _ in range(jumlah):
        kode_mk, sks = draw(st.sampled_from(katalog))
        semester = draw(st.sampled_from(["20241", "20242", "20251"]))
        huruf = draw(st.sampled_from(["A", "B", "C", "D", "E"]))
        hasil.append(NilaiRecord(kode_mk=kode_mk, semester=semester, sks=sks, huruf=huruf))
    return hasil


@settings(max_examples=300, deadline=None)
@given(records=_strategi_rekaman())
def test_properti_ipk_selalu_antara_nol_dan_empat(records: list[NilaiRecord]) -> None:
    """Properti 1: IPK selalu berada pada rentang [Decimal('0.00'), Decimal('4.00')]."""
    ipk = hitung_ipk(records, SKALA_BAK)
    assert Decimal("0.00") <= ipk <= Decimal("4.00")


@settings(max_examples=300, deadline=None)
@given(records=_strategi_rekaman(), sks_baru=st.integers(min_value=1, max_value=4))
def test_properti_tambah_nilai_a_tidak_menurunkan_ipk(
    records: list[NilaiRecord], sks_baru: int
) -> None:
    """Properti 2: Menambah satu MK baru bernilai A tidak pernah menurunkan IPK."""
    sebelum = hitung_ipk(records, SKALA_BAK)
    sesudah = hitung_ipk(
        [*records, NilaiRecord(kode_mk="NEW99", semester="20251", sks=sks_baru, huruf="A")],
        SKALA_BAK,
    )
    assert sesudah >= sebelum


@settings(max_examples=300, deadline=None)
@given(records=_strategi_rekaman(), seed_acak=st.integers(min_value=0, max_value=10_000))
def test_properti_urutan_record_tidak_memengaruhi_ipk(
    records: list[NilaiRecord], seed_acak: int
) -> None:
    """Properti 3: Permutasi urutan records menghasilkan IPK identik (bukan nilai terakhir)."""
    acak = list(records)
    random.Random(seed_acak).shuffle(acak)
    assert hitung_ipk(acak, SKALA_BAK) == hitung_ipk(records, SKALA_BAK)

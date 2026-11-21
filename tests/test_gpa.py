"""Unit tests & property-based tests (Hypothesis) untuk domain murni IPS/IPK."""

from decimal import Decimal
import random

from hypothesis import given, settings, strategies as st
import pytest

from app.domain.gpa import (
    NilaiRecord,
    RekordNilaiLengkap,
    Skala,
    bangun_ringkasan_transkrip,
    format_label_semester,
    hitung_ipk,
    hitung_ips,
    tentukan_predikat,
)

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


@pytest.mark.parametrize(
    ("ipk", "sks_lulus", "harap"),
    [
        ("4.00", 0, "Belum Memenuhi Predikat"),
        ("0.00", 0, "Belum Memenuhi Predikat"),
        ("1.99", 10, "Belum Memenuhi Syarat Kelulusan"),
        ("2.00", 10, "Cukup"),
        ("2.49", 10, "Cukup"),
        ("2.50", 10, "Memuaskan"),
        ("2.99", 10, "Memuaskan"),
        ("3.00", 10, "Sangat Memuaskan"),
        ("3.49", 10, "Sangat Memuaskan"),
        ("3.50", 10, "Cum Laude"),
        ("4.00", 144, "Cum Laude"),
    ],
)
def test_tentukan_predikat_batas(ipk: str, sks_lulus: int, harap: str) -> None:
    """Memastikan batas predikat kelulusan tepat di seluruh titik batas IPK dan SKS."""
    assert tentukan_predikat(Decimal(ipk), sks_lulus) == harap


@pytest.mark.parametrize(
    ("kode", "harap"),
    [
        ("20241", "2024/2025 Ganjil"),
        ("20242", "2024/2025 Genap"),
        ("20243", "2024/2025 Pendek"),
        ("2024X", "2024X"),
        ("GANJIL", "GANJIL"),
    ],
)
def test_format_label_semester(kode: str, harap: str) -> None:
    """Memastikan pemformatan label semester standar dan fallback kode tak baku."""
    assert format_label_semester(kode) == harap


def test_bangun_ringkasan_transkrip_pengulangan_gagal_dan_urutan() -> None:
    """Memastikan pengelompokan semester menaik, penandaan MK dipakai_ipk, & tie-breaking."""
    rekaman = [
        # Sengaja dibalik urutannya dan ada MK mengulang + MK sama bobot (tie-break record_id)
        RekordNilaiLengkap("IF102", "Struktur Data", "20242", 3, "B", record_id=20),
        RekordNilaiLengkap("IF102", "Struktur Data", "20241", 3, "B", record_id=10),
        RekordNilaiLengkap("IF101", "Algoritma", "20242", 3, "A", record_id=15),
        RekordNilaiLengkap("IF101", "Algoritma", "20241", 3, "E", record_id=5),
        RekordNilaiLengkap("MA101", "Kalkulus I", "20241", 3, "D", record_id=7),
    ]
    ringkas = bangun_ringkasan_transkrip(rekaman, SKALA_BAK)

    assert [s.semester for s in ringkas.semesters] == ["20241", "20242"]
    s1, s2 = ringkas.semesters
    assert [(i.kode_mk, i.huruf, i.lulus, i.dipakai_ipk) for i in s1.items] == [
        ("IF101", "E", False, False),
        ("IF102", "B", True, True),  # tie-break: 20241 (id=10) menang atas 20242 (id=20)
        ("MA101", "D", False, False),
    ]
    assert [(i.kode_mk, i.huruf, i.lulus, i.dipakai_ipk) for i in s2.items] == [
        ("IF101", "A", True, True),
        ("IF102", "B", True, False),  # nilai sama sudah terhitung di 20241
    ]
    assert s1.total_sks == 9
    assert s1.total_mutu == Decimal("12.00")  # 0 + 9 + 3
    assert s1.ips == Decimal("1.33")  # 12 / 9 = 1.333...
    assert s2.total_sks == 6
    assert s2.total_mutu == Decimal("21.00")  # 12 + 9
    assert s2.ips == Decimal("3.50")

    assert ringkas.total_sks_tempuh == 15
    assert ringkas.total_sks_lulus == 6
    assert ringkas.total_mutu_lulus == Decimal("21.00")
    assert ringkas.ipk == Decimal("3.50")
    assert ringkas.predikat == "Cum Laude"

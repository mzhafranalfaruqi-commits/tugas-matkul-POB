"""Property-based testing (Hypothesis) untuk domain murni Modul Keuangan (SPP)."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings, strategies as st

from app.domain.keuangan import (
    bulatkan_uang,
    hitung_denda_keterlambatan,
    hitung_persentase,
    tentukan_status_pembayaran,
)


@settings(max_examples=500, deadline=None)
@given(
    pokok_juta=st.integers(min_value=1, max_value=25),
    hari_a=st.integers(min_value=-30, max_value=90),
    delta_hari=st.integers(min_value=0, max_value=60),
)
def test_property_denda_bounded_dan_monotonik(
    pokok_juta: int, hari_a: int, delta_hari: int
) -> None:
    """Property: denda berada dalam [0, 10% pokok], nol bila <= due_date, dan monotonik naik."""
    pokok = Decimal(pokok_juta) * Decimal("1000000.00")
    due = date(2026, 9, 1)
    tgl_a = due + timedelta(days=hari_a)
    tgl_b = tgl_a + timedelta(days=delta_hari)

    denda_a = hitung_denda_keterlambatan(pokok, due, tgl_a)
    denda_b = hitung_denda_keterlambatan(pokok, due, tgl_b)
    maks = bulatkan_uang(pokok * Decimal("0.10"))

    assert Decimal("0.00") <= denda_a <= maks
    assert Decimal("0.00") <= denda_b <= maks
    if tgl_a <= due:
        assert denda_a == Decimal("0.00")
    assert denda_b >= denda_a


@settings(max_examples=500, deadline=None)
@given(
    total_ribu=st.integers(min_value=500, max_value=10_000),
    cicilan_ribu=st.lists(st.integers(min_value=1, max_value=3_000), max_size=8),
)
def test_property_cicilan_status_konsisten(
    total_ribu: int, cicilan_ribu: list[int]
) -> None:
    """Property: transisi unpaid -> partial -> paid tepat mencerminkan total akumulasi bayar."""
    total_tagihan = Decimal(total_ribu) * Decimal("1000.00")
    terbayar = Decimal("0.00")

    for nominal_ribu in cicilan_ribu:
        terbayar += Decimal(nominal_ribu) * Decimal("1000.00")

    status = tentukan_status_pembayaran(total_tagihan, terbayar)
    if terbayar >= total_tagihan:
        assert status == "paid"
    elif terbayar > Decimal("0.00"):
        assert status == "partial"
    else:
        assert status == "unpaid"


@settings(max_examples=500, deadline=None)
@given(
    penyebut_ribu=st.integers(min_value=0, max_value=100_000),
    rasio_persen=st.integers(min_value=0, max_value=100),
)
def test_property_persentase_collection_rate_bounded(
    penyebut_ribu: int, rasio_persen: int
) -> None:
    """Property: persentase berada di [0.00, 100.00] bila 0 <= pembilang <= penyebut."""
    penyebut = Decimal(penyebut_ribu) * Decimal("1000.00")
    pembilang = (penyebut * Decimal(rasio_persen)) / Decimal("100")

    hasil = hitung_persentase(pembilang, penyebut)
    assert Decimal("0.00") <= hasil <= Decimal("100.00")
    if penyebut == 0 or pembilang == 0:
        assert hasil == Decimal("0.00")
    elif pembilang == penyebut:
        assert hasil == Decimal("100.00")

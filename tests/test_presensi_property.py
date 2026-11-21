"""Property-based testing (Hypothesis) untuk domain murni Modul Presensi (QR Code)."""

from datetime import time
from decimal import Decimal

from hypothesis import assume, given, settings, strategies as st

from app.domain.presensi import (
    hitung_jarak_haversine_meter,
    hitung_persentase_kehadiran,
    tentukan_status_kehadiran,
)


@settings(max_examples=500, deadline=None)
@given(
    total_sesi=st.integers(min_value=0, max_value=40),
    hadir_a=st.integers(min_value=0, max_value=40),
    delta_hadir=st.integers(min_value=0, max_value=10),
)
def test_property_persentase_kehadiran_bounded_dan_monotonik(
    total_sesi: int, hadir_a: int, delta_hadir: int
) -> None:
    """Property: persentase kehadiran selalu dalam [0.00, 100.00] dan monotonik naik."""
    assume(hadir_a <= total_sesi)
    hadir_b = min(total_sesi, hadir_a + delta_hadir)

    pct_a = hitung_persentase_kehadiran(hadir_a, total_sesi)
    pct_b = hitung_persentase_kehadiran(hadir_b, total_sesi)

    assert Decimal("0.00") <= pct_a <= Decimal("100.00")
    assert Decimal("0.00") <= pct_b <= Decimal("100.00")
    assert pct_b >= pct_a
    if total_sesi == 0 or hadir_a == 0:
        assert pct_a == Decimal("0.00")
    if total_sesi > 0 and hadir_a == total_sesi:
        assert pct_a == Decimal("100.00")


@settings(max_examples=500, deadline=None)
@given(
    lat1=st.floats(min_value=-85.0, max_value=85.0, allow_nan=False, allow_infinity=False),
    lon1=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False),
    lat2=st.floats(min_value=-85.0, max_value=85.0, allow_nan=False, allow_infinity=False),
    lon2=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False),
)
def test_property_haversine_simetris_dan_nonnegatif(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> None:
    """Property: jarak Haversine >= 0, simetris d(A, B) == d(B, A), dan d(A, A) == 0."""
    d_same = hitung_jarak_haversine_meter(lat1, lon1, lat1, lon1)
    d_ab = hitung_jarak_haversine_meter(lat1, lon1, lat2, lon2)
    d_ba = hitung_jarak_haversine_meter(lat2, lon2, lat1, lon1)

    assert d_same == 0.0
    assert d_ab >= 0.0
    assert abs(d_ab - d_ba) < 1e-6


@settings(max_examples=500, deadline=None)
@given(menit=st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False))
def test_property_status_kehadiran_window_15_dan_30(menit: float) -> None:
    """Property: menit [0, 15] -> 'hadir', dan (15, 30] -> 'terlambat'."""
    status = tentukan_status_kehadiran(menit)
    if menit <= 15.0:
        assert status == "hadir"
    else:
        assert status == "terlambat"

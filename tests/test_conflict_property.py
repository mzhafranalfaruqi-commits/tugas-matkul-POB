"""Property-based testing (Hypothesis) dan differential testing untuk detektor bentrok jadwal."""

from collections import Counter
from datetime import time

from hypothesis import given, settings, strategies as st

from app.services.conflict import (
    JadwalSlot,
    detect_naive,
    detect_schedule_conflict,
)


@st.composite
def _strategi_daftar_jadwal(draw: st.DrawFn) -> list[JadwalSlot]:
    """Membangkitkan 1 sampai 20 jadwal acak di ruang sempit agar bentrok sering muncul."""
    jumlah = draw(st.integers(min_value=1, max_value=20))
    hasil: list[JadwalSlot] = []
    for idx in range(1, jumlah + 1):
        hari = draw(st.integers(min_value=1, max_value=3))
        jam = draw(st.integers(min_value=7, max_value=16))
        durasi = draw(st.integers(min_value=1, max_value=3))
        ruang = draw(st.sampled_from(["A101", "A102"]))
        dosen = draw(st.integers(min_value=1, max_value=3))
        hasil.append(
            JadwalSlot(
                id=idx,
                hari=hari,
                jam_mulai=time(jam, 0),
                jam_selesai=time(jam + durasi, 0),
                ruangan_kode=ruang,
                dosen_id=dosen,
            )
        )
    return hasil


def _kunci_slot(j: JadwalSlot) -> set[tuple[str, int, str | int, int]]:
    """Oracle independen pemecah jadwal menjadi slot 1-jam per ruangan dan per dosen."""
    return {
        kunci
        for jam in range(j.jam_mulai.hour, j.jam_selesai.hour)
        for kunci in (("R", j.hari, j.ruangan_kode, jam), ("D", j.hari, j.dosen_id, jam))
    }


@settings(max_examples=500, deadline=None)
@given(daftar=_strategi_daftar_jadwal())
def test_jadwal_diterima_tidak_pernah_bentrok(daftar: list[JadwalSlot]) -> None:
    """Property: daftar jadwal yang diterima detektor tidak pernah memakai slot ruang/dosen ganda."""
    diterima: list[JadwalSlot] = []
    for j in daftar:
        if not detect_schedule_conflict(diterima + [j]):
            diterima.append(j)
        else:
            # Oracle independen: penolakan wajib karena slot ruang/dosen beririsan dengan jadwal diterima.
            slot_terpakai = {k for x in diterima for k in _kunci_slot(x)}
            assert not _kunci_slot(j).isdisjoint(slot_terpakai)

    pakai = Counter(kunci for j in diterima for kunci in _kunci_slot(j))
    assert all(n == 1 for n in pakai.values())


@settings(max_examples=500, deadline=None)
@given(daftar=_strategi_daftar_jadwal())
def test_sweep_sama_dengan_naif(daftar: list[JadwalSlot]) -> None:
    """Differential testing: versi Grouping + Sort & Sweep identik dengan versi naif O(n^2)."""
    assert Counter(detect_schedule_conflict(daftar)) == Counter(detect_naive(daftar))

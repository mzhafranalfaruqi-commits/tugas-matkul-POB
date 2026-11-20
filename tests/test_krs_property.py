"""Property-based testing (Hypothesis) dan exhaustive state machine test untuk Modul KRS."""

from datetime import time
import itertools
from typing import cast

from hypothesis import given, settings, strategies as st
import pytest
from sqlalchemy.orm import Session

from app.models.krs import Actor, KRS, KRSDetail, KRSStatus, MataKuliah
from app.services.exceptions import TransitionError
from app.validators.base import KRSContext
from app.validators.krs import ConflictValidator, MAX_SKS, SKSValidator


@st.composite
def _strategi_daftar_mk(draw: st.DrawFn) -> list[MataKuliah]:
    """Membangkitkan 1 sampai 15 jadwal MataKuliah acak yang valid di memori."""
    jumlah = draw(st.integers(min_value=1, max_value=15))
    hasil: list[MataKuliah] = []
    for idx in range(jumlah):
        hari = draw(st.integers(min_value=1, max_value=6))
        jam_mulai = draw(st.integers(min_value=7, max_value=17))
        durasi = draw(st.integers(min_value=1, max_value=3))
        sks = draw(st.integers(min_value=1, max_value=4))
        hasil.append(
            MataKuliah(
                kode_mk=f"HYP{idx:02d}",
                nama=f"Matkul Acak {idx}",
                sks=sks,
                hari=hari,
                jam_mulai=time(jam_mulai, 0),
                jam_selesai=time(jam_mulai + durasi, 0),
            )
        )
    return hasil


def _slot(mk: MataKuliah) -> set[tuple[int, int]]:
    """Oracle independen penghitung himpunan slot jam (hari, jam) milik sebuah mata kuliah."""
    return {(mk.hari, jam) for jam in range(mk.jam_mulai.hour, mk.jam_selesai.hour)}


@settings(max_examples=1000, deadline=None)
@given(sks_list=st.lists(st.integers(min_value=1, max_value=4), max_size=20))
def test_total_sks_tidak_pernah_lebih_dari_24(sks_list: list[int]) -> None:
    """Property: SKSValidator tidak pernah meloloskan >24 SKS dan penolakan hanya bila >24."""
    validator = SKSValidator()
    details: list[KRSDetail] = []
    fake_db = cast(Session, None)

    for idx, sks in enumerate(sks_list):
        mk = MataKuliah(
            kode_mk=f"SKS{idx:02d}",
            nama=f"Matkul SKS {idx}",
            sks=sks,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(9, 0),
        )
        total_sebelum = sum(d.matakuliah.sks for d in details)
        ctx = KRSContext(
            nim="2025001-0001",
            semester="20251",
            details=list(details),
            mk_baru=mk,
            db=fake_db,
        )
        hasil = validator.check(ctx)
        if hasil.ok:
            details.append(KRSDetail(krs_id=1, kode_mk=mk.kode_mk, matakuliah=mk))
        else:
            assert total_sebelum + sks > MAX_SKS

    assert sum(d.matakuliah.sks for d in details) <= MAX_SKS


@settings(max_examples=1000, deadline=None)
@given(daftar_mk=_strategi_daftar_mk())
def test_mk_diterima_tidak_pernah_bentrok(daftar_mk: list[MataKuliah]) -> None:
    """Property: ConflictValidator selalu menjamin irisan slot kosong untuk seluruh MK diterima."""
    validator = ConflictValidator()
    details: list[KRSDetail] = []
    diterima: list[MataKuliah] = []
    fake_db = cast(Session, None)

    for mk in daftar_mk:
        ctx = KRSContext(
            nim="2025001-0001",
            semester="20251",
            details=list(details),
            mk_baru=mk,
            db=fake_db,
        )
        hasil = validator.check(ctx)
        if hasil.ok:
            details.append(KRSDetail(krs_id=1, kode_mk=mk.kode_mk, matakuliah=mk))
            diterima.append(mk)
        else:
            # Oracle independen: penolakan wajib karena ada irisan slot dengan MK diterima.
            assert any(not _slot(mk).isdisjoint(_slot(ada)) for ada in diterima)

    for idx_a, mk_a in enumerate(diterima):
        for mk_b in diterima[idx_a + 1 :]:
            assert _slot(mk_a).isdisjoint(_slot(mk_b))


# 4 transisi sah ditulis langsung dari spesifikasi alur KRS (bukan diimpor dari TRANSITIONS).
_TRANSISI_SAH: set[tuple[KRSStatus, Actor, KRSStatus]] = {
    (KRSStatus.DRAFT, Actor.MAHASISWA, KRSStatus.SUBMITTED),
    (KRSStatus.SUBMITTED, Actor.DOSEN_PA, KRSStatus.APPROVED),
    (KRSStatus.SUBMITTED, Actor.DOSEN_PA, KRSStatus.REVISION),
    (KRSStatus.REVISION, Actor.MAHASISWA, KRSStatus.SUBMITTED),
}

_SEMUA_KOMBINASI = list(itertools.product(KRSStatus, Actor, KRSStatus))
_TRANSISI_ILEGAL = [t for t in _SEMUA_KOMBINASI if t not in _TRANSISI_SAH]


def test_jumlah_kombinasi_state_machine_lengkap() -> None:
    """Memastikan ruang uji state machine mencakup tepat 4 sah + 28 ilegal = 32 kombinasi."""
    assert len(_SEMUA_KOMBINASI) == 32
    assert len(_TRANSISI_SAH) == 4
    assert len(_TRANSISI_ILEGAL) == 28


@pytest.mark.parametrize(("status_awal", "aktor", "status_tujuan"), _TRANSISI_ILEGAL)
def test_transisi_ilegal_ditolak(
    status_awal: KRSStatus, aktor: Actor, status_tujuan: KRSStatus
) -> None:
    """Exhaustive: ke-28 kombinasi ilegal wajib melempar TransitionError & menjaga status."""
    krs = KRS(nim="2025001-0001", semester="20251", status=status_awal)
    with pytest.raises(TransitionError):
        krs.transition(status_tujuan, aktor)
    assert krs.status == status_awal


@pytest.mark.parametrize(
    ("status_awal", "aktor", "status_tujuan"),
    sorted(_TRANSISI_SAH, key=lambda item: (item[0].value, item[1].value, item[2].value)),
)
def test_transisi_legal_berhasil(
    status_awal: KRSStatus, aktor: Actor, status_tujuan: KRSStatus
) -> None:
    """Exhaustive: ke-4 kombinasi sah sesuai spesifikasi berhasil memindahkan status KRS."""
    krs = KRS(nim="2025001-0001", semester="20251", status=status_awal)
    krs.transition(status_tujuan, aktor)
    assert krs.status == status_tujuan

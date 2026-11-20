"""Algoritma deteksi bentrok jadwal kuliah 3 dimensi (waktu x ruangan x dosen)."""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import time
import itertools
from typing import Literal, Protocol

ConflictType = Literal["room_conflict", "lecturer_conflict"]


@dataclass(frozen=True)
class Conflict:
    """Representasi satu kejadian bentrok antara dua jadwal kuliah."""

    type: ConflictType
    affected: tuple[int, ...]


class JadwalLike(Protocol):
    """Protokol struktural agar detektor menerima ORM Jadwal maupun JadwalSlot."""

    id: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan_kode: str
    dosen_id: int


@dataclass(frozen=True)
class JadwalSlot:
    """Representasi ringan jadwal tanpa database untuk unit test dan property test."""

    id: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan_kode: str
    dosen_id: int


def overlap(a: JadwalLike, b: JadwalLike) -> bool:
    """Mendeteksi irisan interval setengah-terbuka [jam_mulai, jam_selesai) di hari sama."""
    return (
        a.hari == b.hari
        and a.jam_mulai < b.jam_selesai
        and b.jam_mulai < a.jam_selesai
    )


def _pasangan(tipe: ConflictType, a: JadwalLike, b: JadwalLike) -> Conflict:
    """Membentuk objek Conflict dengan urutan ID kanonik agar simetris (A,B == B,A)."""
    id_pertama, id_kedua = (a.id, b.id) if a.id <= b.id else (b.id, a.id)
    return Conflict(tipe, (id_pertama, id_kedua))


def detect_naive(jadwal: Sequence[JadwalLike]) -> list[Conflict]:
    """Detektor acuan O(n^2): memeriksa setiap kombinasi pasangan jadwal tepat sekali."""
    hasil: list[Conflict] = []
    for a, b in itertools.combinations(jadwal, 2):
        if not overlap(a, b):
            continue
        if a.ruangan_kode == b.ruangan_kode:
            hasil.append(_pasangan("room_conflict", a, b))
        if a.dosen_id == b.dosen_id:
            hasil.append(_pasangan("lecturer_conflict", a, b))
    return hasil


KUNCI: dict[ConflictType, Callable[[JadwalLike], tuple[int, str | int]]] = {
    "room_conflict": lambda j: (j.hari, j.ruangan_kode),
    "lecturer_conflict": lambda j: (j.hari, j.dosen_id),
}


def detect_schedule_conflict(jadwal: Sequence[JadwalLike]) -> list[Conflict]:
    """Detektor teroptimasi (Grouping + Sort & Sweep) O(n log n + k)."""
    hasil: list[Conflict] = []
    for tipe, kunci in KUNCI.items():
        grup: dict[tuple[int, str | int], list[JadwalLike]] = defaultdict(list)
        for j in jadwal:
            grup[kunci(j)].append(j)
        for isi in grup.values():
            aktif: list[JadwalLike] = []
            for j in sorted(isi, key=lambda x: (x.jam_mulai, x.jam_selesai, x.id)):
                aktif = [x for x in aktif if x.jam_selesai > j.jam_mulai]
                hasil.extend(_pasangan(tipe, x, j) for x in aktif)
                aktif.append(j)
    return hasil

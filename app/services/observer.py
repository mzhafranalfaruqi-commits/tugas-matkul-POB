"""Implementasi Observer Pattern, Strategy Channel, Idempotency, & Transactional Outbox."""

from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import time
from enum import Enum
import logging
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.jadwal import Outbox
from app.models.krs import KRS, KRSDetail

if TYPE_CHECKING:
    from app.models.jadwal import Jadwal

logger = logging.getLogger("sevima.observer")

# ContextVar agar Subject singleton yang dipasang sekali saat startup tetap memakai
# Session database transaksi dispatch aktif (termasuk db_session in-memory di pytest).
_dispatch_session_var: ContextVar[Session | None] = ContextVar(
    "sevima_dispatch_session", default=None
)


class EventType(str, Enum):
    """Jenis peristiwa perubahan jadwal kuliah."""

    SCHEDULE_CHANGED = "SCHEDULE_CHANGED"
    SCHEDULE_DELETED = "SCHEDULE_DELETED"


@dataclass(frozen=True)
class ScheduleEvent:
    """Payload event immutable ketika jadwal diubah atau dihapus."""

    event_type: EventType
    jadwal_id: int
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    event_id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        """Menserialisasi event menjadi kamus JSON-serializable untuk tabel outbox."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "jadwal_id": self.jadwal_id,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleEvent":
        """Merekonstruksi ScheduleEvent dari payload JSON tabel outbox."""
        return cls(
            event_id=str(data["event_id"]),
            event_type=EventType(data["event_type"]),
            jadwal_id=int(data["jadwal_id"]),
            before=data.get("before"),
            after=data.get("after"),
        )


def _format_jam(val: time | str) -> str:
    """Memformat nilai time/str ke string HH:MM yang stabil."""
    if isinstance(val, time):
        return val.strftime("%H:%M")
    return str(val)[:5]


def snapshot_jadwal(jadwal: "Jadwal") -> dict[str, Any]:
    """Mengambil snapshot JSON-serializable dari objek ORM Jadwal."""
    return {
        "id": jadwal.id,
        "kelas_id": jadwal.kelas_id,
        "hari": jadwal.hari,
        "jam_mulai": _format_jam(jadwal.jam_mulai),
        "jam_selesai": _format_jam(jadwal.jam_selesai),
        "ruangan_kode": jadwal.ruangan_kode,
        "dosen_id": jadwal.dosen_id,
        "sequence": jadwal.sequence,
    }


def format_ringkas_slot(data: dict[str, Any]) -> str:
    """Memformat ringkasan slot jadwal menjadi teks mudah dibaca."""
    return (
        f"Hari {data['hari']} {data['jam_mulai']}-{data['jam_selesai']} "
        f"@ {data['ruangan_kode']}"
    )


def _format_pesan_event(event: ScheduleEvent) -> str:
    """Menyusun isi pesan notifikasi yang ringkas untuk mahasiswa, dosen, dan admin."""
    if event.event_type == EventType.SCHEDULE_DELETED:
        info = format_ringkas_slot(event.before) if event.before else ""
        return f"Jadwal #{event.jadwal_id} dihapus ({info})".strip()

    if event.before and event.after:
        return (
            f"Jadwal #{event.jadwal_id} berubah: "
            f"{format_ringkas_slot(event.before)} -> {format_ringkas_slot(event.after)}"
        )

    sumber = event.after or event.before
    ringkas = format_ringkas_slot(sumber) if sumber else "-"
    return f"Jadwal #{event.jadwal_id} diperbarui ({ringkas})"


class Observer(Protocol):
    """Kontrak dasar seluruh observer penerima ScheduleEvent."""

    def update(self, event: ScheduleEvent) -> None:
        """Memproses satu event perubahan jadwal."""


class ScheduleSubject:
    """Subject pada Observer Pattern dengan deduplikasi attach dan isolasi exception."""

    def __init__(self) -> None:
        self._observers: list[Observer] = []

    @property
    def observers(self) -> tuple[Observer, ...]:
        """Mengembalikan tuple observer terdaftar secara read-only."""
        return tuple(self._observers)

    def attach(self, observer: Observer) -> None:
        """Mendaftarkan observer sekali saja; pendaftaran duplikat diabaikan."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: Observer) -> None:
        """Melepaskan observer dari daftar jika masih terdaftar."""
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, event: ScheduleEvent) -> list[str]:
        """Mengabari seluruh observer secara terisolasi dan mengembalikan daftar nama yang gagal."""
        gagal: list[str] = []
        for observer in list(self._observers):
            try:
                observer.update(event)
            except Exception:
                logger.exception(
                    "Observer %s gagal memproses event %s",
                    type(observer).__name__,
                    event.event_id,
                )
                gagal.append(type(observer).__name__)
        return gagal


class IdemStore(Protocol):
    """Abstraksi penyimpanan kunci idempotensi untuk deduplikasi pengiriman notifikasi."""

    def sudah(self, key: str) -> bool:
        """Mengembalikan True bila kunci notifikasi sudah pernah diproses."""

    def catat(self, key: str) -> None:
        """Menandai kunci notifikasi sudah terkirim."""


class MemoryIdemStore:
    """Implementasi IdemStore berbasis himpunan string di memori."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def sudah(self, key: str) -> bool:
        return key in self._seen

    def catat(self, key: str) -> None:
        self._seen.add(key)

    def reset(self) -> None:
        """Mengosongkan riwayat kunci idempotensi (berguna untuk isolasi pengujian)."""
        self._seen.clear()


class Channel(Protocol):
    """Kontrak kanal pengiriman notifikasi (Email, SMS, Push)."""

    name: str

    def send(self, penerima: str, pesan: str, key: str) -> None:
        """Mengirim notifikasi secara idempoten berdasarkan key."""


class LogChannel:
    """Kanal pengiriman berbasis logging Python dan pencatatan jejak untuk simulasi."""

    def __init__(self, nama: str, store: IdemStore) -> None:
        self.name = nama
        self._store = store
        self.terkirim: list[tuple[str, str, str]] = []

    def send(self, penerima: str, pesan: str, key: str) -> None:
        """Mengirim pesan jika belum pernah tercatat di store idempotensi."""
        if self._store.sudah(key):
            return
        logger.info("[%s] ke %s: %s", self.name, penerima, pesan)
        self.terkirim.append((penerima, pesan, key))
        self._store.catat(key)


class PesertaRepo(Protocol):
    """Abstraksi pembaca daftar NIM mahasiswa peserta suatu kelas."""

    def nim_di_kelas(self, kelas_id: int) -> list[str]:
        """Mengembalikan daftar NIM terurut yang terdaftar pada kelas_id."""


class DBPesertaRepo:
    """Pembaca daftar NIM peserta kelas dari tabel KRSDetail & KRS."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def nim_di_kelas(self, kelas_id: int) -> list[str]:
        session = _dispatch_session_var.get() or self._db
        stmt = (
            select(KRS.nim)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(KRSDetail.kelas_id == kelas_id)
            .distinct()
            .order_by(KRS.nim)
        )
        if session is not None:
            return list(session.scalars(stmt).all())

        with SessionLocal() as own_db:
            return list(own_db.scalars(stmt).all())


class StudentObserver:
    """Observer pengirim notifikasi ke seluruh mahasiswa peserta kelas terkait."""

    def __init__(self, peserta: PesertaRepo, channels: Sequence[Channel]) -> None:
        self._peserta = peserta
        self._channels = list(channels)

    def update(self, event: ScheduleEvent) -> None:
        kelas_ids: list[int] = []
        for snap in (event.after, event.before):
            if snap and snap.get("kelas_id") is not None:
                kid = int(snap["kelas_id"])
                if kid not in kelas_ids:
                    kelas_ids.append(kid)
        if not kelas_ids:
            return

        pesan = _format_pesan_event(event)
        nims: list[str] = []
        for kid in kelas_ids:
            for nim in self._peserta.nim_di_kelas(kid):
                if nim not in nims:
                    nims.append(nim)

        for nim in nims:
            for ch in self._channels:
                ch.send(nim, pesan, key=f"{event.event_id}:{nim}:{ch.name}")


class LecturerObserver:
    """Observer pengirim notifikasi ke dosen pengampu baru maupun sebelumnya."""

    def __init__(self, channels: Sequence[Channel]) -> None:
        self._channels = list(channels)

    def update(self, event: ScheduleEvent) -> None:
        dosen_ids: list[int] = []
        for snap in (event.after, event.before):
            if snap and snap.get("dosen_id") is not None:
                did = int(snap["dosen_id"])
                if did not in dosen_ids:
                    dosen_ids.append(did)
        if not dosen_ids:
            return

        pesan = _format_pesan_event(event)
        for did in dosen_ids:
            penerima = f"dosen-{did}"
            for ch in self._channels:
                ch.send(penerima, pesan, key=f"{event.event_id}:{penerima}:{ch.name}")


class AdminObserver:
    """Observer pencatat ringkasan perubahan jadwal untuk admin akademik."""

    def __init__(self, channels: Sequence[Channel]) -> None:
        self._channels = list(channels)

    def update(self, event: ScheduleEvent) -> None:
        pesan = _format_pesan_event(event)
        for ch in self._channels:
            ch.send("admin-akademik", pesan, key=f"{event.event_id}:admin:{ch.name}")


class OutboxDispatcher:
    """Pemroses tabel outbox pasca-commit dengan batas retry dan dukungan SKIP LOCKED."""

    MAX_ATTEMPTS = 5

    def __init__(self, db: Session, subject: ScheduleSubject) -> None:
        self.db = db
        self.subject = subject

    def run(self, batch: int = 50) -> int:
        """Memproses hingga `batch` baris outbox berstatus PENDING secara aman."""
        token = _dispatch_session_var.set(self.db)
        try:
            rows = self.db.scalars(
                select(Outbox)
                .where(Outbox.status == "PENDING")
                .order_by(Outbox.id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            ).all()

            for row in rows:
                row.attempts += 1
                gagal = self.subject.notify(row.ke_event())
                if not gagal:
                    row.status = "SENT"
                elif row.attempts >= self.MAX_ATTEMPTS:
                    row.status = "FAILED"

            self.db.commit()
            return len(rows)
        finally:
            _dispatch_session_var.reset(token)


def build_default_subject(
    peserta: PesertaRepo, channels: Sequence[Channel]
) -> ScheduleSubject:
    """Membangun ScheduleSubject dengan ketiga observer standar terpasang sekali."""
    subject = ScheduleSubject()
    subject.attach(StudentObserver(peserta, channels))
    subject.attach(LecturerObserver(channels))
    subject.attach(AdminObserver(channels))
    return subject


# Wiring singleton dilakukan SEKALI pada inisialisasi modul/startup (bukan per HTTP request).
_default_idem_store = MemoryIdemStore()
_default_channels: tuple[LogChannel, LogChannel, LogChannel] = (
    LogChannel("EMAIL", _default_idem_store),
    LogChannel("SMS", _default_idem_store),
    LogChannel("PUSH", _default_idem_store),
)
_default_subject = build_default_subject(DBPesertaRepo(), _default_channels)


def get_default_subject() -> ScheduleSubject:
    """Mengembalikan singleton ScheduleSubject aplikasi."""
    return _default_subject


def get_default_channels() -> tuple[LogChannel, LogChannel, LogChannel]:
    """Mengembalikan tuple channel default (EMAIL, SMS, PUSH) untuk inspeksi/log."""
    return _default_channels


def get_default_idem_store() -> MemoryIdemStore:
    """Mengembalikan store idempotensi default aplikasi."""
    return _default_idem_store

"""Service layer SchedulingService untuk CRUD jadwal, validasi, KRS invalidation, dan Outbox."""

from collections.abc import Callable
import logging
import time

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.jadwal import Dosen, Jadwal, Kelas, Outbox, Ruangan
from app.models.krs import KRSDetail
from app.schemas.jadwal import JadwalIn
from app.services.conflict import Conflict, detect_schedule_conflict
from app.services.exceptions import (
    CapacityError,
    NotFoundError,
    ScheduleConflictError,
)
from app.services.krs_invalidator import KRSInvalidator
from app.services.observer import (
    EventType,
    OutboxDispatcher,
    ScheduleEvent,
    ScheduleSubject,
    format_ringkas_slot,
    get_default_subject,
    snapshot_jadwal,
)

logger = logging.getLogger("sevima.scheduling")


def cek_kapasitas(db: Session, kelas_id: int, ruangan_kode: str) -> None:
    """Memastikan kapasitas ruangan mencukupi untuk max(kuota kelas, mahasiswa terdaftar)."""
    ruang = db.get(Ruangan, ruangan_kode)
    kelas = db.get(Kelas, kelas_id)
    if ruang is None or kelas is None:
        raise NotFoundError("Ruangan atau kelas tidak ditemukan")

    terdaftar = (
        db.scalar(
            select(func.count())
            .select_from(KRSDetail)
            .where(KRSDetail.kelas_id == kelas_id)
        )
        or 0
    )
    peserta = max(kelas.kuota, terdaftar)
    if peserta > ruang.kapasitas:
        raise CapacityError(
            f"Ruang {ruang.kode} berkapasitas {ruang.kapasitas}, "
            f"kelas {kelas.nama} butuh {peserta} kursi"
        )


class SchedulingService:
    """Mengelola penjadwalan kuliah dengan penguncian baris, KRS invalidation, dan Outbox."""

    def __init__(
        self,
        db: Session,
        subject: ScheduleSubject | None = None,
        auto_dispatch: bool = True,
    ) -> None:
        self.db = db
        self.subject = subject if subject is not None else get_default_subject()
        self.auto_dispatch = auto_dispatch
        self.krs = KRSInvalidator(db)

    def _dispatch_after_commit(self) -> None:
        """Memproses outbox pasca-commit tanpa membatalkan jadwal jika notifikasi bermasalah."""
        if not self.auto_dispatch:
            return
        try:
            OutboxDispatcher(self.db, self.subject).run()
        except Exception:
            logger.exception("Gagal mendispatch outbox pasca-commit")
            if self.db.in_transaction():
                self.db.rollback()

    def _mulai_transaksi_terkunci(self) -> bool:
        """Membuka BEGIN IMMEDIATE pada SQLite agar baca-cek-simpan bersifat atomik."""
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "sqlite" and not self.db.in_transaction():
            self.db.execute(text("BEGIN IMMEDIATE"))
            return True
        return False

    def _kunci(self, ruangan_kode: str, dosen_id: int) -> tuple[Ruangan | None, Dosen | None]:
        """Mengunci baris Ruangan lalu Dosen (urutan tetap anti-deadlock)."""
        ruang = self.db.execute(
            select(Ruangan).where(Ruangan.kode == ruangan_kode).with_for_update()
        ).scalar_one_or_none()
        dosen = self.db.execute(
            select(Dosen).where(Dosen.id == dosen_id).with_for_update()
        ).scalar_one_or_none()
        return ruang, dosen

    def _bentrok_di_db(
        self, data: JadwalIn, abaikan_id: int | None = None
    ) -> list[Conflict]:
        """Mencari jadwal tersimpan di database yang bertumpuk ruangan atau dosen."""
        q = select(Jadwal).where(
            Jadwal.hari == data.hari,
            Jadwal.jam_mulai < data.jam_selesai,
            Jadwal.jam_selesai > data.jam_mulai,
            or_(
                Jadwal.ruangan_kode == data.ruangan_kode,
                Jadwal.dosen_id == data.dosen_id,
            ),
        )
        if abaikan_id is not None:
            q = q.where(Jadwal.id != abaikan_id)

        hasil: list[Conflict] = []
        for lama in self.db.scalars(q):
            if lama.ruangan_kode == data.ruangan_kode:
                hasil.append(Conflict("room_conflict", (lama.id,)))
            if lama.dosen_id == data.dosen_id:
                hasil.append(Conflict("lecturer_conflict", (lama.id,)))
        return hasil

    def _simpan(self, jadwal: Jadwal, data: JadwalIn) -> Jadwal:
        """Memvalidasi referensi, kunci baris, bentrok, dan kapasitas lalu commit atomik."""
        is_update = jadwal.id is not None
        before = snapshot_jadwal(jadwal) if is_update else None

        ruang, dosen = self._kunci(data.ruangan_kode, data.dosen_id)
        kelas = self.db.get(Kelas, data.kelas_id)
        if ruang is None or kelas is None or dosen is None:
            raise NotFoundError("Ruangan, kelas, atau dosen tidak ditemukan")

        konflik = self._bentrok_di_db(data, abaikan_id=jadwal.id)
        if konflik:
            raise ScheduleConflictError(konflik)

        cek_kapasitas(self.db, data.kelas_id, data.ruangan_kode)

        jadwal.kelas_id = data.kelas_id
        jadwal.hari = data.hari
        jadwal.jam_mulai = data.jam_mulai
        jadwal.jam_selesai = data.jam_selesai
        jadwal.ruangan_kode = data.ruangan_kode
        jadwal.dosen_id = data.dosen_id

        if is_update and before is not None:
            jadwal.sequence = (jadwal.sequence or 0) + 1
            after = snapshot_jadwal(jadwal)
            alasan = (
                f"Jadwal #{jadwal.id} berubah: "
                f"{format_ringkas_slot(before)} -> {format_ringkas_slot(after)}"
            )
            kelas_terdampak = {int(before["kelas_id"]), data.kelas_id}
            for kid in sorted(kelas_terdampak):
                self.krs.invalidate(kid, alasan)
            event = ScheduleEvent(
                event_type=EventType.SCHEDULE_CHANGED,
                jadwal_id=jadwal.id,
                before=before,
                after=after,
            )
            self.db.add(Outbox.dari_event(event))
        else:
            # Tambahkan objek baru paling akhir agar autoflush tidak memicu cek ke diri sendiri.
            self.db.add(jadwal)

        self.db.commit()
        self.db.refresh(jadwal)
        return jadwal

    def _jalankan_dengan_retry(self, aksi: Callable[[], Jadwal]) -> Jadwal:
        """Menjalankan operasi tulis dalam transaksi terkunci dengan retry lock SQLite."""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self._mulai_transaksi_terkunci()
                return aksi()
            except OperationalError as exc:
                self.db.rollback()
                msg = str(exc).lower()
                is_lock_error = any(
                    token in msg for token in ("locked", "busy", "deadlock")
                )
                if is_lock_error and attempt < max_attempts - 1:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise
            except Exception:
                self.db.rollback()
                raise

        raise RuntimeError("Gagal menyimpan jadwal")  # pragma: no cover

    def create(self, data: JadwalIn) -> Jadwal:
        """Membuat jadwal kuliah baru setelah lolos validasi bentrok dan kapasitas."""
        return self._jalankan_dengan_retry(lambda: self._simpan(Jadwal(), data))

    def update(self, jadwal_id: int, data: JadwalIn) -> Jadwal:
        """Memperbarui jadwal, menginvalidasi KRS terdampak, lalu mendispatch outbox."""

        def _aksi() -> Jadwal:
            jadwal = self.db.get(Jadwal, jadwal_id)
            if jadwal is None:
                raise NotFoundError(f"Jadwal {jadwal_id} tidak ditemukan")
            return self._simpan(jadwal, data)

        jadwal = self._jalankan_dengan_retry(_aksi)
        # Outbox selalu diproses SETELAH transaksi utama benar-benar COMMIT.
        self._dispatch_after_commit()
        return jadwal

    def delete(self, jadwal_id: int) -> None:
        """Menghapus jadwal, menginvalidasi KRS, mencatat outbox atomik, lalu dispatch."""
        max_attempts = 3
        deleted = False
        for attempt in range(max_attempts):
            try:
                self._mulai_transaksi_terkunci()
                jadwal = self.db.get(Jadwal, jadwal_id)
                if jadwal is None:
                    raise NotFoundError(f"Jadwal {jadwal_id} tidak ditemukan")

                before = snapshot_jadwal(jadwal)
                alasan = f"Jadwal #{jadwal.id} dihapus ({format_ringkas_slot(before)})"
                self.krs.invalidate(jadwal.kelas_id, alasan)
                event = ScheduleEvent(
                    event_type=EventType.SCHEDULE_DELETED,
                    jadwal_id=jadwal.id,
                    before=before,
                    after=None,
                )
                self.db.delete(jadwal)
                self.db.add(Outbox.dari_event(event))
                self.db.commit()
                deleted = True
                break
            except OperationalError as exc:
                self.db.rollback()
                msg = str(exc).lower()
                is_lock_error = any(
                    token in msg for token in ("locked", "busy", "deadlock")
                )
                if is_lock_error and attempt < max_attempts - 1:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise
            except Exception:
                self.db.rollback()
                raise

        if deleted:
            self._dispatch_after_commit()

    def list_conflicts(self) -> list[Conflict]:
        """Mendeteksi seluruh bentrok ruangan dan dosen dari jadwal yang tersimpan."""
        semua = self.db.scalars(select(Jadwal).order_by(Jadwal.id)).all()
        return detect_schedule_conflict(semua)

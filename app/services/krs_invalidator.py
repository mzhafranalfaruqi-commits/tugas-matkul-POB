"""Service untuk menginvalidasi KRS terdampak perubahan jadwal dalam satu Unit of Work."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.krs import Actor, KRS, KRSDetail, KRSLog, KRSStatus, Notifikasi


class KRSInvalidator:
    """Mengembalikan KRS SUBMITTED/APPROVED ke status REVISION saat jadwal kelas berubah."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def invalidate(self, kelas_id: int, alasan: str) -> list[KRS]:
        """Menandai seluruh KRS SUBMITTED/APPROVED yang mengambil kelas_id untuk revisi.

        Catatan transaksional: method ini TIDAK memanggil db.commit() agar tetap
        atomik bersama pembaruan jadwal dan pencatatan Outbox pada SchedulingService.
        """
        alasan_ringkas = alasan.strip()[:480]
        stmt = (
            select(KRS)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(
                KRSDetail.kelas_id == kelas_id,
                KRS.status.in_((KRSStatus.SUBMITTED, KRSStatus.APPROVED)),
            )
            .order_by(KRS.id)
            .with_for_update()
        )

        terdampak: list[KRS] = []
        seen_ids: set[int] = set()
        now = datetime.now(timezone.utc)

        for krs in self.db.scalars(stmt):
            if krs.id in seen_ids:
                continue
            seen_ids.add(krs.id)

            krs.transition(KRSStatus.REVISION, Actor.SISTEM)
            krs.catatan_revisi = f"Otomatis: {alasan_ringkas}"[:500]
            krs.diubah_pada = now

            self.db.add(
                KRSLog(
                    krs_id=krs.id,
                    aksi="INVALIDATE",
                    aktor_id=Actor.SISTEM.value,
                    catatan=alasan_ringkas[:500],
                )
            )
            self.db.add(
                Notifikasi(
                    nim=krs.nim,
                    pesan=(
                        f"KRS semester {krs.semester} perlu direvisi: {alasan_ringkas}"
                    )[:500],
                )
            )
            terdampak.append(krs)

        return terdampak

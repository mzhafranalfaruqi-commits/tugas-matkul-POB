"""Penjadwal cron otomatis (APScheduler) untuk generate tagihan semester dan reminder tunggakan."""

from collections.abc import Callable
from datetime import date
import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain.keuangan import tentukan_semester_aktif
from app.services.billing_service import (
    BillingService,
    GenerateBillingResult,
    ReminderResult,
)

logger = logging.getLogger("sevima.scheduler")

DEFAULT_TIMEZONE = "Asia/Jakarta"


class BillingScheduler:
    """Wrapper APScheduler untuk cron job tagihan semester dan reminder harian."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        self._session_factory = session_factory
        self.timezone = timezone_name
        self._scheduler = self._create_scheduler()

    def _create_scheduler(self) -> BackgroundScheduler:
        """Membangun instance BackgroundScheduler baru dan mendaftarkan seluruh cron job."""
        scheduler = BackgroundScheduler(timezone=self.timezone)
        scheduler.add_job(
            self.run_semester_billing_job,
            trigger=CronTrigger(
                month="2,8",
                day=1,
                hour=0,
                minute=5,
                timezone=self.timezone,
            ),
            id="semester_billing_generator",
            name="Generate Tagihan SPP Awal Semester",
            replace_existing=True,
        )
        scheduler.add_job(
            self.run_daily_reminder_job,
            trigger=CronTrigger(
                hour=7,
                minute=0,
                timezone=self.timezone,
            ),
            id="daily_overdue_reminder",
            name="Hitung Denda & Kirim Reminder Tunggakan Harian",
            replace_existing=True,
        )
        return scheduler

    @property
    def is_running(self) -> bool:
        """Mengembalikan True apabila scheduler APScheduler sedang aktif berjalan."""
        return bool(self._scheduler.running)

    def start(self) -> None:
        """Menyalakan BackgroundScheduler secara idempoten."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("BillingScheduler aktif (%s)", self.timezone)

    def shutdown(self, wait: bool = False) -> None:
        """Menghentikan scheduler dan menyiapkan ulang instance bersih untuk siklus berikutnya."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("BillingScheduler dimatikan")
            self._scheduler = self._create_scheduler()

    def list_jobs(self) -> list[dict[str, Any]]:
        """Mengembalikan daftar job terjadwal beserta trigger dan jadwal eksekusi berikutnya."""
        return [
            {
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run_time": getattr(job, "next_run_time", None),
            }
            for job in self._scheduler.get_jobs()
        ]

    def run_semester_billing_job(
        self,
        semester: str | None = None,
        semester_start: date | None = None,
    ) -> GenerateBillingResult:
        """Menjalankan generate tagihan SPP untuk awal semester secara atomik."""
        tgl_mulai = semester_start or date.today()
        sem = semester or tentukan_semester_aktif(tgl_mulai)
        with self._session_factory() as db:
            hasil = BillingService(db).generate_billing(
                semester=sem, semester_start=tgl_mulai
            )
        logger.info(
            "Cron semester_billing_generator (%s): created=%d skipped=%d",
            sem,
            hasil.created_count,
            hasil.skipped_count,
        )
        return hasil

    def run_daily_reminder_job(
        self, as_of: date | None = None
    ) -> ReminderResult:
        """Menjalankan kalkulasi denda harian dan pengiriman reminder tunggakan."""
        ref_date = as_of or date.today()
        with self._session_factory() as db:
            hasil = BillingService(db).send_overdue_reminders(as_of=ref_date)
        logger.info(
            "Cron daily_overdue_reminder (%s): reminded=%d",
            ref_date.isoformat(),
            hasil.reminded_count,
        )
        return hasil


_default_billing_scheduler = BillingScheduler()


def get_billing_scheduler() -> BillingScheduler:
    """Mengembalikan singleton BillingScheduler aplikasi."""
    return _default_billing_scheduler

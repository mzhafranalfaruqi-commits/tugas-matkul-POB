"""Model ORM SQLAlchemy untuk Modul PMB, KRS, Jadwal, Nilai, Keuangan, dan Presensi."""

from app.models.jadwal import Dosen, Jadwal, Kelas, Outbox, Ruangan
from app.models.keuangan import (
    Billing,
    BillingStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.models.krs import (
    Actor,
    KRS,
    KRSDetail,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    SkalaNilai,
    TRANSITIONS,
    prerequisite,
)
from app.models.nilai import GradeHistory
from app.models.pmb import (
    Base,
    CalonMahasiswa,
    JalurMasuk,
    NimCounter,
    ProgramStudi,
    StatusPMB,
)
from app.models.presensi import (
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
)

__all__ = [
    "Actor",
    "AttendanceRecord",
    "AttendanceSession",
    "AttendanceStatus",
    "Base",
    "Billing",
    "BillingStatus",
    "CalonMahasiswa",
    "Dosen",
    "GradeHistory",
    "Jadwal",
    "JalurMasuk",
    "Kelas",
    "KRS",
    "KRSDetail",
    "KRSLog",
    "KRSStatus",
    "MataKuliah",
    "NimCounter",
    "Notifikasi",
    "Outbox",
    "Payment",
    "PaymentMethod",
    "PaymentStatus",
    "ProgramStudi",
    "Ruangan",
    "SkalaNilai",
    "StatusPMB",
    "TRANSITIONS",
    "prerequisite",
]

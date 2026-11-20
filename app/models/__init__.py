"""Model ORM SQLAlchemy untuk Modul PMB, Modul KRS, dan Modul Jadwal."""

from app.models.jadwal import Dosen, Jadwal, Kelas, Ruangan
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
from app.models.pmb import (
    Base,
    CalonMahasiswa,
    JalurMasuk,
    NimCounter,
    ProgramStudi,
    StatusPMB,
)

__all__ = [
    "Actor",
    "Base",
    "CalonMahasiswa",
    "Dosen",
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
    "ProgramStudi",
    "Ruangan",
    "SkalaNilai",
    "StatusPMB",
    "TRANSITIONS",
    "prerequisite",
]

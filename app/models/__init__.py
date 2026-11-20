"""Model ORM SQLAlchemy untuk Modul PMB dan Modul KRS."""

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
    "JalurMasuk",
    "KRS",
    "KRSDetail",
    "KRSLog",
    "KRSStatus",
    "MataKuliah",
    "NimCounter",
    "Notifikasi",
    "ProgramStudi",
    "SkalaNilai",
    "StatusPMB",
    "TRANSITIONS",
    "prerequisite",
]

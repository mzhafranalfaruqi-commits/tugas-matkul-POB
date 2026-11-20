"""Model ORM SQLAlchemy untuk Modul PMB dan Modul KRS."""

from app.models.krs import (
    KRS,
    KRSDetail,
    KRSStatus,
    MataKuliah,
    SkalaNilai,
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
    "Base",
    "CalonMahasiswa",
    "JalurMasuk",
    "KRS",
    "KRSDetail",
    "KRSStatus",
    "MataKuliah",
    "NimCounter",
    "ProgramStudi",
    "SkalaNilai",
    "StatusPMB",
    "prerequisite",
]

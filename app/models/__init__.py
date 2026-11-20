"""Model ORM SQLAlchemy untuk Modul PMB."""

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
    "NimCounter",
    "ProgramStudi",
    "StatusPMB",
]

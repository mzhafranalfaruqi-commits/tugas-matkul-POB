"""Model ORM SQLAlchemy untuk Modul PMB."""

from app.models.pmb import Base, CalonMahasiswa, JalurMasuk, ProgramStudi, StatusPMB

__all__ = [
    "Base",
    "CalonMahasiswa",
    "JalurMasuk",
    "ProgramStudi",
    "StatusPMB",
]

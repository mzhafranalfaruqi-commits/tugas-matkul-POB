"""Router FastAPI tipis untuk endpoint Modul Jadwal & Ruangan (/api/jadwal)."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.jadwal import ConflictOut, JadwalIn, JadwalOut
from app.services.scheduling_service import SchedulingService

router = APIRouter(prefix="/api/jadwal", tags=["Jadwal"])


@router.get(
    "/conflicts",
    response_model=list[ConflictOut],
    summary="Daftar seluruh bentrok jadwal yang terdeteksi di database",
    responses={
        200: {"description": "Daftar konflik ruangan dan/atau dosen dari jadwal tersimpan"},
    },
)
def list_conflicts(db: Session = Depends(get_db)) -> list[ConflictOut]:
    """Mengembalikan seluruh pasangan jadwal bentrok (ruangan & dosen) untuk dashboard admin."""
    konflik = SchedulingService(db).list_conflicts()
    return [ConflictOut(type=k.type, affected=list(k.affected)) for k in konflik]


@router.post(
    "",
    response_model=JadwalOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat jadwal kuliah baru dengan validasi bentrok & kapasitas",
    responses={
        201: {"description": "Jadwal kuliah berhasil dibuat"},
        404: {"description": "Ruangan, kelas, atau dosen tidak ditemukan"},
        409: {"description": "Bentrok jadwal ruangan/dosen atau kapasitas ruangan tidak cukup"},
        422: {"description": "Payload jadwal tidak valid (mis. jam_mulai >= jam_selesai)"},
    },
)
def create_jadwal(
    data_in: JadwalIn,
    db: Session = Depends(get_db),
) -> JadwalOut:
    """Menyimpan jadwal kuliah baru setelah melewati pemeriksaan hard constraint."""
    jadwal = SchedulingService(db).create(data_in)
    return JadwalOut.model_validate(jadwal)


@router.put(
    "/{jadwal_id}",
    response_model=JadwalOut,
    summary="Perbarui jadwal kuliah (mengabaikan dirinya sendiri saat cek bentrok)",
    responses={
        200: {"description": "Jadwal kuliah berhasil diperbarui"},
        404: {"description": "Jadwal, ruangan, kelas, atau dosen tidak ditemukan"},
        409: {"description": "Bentrok jadwal dengan jadwal lain atau kapasitas tidak cukup"},
        422: {"description": "Payload jadwal tidak valid (mis. jam_mulai >= jam_selesai)"},
    },
)
def update_jadwal(
    jadwal_id: int,
    data_in: JadwalIn,
    db: Session = Depends(get_db),
) -> JadwalOut:
    """Memperbarui hari, jam, ruangan, atau dosen pada jadwal kuliah tertentu."""
    jadwal = SchedulingService(db).update(jadwal_id, data_in)
    return JadwalOut.model_validate(jadwal)


@router.delete(
    "/{jadwal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus jadwal kuliah",
    responses={
        204: {"description": "Jadwal kuliah berhasil dihapus"},
        404: {"description": "Jadwal tidak ditemukan"},
    },
)
def delete_jadwal(
    jadwal_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Menghapus satu entri jadwal kuliah dari database."""
    SchedulingService(db).delete(jadwal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

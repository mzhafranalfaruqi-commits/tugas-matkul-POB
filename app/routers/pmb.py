"""Router FastAPI tipis untuk endpoint Modul PMB (/api/pmb)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.pmb import (
    ApproveOut,
    PendaftarOut,
    RejectOut,
    StatsOut,
    StatusPendaftaranOut,
)
from app.services import pmb_service
from app.services.exceptions import (
    EmailSudahTerdaftar,
    PendaftarTidakDitemukan,
    ReferensiTidakValid,
    StatusTidakValid,
)

router = APIRouter(prefix="/api/pmb", tags=["PMB"])


@router.post(
    "/register",
    response_model=PendaftarOut,
    status_code=status.HTTP_201_CREATED,
    summary="Daftar calon mahasiswa baru",
)
def register(data_in: pmb_service.RegisterRequest, db: Session = Depends(get_db)) -> PendaftarOut:
    """Mendaftarkan calon mahasiswa baru dan menyimpannya dengan status awal pending."""
    try:
        calon = pmb_service.register(db, data_in)
    except EmailSudahTerdaftar as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ReferensiTidakValid as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return PendaftarOut.model_validate(calon)


@router.get(
    "/status/{pendaftar_id}",
    response_model=StatusPendaftaranOut,
    summary="Cek status pendaftaran",
)
def get_status(pendaftar_id: int, db: Session = Depends(get_db)) -> StatusPendaftaranOut:
    """Mengambil detail pendaftar, status saat ini, dan NIM jika sudah disetujui."""
    try:
        calon = pmb_service.get_status(db, pendaftar_id)
    except PendaftarTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return StatusPendaftaranOut(
        id=calon.id,
        nama_lengkap=calon.nama_lengkap,
        email=calon.email,
        program_studi_kode=calon.program_studi.kode,
        program_studi_nama=calon.program_studi.nama,
        jalur_masuk=calon.jalur_masuk.nama,
        status=calon.status,
        nim=calon.nim,
        created_at=calon.created_at,
        approved_at=calon.approved_at,
    )


@router.put(
    "/approve/{pendaftar_id}",
    response_model=ApproveOut,
    summary="Admin approve pendaftaran dan generate NIM otomatis",
)
def approve(
    pendaftar_id: int,
    tahun: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> ApproveOut:
    """Menyetujui pendaftar dan meng-generate NIM secara otomatis (idempotent)."""
    try:
        calon, already_approved = pmb_service.approve(db, pendaftar_id, tahun=tahun)
    except PendaftarTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (StatusTidakValid, ReferensiTidakValid) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return ApproveOut(
        id=calon.id,
        nama_lengkap=calon.nama_lengkap,
        status=calon.status,
        nim=calon.nim,
        approved_at=calon.approved_at,
        already_approved=already_approved,
    )


@router.put(
    "/reject/{pendaftar_id}",
    response_model=RejectOut,
    summary="Admin reject pendaftaran calon mahasiswa",
)
def reject(pendaftar_id: int, db: Session = Depends(get_db)) -> RejectOut:
    """Menolak pendaftaran calon mahasiswa selama statusnya belum approved."""
    try:
        calon = pmb_service.reject(db, pendaftar_id)
    except PendaftarTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except StatusTidakValid as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return RejectOut.model_validate(calon)


@router.get(
    "/stats",
    response_model=StatsOut,
    summary="Dashboard statistik jumlah pendaftar PMB",
)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    """Menyajikan statistik pendaftar berdasarkan status, program studi, dan jalur masuk."""
    return pmb_service.get_stats(db)

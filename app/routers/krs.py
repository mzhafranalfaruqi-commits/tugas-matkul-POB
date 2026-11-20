"""Router FastAPI tipis untuk endpoint Modul KRS (/api/krs)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.krs import KRSDetail
from app.schemas.krs import (
    AddCourseRequest,
    KRSDetailOut,
    KRSOut,
    KRSValidationOut,
    RemoveCourseOut,
    ValidationIssueOut,
)
from app.services.exceptions import (
    KRSStatusTidakValid,
    KRSTidakDitemukan,
    KRSValidasiGagal,
)
from app.services.krs_manager import KRSManager

router = APIRouter(prefix="/api/krs", tags=["KRS"])


def _to_detail_out(detail: KRSDetail) -> KRSDetailOut:
    """Mengubah objek ORM KRSDetail menjadi DTO response."""
    return KRSDetailOut(
        id=detail.id,
        kode_mk=detail.kode_mk,
        nama_mk=detail.matakuliah.nama,
        sks=detail.matakuliah.sks,
        hari=detail.matakuliah.hari,
        jam_mulai=detail.matakuliah.jam_mulai,
        jam_selesai=detail.matakuliah.jam_selesai,
        nilai=detail.nilai,
    )


@router.get(
    "/{nim}",
    response_model=KRSOut,
    summary="Lihat isi KRS mahasiswa pada semester aktif",
    responses={
        200: {"description": "Detail KRS beserta daftar mata kuliah ditemukan"},
        404: {"description": "Mahasiswa ber-NIM atau KRS semester terkait tidak ditemukan"},
    },
)
def get_krs(
    nim: str,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSOut:
    """Mengambil isi Kartu Rencana Studi mahasiswa beserta total SKS."""
    manager = KRSManager(db, semester=semester)
    try:
        krs = manager.get_krs(nim)
    except KRSTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    details_out = [_to_detail_out(d) for d in krs.details]
    total_sks = sum(item.sks for item in details_out)
    return KRSOut(
        id=krs.id,
        nim=krs.nim,
        semester=krs.semester,
        status=krs.status,
        dosen_pa_id=krs.dosen_pa_id,
        total_sks=total_sks,
        details=details_out,
    )


@router.post(
    "/{nim}/courses",
    response_model=KRSDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tambah mata kuliah ke KRS (melewati rantai validator)",
    responses={
        201: {"description": "Mata kuliah lolos seluruh validasi dan tersimpan di KRS"},
        400: {
            "description": "Gagal aturan validasi KRS (duplikat, SKS > 24, prasyarat belum lulus, atau jadwal bentrok)"
        },
        404: {"description": "Mahasiswa ber-NIM atau mata kuliah tidak ditemukan"},
        409: {"description": "Konflik status: KRS sudah SUBMITTED atau APPROVED"},
    },
)
def add_course(
    nim: str,
    data_in: AddCourseRequest,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSDetailOut:
    """Menambahkan mata kuliah ke KRS mahasiswa selama berstatus DRAFT/REVISION."""
    manager = KRSManager(db, semester=semester)
    try:
        detail = manager.add_course(nim, data_in.kode_mk)
    except KRSTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except KRSStatusTidakValid as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except KRSValidasiGagal as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _to_detail_out(detail)


@router.delete(
    "/{nim}/courses/{kode_mk}",
    response_model=RemoveCourseOut,
    summary="Hapus mata kuliah dari KRS",
    responses={
        200: {"description": "Mata kuliah berhasil dihapus dari KRS"},
        404: {"description": "Mahasiswa ber-NIM, KRS, atau mata kuliah terkait tidak ditemukan"},
        409: {"description": "Konflik status: KRS sudah SUBMITTED atau APPROVED"},
    },
)
def remove_course(
    nim: str,
    kode_mk: str,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> RemoveCourseOut:
    """Menghapus satu baris mata kuliah dari KRS mahasiswa."""
    manager = KRSManager(db, semester=semester)
    try:
        manager.remove_course(nim, kode_mk)
    except KRSTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except KRSStatusTidakValid as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return RemoveCourseOut(
        message=f"Mata kuliah {kode_mk} berhasil dihapus dari KRS",
        nim=nim,
        semester=semester,
        kode_mk=kode_mk,
    )


@router.get(
    "/{nim}/validate",
    response_model=KRSValidationOut,
    summary="Validasi menyeluruh isi KRS (mengumpulkan seluruh error)",
    responses={
        200: {"description": "Hasil validasi menyeluruh KRS (daftar error kosong bila valid)"},
        404: {"description": "Mahasiswa ber-NIM tidak ditemukan"},
    },
)
def validate_krs(
    nim: str,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSValidationOut:
    """Memvalidasi seluruh mata kuliah dalam KRS dan mengembalikan seluruh pelanggaran."""
    manager = KRSManager(db, semester=semester)
    try:
        errors = manager.validate_krs(nim)
    except KRSTidakDitemukan as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return KRSValidationOut(
        nim=nim,
        semester=semester,
        valid=len(errors) == 0,
        errors=[ValidationIssueOut(ok=e.ok, message=e.message) for e in errors],
    )

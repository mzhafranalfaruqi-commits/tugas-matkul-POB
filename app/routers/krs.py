"""Router FastAPI tipis untuk endpoint Modul KRS (/api/krs)."""

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.krs import KRS, KRSDetail
from app.schemas.krs import (
    AddCourseRequest,
    ApproveKRSRequest,
    KRSDetailOut,
    KRSOut,
    KRSValidationOut,
    MataKuliahOut,
    RecommendKRSOut,
    RecommendKRSRequest,
    RemoveCourseOut,
    ReviseKRSRequest,
    ValidationIssueOut,
)
from app.services.krs_manager import KRSManager
from app.services.krs_recommender import KRSRecommender

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


def _to_krs_out(krs: KRS) -> KRSOut:
    """Mengubah objek ORM KRS beserta detailnya menjadi DTO response KRSOut."""
    details_out = [_to_detail_out(d) for d in krs.details]
    return KRSOut(
        id=krs.id,
        nim=krs.nim,
        semester=krs.semester,
        status=krs.status,
        dosen_pa_id=krs.dosen_pa_id,
        version=krs.version,
        submitted_at=krs.submitted_at,
        approved_at=krs.approved_at,
        catatan_revisi=krs.catatan_revisi,
        total_sks=sum(item.sks for item in details_out),
        details=details_out,
    )


@router.get(
    "/{nim}",
    response_model=KRSOut,
    summary="Lihat isi KRS mahasiswa pada semester aktif",
    responses={
        200: {"description": "Detail KRS beserta daftar mata kuliah dan versi ditemukan"},
        404: {"description": "Mahasiswa ber-NIM atau KRS semester terkait tidak ditemukan"},
    },
)
def get_krs(
    nim: str,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSOut:
    """Mengambil isi Kartu Rencana Studi mahasiswa beserta total SKS dan version."""
    krs = KRSManager(db, semester=semester).get_krs(nim)
    return _to_krs_out(krs)


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
        409: {"description": "Konflik status atau versi KRS (sudah SUBMITTED/APPROVED)"},
    },
)
def add_course(
    nim: str,
    data_in: AddCourseRequest,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSDetailOut:
    """Menambahkan mata kuliah ke KRS mahasiswa selama berstatus DRAFT/REVISION."""
    detail = KRSManager(db, semester=semester).add_course(nim, data_in.kode_mk)
    return _to_detail_out(detail)


@router.delete(
    "/{nim}/courses/{kode_mk}",
    response_model=RemoveCourseOut,
    summary="Hapus mata kuliah dari KRS",
    responses={
        200: {"description": "Mata kuliah berhasil dihapus dari KRS"},
        404: {"description": "Mahasiswa ber-NIM, KRS, atau mata kuliah terkait tidak ditemukan"},
        409: {"description": "Konflik status atau versi KRS (sudah SUBMITTED/APPROVED)"},
    },
)
def remove_course(
    nim: str,
    kode_mk: str,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> RemoveCourseOut:
    """Menghapus satu baris mata kuliah dari KRS mahasiswa."""
    KRSManager(db, semester=semester).remove_course(nim, kode_mk)
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
    errors = KRSManager(db, semester=semester).validate_krs(nim)
    return KRSValidationOut(
        nim=nim,
        semester=semester,
        valid=len(errors) == 0,
        errors=[ValidationIssueOut(ok=e.ok, message=e.message) for e in errors],
    )


@router.post(
    "/{nim}/submit",
    response_model=KRSOut,
    summary="Ajukan KRS oleh mahasiswa (DRAFT/REVISION -> SUBMITTED)",
    responses={
        200: {"description": "KRS berhasil diajukan ke Dosen PA"},
        400: {"description": "KRS kosong atau gagal validasi ulang sebelum pengajuan"},
        404: {"description": "Mahasiswa ber-NIM atau KRS semester terkait tidak ditemukan"},
        409: {"description": "Konflik state machine (status KRS bukan DRAFT/REVISION) atau versi berubah"},
    },
)
def submit_krs(
    nim: str,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSOut:
    """Mengajukan KRS mahasiswa setelah memeriksa kelengkapan & validasi ulang."""
    krs = KRSManager(db, semester=semester).submit_krs(nim)
    return _to_krs_out(krs)


@router.post(
    "/{nim}/approve",
    response_model=KRSOut,
    summary="Setujui KRS oleh Dosen PA (SUBMITTED -> APPROVED)",
    responses={
        200: {"description": "KRS berhasil disetujui secara atomik beserta audit log & notifikasi"},
        400: {"description": "Payload permintaan tidak valid"},
        403: {"description": "Ditolak karena aktor bukan Dosen PA pemilik mahasiswa ini"},
        404: {"description": "Mahasiswa ber-NIM atau KRS semester terkait tidak ditemukan"},
        409: {"description": "Konflik state machine (bukan SUBMITTED) atau stale version (muat ulang)"},
    },
)
def approve_krs(
    nim: str,
    data_in: ApproveKRSRequest,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSOut:
    """Menyetujui KRS berstatus SUBMITTED secara atomik dengan optimistic locking."""
    krs = KRSManager(db, semester=semester).approve_krs(
        nim=nim,
        dosen_pa_id=data_in.dosen_pa_id,
        expected_version=data_in.expected_version,
    )
    return _to_krs_out(krs)


@router.post(
    "/{nim}/revise",
    response_model=KRSOut,
    summary="Kembalikan KRS untuk revisi oleh Dosen PA (SUBMITTED -> REVISION)",
    responses={
        200: {"description": "KRS dikembalikan ke mahasiswa dengan status REVISION beserta catatan"},
        400: {"description": "Catatan revisi kosong atau payload tidak valid"},
        403: {"description": "Ditolak karena aktor bukan Dosen PA pemilik mahasiswa ini"},
        404: {"description": "Mahasiswa ber-NIM atau KRS semester terkait tidak ditemukan"},
        409: {"description": "Konflik state machine (bukan SUBMITTED) atau stale version (muat ulang)"},
    },
)
def revise_krs(
    nim: str,
    data_in: ReviseKRSRequest,
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> KRSOut:
    """Meminta revisi KRS berstatus SUBMITTED dengan catatan wajib untuk mahasiswa."""
    krs = KRSManager(db, semester=semester).revise_krs(
        nim=nim,
        dosen_pa_id=data_in.dosen_pa_id,
        catatan=data_in.catatan,
        expected_version=data_in.expected_version,
    )
    return _to_krs_out(krs)


@router.post(
    "/{nim}/recommend",
    response_model=RecommendKRSOut,
    summary="Rekomendasi paket KRS optimal berbasis CSP Backtracking",
    responses={
        200: {"description": "Kombinasi mata kuliah optimal bebas bentrok, lulus prasyarat, & <= max_sks"},
        400: {"description": "Parameter max_sks atau hasil validasi guardrail tidak valid"},
        404: {"description": "Mahasiswa ber-NIM atau kode mata kuliah kandidat tidak ditemukan"},
    },
)
def recommend_krs(
    nim: str,
    data_in: RecommendKRSRequest = Body(default_factory=RecommendKRSRequest),
    semester: str = Query(default="20251", min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> RecommendKRSOut:
    """Menyusun rekomendasi kombinasi KRS (wajib > pilihan) lalu memverifikasinya via validator."""
    hasil = KRSRecommender().recommend(
        db=db,
        nim=nim,
        semester=semester,
        wajib=data_in.wajib,
        pilihan=data_in.pilihan,
        max_sks=data_in.max_sks,
    )
    return RecommendKRSOut(
        nim=hasil.nim,
        semester=hasil.semester,
        total_sks=hasil.total_sks,
        max_sks=hasil.max_sks,
        selected=[MataKuliahOut.model_validate(mk) for mk in hasil.selected],
        wajib_terpilih=hasil.wajib_terpilih,
        ditolak=hasil.ditolak,
    )

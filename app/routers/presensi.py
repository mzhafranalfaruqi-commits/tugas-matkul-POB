"""Router FastAPI untuk Modul Presensi (QR Code), Laporan Excel, & AI Attendance Insights."""

import base64
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.presensi import (
    AIAnalyzeRequest,
    AIAttendanceInsightsOut,
    JadwalRingkasPresensiOut,
    KelasPresensiReportOut,
    MahasiswaPresensiReportOut,
    QRGenerateOut,
    QRGenerateRequest,
    ScanOut,
    ScanRequest,
)
from app.services.attendance_ai import AttendanceAIService
from app.services.presensi_service import PresensiService, QRSessionResult
from app.services.transcript_pdf import sanitize_filename_segment

_PRESENSI_DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "presensi_dashboard.html"
)

presensi_router = APIRouter(prefix="/api/presensi", tags=["Presensi"])
attendance_alias_router = APIRouter(prefix="/attendance", tags=["Presensi"])


def _qr_image_response(res: QRSessionResult) -> Response:
    """Membentuk HTTP Response PNG QR Code lengkap dengan header metadata sesi & JWT token."""
    return Response(
        content=res.qr_png,
        media_type="image/png",
        headers={
            "X-Attendance-Token": res.token,
            "X-Session-Id": str(res.session_id),
            "X-Expires-At": res.expires_at.isoformat(),
            "Cache-Control": "no-store",
        },
    )


def _to_qr_out(res: QRSessionResult) -> QRGenerateOut:
    """Mengonversi QRSessionResult ke DTO JSON termasuk data URI base64 PNG."""
    b64 = base64.b64encode(res.qr_png).decode("ascii")
    return QRGenerateOut(
        session_id=res.session_id,
        schedule_id=res.schedule_id,
        kelas_id=res.kelas_id,
        kode_mk=res.kode_mk,
        nama_mk=res.nama_mk,
        nama_kelas=res.nama_kelas,
        pertemuan_ke=res.pertemuan_ke,
        tanggal=res.tanggal,
        valid_minutes=res.valid_minutes,
        generated_at=res.generated_at,
        expires_at=res.expires_at,
        jti=res.jti,
        token=res.token,
        qr_base64=f"data:image/png;base64,{b64}",
    )


@presensi_router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Dashboard Web Presensi QR Code, Simulasi Scan, Laporan, & AI Insights",
    responses={200: {"description": "Halaman HTML Dashboard Modul Presensi"}},
)
def presensi_dashboard_ui() -> HTMLResponse:
    """Menyajikan antarmuka web interaktif untuk dosen dan simulasi scan mahasiswa."""
    return HTMLResponse(
        content=_PRESENSI_DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    )


@presensi_router.get(
    "/schedules",
    response_model=list[JadwalRingkasPresensiOut],
    summary="Daftar seluruh jadwal kuliah untuk pemilih QR sesi presensi",
    responses={200: {"description": "Daftar jadwal beserta metadata MK, kelas, dosen, & ruang"}},
)
def list_presensi_schedules(
    db: Session = Depends(get_db),
) -> list[JadwalRingkasPresensiOut]:
    """Mengembalikan daftar jadwal kuliah terurut per hari dan jam mulai."""
    rows = PresensiService(db).list_schedules()
    return [JadwalRingkasPresensiOut(**r) for r in rows]


@attendance_alias_router.get(
    "/qr/{schedule_id}",
    summary="Generate gambar PNG QR code presensi untuk suatu jadwal kuliah (sesuai kontrak modul)",
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "Gambar PNG QR code beserta token JWT di header X-Attendance-Token",
        },
        400: {"description": "Parameter durasi atau geofence tidak valid"},
        403: {"description": "Dosen pada header X-Dosen-Id bukan pengampu jadwal ini"},
        404: {"description": "Jadwal kuliah tidak ditemukan"},
    },
)
@presensi_router.get(
    "/qr/{schedule_id}",
    summary="Generate gambar PNG QR code presensi untuk suatu jadwal kuliah",
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "Gambar PNG QR code beserta token JWT di header X-Attendance-Token",
        },
        400: {"description": "Parameter durasi atau geofence tidak valid"},
        403: {"description": "Dosen pada header X-Dosen-Id bukan pengampu jadwal ini"},
        404: {"description": "Jadwal kuliah tidak ditemukan"},
    },
)
def get_attendance_qr_image(
    schedule_id: int,
    valid_minutes: int = Query(default=15, ge=1, le=30),
    tanggal: date | None = Query(default=None),
    pertemuan_ke: int | None = Query(default=None, ge=1),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0),
    max_radius_meters: int | None = Query(default=None, ge=10, le=10000),
    x_dosen_id: int | None = Header(default=None, alias="X-Dosen-Id"),
    db: Session = Depends(get_db),
) -> Response:
    """Men-generate atau merotasi QR sesi kuliah dan mengembalikannya sebagai image/png."""
    res = PresensiService(db).create_or_rotate_qr(
        schedule_id=schedule_id,
        dosen_id=x_dosen_id,
        valid_minutes=valid_minutes,
        tanggal=tanggal,
        pertemuan_ke=pertemuan_ke,
        latitude=latitude,
        longitude=longitude,
        max_radius_meters=max_radius_meters,
    )
    return _qr_image_response(res)


@presensi_router.post(
    "/qr/{schedule_id}",
    response_model=QRGenerateOut,
    summary="Generate QR sesi presensi dalam format JSON (token + PNG base64 untuk UI)",
    responses={
        200: {"description": "Token JWT dan gambar QR base64 berhasil dibuat"},
        400: {"description": "Parameter durasi atau geofence tidak valid"},
        403: {"description": "Dosen bukan pengampu jadwal terkait"},
        404: {"description": "Jadwal kuliah tidak ditemukan"},
    },
)
def create_attendance_qr_json(
    schedule_id: int,
    data_in: QRGenerateRequest = Body(default_factory=QRGenerateRequest),
    x_dosen_id: int | None = Header(default=None, alias="X-Dosen-Id"),
    db: Session = Depends(get_db),
) -> QRGenerateOut:
    """Men-generate atau merotasi QR sesi dan mengembalikan metadata JSON + base64 PNG."""
    res = PresensiService(db).create_or_rotate_qr(
        schedule_id=schedule_id,
        dosen_id=x_dosen_id,
        valid_minutes=data_in.valid_minutes,
        tanggal=data_in.tanggal,
        pertemuan_ke=data_in.pertemuan_ke,
        latitude=data_in.latitude,
        longitude=data_in.longitude,
        max_radius_meters=data_in.max_radius_meters,
    )
    return _to_qr_out(res)


@attendance_alias_router.post(
    "/scan",
    response_model=ScanOut,
    summary="Validasi scan QR presensi mahasiswa (sesuai kontrak modul)",
    responses={
        200: {"description": "Presensi tercatat sebagai 'hadir' atau 'terlambat'"},
        400: {"description": "Hari kuliah tidak cocok, lewat batas >30 menit, atau koordinat wajib kosong"},
        401: {"description": "QR code kedaluwarsa, signature invalid, atau telah dirotasi"},
        403: {"description": "Mahasiswa tidak terdaftar di kelas ini atau di luar radius geofence"},
        404: {"description": "Mahasiswa atau jadwal tidak ditemukan"},
        409: {"description": "Duplikat: mahasiswa sudah melakukan scan pada sesi ini"},
        429: {"description": "Rate limit scan terlampaui (anti-spam)"},
    },
)
@presensi_router.post(
    "/scan",
    response_model=ScanOut,
    summary="Validasi scan QR presensi mahasiswa",
    responses={
        200: {"description": "Presensi tercatat sebagai 'hadir' atau 'terlambat'"},
        400: {"description": "Hari kuliah tidak cocok, lewat batas >30 menit, atau koordinat wajib kosong"},
        401: {"description": "QR code kedaluwarsa, signature invalid, atau telah dirotasi"},
        403: {"description": "Mahasiswa tidak terdaftar di kelas ini atau di luar radius geofence"},
        404: {"description": "Mahasiswa atau jadwal tidak ditemukan"},
        409: {"description": "Duplikat: mahasiswa sudah melakukan scan pada sesi ini"},
        429: {"description": "Rate limit scan terlampaui (anti-spam)"},
    },
)
def scan_attendance_qr(
    data_in: ScanRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ScanOut:
    """Memvalidasi QR JWT, jadwal, kepesertaan kelas, geofence, anti-duplikat, & batas waktu."""
    client_host = request.client.host if request.client else "unknown"
    client_key = f"{client_host}:{data_in.nim.strip()}"
    res = PresensiService(db).scan_qr(
        token=data_in.token,
        nim=data_in.nim,
        latitude=data_in.latitude,
        longitude=data_in.longitude,
        client_key=client_key,
    )
    return ScanOut(
        success=res.success,
        status=res.status,
        message=res.message,
        record_id=res.record_id,
        session_id=res.session_id,
        schedule_id=res.schedule_id,
        nim=res.nim,
        scanned_at=res.scanned_at,
        distance_meters=res.distance_meters,
    )


@presensi_router.get(
    "/mahasiswa/{nim}/report",
    response_model=MahasiswaPresensiReportOut,
    summary="Laporan persentase kehadiran per mata kuliah untuk satu mahasiswa",
    responses={
        200: {"description": "Rekap kehadiran mahasiswa per MK ditemukan"},
        404: {"description": "Mahasiswa ber-NIM tidak ditemukan"},
    },
)
def get_mahasiswa_attendance_report(
    nim: str,
    db: Session = Depends(get_db),
) -> MahasiswaPresensiReportOut:
    """Mengembalikan persentase kehadiran dan penanda warning <75% per mata kuliah."""
    data = PresensiService(db).get_mahasiswa_report(nim)
    return MahasiswaPresensiReportOut.model_validate(data)


@presensi_router.get(
    "/kelas/{kelas_id}/report",
    response_model=KelasPresensiReportOut,
    summary="Laporan presensi seluruh peserta kelas beserta daftar mahasiswa <75% (warning)",
    responses={
        200: {"description": "Laporan presensi kelas berhasil disusun"},
        404: {"description": "Kelas tidak ditemukan"},
    },
)
def get_kelas_attendance_report(
    kelas_id: int,
    db: Session = Depends(get_db),
) -> KelasPresensiReportOut:
    """Mengembalikan rekap kehadiran seluruh peserta kelas dan daftar berisiko <75%."""
    data = PresensiService(db).get_kelas_report(kelas_id)
    return KelasPresensiReportOut.model_validate(data)


@presensi_router.get(
    "/kelas/{kelas_id}/export.xlsx",
    summary="Ekspor laporan presensi kelas dan log scan mahasiswa ke format Excel (.xlsx)",
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            },
            "description": "File Excel (.xlsx) rekap presensi dan log kehadiran mahasiswa",
        },
        404: {"description": "Kelas tidak ditemukan"},
    },
)
def export_kelas_attendance_excel(
    kelas_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Menghasilkan workbook Excel (.xlsx) 2 sheet berisi rekap presensi dan log scan."""
    xlsx_bytes, raw_name = PresensiService(db).export_kelas_excel(kelas_id)
    safe_stem = sanitize_filename_segment(raw_name.removesuffix(".xlsx"))
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_stem}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@presensi_router.get(
    "/ai-insights",
    response_model=AIAttendanceInsightsOut,
    summary="AI Attendance Insights dari seluruh rekord kehadiran live di database",
    responses={200: {"description": "Structured JSON berisi insights, early warning, & actions"}},
)
def get_live_attendance_insights(
    db: Session = Depends(get_db),
) -> AIAttendanceInsightsOut:
    """Menganalisis seluruh catatan kehadiran DB menjadi structured JSON insights + actions."""
    data = AttendanceAIService().analyze_from_db(db)
    return AIAttendanceInsightsOut.model_validate(data)


@presensi_router.post(
    "/ai-insights/analyze",
    response_model=AIAttendanceInsightsOut,
    summary="Analisis array JSON `attendance_records` untuk deteksi pola absen & early warning",
    responses={
        200: {"description": "Structured JSON insights + recommendations berhasil dibuat"},
        400: {"description": "Struktur atau nilai field pada attendance_records tidak valid"},
        422: {"description": "Payload permintaan tidak valid"},
    },
)
def analyze_attendance_records(
    data_in: AIAnalyzeRequest,
) -> AIAttendanceInsightsOut:
    """Menerima array JSON `attendance_records` dan menghasilkan structured JSON insights + actions."""
    data = AttendanceAIService().analyze_records(data_in.attendance_records)
    return AIAttendanceInsightsOut.model_validate(data)

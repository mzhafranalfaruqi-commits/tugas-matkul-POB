"""Skema Pydantic v2 untuk Modul Presensi (QR Code), Laporan Excel, & AI Attendance Insights."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class JadwalRingkasPresensiOut(BaseModel):
    """DTO jadwal kuliah ringkas untuk memilih sesi pembuatan QR presensi."""

    id: int
    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    hari: int
    nama_hari: str
    jam_mulai: str
    jam_selesai: str
    ruangan_kode: str
    dosen_id: int
    dosen_nama: str


class QRGenerateRequest(BaseModel):
    """Payload opsional dosen saat men-generate atau merotasi QR sesi kuliah."""

    valid_minutes: int = Field(default=15, ge=1, le=30)
    tanggal: date | None = None
    pertemuan_ke: int | None = Field(default=None, ge=1)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    max_radius_meters: int | None = Field(default=None, ge=10, le=10000)


class QRGenerateOut(BaseModel):
    """DTO respons JSON generasi QR code sesi kuliah beserta base64 PNG dan JWT token."""

    session_id: int
    schedule_id: int
    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    pertemuan_ke: int
    tanggal: date
    valid_minutes: int
    generated_at: datetime
    expires_at: datetime
    jti: str
    token: str
    qr_base64: str


class ScanRequest(BaseModel):
    """Payload scan QR code presensi oleh mahasiswa."""

    token: str = Field(min_length=1)
    nim: str = Field(min_length=1, max_length=15)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)


class ScanOut(BaseModel):
    """Respons hasil validasi dan pencatatan scan presensi QR."""

    success: bool
    status: str
    message: str
    record_id: int
    session_id: int
    schedule_id: int
    nim: str
    scanned_at: datetime
    distance_meters: float | None = None


class MahasiswaMKPresensiOut(BaseModel):
    """Statistik presensi mahasiswa pada satu kelas mata kuliah."""

    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    total_sesi: int
    hadir: int
    terlambat: int
    izin: int
    alpha: int
    persentase: str
    warning: bool


class MahasiswaPresensiReportOut(BaseModel):
    """Laporan kehadiran lengkap per mahasiswa lintas mata kuliah."""

    nim: str
    nama_lengkap: str
    mata_kuliah: list[MahasiswaMKPresensiOut]


class PesertaPresensiOut(BaseModel):
    """Baris rekap presensi satu peserta di dalam laporan kelas."""

    nim: str
    nama_lengkap: str
    total_sesi: int
    hadir: int
    terlambat: int
    izin: int
    alpha: int
    persentase: str
    warning: bool


class KelasPresensiReportOut(BaseModel):
    """Laporan presensi satu kelas lengkap dengan daftar mahasiswa berisiko <75%."""

    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    total_sesi: int
    peserta: list[PesertaPresensiOut]
    mahasiswa_berisiko: list[PesertaPresensiOut]


class AttendanceRecordInput(BaseModel):
    """Satu entri rekord presensi pada input array JSON untuk AI Attendance Analyzer."""

    nim: str = Field(min_length=1)
    nama: str | None = None
    kelas: str = Field(min_length=1)
    hari: int | str
    jam_mulai: str = Field(min_length=4, max_length=8)
    status: str = Field(min_length=1)
    tanggal: date | None = None


class AIAnalyzeRequest(BaseModel):
    """Payload JSON array `attendance_records` untuk analisis pola AI."""

    attendance_records: list[dict[str, Any]] = Field(min_length=1)


class AIPerMahasiswaOut(BaseModel):
    """Rekap persentase dan status warning satu mahasiswa pada laporan AI."""

    nim: str
    nama: str | None = None
    total_sesi: int
    hadir: int
    terlambat: int
    izin: int
    alpha: int
    persentase: str
    warning: bool


class AIPolaHariJamOut(BaseModel):
    """Pola ketidakhadiran tinggi pada kelas, hari, dan jam tertentu."""

    kelas: str
    hari: int
    nama_hari: str
    jam_mulai: str
    slot_waktu: str
    total_rekord: int
    jumlah_absen: int
    absen_rate_persen: str


class AIAttendanceSummaryOut(BaseModel):
    """Ringkasan agregat jumlah rekord, mahasiswa, warning, & pola kelas."""

    total_rekord: int
    total_mahasiswa: int
    jumlah_warning: int
    jumlah_pola_kelas: int


class AIAttendanceInsightsOut(BaseModel):
    """Format output JSON terstruktur AI Attendance Insights (insights + actions)."""

    summary: AIAttendanceSummaryOut
    per_mahasiswa: list[AIPerMahasiswaOut]
    warning_mahasiswa: list[AIPerMahasiswaOut]
    pola_hari_jam: list[AIPolaHariJamOut]
    insights: list[str]
    actions: list[str]
    narasi_ai: str

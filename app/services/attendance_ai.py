"""Layanan AI Attendance Insights untuk mendeteksi pola ketidakhadiran dan early warning."""

from collections.abc import Mapping, Sequence
from datetime import date, time
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.domain.presensi import (
    HasilAnalisisPresensi,
    RekordPresensiInput,
    analisis_pola_presensi,
    normalisasi_hari,
)
from app.services.exceptions import AttendanceValidationError
from app.services.presensi_service import PresensiService


class AttendanceNarrativeClient(Protocol):
    """Port penyusun narasi eksekutif berbasis hasil analisis presensi terverifikasi."""

    def generate_narrative(self, hasil: HasilAnalisisPresensi) -> str:
        """Menghasilkan ringkasan narasi Indonesia tanpa memfabrikasi angka."""


class DeterministicAttendanceNarrativeClient:
    """Generator narasi deterministik berbasis metrik aktual hasil analisis pola presensi."""

    def generate_narrative(self, hasil: HasilAnalisisPresensi) -> str:
        bagian = [
            (
                f"Dari analisis {hasil.total_rekord} catatan kehadiran lintas "
                f"{hasil.total_mahasiswa} mahasiswa, ditemukan {len(hasil.warning_mahasiswa)} "
                f"mahasiswa berisiko tidak memenuhi syarat presensi (<75%)."
            )
        ]
        if hasil.pola_hari_jam:
            tertinggi = max(
                hasil.pola_hari_jam, key=lambda p: p.absen_rate_persen
            )
            bagian.append(
                f"Tingkat absen tertinggi muncul pada kelas {tertinggi.kelas} "
                f"hari {tertinggi.nama_hari} jam {tertinggi.jam_mulai} "
                f"sebesar {tertinggi.absen_rate_persen}%."
            )
        if hasil.actions:
            bagian.append(f"Rekomendasi prioritas: {hasil.actions[0]}.")
        return " ".join(bagian)


def _parse_jam(raw: Any) -> time:
    """Mem-parsing jam bertipe time atau string 'HH:MM' / 'HH:MM:SS'."""
    if isinstance(raw, time):
        return raw
    teks = str(raw or "").strip()
    if not teks:
        raise ValueError("Kolom 'jam_mulai' tidak boleh kosong")
    if len(teks) == 5:
        teks = f"{teks}:00"
    return time.fromisoformat(teks)


def _parse_records_json(
    records: Sequence[Mapping[str, Any]],
) -> list[RekordPresensiInput]:
    """Mengonversi array JSON rekord presensi menjadi daftar RekordPresensiInput."""
    parsed: list[RekordPresensiInput] = []
    for idx, raw in enumerate(records, start=1):
        try:
            nim = str(raw["nim"])
            kelas = str(raw["kelas"])
            hari = normalisasi_hari(raw["hari"])
            jam_mulai = _parse_jam(raw.get("jam_mulai") or raw.get("jam"))
            status = str(raw["status"])
            nama = raw.get("nama")
            tgl_raw = raw.get("tanggal")
            tgl = (
                tgl_raw
                if isinstance(tgl_raw, date)
                else (date.fromisoformat(str(tgl_raw)) if tgl_raw else None)
            )
        except KeyError as exc:
            raise AttendanceValidationError(
                f"Rekord ke-{idx}: field wajib {exc} tidak ditemukan"
            ) from exc
        except ValueError as exc:
            raise AttendanceValidationError(
                f"Rekord ke-{idx}: {exc}"
            ) from exc

        parsed.append(
            RekordPresensiInput(
                nim=nim,
                nama=str(nama) if nama is not None else None,
                kelas=kelas,
                hari=hari,
                jam_mulai=jam_mulai,
                status=status,
                tanggal=tgl,
            )
        )
    return parsed


class AttendanceAIService:
    """Orkestrator analisis pola kehadiran (JSON input maupun database live)."""

    def __init__(
        self, narrative_client: AttendanceNarrativeClient | None = None
    ) -> None:
        self.narrative_client = (
            narrative_client or DeterministicAttendanceNarrativeClient()
        )

    def _to_json_dict(self, hasil: HasilAnalisisPresensi) -> dict[str, Any]:
        """Menserialisasi HasilAnalisisPresensi menjadi structured JSON (insights + actions)."""
        narasi = self.narrative_client.generate_narrative(hasil)
        return {
            "summary": {
                "total_rekord": hasil.total_rekord,
                "total_mahasiswa": hasil.total_mahasiswa,
                "jumlah_warning": len(hasil.warning_mahasiswa),
                "jumlah_pola_kelas": len(hasil.pola_hari_jam),
            },
            "per_mahasiswa": [
                {
                    "nim": m.nim,
                    "nama": m.nama,
                    "total_sesi": m.total_sesi,
                    "hadir": m.hadir,
                    "terlambat": m.terlambat,
                    "izin": m.izin,
                    "alpha": m.alpha,
                    "persentase": f"{m.persentase:.2f}",
                    "warning": m.warning,
                }
                for m in hasil.per_mahasiswa
            ],
            "warning_mahasiswa": [
                {
                    "nim": m.nim,
                    "nama": m.nama,
                    "total_sesi": m.total_sesi,
                    "hadir": m.hadir,
                    "terlambat": m.terlambat,
                    "izin": m.izin,
                    "alpha": m.alpha,
                    "persentase": f"{m.persentase:.2f}",
                    "warning": m.warning,
                }
                for m in hasil.warning_mahasiswa
            ],
            "pola_hari_jam": [
                {
                    "kelas": p.kelas,
                    "hari": p.hari,
                    "nama_hari": p.nama_hari,
                    "jam_mulai": p.jam_mulai,
                    "slot_waktu": p.slot_waktu,
                    "total_rekord": p.total_rekord,
                    "jumlah_absen": p.jumlah_absen,
                    "absen_rate_persen": f"{p.absen_rate_persen:.2f}",
                }
                for p in hasil.pola_hari_jam
            ],
            "insights": list(hasil.insights),
            "actions": list(hasil.actions),
            "narasi_ai": narasi,
        }

    def analyze_records(
        self, records: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        """Menganalisis JSON array `attendance_records` menjadi structured JSON insights + actions."""
        parsed = _parse_records_json(records)
        try:
            hasil = analisis_pola_presensi(parsed)
        except ValueError as exc:
            raise AttendanceValidationError(str(exc)) from exc
        return self._to_json_dict(hasil)

    def analyze_from_db(self, db: Session) -> dict[str, Any]:
        """Mengambil data presensi aktual dari database lalu menghasilkan insights + actions."""
        rekords = PresensiService(db).build_live_attendance_records()
        hasil = analisis_pola_presensi(rekords)
        return self._to_json_dict(hasil)

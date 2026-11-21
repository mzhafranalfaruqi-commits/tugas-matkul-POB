"""Service GradeService untuk input/edit nilai, PresensiPort (DIP), & audit grade_history."""

from decimal import Decimal
from typing import Any, Protocol

from fastapi import Depends
from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.jadwal import Jadwal, Kelas
from app.models.krs import KRS, KRSDetail, SkalaNilai
from app.models.nilai import GradeHistory
from app.models.pmb import CalonMahasiswa
from app.services.exceptions import (
    GradeForbiddenError,
    GradeNotFoundError,
    GradeValidationError,
)
from app.services.gpa_calculator import GPACalculator, NilaiRepo

MIN_PRESENSI = Decimal("75")


class PresensiPort(Protocol):
    """Port Dependency Inversion untuk membaca persentase kehadiran mahasiswa di kelas."""

    def persentase(self, nim: str, kelas_id: int) -> Decimal:
        """Mengembalikan persentase presensi (0..100) untuk `nim` di `kelas_id`."""


class PresensiStub:
    """Implementasi sementara PresensiPort berbasis kamus statis (sebelum Minggu 12)."""

    def __init__(
        self,
        data: dict[tuple[str, int], Decimal] | None = None,
        default: Decimal = Decimal("100"),
    ) -> None:
        self.data = dict(data) if data is not None else {}
        self.default = default

    def persentase(self, nim: str, kelas_id: int) -> Decimal:
        return self.data.get((nim, kelas_id), self.default)


class DemoPresensiStub:
    """Stub demo terhubung ke kode MK agar form web dapat memperagakan baris < 75%."""

    def __init__(self, db: Session, default: Decimal = Decimal("100")) -> None:
        self.db = db
        self.default = default

    def persentase(self, nim: str, kelas_id: int) -> Decimal:
        kelas = self.db.get(Kelas, kelas_id)
        if nim == "2025001-0001" and kelas is not None and kelas.kode_mk == "IF204":
            return Decimal("70")
        if nim == "2025001-0002":
            return Decimal("92")
        if nim == "2025001-0003":
            return Decimal("81")
        return self.default


def get_presensi_port(db: Session = Depends(get_db)) -> PresensiPort:
    """Dependency FastAPI penyedia PresensiPort nyata berbasis DBPresensiAdapter (Minggu 12)."""
    from app.services.presensi_service import DBPresensiAdapter

    return DBPresensiAdapter(db)


def is_pengampu(db: Session, dosen_id: int, kelas_id: int) -> bool:
    """Memastikan dosen pengampu terikat sah ke kelas melalui tabel jadwal (Minggu 7)."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    Jadwal.kelas_id == kelas_id,
                    Jadwal.dosen_id == dosen_id,
                )
            )
        )
    )


class GradeService:
    """Mengelola input & edit nilai dengan 2 penjaga, lock baris, dan audit trail atomik."""

    def __init__(self, db: Session, presensi: PresensiPort) -> None:
        self.db = db
        self.presensi = presensi

    def _mulai_transaksi_terkunci(self) -> bool:
        """Membuka BEGIN IMMEDIATE pada SQLite agar perubahan nilai & history atomik."""
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "sqlite" and not self.db.in_transaction():
            self.db.execute(text("BEGIN IMMEDIATE"))
            return True
        return False

    def _detail_terkunci(self, kelas_id: int, nim: str) -> KRSDetail:
        """Mengambil baris KRSDetail mahasiswa di kelas tertentu dengan lock FOR UPDATE."""
        detail = self.db.execute(
            select(KRSDetail)
            .join(KRS, KRS.id == KRSDetail.krs_id)
            .where(KRSDetail.kelas_id == kelas_id, KRS.nim == nim)
            .with_for_update()
        ).scalar_one_or_none()
        if detail is None:
            raise GradeNotFoundError(
                f"Mahasiswa {nim} tidak terdaftar pada kelas {kelas_id}"
            )
        return detail

    def _pastikan_mahasiswa_ada(self, nim: str) -> CalonMahasiswa:
        mhs = self.db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mhs is None:
            raise GradeNotFoundError(f"Mahasiswa ber-NIM {nim} tidak ditemukan")
        return mhs

    def input_nilai(
        self,
        dosen_id: int,
        kelas_id: int,
        nim: str,
        huruf: str,
        alasan: str | None = None,
    ) -> KRSDetail:
        """Menyimpan atau memperbarui nilai huruf sekaligus mencatat GradeHistory atomik."""
        started_immediate = False
        try:
            started_immediate = self._mulai_transaksi_terkunci()

            # Penjaga 1: cek pengampu sebelum menyentuh data mahasiswa (403 Forbidden).
            if not is_pengampu(self.db, dosen_id, kelas_id):
                raise GradeForbiddenError("Anda bukan dosen pengampu kelas ini")

            detail = self._detail_terkunci(kelas_id, nim)

            # Penjaga 2: cek persentase kehadiran via PresensiPort (tepat 75% boleh).
            if self.presensi.persentase(nim, kelas_id) < MIN_PRESENSI:
                raise GradeValidationError(
                    "Nilai tidak dapat diinput: presensi mahasiswa di bawah 75%"
                )

            if self.db.get(SkalaNilai, huruf) is None:
                raise GradeValidationError(
                    f"Nilai huruf '{huruf}' tidak terdaftar pada skala_nilai"
                )

            # Idempoten: huruf sama dengan nilai tersimpan -> tanpa duplikasi riwayat audit.
            if detail.nilai == huruf:
                self.db.rollback()
                return detail

            alasan_bersih = (alasan or "").strip()[:500] or None
            if detail.nilai is not None and alasan_bersih is None:
                raise GradeValidationError(
                    "Perubahan nilai yang sudah terisi wajib disertai alasan"
                )

            old_val = detail.nilai
            detail.nilai = huruf
            self.db.add(
                GradeHistory(
                    grade_id=detail.id,
                    old_value=old_val,
                    new_value=huruf,
                    changed_by=dosen_id,
                    reason=alasan_bersih,
                )
            )
            self.db.commit()
            self.db.refresh(detail)
            return detail
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

    def daftar_peserta(self, dosen_id: int, kelas_id: int) -> list[dict[str, Any]]:
        """Mengembalikan daftar mahasiswa peserta kelas beserta presensi, nilai, & IPK terkini."""
        if self.db.get(Kelas, kelas_id) is None:
            raise GradeNotFoundError(f"Kelas {kelas_id} tidak ditemukan")

        if not is_pengampu(self.db, dosen_id, kelas_id):
            raise GradeForbiddenError("Anda bukan dosen pengampu kelas ini")

        details = self.db.scalars(
            select(KRSDetail)
            .options(joinedload(KRSDetail.krs))
            .join(KRS, KRS.id == KRSDetail.krs_id)
            .where(KRSDetail.kelas_id == kelas_id)
            .order_by(KRS.nim)
        ).all()

        nims = [d.krs.nim for d in details]
        nama_map: dict[str, str] = {}
        if nims:
            rows = self.db.execute(
                select(CalonMahasiswa.nim, CalonMahasiswa.nama_lengkap).where(
                    CalonMahasiswa.nim.in_(nims)
                )
            ).all()
            nama_map = {str(r[0]): str(r[1]) for r in rows if r[0] is not None}

        calc = GPACalculator(NilaiRepo(self.db))
        hasil: list[dict[str, Any]] = []
        for d in details:
            nim_mhs = d.krs.nim
            persen = self.presensi.persentase(nim_mhs, kelas_id)
            hasil.append(
                {
                    "grade_id": d.id,
                    "nim": nim_mhs,
                    "nama": nama_map.get(nim_mhs, nim_mhs),
                    "semester": d.krs.semester,
                    "kode_mk": d.kode_mk,
                    "presensi": str(persen),
                    "boleh_input": bool(persen >= MIN_PRESENSI),
                    "nilai": d.nilai,
                    "ipk": str(calc.calculate_ipk(nim_mhs)),
                }
            )
        return hasil

    def riwayat_nilai_mahasiswa(self, nim: str) -> list[dict[str, Any]]:
        """Membaca audit trail perubahan nilai mahasiswa melalui SQL view v_riwayat_nilai."""
        self._pastikan_mahasiswa_ada(nim)
        rows = self.db.execute(
            text(
                """
                SELECT id, grade_id, nim, semester, kode_mk, old_value, new_value,
                       pengubah, changed_at, reason
                FROM v_riwayat_nilai
                WHERE nim = :nim
                ORDER BY changed_at DESC, id DESC
                """
            ),
            {"nim": nim},
        ).mappings()
        return [dict(r) for r in rows]

"""Repository tipis NilaiRepo dan orchestrator GPACalculator (compute-on-read)."""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.gpa import DUA_DESIMAL, NilaiRecord, Skala, hitung_ipk, hitung_ips
from app.models.krs import KRS, KRSDetail, MataKuliah, SkalaNilai

_IPK_SQL = text(
    """
    WITH terbaik AS (
        SELECT
            d.kode_mk AS kode_mk,
            m.sks AS sks,
            s.bobot AS bobot,
            s.lulus AS lulus,
            ROW_NUMBER() OVER (
                PARTITION BY d.kode_mk
                ORDER BY s.bobot DESC, d.id ASC
            ) AS rn
        FROM krs_detail d
        JOIN krs k ON k.id = d.krs_id
        JOIN matakuliah m ON m.kode_mk = d.kode_mk
        JOIN skala_nilai s ON s.huruf = d.nilai
        WHERE k.nim = :nim
          AND d.nilai IS NOT NULL
    )
    SELECT
        COALESCE(SUM(bobot * sks), 0) AS total_mutu,
        COALESCE(SUM(sks), 0) AS total_sks
    FROM terbaik
    WHERE rn = 1 AND lulus = 1
    """
)


class NilaiRepo:
    """Repository pembaca rekord nilai dan skala nilai dari database SQL."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def records(self, nim: str) -> list[NilaiRecord]:
        """Mengambil seluruh baris nilai yang sudah terisi milik mahasiswa `nim` dalam 1 query."""
        rows = self.db.execute(
            select(KRSDetail.kode_mk, KRS.semester, MataKuliah.sks, KRSDetail.nilai)
            .join(KRS, KRS.id == KRSDetail.krs_id)
            .join(MataKuliah, MataKuliah.kode_mk == KRSDetail.kode_mk)
            .where(KRS.nim == nim, KRSDetail.nilai.is_not(None))
        ).all()
        return [
            NilaiRecord(
                kode_mk=kode_mk,
                semester=semester,
                sks=sks,
                huruf=huruf,
            )
            for kode_mk, semester, sks, huruf in rows
            if huruf is not None
        ]

    def skala(self) -> dict[str, Skala]:
        """Membaca kamus SkalaNilai (huruf -> Skala(bobot Decimal, lulus bool))."""
        return {
            s.huruf: Skala(bobot=Decimal(str(s.bobot)), lulus=bool(s.lulus))
            for s in self.db.scalars(select(SkalaNilai))
        }

    def calculate_ipk_sql(self, nim: str) -> Decimal:
        """Menghitung IPK menggunakan CTE Window Function SQL (pembanding differential test)."""
        row = self.db.execute(_IPK_SQL, {"nim": nim}).one()
        total_sks = int(row.total_sks or 0)
        if total_sks == 0:
            return Decimal("0.00")
        total_mutu = Decimal(str(row.total_mutu or 0))
        return (total_mutu / Decimal(total_sks)).quantize(
            DUA_DESIMAL, rounding=ROUND_HALF_UP
        )


class GPACalculator:
    """Penghitung IPS dan IPK mahasiswa secara compute-on-read melalui NilaiRepo."""

    def __init__(self, repo: NilaiRepo) -> None:
        self.repo = repo

    def calculate_ips(self, nim: str, semester: str) -> Decimal:
        """Menghitung Indeks Prestasi Semester (IPS) mahasiswa pada `semester`."""
        return hitung_ips(self.repo.records(nim), semester, self.repo.skala())

    def calculate_ipk(self, nim: str) -> Decimal:
        """Menghitung Indeks Prestasi Kumulatif (IPK) mahasiswa secara compute-on-read."""
        return hitung_ipk(self.repo.records(nim), self.repo.skala())

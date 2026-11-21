"""Repository tipis NilaiRepo dan orchestrator GPACalculator (compute-on-read)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.domain.gpa import (
    DUA_DESIMAL,
    NilaiRecord,
    RekordNilaiLengkap,
    SemesterTranskrip,
    Skala,
    bangun_ringkasan_transkrip,
    hitung_ipk,
    hitung_ips,
)
from app.models.krs import KRS, KRSDetail, MataKuliah, SkalaNilai
from app.models.pmb import CalonMahasiswa
from app.services.exceptions import GradeNotFoundError

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


@dataclass(frozen=True)
class BiodataTranskrip:
    """Biodata resmi mahasiswa yang ditampilkan pada header transkrip akademik."""

    nim: str
    nama: str
    program_studi: str
    fakultas: str
    angkatan: str


@dataclass(frozen=True)
class TranskripAkademik:
    """Dokumen lengkap transkrip akademik mahasiswa (biodata, per semester, & rekap)."""

    biodata: BiodataTranskrip
    semesters: tuple[SemesterTranskrip, ...]
    total_sks_tempuh: int
    total_sks_lulus: int
    total_mutu_lulus: Decimal
    ipk: Decimal
    predikat: str
    tanggal_cetak: date


class NilaiRepo:
    """Repository pembaca rekord nilai, biodata, dan skala nilai dari database SQL."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def biodata_mahasiswa(self, nim: str) -> BiodataTranskrip | None:
        """Membaca biodata resmi mahasiswa beserta prodi & fakultasnya dari DB."""
        mhs = self.db.execute(
            select(CalonMahasiswa)
            .options(joinedload(CalonMahasiswa.program_studi))
            .where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mhs is None:
            return None

        referensi_waktu = mhs.approved_at or mhs.created_at
        if len(nim) >= 4 and nim[:4].isdigit():
            angkatan = nim[:4]
        elif referensi_waktu is not None:
            angkatan = str(referensi_waktu.year)
        else:
            angkatan = "-"

        prodi_nama = mhs.program_studi.nama if mhs.program_studi is not None else "-"
        fakultas_nama = (
            mhs.program_studi.fakultas if mhs.program_studi is not None else "-"
        )
        return BiodataTranskrip(
            nim=mhs.nim or nim,
            nama=mhs.nama_lengkap,
            program_studi=prodi_nama,
            fakultas=fakultas_nama,
            angkatan=angkatan,
        )

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

    def records_lengkap(self, nim: str) -> list[RekordNilaiLengkap]:
        """Mengambil catatan nilai lengkap dengan nama MK dan urutan deterministik untuk transkrip."""
        rows = self.db.execute(
            select(
                KRSDetail.id,
                KRSDetail.kode_mk,
                MataKuliah.nama,
                KRS.semester,
                MataKuliah.sks,
                KRSDetail.nilai,
            )
            .join(KRS, KRS.id == KRSDetail.krs_id)
            .join(MataKuliah, MataKuliah.kode_mk == KRSDetail.kode_mk)
            .where(KRS.nim == nim, KRSDetail.nilai.is_not(None))
            .order_by(KRS.semester.asc(), KRSDetail.kode_mk.asc(), KRSDetail.id.asc())
        ).all()
        return [
            RekordNilaiLengkap(
                kode_mk=kode_mk,
                nama_mk=nama_mk,
                semester=semester,
                sks=sks,
                huruf=huruf,
                record_id=detail_id,
            )
            for detail_id, kode_mk, nama_mk, semester, sks, huruf in rows
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
    """Penghitung IPS, IPK, dan transkrip akademik secara compute-on-read melalui NilaiRepo."""

    def __init__(self, repo: NilaiRepo) -> None:
        self.repo = repo

    def calculate_ips(self, nim: str, semester: str) -> Decimal:
        """Menghitung Indeks Prestasi Semester (IPS) mahasiswa pada `semester`."""
        return hitung_ips(self.repo.records(nim), semester, self.repo.skala())

    def calculate_ipk(self, nim: str) -> Decimal:
        """Menghitung Indeks Prestasi Kumulatif (IPK) mahasiswa secara compute-on-read."""
        return hitung_ipk(self.repo.records(nim), self.repo.skala())

    def get_transcript(
        self,
        nim: str,
        tanggal_cetak: date | None = None,
    ) -> TranskripAkademik:
        """Menyusun catatan akademik lengkap lintas semester beserta predikat secara compute-on-read."""
        biodata = self.repo.biodata_mahasiswa(nim)
        if biodata is None:
            raise GradeNotFoundError(f"Mahasiswa ber-NIM {nim} tidak ditemukan")

        ringkasan = bangun_ringkasan_transkrip(
            self.repo.records_lengkap(nim),
            self.repo.skala(),
        )
        return TranskripAkademik(
            biodata=biodata,
            semesters=ringkasan.semesters,
            total_sks_tempuh=ringkasan.total_sks_tempuh,
            total_sks_lulus=ringkasan.total_sks_lulus,
            total_mutu_lulus=ringkasan.total_mutu_lulus,
            ipk=ringkasan.ipk,
            predikat=ringkasan.predikat,
            tanggal_cetak=tanggal_cetak or date.today(),
        )

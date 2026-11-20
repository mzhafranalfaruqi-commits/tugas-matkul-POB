"""Rekomendasi KRS otomatis berbasis Constraint Satisfaction Problem (CSP) Backtracking."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.krs import KRSDetail, MataKuliah
from app.models.pmb import CalonMahasiswa
from app.services.exceptions import KRSTidakDitemukan, KRSValidasiGagal
from app.services.krs_queries import prasyarat_belum_lulus
from app.validators.base import KRSContext, build_chain
from app.validators.krs import MAX_SKS, bentrok, default_krs_validators


@dataclass(frozen=True)
class CourseCandidate:
    """Kandidat mata kuliah masukan beserta penanda apakah berstatus wajib atau pilihan."""

    kode_mk: str
    wajib: bool = False


@dataclass(frozen=True)
class _ResolvedCandidate:
    """Representasi internal kandidat mata kuliah yang sudah dimuat dari database."""

    mk: MataKuliah
    wajib: bool


@dataclass(frozen=True)
class RecommendationResult:
    """Hasil rekomendasi kombinasi KRS optimal beserta alasan penolakan kandidat lain."""

    nim: str
    semester: str
    total_sks: int
    max_sks: int
    selected: list[MataKuliah]
    wajib_terpilih: list[str]
    ditolak: dict[str, str]


class KRSRecommender:
    """Solver CSP Backtracking untuk menyusun paket KRS optimal tanpa melanggar aturan."""

    @staticmethod
    def _muat_kandidat(
        db: Session,
        wajib: list[str] | None,
        pilihan: list[str] | None,
    ) -> list[_ResolvedCandidate]:
        """Memuat daftar MataKuliah dari database dengan deduplikasi (wajib menang atas pilihan)."""
        if not wajib and not pilihan:
            semua_mk = db.execute(
                select(MataKuliah).order_by(MataKuliah.kode_mk)
            ).scalars().all()
            return [_ResolvedCandidate(mk=mk, wajib=False) for mk in semua_mk]

        status_wajib: dict[str, bool] = {}
        urutan: list[str] = []
        for kode in wajib or []:
            k = kode.strip()
            if k not in status_wajib:
                urutan.append(k)
            status_wajib[k] = True

        for kode in pilihan or []:
            k = kode.strip()
            if k not in status_wajib:
                status_wajib[k] = False
                urutan.append(k)

        rows = db.execute(
            select(MataKuliah).where(MataKuliah.kode_mk.in_(urutan))
        ).scalars().all()
        by_code = {mk.kode_mk: mk for mk in rows}

        hilang = [k for k in urutan if k not in by_code]
        if hilang:
            raise KRSTidakDitemukan(
                f"Mata kuliah tidak ditemukan: {', '.join(hilang)}"
            )

        return [_ResolvedCandidate(mk=by_code[k], wajib=status_wajib[k]) for k in urutan]

    @staticmethod
    def _solve_csp(
        candidates: list[_ResolvedCandidate],
        max_sks: int,
    ) -> list[_ResolvedCandidate]:
        """Mencari himpunan bagian kandidat terbaik (wajib terbanyak, lalu SKS terbanyak)."""
        ordered = sorted(
            candidates,
            key=lambda c: (not c.wajib, -c.mk.sks, c.mk.kode_mk),
        )
        n = len(ordered)
        suffix_wajib = [0] * (n + 1)
        suffix_sks = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            suffix_wajib[i] = suffix_wajib[i + 1] + (1 if ordered[i].wajib else 0)
            suffix_sks[i] = suffix_sks[i + 1] + ordered[i].mk.sks

        best_score: tuple[int, int, int] = (-1, -1, -1)
        best_choice: list[_ResolvedCandidate] = []
        chosen: list[_ResolvedCandidate] = []

        def backtrack(idx: int, cur_wajib: int, cur_sks: int) -> None:
            nonlocal best_score, best_choice

            max_possible_wajib = cur_wajib + suffix_wajib[idx]
            if max_possible_wajib < best_score[0]:
                return

            max_possible_sks = min(max_sks, cur_sks + suffix_sks[idx])
            if (
                max_possible_wajib == best_score[0]
                and max_possible_sks < best_score[1]
            ):
                return

            if idx == n:
                score = (cur_wajib, cur_sks, len(chosen))
                if score > best_score:
                    best_score = score
                    best_choice = list(chosen)
                return

            cand = ordered[idx]
            dapat_diambil = (
                cur_sks + cand.mk.sks <= max_sks
                and all(not bentrok(cand.mk, c.mk) for c in chosen)
            )
            if dapat_diambil:
                chosen.append(cand)
                backtrack(
                    idx + 1,
                    cur_wajib + (1 if cand.wajib else 0),
                    cur_sks + cand.mk.sks,
                )
                chosen.pop()

            backtrack(idx + 1, cur_wajib, cur_sks)

        backtrack(0, 0, 0)
        return best_choice

    @staticmethod
    def _verifikasi_guardrail(
        db: Session,
        nim: str,
        semester: str,
        terpilih: list[MataKuliah],
    ) -> None:
        """Memvalidasi ulang hasil solver melalui rantai validator sebagai guardrail akhir."""
        chain = build_chain(default_krs_validators())
        details_simulasi: list[KRSDetail] = []
        for mk in terpilih:
            ctx = KRSContext(
                nim=nim,
                semester=semester,
                details=details_simulasi,
                mk_baru=mk,
                db=db,
            )
            hasil = chain.validate(ctx)
            if not hasil.ok:
                raise KRSValidasiGagal(
                    f"Guardrail validator menolak rekomendasi {mk.kode_mk}: {hasil.message}"
                )
            details_simulasi.append(
                KRSDetail(krs_id=0, kode_mk=mk.kode_mk, matakuliah=mk)
            )

    def recommend(
        self,
        db: Session,
        nim: str,
        semester: str = "20251",
        wajib: list[str] | None = None,
        pilihan: list[str] | None = None,
        max_sks: int = MAX_SKS,
    ) -> RecommendationResult:
        """Menyusun rekomendasi mata kuliah optimal dengan kendala prasyarat, jadwal, dan SKS."""
        if not nim or not nim.strip():
            raise KRSTidakDitemukan("NIM mahasiswa wajib diisi")

        mahasiswa = db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mahasiswa is None:
            raise KRSTidakDitemukan(f"Mahasiswa dengan NIM {nim} tidak ditemukan")

        if max_sks < 1 or max_sks > MAX_SKS:
            raise KRSValidasiGagal(
                f"Batas SKS rekomendasi harus antara 1 sampai {MAX_SKS}"
            )

        semua_kandidat = self._muat_kandidat(db, wajib, pilihan)
        ditolak: dict[str, str] = {}
        eligible: list[_ResolvedCandidate] = []

        for cand in semua_kandidat:
            kurang = prasyarat_belum_lulus(db, nim, cand.mk.kode_mk, semester)
            if kurang:
                ditolak[cand.mk.kode_mk] = (
                    f"Prasyarat belum lulus: {', '.join(kurang)}"
                )
            elif cand.mk.sks > max_sks:
                ditolak[cand.mk.kode_mk] = (
                    f"Bobot {cand.mk.sks} SKS melebihi batas {max_sks} SKS"
                )
            else:
                eligible.append(cand)

        solusi = self._solve_csp(eligible, max_sks)
        terpilih_mk = [c.mk for c in solusi]
        terpilih_kode = {mk.kode_mk for mk in terpilih_mk}

        self._verifikasi_guardrail(db, nim, semester, terpilih_mk)

        for cand in eligible:
            if cand.mk.kode_mk in terpilih_kode:
                continue
            konflik = [
                mk.kode_mk for mk in terpilih_mk if bentrok(cand.mk, mk)
            ]
            if konflik:
                ditolak[cand.mk.kode_mk] = (
                    f"Jadwal bentrok dengan {', '.join(konflik)}"
                )
            else:
                ditolak[cand.mk.kode_mk] = (
                    f"Melebihi sisa kuota {max_sks} SKS atau kalah prioritas optimasi"
                )

        return RecommendationResult(
            nim=nim,
            semester=semester,
            total_sks=sum(mk.sks for mk in terpilih_mk),
            max_sks=max_sks,
            selected=terpilih_mk,
            wajib_terpilih=[c.mk.kode_mk for c in solusi if c.wajib],
            ditolak=ditolak,
        )

"""Service layer KRSManager sebagai pintu tunggal operasi Kartu Rencana Studi."""

import time

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
from app.models.pmb import CalonMahasiswa
from app.services.exceptions import (
    KRSStatusTidakValid,
    KRSTidakDitemukan,
    KRSValidasiGagal,
)
from app.validators.base import KRSContext, ValidationResult, Validator, build_chain
from app.validators.krs import default_krs_validators

EDITABLE = (KRSStatus.DRAFT, KRSStatus.REVISION)


class KRSManager:
    """Mengelola penambahan, penghapusan, dan validasi mata kuliah dalam KRS."""

    def __init__(
        self,
        db: Session,
        validators: list[Validator] | None = None,
        semester: str = "20251",
    ) -> None:
        self.db = db
        self.semester = semester
        self.validators = (
            list(validators) if validators is not None else default_krs_validators()
        )
        self.chain = build_chain(self.validators)

    def _mulai_transaksi_terkunci(self) -> bool:
        """Membuka BEGIN IMMEDIATE pada SQLite agar baca-validasi-tulis bersifat atomik."""
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "sqlite" and not self.db.in_transaction():
            self.db.execute(text("BEGIN IMMEDIATE"))
            return True
        return False

    def _pastikan_mahasiswa_bernim(self, nim: str) -> CalonMahasiswa:
        """Memvalidasi bahwa NIM terdaftar sebagai mahasiswa yang telah diterima."""
        if not nim or not nim.strip():
            raise KRSTidakDitemukan("NIM mahasiswa wajib diisi")

        mahasiswa = self.db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mahasiswa is None:
            raise KRSTidakDitemukan(f"Mahasiswa dengan NIM {nim} tidak ditemukan")
        return mahasiswa

    def _krs_terkunci(
        self, nim: str, buat_jika_belum_ada: bool = True
    ) -> KRS | None:
        """Mengambil baris KRS beserta detailnya dengan row-level lock (with_for_update)."""
        self._pastikan_mahasiswa_bernim(nim)

        krs = self.db.execute(
            select(KRS)
            .options(selectinload(KRS.details).joinedload(KRSDetail.matakuliah))
            .where(KRS.nim == nim, KRS.semester == self.semester)
            .with_for_update()
        ).scalar_one_or_none()

        if krs is None and buat_jika_belum_ada:
            krs = KRS(nim=nim, semester=self.semester, status=KRSStatus.DRAFT)
            self.db.add(krs)
            self.db.flush()

        return krs

    def add_course(self, nim: str, kode_mk: str) -> KRSDetail:
        """Menambahkan satu mata kuliah ke KRS setelah lolos seluruh rantai validator."""
        max_attempts = 3
        for attempt in range(max_attempts):
            started_immediate = False
            try:
                started_immediate = self._mulai_transaksi_terkunci()
                krs = self._krs_terkunci(nim, buat_jika_belum_ada=True)
                assert krs is not None

                if krs.status not in EDITABLE:
                    if started_immediate:
                        self.db.rollback()
                    raise KRSStatusTidakValid(
                        f"KRS berstatus {krs.status.value} tidak dapat diubah"
                    )

                mk = self.db.get(MataKuliah, kode_mk)
                if mk is None:
                    if started_immediate:
                        self.db.rollback()
                    raise KRSTidakDitemukan(
                        f"Mata kuliah dengan kode {kode_mk} tidak ditemukan"
                    )

                ctx = KRSContext(
                    nim=nim,
                    semester=self.semester,
                    details=list(krs.details),
                    mk_baru=mk,
                    db=self.db,
                )
                hasil = self.chain.validate(ctx)
                if not hasil.ok:
                    if started_immediate:
                        self.db.rollback()
                    raise KRSValidasiGagal(hasil.message)

                detail = KRSDetail(matakuliah=mk)
                krs.details.append(detail)
                self.db.commit()
                self.db.refresh(detail)
                _ = detail.matakuliah
                return detail
            except IntegrityError as exc:
                self.db.rollback()
                msg = str(exc).lower()
                if "krs_detail" in msg or "uq_krs_detail_krs_mk" in msg:
                    raise KRSValidasiGagal(f"Sudah ada di KRS: {kode_mk}") from exc
                if attempt == max_attempts - 1:
                    raise
                continue
            except OperationalError as exc:
                self.db.rollback()
                msg = str(exc).lower()
                is_lock_error = any(
                    token in msg for token in ("locked", "busy", "deadlock")
                )
                if is_lock_error and attempt < max_attempts - 1:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise

        raise RuntimeError("Gagal menambahkan mata kuliah ke KRS")  # pragma: no cover

    def remove_course(self, nim: str, kode_mk: str) -> None:
        """Menghapus mata kuliah dari KRS selama status masih DRAFT atau REVISION."""
        started_immediate = self._mulai_transaksi_terkunci()
        krs = self._krs_terkunci(nim, buat_jika_belum_ada=False)
        if krs is None:
            if started_immediate:
                self.db.rollback()
            raise KRSTidakDitemukan(
                f"KRS untuk NIM {nim} semester {self.semester} tidak ditemukan"
            )

        if krs.status not in EDITABLE:
            if started_immediate:
                self.db.rollback()
            raise KRSStatusTidakValid(
                f"KRS berstatus {krs.status.value} tidak dapat diubah"
            )

        detail = next((d for d in krs.details if d.kode_mk == kode_mk), None)
        if detail is None:
            if started_immediate:
                self.db.rollback()
            raise KRSTidakDitemukan(f"Mata kuliah {kode_mk} tidak ada di KRS")

        krs.details.remove(detail)
        self.db.commit()

    def validate_krs(self, nim: str) -> list[ValidationResult]:
        """Memeriksa seluruh isi KRS dan mengumpulkan semua pelanggaran sekaligus."""
        self._pastikan_mahasiswa_bernim(nim)

        krs = self.db.execute(
            select(KRS)
            .options(selectinload(KRS.details).joinedload(KRSDetail.matakuliah))
            .where(KRS.nim == nim, KRS.semester == self.semester)
        ).scalar_one_or_none()
        if krs is None or not krs.details:
            return []

        gagal: dict[str, ValidationResult] = {}
        for detail in krs.details:
            lain = [x for x in krs.details if x is not detail]
            ctx = KRSContext(
                nim=nim,
                semester=self.semester,
                details=lain,
                mk_baru=detail.matakuliah,
                db=self.db,
            )
            for validator in self.validators:
                hasil = validator.check(ctx)
                if not hasil.ok:
                    gagal.setdefault(hasil.message, hasil)

        return list(gagal.values())

    def get_krs(self, nim: str) -> KRS:
        """Mengambil ringkasan dan seluruh detail KRS aktif mahasiswa."""
        self._pastikan_mahasiswa_bernim(nim)

        krs = self.db.execute(
            select(KRS)
            .options(selectinload(KRS.details).joinedload(KRSDetail.matakuliah))
            .where(KRS.nim == nim, KRS.semester == self.semester)
        ).scalar_one_or_none()
        if krs is None:
            raise KRSTidakDitemukan(
                f"KRS untuk NIM {nim} semester {self.semester} tidak ditemukan"
            )
        return krs

    def submit_krs(self, nim: str) -> KRS:
        """Mengajukan KRS mahasiswa (state transition lengkap diimplementasikan di Minggu 6)."""
        raise NotImplementedError(
            "Transisi state submit_krs akan diimplementasikan pada Minggu 6 bersama State Machine"
        )

    def approve_krs(self, nim: str, dosen_pa_id: int) -> KRS:
        """Menyetujui KRS oleh dosen PA (state transition lengkap diimplementasikan di Minggu 6)."""
        raise NotImplementedError(
            "Transisi state approve_krs akan diimplementasikan pada Minggu 6 bersama State Machine"
        )

"""Service layer KRSManager sebagai pintu tunggal operasi Kartu Rencana Studi."""

from datetime import datetime, timedelta, timezone
import time

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.models.krs import (
    Actor,
    KRS,
    KRSDetail,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
)
from app.models.pmb import CalonMahasiswa
from app.services.exceptions import (
    ForbiddenError,
    KRSLockedError,
    KRSTidakDitemukan,
    KRSValidasiGagal,
    StaleVersionError,
)
from app.validators.base import KRSContext, ValidationResult, Validator, build_chain
from app.validators.krs import default_krs_validators

EDITABLE = (KRSStatus.DRAFT, KRSStatus.REVISION)


class KRSManager:
    """Mengelola pengisian, validasi, state machine workflow, dan approval KRS."""

    def __init__(
        self,
        db: Session,
        validators: list[Validator] | None = None,
        semester: str = "20251",
        default_dosen_pa_id: int | None = None,
    ) -> None:
        self.db = db
        self.semester = semester
        self.default_dosen_pa_id = default_dosen_pa_id
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

    def _tentukan_dosen_pa(self, nim: str) -> int | None:
        """Menentukan ID dosen PA dari parameter default atau riwayat KRS sebelumnya."""
        if self.default_dosen_pa_id is not None:
            return self.default_dosen_pa_id

        return self.db.execute(
            select(KRS.dosen_pa_id)
            .where(KRS.nim == nim, KRS.dosen_pa_id.is_not(None))
            .order_by(KRS.semester.desc(), KRS.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _sentuh_krs(self, krs: KRS) -> datetime:
        """Memajukan timestamp diubah_pada secara ketat agar optimistic version naik."""
        sekarang = datetime.now(timezone.utc)
        if krs.diubah_pada is not None:
            prev = krs.diubah_pada
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=timezone.utc)
            if sekarang <= prev:
                sekarang = prev + timedelta(microseconds=1)
        krs.diubah_pada = sekarang
        return sekarang

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
            krs = KRS(
                nim=nim,
                semester=self.semester,
                status=KRSStatus.DRAFT,
                dosen_pa_id=self._tentukan_dosen_pa(nim),
                diubah_pada=datetime.now(timezone.utc),
            )
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
                    raise KRSLockedError(
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
                # Sentuh header KRS agar SQLAlchemy menaikkan kolom version (optimistic lock).
                self._sentuh_krs(krs)
                self.db.commit()
                self.db.refresh(detail)
                _ = detail.matakuliah
                return detail
            except StaleDataError as exc:
                self.db.rollback()
                raise StaleVersionError("KRS sudah berubah, muat ulang") from exc
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
        started_immediate = False
        try:
            started_immediate = self._mulai_transaksi_terkunci()
            krs = self._krs_terkunci(nim, buat_jika_belum_ada=False)
            if krs is None:
                raise KRSTidakDitemukan(
                    f"KRS untuk NIM {nim} semester {self.semester} tidak ditemukan"
                )

            if krs.status not in EDITABLE:
                raise KRSLockedError(
                    f"KRS berstatus {krs.status.value} tidak dapat diubah"
                )

            detail = next((d for d in krs.details if d.kode_mk == kode_mk), None)
            if detail is None:
                raise KRSTidakDitemukan(f"Mata kuliah {kode_mk} tidak ada di KRS")

            krs.details.remove(detail)
            # Sentuh header KRS agar penghapusan detail juga menaikkan kolom version.
            self._sentuh_krs(krs)
            self.db.commit()
        except StaleDataError as exc:
            self.db.rollback()
            raise StaleVersionError("KRS sudah berubah, muat ulang") from exc
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

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
        """Mengajukan KRS mahasiswa setelah memastikan tidak kosong dan lolos validasi ulang."""
        started_immediate = False
        try:
            started_immediate = self._mulai_transaksi_terkunci()
            krs = self._krs_terkunci(nim, buat_jika_belum_ada=False)
            if krs is None:
                raise KRSTidakDitemukan(
                    f"KRS untuk NIM {nim} semester {self.semester} tidak ditemukan"
                )

            krs.cek_transisi(KRSStatus.SUBMITTED, Actor.MAHASISWA)

            if not krs.details:
                raise KRSValidasiGagal("KRS kosong tidak dapat diajukan")

            errors = self.validate_krs(nim)
            if errors:
                raise KRSValidasiGagal("; ".join(e.message for e in errors))

            krs.transition(KRSStatus.SUBMITTED, Actor.MAHASISWA)
            now = self._sentuh_krs(krs)
            krs.submitted_at = now
            self.db.add(
                KRSLog(
                    krs_id=krs.id,
                    aksi="SUBMIT",
                    aktor_id=nim,
                    catatan=f"Pengajuan KRS semester {self.semester}",
                )
            )
            self.db.commit()
            return self.get_krs(nim)
        except StaleDataError as exc:
            self.db.rollback()
            raise StaleVersionError("KRS sudah berubah, muat ulang") from exc
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

    def _proses_review_pa(
        self,
        nim: str,
        dosen_pa_id: int,
        target_status: KRSStatus,
        aksi: str,
        catatan_log: str,
        pesan_notif: str,
        expected_version: int | None = None,
        catatan_revisi: str | None = None,
    ) -> KRS:
        """Menjalankan approval/revisi Dosen PA secara atomik (otorisasi, version lock, log, notif)."""
        started_immediate = False
        try:
            started_immediate = self._mulai_transaksi_terkunci()
            krs = self._krs_terkunci(nim, buat_jika_belum_ada=False)
            if krs is None:
                raise KRSTidakDitemukan(
                    f"KRS untuk NIM {nim} semester {self.semester} tidak ditemukan"
                )

            if krs.dosen_pa_id != dosen_pa_id:
                raise ForbiddenError("Anda bukan dosen PA mahasiswa ini")

            if expected_version is not None and krs.version != expected_version:
                raise StaleVersionError("KRS sudah berubah, muat ulang")

            krs.transition(target_status, Actor.DOSEN_PA)
            now = self._sentuh_krs(krs)
            if target_status == KRSStatus.APPROVED:
                krs.approved_at = now
            elif target_status == KRSStatus.REVISION:
                krs.catatan_revisi = catatan_revisi

            self.db.add(
                KRSLog(
                    krs_id=krs.id,
                    aksi=aksi,
                    aktor_id=str(dosen_pa_id),
                    catatan=catatan_log,
                )
            )
            self.db.add(Notifikasi(nim=nim, pesan=pesan_notif))
            self.db.commit()
            return self.get_krs(nim)
        except StaleDataError as exc:
            self.db.rollback()
            raise StaleVersionError("KRS sudah berubah, muat ulang") from exc
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

    def approve_krs(
        self, nim: str, dosen_pa_id: int, expected_version: int | None = None
    ) -> KRS:
        """Menyetujui KRS mahasiswa oleh Dosen PA dalam satu transaksi atomik."""
        return self._proses_review_pa(
            nim=nim,
            dosen_pa_id=dosen_pa_id,
            target_status=KRSStatus.APPROVED,
            aksi="APPROVE",
            catatan_log="KRS disetujui dosen PA",
            pesan_notif=f"KRS semester {self.semester} telah disetujui oleh Dosen PA",
            expected_version=expected_version,
        )

    def revise_krs(
        self,
        nim: str,
        dosen_pa_id: int,
        catatan: str,
        expected_version: int | None = None,
    ) -> KRS:
        """Mengembalikan KRS ke status REVISION dengan catatan wajib dari Dosen PA."""
        catatan_bersih = catatan.strip()
        if not catatan_bersih:
            raise KRSValidasiGagal("Catatan revisi wajib diisi")

        return self._proses_review_pa(
            nim=nim,
            dosen_pa_id=dosen_pa_id,
            target_status=KRSStatus.REVISION,
            aksi="REVISE",
            catatan_log=catatan_bersih,
            pesan_notif=f"KRS semester {self.semester} perlu revisi: {catatan_bersih}",
            expected_version=expected_version,
            catatan_revisi=catatan_bersih,
        )

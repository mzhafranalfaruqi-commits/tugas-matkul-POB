"""Service layer OOP yang merangkum seluruh aturan bisnis Modul PMB."""

from datetime import datetime, timezone
import time

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload

from app.models.pmb import CalonMahasiswa, JalurMasuk, ProgramStudi, StatusPMB
from app.schemas.pmb import JalurStat, ProdiStat, RegisterRequest, StatsOut
from app.services.exceptions import (
    DataNIMTidakValid,
    EmailSudahTerdaftar,
    PendaftarTidakDitemukan,
    ReferensiTidakValid,
    StatusTidakValid,
)
from app.services.nim_generator import generate_nim


class PMBService:
    """Kumpulan operasi bisnis Modul Penerimaan Mahasiswa Baru (register, status, approve, reject, stats)."""

    @staticmethod
    def register(db: Session, data: RegisterRequest) -> CalonMahasiswa:
        """Mendaftarkan calon mahasiswa baru dengan status awal pending."""
        existing = db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.email == data.email)
        ).scalar_one_or_none()
        if existing is not None:
            raise EmailSudahTerdaftar(f"Email {data.email} sudah terdaftar")

        if db.get(ProgramStudi, data.program_studi_id) is None:
            raise ReferensiTidakValid(
                f"Program studi dengan id {data.program_studi_id} tidak ditemukan"
            )

        if db.get(JalurMasuk, data.jalur_masuk_id) is None:
            raise ReferensiTidakValid(
                f"Jalur masuk dengan id {data.jalur_masuk_id} tidak ditemukan"
            )

        calon = CalonMahasiswa(**data.model_dump())
        db.add(calon)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise EmailSudahTerdaftar(f"Email {data.email} sudah terdaftar") from exc

        db.refresh(calon)
        return calon

    @staticmethod
    def get_status(db: Session, pendaftar_id: int) -> CalonMahasiswa:
        """Mengambil data pendaftar beserta relasi program studi dan jalur masuk."""
        calon = db.execute(
            select(CalonMahasiswa)
            .options(
                joinedload(CalonMahasiswa.program_studi),
                joinedload(CalonMahasiswa.jalur_masuk),
            )
            .where(CalonMahasiswa.id == pendaftar_id)
        ).scalar_one_or_none()

        if calon is None:
            raise PendaftarTidakDitemukan(
                f"Calon mahasiswa dengan id {pendaftar_id} tidak ditemukan"
            )
        return calon

    @staticmethod
    def approve(
        db: Session, pendaftar_id: int, tahun: int | None = None
    ) -> tuple[CalonMahasiswa, bool]:
        """Menyetujui pendaftar dan meng-generate NIM secara idempotent dan aman terhadap race condition.

        Mengembalikan tuple (CalonMahasiswa, already_approved).
        """
        max_attempts = 3
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        for attempt in range(max_attempts):
            started_immediate = False
            try:
                if dialect_name == "sqlite" and not db.in_transaction():
                    # SQLite tidak mendukung FOR UPDATE; BEGIN IMMEDIATE mengantrekan
                    # transaksi tulis di level database agar counter tidak dibaca ganda.
                    db.execute(text("BEGIN IMMEDIATE"))
                    started_immediate = True

                calon = db.get(CalonMahasiswa, pendaftar_id, with_for_update=True)
                if calon is None:
                    if started_immediate:
                        db.rollback()
                    raise PendaftarTidakDitemukan(
                        f"Calon mahasiswa dengan id {pendaftar_id} tidak ditemukan"
                    )

                if calon.status == StatusPMB.approved and calon.nim is not None:
                    if started_immediate:
                        db.rollback()
                        db.refresh(calon)
                    return calon, True

                if calon.status != StatusPMB.pending:
                    if started_immediate:
                        db.rollback()
                    raise StatusTidakValid("Status bukan pending")

                prodi = db.get(ProgramStudi, calon.program_studi_id)
                if prodi is None:
                    if started_immediate:
                        db.rollback()
                    raise DataNIMTidakValid(
                        f"Program studi dengan id {calon.program_studi_id} tidak ditemukan"
                    )

                kode_prodi = (prodi.kode or "").strip()
                if len(kode_prodi) != 3 or not kode_prodi.isdigit():
                    if started_immediate:
                        db.rollback()
                    raise DataNIMTidakValid(
                        f"Kode program studi '{prodi.kode}' harus tepat 3 digit angka"
                    )

                now_utc = datetime.now(timezone.utc)
                target_tahun = tahun if tahun is not None else now_utc.year
                calon.nim = generate_nim(target_tahun, kode_prodi, db)
                calon.status = StatusPMB.approved
                calon.approved_at = now_utc

                db.commit()
                db.refresh(calon)
                return calon, False
            except IntegrityError:
                db.rollback()
                if attempt == max_attempts - 1:
                    raise
                continue
            except OperationalError as exc:
                db.rollback()
                msg = str(exc).lower()
                is_lock_error = any(
                    token in msg for token in ("locked", "busy", "deadlock")
                )
                if is_lock_error and attempt < max_attempts - 1:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise

        raise RuntimeError("Gagal memproses approval pendaftar")  # pragma: no cover

    @staticmethod
    def reject(db: Session, pendaftar_id: int) -> CalonMahasiswa:
        """Menolak pendaftaran calon mahasiswa (idempotent jika sudah rejected)."""
        calon = db.get(CalonMahasiswa, pendaftar_id)
        if calon is None:
            raise PendaftarTidakDitemukan(
                f"Calon mahasiswa dengan id {pendaftar_id} tidak ditemukan"
            )

        if calon.status == StatusPMB.approved:
            raise StatusTidakValid("Pendaftar yang sudah approved tidak dapat di-reject")

        if calon.status == StatusPMB.rejected:
            return calon

        calon.status = StatusPMB.rejected
        db.commit()
        db.refresh(calon)
        return calon

    @staticmethod
    def get_stats(db: Session) -> StatsOut:
        """Menghitung statistik dashboard jumlah pendaftar per status, prodi, dan jalur."""
        status_counts = {status.value: 0 for status in StatusPMB}
        rows_status = db.execute(
            select(CalonMahasiswa.status, func.count(CalonMahasiswa.id)).group_by(
                CalonMahasiswa.status
            )
        ).all()
        for status_val, cnt in rows_status:
            key = status_val.value if isinstance(status_val, StatusPMB) else str(status_val)
            status_counts[key] = cnt

        total_pendaftar = sum(status_counts.values())

        prodi_rows = db.execute(select(ProgramStudi).order_by(ProgramStudi.kode)).scalars().all()
        prodi_status_rows = db.execute(
            select(
                CalonMahasiswa.program_studi_id,
                CalonMahasiswa.status,
                func.count(CalonMahasiswa.id),
            ).group_by(CalonMahasiswa.program_studi_id, CalonMahasiswa.status)
        ).all()
        prodi_map: dict[int, dict[str, int]] = {
            p.id: {"pending": 0, "approved": 0, "rejected": 0} for p in prodi_rows
        }
        for prodi_id, status_val, cnt in prodi_status_rows:
            if prodi_id in prodi_map:
                key = status_val.value if isinstance(status_val, StatusPMB) else str(status_val)
                prodi_map[prodi_id][key] = cnt

        per_program_studi = [
            ProdiStat(
                kode=p.kode,
                nama=p.nama,
                total=sum(prodi_map[p.id].values()),
                pending=prodi_map[p.id]["pending"],
                approved=prodi_map[p.id]["approved"],
                rejected=prodi_map[p.id]["rejected"],
            )
            for p in prodi_rows
        ]

        jalur_rows = db.execute(select(JalurMasuk).order_by(JalurMasuk.id)).scalars().all()
        jalur_counts_rows = db.execute(
            select(CalonMahasiswa.jalur_masuk_id, func.count(CalonMahasiswa.id)).group_by(
                CalonMahasiswa.jalur_masuk_id
            )
        ).all()
        jalur_map = {jalur_id: cnt for jalur_id, cnt in jalur_counts_rows}
        per_jalur_masuk = [
            JalurStat(nama=j.nama, total=jalur_map.get(j.id, 0)) for j in jalur_rows
        ]

        return StatsOut(
            total_pendaftar=total_pendaftar,
            per_status=status_counts,
            per_program_studi=per_program_studi,
            per_jalur_masuk=per_jalur_masuk,
        )


# Alias level modul untuk menjaga kompatibilitas pemanggilan langsung.
register = PMBService.register
get_status = PMBService.get_status
approve = PMBService.approve
reject = PMBService.reject
get_stats = PMBService.get_stats

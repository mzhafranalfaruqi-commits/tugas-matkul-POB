"""Service layer Modul Presensi (QR Code): JWT 15 menit, rotasi jti, geofence, rate limit, & Excel export."""

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import io
import logging
import os
import threading
import time as time_mod
from typing import Any
from uuid import uuid4

import jwt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
import qrcode
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.presensi import (
    BATAS_TERLAMBAT_MENIT,
    MIN_PRESENSI_PERSEN,
    NAMA_HARI,
    RekordPresensiInput,
    hitung_jarak_haversine_meter,
    hitung_persentase_kehadiran,
    tentukan_status_kehadiran,
)
from app.models.jadwal import Jadwal, Kelas
from app.models.krs import KRS, KRSDetail
from app.models.pmb import CalonMahasiswa
from app.models.presensi import (
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
)
from app.services.exceptions import (
    AttendanceDuplicateError,
    AttendanceExpiredError,
    AttendanceForbiddenError,
    AttendanceNotFoundError,
    AttendanceRateLimitError,
    AttendanceValidationError,
)

logger = logging.getLogger("sevima.presensi")

WIB = timezone(timedelta(hours=7))
DEFAULT_QR_SECRET = "sevima-qr-attendance-secret-dev-2026"


def get_qr_secret() -> str:
    """Membaca secret penandatangan JWT QR presensi dari environment variable."""
    return os.getenv("ATTENDANCE_JWT_SECRET", DEFAULT_QR_SECRET)


def _ensure_utc(dt: datetime | None) -> datetime:
    """Menormalisasi datetime menjadi UTC aware (menganggap naive sebagai WIB kampus)."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=WIB).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def generate_attendance_qr(
    schedule_id: int,
    valid_minutes: int = 15,
    *,
    session_id: int | None = None,
    jti: str | None = None,
    issued_at: datetime | None = None,
    secret: str | None = None,
) -> tuple[bytes, str, str, datetime, datetime]:
    """Menghasilkan gambar PNG QR code dan token JWT HS256 berumur `valid_minutes`."""
    if valid_minutes < 1 or valid_minutes > BATAS_TERLAMBAT_MENIT:
        raise AttendanceValidationError(
            f"Masa berlaku QR harus antara 1 sampai {BATAS_TERLAMBAT_MENIT} menit"
        )

    iat = _ensure_utc(issued_at)
    exp = iat + timedelta(minutes=valid_minutes)
    token_jti = (jti or uuid4().hex).strip()
    kunci = secret if secret is not None else get_qr_secret()

    payload: dict[str, Any] = {
        "schedule_id": int(schedule_id),
        "jti": token_jti,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if session_id is not None:
        payload["session_id"] = int(session_id)

    encoded = jwt.encode(payload, kunci, algorithm="HS256")
    token = encoded if isinstance(encoded, str) else encoded.decode("utf-8")

    qr_img = qrcode.make(token)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    return buf.getvalue(), token, token_jti, iat, exp


def decode_attendance_token(
    token: str,
    secret: str | None = None,
    *,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    """Memverifikasi signature HS256 dan masa kedaluwarsa JWT QR presensi."""
    if not token or not token.strip():
        raise AttendanceExpiredError("Token QR presensi wajib disertakan")

    kunci = secret if secret is not None else get_qr_secret()
    ref_now = _ensure_utc(current_time)

    try:
        payload = jwt.decode(
            token.strip(),
            kunci,
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_iat": False},
        )
    except jwt.InvalidTokenError as exc:
        raise AttendanceExpiredError(
            "Token QR presensi tidak valid atau rusak"
        ) from exc

    if (
        "schedule_id" not in payload
        or "jti" not in payload
        or "iat" not in payload
        or "exp" not in payload
    ):
        raise AttendanceExpiredError("Payload token QR presensi tidak lengkap")

    if float(payload["iat"]) > ref_now.timestamp() + 5:
        raise AttendanceExpiredError("Token QR presensi belum berlaku")

    if ref_now.timestamp() >= float(payload["exp"]):
        raise AttendanceExpiredError(
            "QR code presensi sudah kedaluwarsa; minta dosen generate QR baru"
        )

    return payload


class SlidingWindowRateLimiter:
    """Rate limiter sliding-window di memori untuk mencegah spam scan QR berulang."""

    def __init__(
        self,
        max_requests: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock or time_mod.monotonic
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Memeriksa kuota request untuk `key` dan melempar 429 bila terlampaui."""
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            dq = self._buckets[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max_requests:
                raise AttendanceRateLimitError(
                    f"Terlalu banyak percobaan scan presensi; coba lagi dalam {int(self.window_seconds)} detik"
                )
            dq.append(now)

    def reset(self) -> None:
        """Mengosongkan seluruh bucket rate limiter (berguna untuk isolasi tes)."""
        with self._lock:
            self._buckets.clear()


_default_scan_rate_limiter = SlidingWindowRateLimiter(
    max_requests=5, window_seconds=60.0
)


def get_scan_rate_limiter() -> SlidingWindowRateLimiter:
    """Mengembalikan singleton rate limiter untuk endpoint scan QR."""
    return _default_scan_rate_limiter


class DBPresensiAdapter:
    """Adaptor nyata PresensiPort yang menghitung kehadiran dari tabel attendance_session/record."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def persentase(self, nim: str, kelas_id: int) -> Decimal:
        """Mengembalikan persentase hadir+terlambat mahasiswa di kelas (fallback ke stub bila belum ada sesi)."""
        total_sesi = int(
            self.db.scalar(
                select(func.count(AttendanceSession.id))
                .join(Jadwal, Jadwal.id == AttendanceSession.jadwal_id)
                .where(Jadwal.kelas_id == kelas_id)
            )
            or 0
        )
        if total_sesi == 0:
            from app.services.grade_service import DemoPresensiStub

            return DemoPresensiStub(self.db).persentase(nim, kelas_id)

        hadir_cnt = int(
            self.db.scalar(
                select(func.count(AttendanceRecord.id))
                .join(
                    AttendanceSession,
                    AttendanceSession.id == AttendanceRecord.session_id,
                )
                .join(Jadwal, Jadwal.id == AttendanceSession.jadwal_id)
                .where(
                    Jadwal.kelas_id == kelas_id,
                    AttendanceRecord.nim == nim,
                    AttendanceRecord.status.in_(
                        (AttendanceStatus.hadir, AttendanceStatus.terlambat)
                    ),
                )
            )
            or 0
        )
        return hitung_persentase_kehadiran(hadir_cnt, total_sesi)


@dataclass(frozen=True)
class QRSessionResult:
    """Hasil pembuatan atau rotasi token QR sesi pertemuan kuliah."""

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
    qr_png: bytes


@dataclass(frozen=True)
class ScanResult:
    """Hasil verifikasi dan pencatatan scan presensi QR oleh mahasiswa."""

    success: bool
    status: str
    message: str
    record_id: int
    session_id: int
    schedule_id: int
    nim: str
    scanned_at: datetime
    distance_meters: float | None


class PresensiService:
    """Mengelola generasi QR ber-JWT, validasi scan presensi, geofence, report, dan Excel export."""

    def __init__(
        self,
        db: Session,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        secret: str | None = None,
    ) -> None:
        self.db = db
        self.rate_limiter = rate_limiter or get_scan_rate_limiter()
        self.secret = secret

    def _mulai_transaksi_terkunci(self) -> bool:
        """Membuka BEGIN IMMEDIATE pada SQLite sebelum SELECT agar operasi tulis atomik."""
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "sqlite" and not self.db.in_transaction():
            self.db.execute(text("BEGIN IMMEDIATE"))
            return True
        return False

    def create_or_rotate_qr(
        self,
        schedule_id: int,
        *,
        dosen_id: int | None = None,
        valid_minutes: int = 15,
        tanggal: date | None = None,
        pertemuan_ke: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        max_radius_meters: int | None = None,
        now: datetime | None = None,
    ) -> QRSessionResult:
        """Membuat sesi presensi hari ini atau merotasi token QR untuk mencegah replay attack."""
        if valid_minutes < 1 or valid_minutes > BATAS_TERLAMBAT_MENIT:
            raise AttendanceValidationError(
                f"Masa berlaku QR harus antara 1 sampai {BATAS_TERLAMBAT_MENIT} menit"
            )
        if (latitude is None) != (longitude is None):
            raise AttendanceValidationError(
                "Koordinat latitude dan longitude geofence harus diisi berpasangan"
            )
        if max_radius_meters is not None and (latitude is None or longitude is None):
            raise AttendanceValidationError(
                "Koordinat latitude dan longitude wajib diisi bila radius geofence diaktifkan"
            )
        if max_radius_meters is not None and max_radius_meters < 10:
            raise AttendanceValidationError(
                "Radius geofence minimal 10 meter"
            )

        ref_utc = _ensure_utc(now)
        tgl_sesi = tanggal or ref_utc.astimezone(WIB).date()
        started_immediate = False

        try:
            started_immediate = self._mulai_transaksi_terkunci()

            jadwal = self.db.execute(
                select(Jadwal)
                .options(
                    joinedload(Jadwal.kelas).joinedload(Kelas.matakuliah),
                    joinedload(Jadwal.dosen),
                    joinedload(Jadwal.ruangan),
                )
                .where(Jadwal.id == schedule_id)
            ).scalar_one_or_none()
            if jadwal is None:
                raise AttendanceNotFoundError(
                    f"Jadwal kuliah dengan ID {schedule_id} tidak ditemukan"
                )

            if dosen_id is not None and jadwal.dosen_id != dosen_id:
                raise AttendanceForbiddenError(
                    "Anda bukan dosen pengampu untuk jadwal kuliah ini"
                )

            session = self.db.execute(
                select(AttendanceSession)
                .where(
                    AttendanceSession.jadwal_id == schedule_id,
                    AttendanceSession.tanggal == tgl_sesi,
                )
                .with_for_update()
            ).scalar_one_or_none()

            if session is None:
                if pertemuan_ke is None:
                    max_pertemuan = (
                        self.db.scalar(
                            select(func.max(AttendanceSession.pertemuan_ke)).where(
                                AttendanceSession.jadwal_id == schedule_id
                            )
                        )
                        or 0
                    )
                    pertemuan_no = int(max_pertemuan) + 1
                else:
                    pertemuan_no = int(pertemuan_ke)
                if pertemuan_no < 1:
                    raise AttendanceValidationError("Nomor pertemuan minimal 1")

                session = AttendanceSession(
                    jadwal_id=schedule_id,
                    pertemuan_ke=pertemuan_no,
                    tanggal=tgl_sesi,
                    dosen_id=jadwal.dosen_id,
                    active_jti=f"TMP-{uuid4().hex}",
                    generated_at=ref_utc,
                    expires_at=ref_utc + timedelta(minutes=valid_minutes),
                    valid_minutes=valid_minutes,
                    is_active=True,
                    latitude=latitude,
                    longitude=longitude,
                    max_radius_meters=(
                        max_radius_meters
                        if max_radius_meters is not None
                        else (100 if latitude is not None else None)
                    ),
                )
                self.db.add(session)
                self.db.flush()
            else:
                if latitude is not None and longitude is not None:
                    session.latitude = latitude
                    session.longitude = longitude
                    session.max_radius_meters = (
                        max_radius_meters
                        if max_radius_meters is not None
                        else (session.max_radius_meters or 100)
                    )

            png_bytes, token, jti, iat, exp = generate_attendance_qr(
                schedule_id=schedule_id,
                valid_minutes=valid_minutes,
                session_id=session.id,
                issued_at=ref_utc,
                secret=self.secret,
            )
            session.active_jti = jti
            session.generated_at = iat
            session.expires_at = exp
            session.valid_minutes = valid_minutes
            session.is_active = True

            self.db.commit()
            return QRSessionResult(
                session_id=session.id,
                schedule_id=jadwal.id,
                kelas_id=jadwal.kelas_id,
                kode_mk=jadwal.kelas.kode_mk,
                nama_mk=jadwal.kelas.matakuliah.nama,
                nama_kelas=jadwal.kelas.nama,
                pertemuan_ke=session.pertemuan_ke,
                tanggal=session.tanggal,
                valid_minutes=session.valid_minutes,
                generated_at=iat,
                expires_at=exp,
                jti=jti,
                token=token,
                qr_png=png_bytes,
            )
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

    def scan_qr(
        self,
        token: str,
        nim: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        now: datetime | None = None,
        client_key: str | None = None,
    ) -> ScanResult:
        """Memvalidasi QR JWT, jadwal hari ini, kepesertaan kelas, geofence, duplikat, & waktu."""
        nim_clean = nim.strip()
        rate_key = client_key or f"scan:{nim_clean}"
        self.rate_limiter.check(rate_key)

        ref_utc = _ensure_utc(now)
        payload = decode_attendance_token(
            token, secret=self.secret, current_time=ref_utc
        )
        schedule_id = int(payload["schedule_id"])
        token_jti = str(payload["jti"])
        session_id_claim = payload.get("session_id")

        started_immediate = False
        try:
            started_immediate = self._mulai_transaksi_terkunci()

            mhs = self.db.execute(
                select(CalonMahasiswa).where(CalonMahasiswa.nim == nim_clean)
            ).scalar_one_or_none()
            if mhs is None:
                raise AttendanceNotFoundError(
                    f"Mahasiswa dengan NIM {nim_clean} tidak ditemukan"
                )

            jadwal = self.db.execute(
                select(Jadwal)
                .options(joinedload(Jadwal.kelas).joinedload(Kelas.matakuliah))
                .where(Jadwal.id == schedule_id)
            ).scalar_one_or_none()
            if jadwal is None:
                raise AttendanceNotFoundError(
                    f"Jadwal kuliah dengan ID {schedule_id} tidak ditemukan"
                )

            session: AttendanceSession | None = None
            if session_id_claim is not None:
                session = self.db.get(AttendanceSession, int(session_id_claim))
            else:
                session = self.db.execute(
                    select(AttendanceSession).where(
                        AttendanceSession.active_jti == token_jti
                    )
                ).scalar_one_or_none()

            if (
                session is None
                or not session.is_active
                or session.jadwal_id != schedule_id
                or session.active_jti != token_jti
            ):
                raise AttendanceExpiredError(
                    "Token QR tidak lagi aktif atau telah digantikan oleh QR sesi terbaru"
                )

            scan_local_dt = ref_utc.astimezone(WIB)
            scan_local_date = scan_local_dt.date()

            # 1. Validasi hari jadwal kuliah & tanggal sesi
            if (
                scan_local_date.isoweekday() != jadwal.hari
                or scan_local_date != session.tanggal
            ):
                hari_jadwal = NAMA_HARI.get(jadwal.hari, str(jadwal.hari))
                raise AttendanceValidationError(
                    f"Scan ditolak: jadwal kuliah berlangsung hari {hari_jadwal} tanggal {session.tanggal.isoformat()}"
                )

            # 2. Validasi mahasiswa terdaftar pada kelas mata kuliah ini
            enrolled = self.db.execute(
                select(KRSDetail.id)
                .join(KRS, KRS.id == KRSDetail.krs_id)
                .where(
                    KRS.nim == nim_clean,
                    KRS.semester == jadwal.kelas.semester,
                    KRSDetail.kelas_id == jadwal.kelas_id,
                )
            ).first()
            if enrolled is None:
                raise AttendanceForbiddenError(
                    f"Mahasiswa {nim_clean} tidak terdaftar pada kelas {jadwal.kelas.kode_mk}-{jadwal.kelas.nama}"
                )

            # 3. Validasi geofencing opsional bila dosen mengaktifkan lokasi sesi
            jarak_meter: float | None = None
            if (
                session.latitude is not None
                and session.longitude is not None
                and session.max_radius_meters is not None
            ):
                if latitude is None or longitude is None:
                    raise AttendanceValidationError(
                        "Koordinat lokasi GPS wajib dikirim untuk sesi kelas dengan geofencing"
                    )
                jarak_meter = round(
                    hitung_jarak_haversine_meter(
                        session.latitude,
                        session.longitude,
                        latitude,
                        longitude,
                    ),
                    2,
                )
                if jarak_meter > session.max_radius_meters:
                    raise AttendanceForbiddenError(
                        f"Lokasi di luar jangkauan kelas ({jarak_meter:.1f} m > batas {session.max_radius_meters} m)"
                    )

            # 4. Cek duplikasi scan pada sesi yang sama (409 Conflict)
            sudah_scan = self.db.execute(
                select(AttendanceRecord.id).where(
                    AttendanceRecord.session_id == session.id,
                    AttendanceRecord.nim == nim_clean,
                )
            ).first()
            if sudah_scan is not None:
                raise AttendanceDuplicateError(
                    f"Mahasiswa {nim_clean} sudah tercatat melakukan presensi pada sesi ini"
                )

            # 5. Hitung status hadir (<=15 mnt) vs terlambat (<=30 mnt) dari jam mulai kuliah
            mulai_dt = datetime.combine(
                session.tanggal, jadwal.jam_mulai, tzinfo=WIB
            )
            menit_dari_mulai = (scan_local_dt - mulai_dt).total_seconds() / 60.0
            try:
                status_str = tentukan_status_kehadiran(menit_dari_mulai)
            except ValueError as exc:
                raise AttendanceValidationError(str(exc)) from exc

            record = AttendanceRecord(
                session_id=session.id,
                nim=nim_clean,
                status=AttendanceStatus(status_str),
                scanned_at=ref_utc,
                latitude=latitude,
                longitude=longitude,
                distance_meters=jarak_meter,
                token_jti=token_jti,
                notes=f"Scan QR sesi #{session.pertemuan_ke}",
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)

            pesan = (
                f"Presensi tercatat ({status_str}) untuk {jadwal.kelas.matakuliah.nama} "
                f"kelas {jadwal.kelas.nama} pertemuan ke-{session.pertemuan_ke}."
            )
            return ScanResult(
                success=True,
                status=status_str,
                message=pesan,
                record_id=record.id,
                session_id=session.id,
                schedule_id=jadwal.id,
                nim=nim_clean,
                scanned_at=ref_utc,
                distance_meters=jarak_meter,
            )
        except IntegrityError as exc:
            self.db.rollback()
            raise AttendanceDuplicateError(
                f"Mahasiswa {nim_clean} sudah tercatat melakukan presensi pada sesi ini"
            ) from exc
        except Exception:
            if started_immediate or self.db.in_transaction():
                self.db.rollback()
            raise

    def list_schedules(self) -> list[dict[str, Any]]:
        """Mengembalikan daftar seluruh jadwal kuliah untuk pemilih sesi QR di UI."""
        rows = self.db.scalars(
            select(Jadwal)
            .options(
                joinedload(Jadwal.kelas).joinedload(Kelas.matakuliah),
                joinedload(Jadwal.dosen),
                joinedload(Jadwal.ruangan),
            )
            .order_by(Jadwal.hari, Jadwal.jam_mulai, Jadwal.id)
        ).all()
        return [
            {
                "id": j.id,
                "kelas_id": j.kelas_id,
                "kode_mk": j.kelas.kode_mk,
                "nama_mk": j.kelas.matakuliah.nama,
                "nama_kelas": j.kelas.nama,
                "semester": j.kelas.semester,
                "hari": j.hari,
                "nama_hari": NAMA_HARI.get(j.hari, str(j.hari)),
                "jam_mulai": j.jam_mulai.strftime("%H:%M"),
                "jam_selesai": j.jam_selesai.strftime("%H:%M"),
                "ruangan_kode": j.ruangan_kode,
                "dosen_id": j.dosen_id,
                "dosen_nama": j.dosen.nama,
            }
            for j in rows
        ]

    def _muat_peserta_kelas(self, kelas_id: int) -> list[CalonMahasiswa]:
        """Memuat seluruh mahasiswa yang mengambil kelas `kelas_id` pada KRS aktif."""
        kelas = self.db.get(Kelas, kelas_id)
        if kelas is None:
            raise AttendanceNotFoundError(f"Kelas dengan ID {kelas_id} tidak ditemukan")

        return list(
            self.db.scalars(
                select(CalonMahasiswa)
                .join(KRS, KRS.nim == CalonMahasiswa.nim)
                .join(KRSDetail, KRSDetail.krs_id == KRS.id)
                .where(
                    KRSDetail.kelas_id == kelas_id,
                    KRS.semester == kelas.semester,
                )
                .order_by(CalonMahasiswa.nim)
            ).all()
        )

    def get_kelas_report(self, kelas_id: int) -> dict[str, Any]:
        """Menghasilkan rekap persentase kehadiran seluruh peserta kelas beserta warning <75%."""
        kelas = self.db.execute(
            select(Kelas)
            .options(joinedload(Kelas.matakuliah))
            .where(Kelas.id == kelas_id)
        ).scalar_one_or_none()
        if kelas is None:
            raise AttendanceNotFoundError(f"Kelas dengan ID {kelas_id} tidak ditemukan")

        sessions = list(
            self.db.scalars(
                select(AttendanceSession)
                .join(Jadwal, Jadwal.id == AttendanceSession.jadwal_id)
                .options(selectinload(AttendanceSession.records))
                .where(Jadwal.kelas_id == kelas_id)
                .order_by(
                    AttendanceSession.pertemuan_ke, AttendanceSession.tanggal
                )
            )
            .unique()
            .all()
        )
        peserta_mhs = self._muat_peserta_kelas(kelas_id)

        total_sesi = len(sessions)
        records_by_nim: dict[str, dict[int, AttendanceRecord]] = defaultdict(dict)
        for sess in sessions:
            for rec in sess.records:
                records_by_nim[rec.nim][sess.id] = rec

        peserta_rows: list[dict[str, Any]] = []
        warning_rows: list[dict[str, Any]] = []

        for mhs in peserta_mhs:
            assert mhs.nim is not None
            mhs_recs = records_by_nim.get(mhs.nim, {})
            hadir_cnt = sum(
                1 for r in mhs_recs.values() if r.status == AttendanceStatus.hadir
            )
            telat_cnt = sum(
                1 for r in mhs_recs.values() if r.status == AttendanceStatus.terlambat
            )
            izin_cnt = sum(
                1 for r in mhs_recs.values() if r.status == AttendanceStatus.izin
            )
            alpha_explicit = sum(
                1 for r in mhs_recs.values() if r.status == AttendanceStatus.alpha
            )
            belum_scan = max(0, total_sesi - len(mhs_recs))
            alpha_cnt = alpha_explicit + belum_scan
            persen = hitung_persentase_kehadiran(
                hadir_cnt + telat_cnt, total_sesi
            )
            is_warning = total_sesi > 0 and persen < MIN_PRESENSI_PERSEN

            item = {
                "nim": mhs.nim,
                "nama_lengkap": mhs.nama_lengkap,
                "total_sesi": total_sesi,
                "hadir": hadir_cnt,
                "terlambat": telat_cnt,
                "izin": izin_cnt,
                "alpha": alpha_cnt,
                "persentase": f"{persen:.2f}",
                "warning": is_warning,
            }
            peserta_rows.append(item)
            if is_warning:
                warning_rows.append(item)

        return {
            "kelas_id": kelas.id,
            "kode_mk": kelas.kode_mk,
            "nama_mk": kelas.matakuliah.nama,
            "nama_kelas": kelas.nama,
            "semester": kelas.semester,
            "total_sesi": total_sesi,
            "peserta": peserta_rows,
            "mahasiswa_berisiko": warning_rows,
        }

    def get_mahasiswa_report(self, nim: str) -> dict[str, Any]:
        """Menghasilkan rekap persentase kehadiran per mata kuliah untuk satu mahasiswa."""
        mhs = self.db.execute(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
        ).scalar_one_or_none()
        if mhs is None:
            raise AttendanceNotFoundError(
                f"Mahasiswa dengan NIM {nim} tidak ditemukan"
            )

        enrolled_classes = list(
            self.db.scalars(
                select(Kelas)
                .join(KRSDetail, KRSDetail.kelas_id == Kelas.id)
                .join(KRS, KRS.id == KRSDetail.krs_id)
                .options(joinedload(Kelas.matakuliah))
                .where(KRS.nim == nim, KRS.semester == Kelas.semester)
                .order_by(Kelas.semester.desc(), Kelas.kode_mk, Kelas.nama)
            )
            .unique()
            .all()
        )

        items: list[dict[str, Any]] = []
        for kelas in enrolled_classes:
            report = self.get_kelas_report(kelas.id)
            row = next((p for p in report["peserta"] if p["nim"] == nim), None)
            if row is not None:
                items.append(
                    {
                        "kelas_id": kelas.id,
                        "kode_mk": kelas.kode_mk,
                        "nama_mk": kelas.matakuliah.nama,
                        "nama_kelas": kelas.nama,
                        "semester": kelas.semester,
                        "total_sesi": row["total_sesi"],
                        "hadir": row["hadir"],
                        "terlambat": row["terlambat"],
                        "izin": row["izin"],
                        "alpha": row["alpha"],
                        "persentase": row["persentase"],
                        "warning": row["warning"],
                    }
                )

        return {
            "nim": nim,
            "nama_lengkap": mhs.nama_lengkap,
            "mata_kuliah": items,
        }

    def export_kelas_excel(self, kelas_id: int) -> tuple[bytes, str]:
        """Mengekspor laporan presensi kelas dan log kehadiran ke file Excel (.xlsx)."""
        report = self.get_kelas_report(kelas_id)
        sessions = list(
            self.db.scalars(
                select(AttendanceSession)
                .join(Jadwal, Jadwal.id == AttendanceSession.jadwal_id)
                .options(
                    selectinload(AttendanceSession.records).joinedload(
                        AttendanceRecord.mahasiswa
                    )
                )
                .where(Jadwal.kelas_id == kelas_id)
                .order_by(
                    AttendanceSession.pertemuan_ke, AttendanceSession.tanggal
                )
            )
            .unique()
            .all()
        )

        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Rekap Presensi"

        header_fill = PatternFill("solid", fgColor="102A43")
        header_font = Font(bold=True, color="FFFFFF")
        warn_fill = PatternFill("solid", fgColor="FEE2E2")
        warn_font = Font(bold=True, color="B91C1C")
        ok_font = Font(bold=True, color="15803D")

        ws["A1"] = "LAPORAN PRESENSI MAHASISWA — SEVIMA-Mini"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = (
            f"Mata Kuliah: {report['kode_mk']} - {report['nama_mk']} "
            f"(Kelas {report['nama_kelas']} | Semester {report['semester']})"
        )
        ws["A3"] = f"Total Sesi Pertemuan: {report['total_sesi']}"

        cols = [
            "No",
            "NIM",
            "Nama Mahasiswa",
            "Total Sesi",
            "Hadir",
            "Terlambat",
            "Izin",
            "Alpha",
            "Persentase (%)",
            "Status Syarat (>=75%)",
        ]
        ws.append([])
        ws.append(cols)
        header_row_idx = 5
        for col_idx in range(1, len(cols) + 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for idx, p in enumerate(report["peserta"], start=1):
            status_syarat = "WARNING (<75%)" if p["warning"] else "MEMENUHI (>=75%)"
            ws.append(
                [
                    idx,
                    p["nim"],
                    p["nama_lengkap"],
                    p["total_sesi"],
                    p["hadir"],
                    p["terlambat"],
                    p["izin"],
                    p["alpha"],
                    float(p["persentase"]),
                    status_syarat,
                ]
            )
            row_idx = header_row_idx + idx
            if p["warning"]:
                for c in range(1, len(cols) + 1):
                    ws.cell(row=row_idx, column=c).fill = warn_fill
                ws.cell(row=row_idx, column=10).font = warn_font
            else:
                ws.cell(row=row_idx, column=10).font = ok_font

        widths = [6, 16, 28, 12, 10, 12, 10, 10, 16, 22]
        for idx, width in enumerate(widths, start=1):
            col_letter = chr(ord("A") + idx - 1)
            ws.column_dimensions[col_letter].width = width

        ws_log = wb.create_sheet("Log Kehadiran")
        log_cols = [
            "Pertemuan Ke",
            "Tanggal",
            "NIM",
            "Nama Mahasiswa",
            "Status",
            "Waktu Scan (UTC)",
            "Jarak GPS (m)",
            "Catatan",
        ]
        ws_log.append(log_cols)
        for col_idx in range(1, len(log_cols) + 1):
            cell = ws_log.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font

        for sess in sessions:
            for rec in sess.records:
                ws_log.append(
                    [
                        sess.pertemuan_ke,
                        sess.tanggal.isoformat(),
                        rec.nim,
                        rec.mahasiswa.nama_lengkap if rec.mahasiswa else "-",
                        rec.status.value,
                        rec.scanned_at.isoformat(),
                        rec.distance_meters if rec.distance_meters is not None else "-",
                        rec.notes or "-",
                    ]
                )

        log_widths = [14, 14, 16, 26, 12, 28, 16, 30]
        for idx, width in enumerate(log_widths, start=1):
            col_letter = chr(ord("A") + idx - 1)
            ws_log.column_dimensions[col_letter].width = width

        buf = io.BytesIO()
        wb.save(buf)
        filename = (
            f"presensi_{report['kode_mk']}_{report['nama_kelas']}_{report['semester']}.xlsx"
        )
        return buf.getvalue(), filename

    def build_live_attendance_records(self) -> list[RekordPresensiInput]:
        """Membangun daftar lengkap rekord presensi (termasuk alpha implisit) dari database."""
        sessions = list(
            self.db.scalars(
                select(AttendanceSession)
                .options(
                    joinedload(AttendanceSession.jadwal)
                    .joinedload(Jadwal.kelas)
                    .joinedload(Kelas.matakuliah),
                    selectinload(AttendanceSession.records).joinedload(
                        AttendanceRecord.mahasiswa
                    ),
                )
                .order_by(AttendanceSession.tanggal, AttendanceSession.id)
            )
            .unique()
            .all()
        )
        if not sessions:
            return []

        kelas_ids = {s.jadwal.kelas_id for s in sessions}
        peserta_map: dict[int, list[CalonMahasiswa]] = {
            kid: self._muat_peserta_kelas(kid) for kid in kelas_ids
        }

        hasil: list[RekordPresensiInput] = []
        for sess in sessions:
            jadwal = sess.jadwal
            kelas = jadwal.kelas
            kelas_label = f"{kelas.kode_mk}-{kelas.nama}"
            by_nim = {r.nim: r for r in sess.records}

            seen_nims: set[str] = set()
            for mhs in peserta_map.get(kelas.id, []):
                assert mhs.nim is not None
                seen_nims.add(mhs.nim)
                rec = by_nim.get(mhs.nim)
                status_str = rec.status.value if rec is not None else "alpha"
                hasil.append(
                    RekordPresensiInput(
                        nim=mhs.nim,
                        nama=mhs.nama_lengkap,
                        kelas=kelas_label,
                        hari=jadwal.hari,
                        jam_mulai=jadwal.jam_mulai,
                        status=status_str,
                        tanggal=sess.tanggal,
                    )
                )

            for nim, rec in by_nim.items():
                if nim in seen_nims:
                    continue
                hasil.append(
                    RekordPresensiInput(
                        nim=nim,
                        nama=rec.mahasiswa.nama_lengkap if rec.mahasiswa else None,
                        kelas=kelas_label,
                        hari=jadwal.hari,
                        jam_mulai=jadwal.jam_mulai,
                        status=rec.status.value,
                        tanggal=sess.tanggal,
                    )
                )

        return hasil

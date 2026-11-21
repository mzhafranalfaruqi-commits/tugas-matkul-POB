"""Router FastAPI tipis untuk Modul Jadwal, Conflict Resolver AI, & Ekspor iCalendar."""

from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.jadwal import Jadwal, Kelas
from app.models.krs import KRS, KRSDetail
from app.models.pmb import CalonMahasiswa
from app.schemas.jadwal import (
    ApplySaranIn,
    ConflictOut,
    JadwalDetailOut,
    JadwalIn,
    JadwalOut,
    SaranOut,
)
from app.services.icalendar import export_jadwal_ics
from app.services.rescheduler import (
    LLMClient,
    ReschedulerService,
    Saran,
    get_llm_client,
    hitung_durasi,
    tambah_durasi,
)
from app.services.scheduling_service import SchedulingService

_RESOLVER_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "templates" / "resolver.html"
)


def require_admin(x_role: str | None = Header(default=None, alias="X-Role")) -> str:
    """Memastikan hanya aktor ber-role admin yang dapat mengubah jadwal atau memicu resolver."""
    if (x_role or "").strip().lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: endpoint ini hanya untuk role admin",
        )
    return "admin"


router = APIRouter(prefix="/api/jadwal", tags=["Jadwal"])
mahasiswa_router = APIRouter(prefix="/api/mahasiswa", tags=["Jadwal"])


@router.get(
    "/resolver",
    response_class=HTMLResponse,
    summary="Antarmuka web Conflict Resolver & AI Rescheduling",
    responses={200: {"description": "Halaman HTML Conflict Resolver Dashboard"}},
)
def resolver_ui() -> HTMLResponse:
    """Menyajikan halaman HTML sederhana untuk inspeksi bentrok & penerapan saran AI."""
    return HTMLResponse(content=_RESOLVER_TEMPLATE.read_text(encoding="utf-8"))


@router.get(
    "/conflicts",
    response_model=list[ConflictOut],
    summary="Daftar seluruh bentrok jadwal yang terdeteksi di database",
    responses={
        200: {"description": "Daftar konflik ruangan dan/atau dosen dari jadwal tersimpan"},
    },
)
def list_conflicts(db: Session = Depends(get_db)) -> list[ConflictOut]:
    """Mengembalikan seluruh pasangan jadwal bentrok (ruangan & dosen) untuk dashboard admin."""
    konflik = SchedulingService(db).list_conflicts()
    return [ConflictOut(type=k.type, affected=list(k.affected)) for k in konflik]


@router.get(
    "",
    response_model=list[JadwalDetailOut],
    summary="Daftar seluruh jadwal lengkap beserta metadata kelas, MK, ruangan, & dosen",
    responses={200: {"description": "Daftar seluruh jadwal kuliah tersimpan"}},
)
def list_jadwal(db: Session = Depends(get_db)) -> list[JadwalDetailOut]:
    """Mengembalikan daftar lengkap jadwal kuliah untuk tampilan dashboard Conflict Resolver."""
    jadwals = db.scalars(
        select(Jadwal)
        .options(
            joinedload(Jadwal.kelas).joinedload(Kelas.matakuliah),
            joinedload(Jadwal.ruangan),
            joinedload(Jadwal.dosen),
        )
        .order_by(Jadwal.id)
    ).all()

    terdaftar_rows = db.execute(
        select(KRSDetail.kelas_id, func.count())
        .where(KRSDetail.kelas_id.is_not(None))
        .group_by(KRSDetail.kelas_id)
    ).all()
    terdaftar_map = {int(kid): int(cnt) for kid, cnt in terdaftar_rows if kid is not None}

    return [
        JadwalDetailOut(
            id=j.id,
            kelas_id=j.kelas_id,
            hari=j.hari,
            jam_mulai=j.jam_mulai,
            jam_selesai=j.jam_selesai,
            ruangan_kode=j.ruangan_kode,
            dosen_id=j.dosen_id,
            sequence=j.sequence,
            kode_mk=j.kelas.kode_mk,
            nama_mk=j.kelas.matakuliah.nama,
            nama_kelas=j.kelas.nama,
            semester=j.kelas.semester,
            kuota=j.kelas.kuota,
            peserta=max(j.kelas.kuota, terdaftar_map.get(j.kelas_id, 0)),
            ruangan_kapasitas=j.ruangan.kapasitas,
            dosen_nama=j.dosen.nama,
        )
        for j in jadwals
    ]


@router.post(
    "",
    response_model=JadwalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    summary="Buat jadwal kuliah baru dengan validasi bentrok & kapasitas",
    responses={
        201: {"description": "Jadwal kuliah berhasil dibuat"},
        403: {"description": "Akses ditolak: membutuhkan role admin"},
        404: {"description": "Ruangan, kelas, atau dosen tidak ditemukan"},
        409: {"description": "Bentrok jadwal ruangan/dosen atau kapasitas ruangan tidak cukup"},
        422: {"description": "Payload jadwal tidak valid (mis. jam_mulai >= jam_selesai)"},
    },
)
def create_jadwal(
    data_in: JadwalIn,
    db: Session = Depends(get_db),
) -> JadwalOut:
    """Menyimpan jadwal kuliah baru setelah melewati pemeriksaan hard constraint."""
    jadwal = SchedulingService(db).create(data_in)
    return JadwalOut.model_validate(jadwal)


@router.get(
    "/{jadwal_id}/suggestions",
    response_model=list[SaranOut],
    dependencies=[Depends(require_admin)],
    summary="Cari saran AI penjadwalan ulang yang telah lolos guardrail deterministik",
    responses={
        200: {"description": "Maksimal 3 alternatif slot bebas bentrok & muat kapasitas"},
        403: {"description": "Akses ditolak: membutuhkan role admin"},
        404: {"description": "Jadwal tidak ditemukan"},
    },
)
def get_suggestions(
    jadwal_id: int,
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
) -> list[SaranOut]:
    """Meminta maksimal 3 rekomendasi slot pengganti dari AI Rescheduler tervalidasi."""
    jadwal, saran_list = ReschedulerService(db, llm=llm).saran_alternatif(jadwal_id)
    durasi = hitung_durasi(jadwal)
    keluaran: list[SaranOut] = []
    for s in saran_list:
        jam_selesai = tambah_durasi(s.jam_mulai, durasi)
        if jam_selesai is None:
            continue
        keluaran.append(
            SaranOut(
                hari=s.hari,
                jam_mulai=s.jam_mulai,
                jam_selesai=jam_selesai,
                ruangan=s.ruangan,
                reason=s.reason,
            )
        )
    return keluaran


@router.post(
    "/{jadwal_id}/apply",
    response_model=JadwalOut,
    dependencies=[Depends(require_admin)],
    summary="Terapkan satu saran slot pengganti melalui SchedulingService.update",
    responses={
        200: {"description": "Saran diterapkan, KRS terdampak direvisi, outbox terkirim"},
        403: {"description": "Akses ditolak: membutuhkan role admin"},
        404: {"description": "Jadwal atau ruangan tidak ditemukan"},
        409: {"description": "Slot sudah terisi atau kapasitas ruangan tidak cukup"},
        422: {"description": "Payload saran tidak valid"},
    },
)
def apply_suggestion(
    jadwal_id: int,
    data_in: ApplySaranIn,
    db: Session = Depends(get_db),
) -> JadwalOut:
    """Menerapkan saran jadwal pilihan admin lewat satu pintu SchedulingService.update."""
    saran = Saran(
        hari=data_in.hari,
        jam_mulai=data_in.jam_mulai,
        ruangan=data_in.ruangan,
        reason=data_in.reason,
    )
    jadwal = ReschedulerService(db).apply_saran(jadwal_id, saran)
    return JadwalOut.model_validate(jadwal)


@router.put(
    "/{jadwal_id}",
    response_model=JadwalOut,
    dependencies=[Depends(require_admin)],
    summary="Perbarui jadwal kuliah, invalidasi KRS terdampak, & kirim notifikasi outbox",
    responses={
        200: {"description": "Jadwal kuliah berhasil diperbarui"},
        403: {"description": "Akses ditolak: membutuhkan role admin"},
        404: {"description": "Jadwal, ruangan, kelas, atau dosen tidak ditemukan"},
        409: {"description": "Bentrok jadwal dengan jadwal lain atau kapasitas tidak cukup"},
        422: {"description": "Payload jadwal tidak valid (mis. jam_mulai >= jam_selesai)"},
    },
)
def update_jadwal(
    jadwal_id: int,
    data_in: JadwalIn,
    db: Session = Depends(get_db),
) -> JadwalOut:
    """Memperbarui jadwal kuliah secara atomik bersama invalidasi KRS & pencatatan Outbox."""
    jadwal = SchedulingService(db).update(jadwal_id, data_in)
    return JadwalOut.model_validate(jadwal)


@router.delete(
    "/{jadwal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
    summary="Hapus jadwal kuliah beserta invalidasi KRS & notifikasi outbox",
    responses={
        204: {"description": "Jadwal kuliah berhasil dihapus"},
        403: {"description": "Akses ditolak: membutuhkan role admin"},
        404: {"description": "Jadwal tidak ditemukan"},
    },
)
def delete_jadwal(
    jadwal_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Menghapus satu entri jadwal kuliah dan memberi tahu mahasiswa/dosen/admin."""
    SchedulingService(db).delete(jadwal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@mahasiswa_router.get(
    "/{nim}/jadwal.ics",
    summary="Ekspor jadwal kuliah mahasiswa ke format iCalendar RFC 5545 (.ics)",
    responses={
        200: {"description": "Dokumen iCalendar (text/calendar) berisi jadwal kuliah mingguan"},
        404: {"description": "Mahasiswa ber-NIM atau KRS semester terkait tidak ditemukan"},
    },
)
def export_mahasiswa_ics(
    nim: str,
    semester: str | None = Query(default=None, min_length=5, max_length=5),
    db: Session = Depends(get_db),
) -> Response:
    """Menghasilkan file .ics berisi seluruh jadwal kelas yang diambil mahasiswa pada KRS."""
    mahasiswa = db.execute(
        select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
    ).scalar_one_or_none()
    if mahasiswa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mahasiswa ber-NIM {nim} tidak ditemukan",
        )

    stmt = select(KRS).options(joinedload(KRS.details)).where(KRS.nim == nim)
    if semester is not None:
        stmt = stmt.where(KRS.semester == semester)
    else:
        stmt = stmt.order_by(KRS.semester.desc(), KRS.id.desc())

    krs = db.scalars(stmt).first()
    if krs is None and semester is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KRS mahasiswa {nim} semester {semester} tidak ditemukan",
        )

    kelas_ids = (
        sorted({d.kelas_id for d in krs.details if d.kelas_id is not None})
        if krs is not None
        else []
    )
    items: list[tuple[Jadwal, str, int]] = []
    if kelas_ids:
        jadwals = db.scalars(
            select(Jadwal)
            .options(joinedload(Jadwal.kelas).joinedload(Kelas.matakuliah))
            .where(Jadwal.kelas_id.in_(kelas_ids))
            .order_by(Jadwal.hari, Jadwal.jam_mulai, Jadwal.id)
        ).all()
        items = [
            (
                j,
                f"{j.kelas.kode_mk}-{j.kelas.nama} {j.kelas.matakuliah.nama}",
                j.sequence,
            )
            for j in jadwals
        ]

    ics_content = export_jadwal_ics(items)
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="jadwal-{nim}.ics"',
        },
    )

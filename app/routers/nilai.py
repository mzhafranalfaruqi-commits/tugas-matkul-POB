"""Router FastAPI tipis untuk Modul Nilai, Kalkulator IPS/IPK, Form Input, & Audit Trail."""

from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.jadwal import Jadwal, Kelas
from app.models.pmb import CalonMahasiswa
from app.schemas.nilai import (
    DosenRingkasOut,
    GradeHistoryOut,
    IPKOut,
    IPSOut,
    KelasNilaiRingkasOut,
    NilaiIn,
    NilaiOut,
    PesertaNilaiOut,
)
from app.services.gpa_calculator import GPACalculator, NilaiRepo
from app.services.grade_service import (
    GradeService,
    PresensiPort,
    get_presensi_port,
)

_NILAI_FORM_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "templates" / "nilai_form.html"
)


def get_current_dosen(
    x_dosen_id: int | None = Header(default=None, alias="X-Dosen-Id"),
) -> int:
    """Membaca identitas dosen terautentikasi dari header X-Dosen-Id (401 jika absen)."""
    if x_dosen_id is None or x_dosen_id < 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi gagal: header X-Dosen-Id dosen wajib disertakan",
        )
    return x_dosen_id


def _pastikan_mahasiswa_ada(db: Session, nim: str) -> None:
    mhs = db.execute(
        select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
    ).scalar_one_or_none()
    if mhs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mahasiswa ber-NIM {nim} tidak ditemukan",
        )


kelas_router = APIRouter(prefix="/api/kelas", tags=["Nilai"])
nilai_mahasiswa_router = APIRouter(prefix="/api/mahasiswa", tags=["Nilai"])


@kelas_router.get(
    "/nilai-form",
    response_class=HTMLResponse,
    summary="Halaman web form input nilai dosen dan riwayat audit nilai",
    responses={200: {"description": "Halaman HTML Form Input Nilai & Audit Trail"}},
)
def nilai_form_ui() -> HTMLResponse:
    """Menyajikan antarmuka web sederhana bagi dosen untuk input nilai & lihat riwayat."""
    return HTMLResponse(content=_NILAI_FORM_TEMPLATE.read_text(encoding="utf-8"))


@kelas_router.get(
    "",
    response_model=list[KelasNilaiRingkasOut],
    summary="Daftar seluruh kelas beserta dosen pengampu terjadwal",
    responses={200: {"description": "Daftar kelas beserta daftar dosen pengampunya"}},
)
def list_kelas_nilai(db: Session = Depends(get_db)) -> list[KelasNilaiRingkasOut]:
    """Mengembalikan daftar kelas paralel & dosen pengampunya untuk pemilih kelas di UI."""
    daftar = db.scalars(
        select(Kelas)
        .options(
            joinedload(Kelas.matakuliah),
            joinedload(Kelas.jadwals).joinedload(Jadwal.dosen),
        )
        .order_by(Kelas.semester.desc(), Kelas.kode_mk, Kelas.nama)
    ).unique().all()

    keluaran: list[KelasNilaiRingkasOut] = []
    for k in daftar:
        dosen_map: dict[int, str] = {}
        for j in sorted(k.jadwals, key=lambda item: item.dosen_id):
            dosen_map.setdefault(j.dosen_id, j.dosen.nama)
        keluaran.append(
            KelasNilaiRingkasOut(
                id=k.id,
                kode_mk=k.kode_mk,
                nama_mk=k.matakuliah.nama,
                nama_kelas=k.nama,
                semester=k.semester,
                dosens=[
                    DosenRingkasOut(id=did, nama=nama)
                    for did, nama in dosen_map.items()
                ],
            )
        )
    return keluaran


@kelas_router.get(
    "/{kelas_id}/peserta",
    response_model=list[PesertaNilaiOut],
    summary="Daftar peserta kelas beserta persentase presensi, nilai, dan IPK terkini",
    responses={
        200: {"description": "Daftar peserta kelas ditemukan"},
        401: {"description": "Header X-Dosen-Id tidak disertakan"},
        403: {"description": "Dosen bukan pengampu kelas ini"},
        404: {"description": "Kelas tidak ditemukan"},
    },
)
def list_peserta_kelas(
    kelas_id: int,
    dosen_id: int = Depends(get_current_dosen),
    db: Session = Depends(get_db),
    presensi: PresensiPort = Depends(get_presensi_port),
) -> list[PesertaNilaiOut]:
    """Menampilkan peserta kelas yang berhak dinilai oleh dosen pengampu."""
    rows = GradeService(db, presensi).daftar_peserta(dosen_id, kelas_id)
    return [PesertaNilaiOut(**row) for row in rows]


@kelas_router.put(
    "/{kelas_id}/nilai/{nim}",
    response_model=NilaiOut,
    summary="Input atau ubah nilai huruf mahasiswa oleh dosen pengampu (idempoten + audit)",
    responses={
        200: {"description": "Nilai huruf berhasil disimpan dan dicatat ke grade_history"},
        400: {"description": "Presensi < 75%, huruf tak dikenal, atau edit tanpa alasan"},
        401: {"description": "Header X-Dosen-Id tidak disertakan"},
        403: {"description": "Dosen bukan pengampu kelas ini"},
        404: {"description": "Mahasiswa tidak terdaftar pada kelas tersebut"},
        422: {"description": "Payload huruf tidak memenuhi pola A-E"},
    },
)
def input_nilai(
    kelas_id: int,
    nim: str,
    body: NilaiIn,
    dosen_id: int = Depends(get_current_dosen),
    db: Session = Depends(get_db),
    presensi: PresensiPort = Depends(get_presensi_port),
) -> NilaiOut:
    """Menetapkan nilai huruf secara idempoten melalui satu pintu GradeService."""
    detail = GradeService(db, presensi).input_nilai(
        dosen_id=dosen_id,
        kelas_id=kelas_id,
        nim=nim,
        huruf=body.huruf,
        alasan=body.alasan,
    )
    return NilaiOut(nim=nim, kode_mk=detail.kode_mk, huruf=body.huruf)


@nilai_mahasiswa_router.get(
    "/{nim}/ipk",
    response_model=IPKOut,
    summary="Hitung IPK kumulatif mahasiswa secara compute-on-read (string Decimal)",
    responses={
        200: {"description": "IPK mahasiswa (string 2 desimal)"},
        404: {"description": "Mahasiswa ber-NIM tidak ditemukan"},
    },
)
def get_ipk(nim: str, db: Session = Depends(get_db)) -> IPKOut:
    """Mengembalikan IPK sebagai string desimal tepat tanpa konversi float."""
    _pastikan_mahasiswa_ada(db, nim)
    ipk = GPACalculator(NilaiRepo(db)).calculate_ipk(nim)
    return IPKOut(nim=nim, ipk=str(ipk))


@nilai_mahasiswa_router.get(
    "/{nim}/ips/{semester}",
    response_model=IPSOut,
    summary="Hitung IPS mahasiswa pada semester tertentu (string Decimal)",
    responses={
        200: {"description": "IPS semester terkait (termasuk E bila sudah terisi)"},
        404: {"description": "Mahasiswa ber-NIM tidak ditemukan"},
    },
)
def get_ips(nim: str, semester: str, db: Session = Depends(get_db)) -> IPSOut:
    """Mengembalikan IPS mahasiswa untuk satu semester sebagai string desimal."""
    _pastikan_mahasiswa_ada(db, nim)
    ips = GPACalculator(NilaiRepo(db)).calculate_ips(nim, semester)
    return IPSOut(nim=nim, semester=semester, ips=str(ips))


@nilai_mahasiswa_router.get(
    "/{nim}/nilai/riwayat",
    response_model=list[GradeHistoryOut],
    summary="Lihat jejak audit perubahan nilai mahasiswa dari view v_riwayat_nilai",
    responses={
        200: {"description": "Riwayat perubahan nilai terurut terbaru lebih dulu"},
        404: {"description": "Mahasiswa ber-NIM tidak ditemukan"},
    },
)
def get_riwayat_nilai(
    nim: str,
    db: Session = Depends(get_db),
    presensi: PresensiPort = Depends(get_presensi_port),
) -> list[GradeHistoryOut]:
    """Mengembalikan daftar lengkap audit perubahan nilai mahasiswa."""
    rows = GradeService(db, presensi).riwayat_nilai_mahasiswa(nim)
    return [GradeHistoryOut.model_validate(row) for row in rows]

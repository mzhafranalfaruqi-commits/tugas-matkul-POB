"""Entrypoint aplikasi FastAPI untuk SEVIMA-Mini Modul PMB, KRS, Jadwal, & Nilai."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers.jadwal import mahasiswa_router, router as jadwal_router
from app.routers.krs import router as krs_router
from app.routers.nilai import kelas_router, nilai_mahasiswa_router
from app.routers.pmb import router as pmb_router
from app.services.exceptions import GradeError, KRSError, ScheduleError

app = FastAPI(
    title="SEVIMA-Mini — Modul PMB, KRS, Jadwal, & Nilai API",
    description=(
        "REST API Penerimaan Mahasiswa Baru, Pengisian & State Machine KRS, "
        "Penjadwalan & Ruangan, Observer/Outbox, AI Rescheduling, Conflict Resolver UI, "
        "Ekspor iCalendar (.ics), Input Nilai Berpenjaga, Kalkulator IPS/IPK, & Audit Trail"
    ),
    version="1.5.0",
)


@app.exception_handler(RequestValidationError)
async def validasi_input(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Mengembalikan 422 pada rute /api/jadwal, /api/kelas, /api/mahasiswa dan 400 untuk PMB/KRS."""
    rute_422 = ("/api/jadwal", "/api/kelas", "/api/mahasiswa")
    status_code = 422 if request.url.path.startswith(rute_422) else 400
    return JSONResponse(
        status_code=status_code,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(KRSError)
async def krs_error_handler(_request: Request, exc: KRSError) -> JSONResponse:
    """Handler polimorfik tunggal yang memetakan setiap subkelas KRSError ke status HTTP-nya."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)},
    )


@app.exception_handler(ScheduleError)
async def schedule_error_handler(_request: Request, exc: ScheduleError) -> JSONResponse:
    """Handler polimorfik tunggal yang memetakan setiap subkelas ScheduleError ke status HTTP-nya."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.body(),
    )


@app.exception_handler(GradeError)
async def grade_error_handler(_request: Request, exc: GradeError) -> JSONResponse:
    """Handler polimorfik tunggal yang memetakan setiap subkelas GradeError ke status HTTP-nya."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)},
    )


app.include_router(pmb_router)
app.include_router(krs_router)
app.include_router(jadwal_router)
app.include_router(mahasiswa_router)
app.include_router(kelas_router)
app.include_router(nilai_mahasiswa_router)


@app.get("/", tags=["Health"])
def root() -> dict[str, str]:
    """Endpoint informasi dasar untuk memastikan layanan API berjalan."""
    return {
        "message": "SEVIMA-Mini Modul PMB, KRS, & Jadwal API aktif",
        "docs": "/docs",
    }

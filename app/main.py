"""Entrypoint aplikasi FastAPI untuk SEVIMA-Mini Modul PMB, KRS, & Jadwal."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers.jadwal import router as jadwal_router
from app.routers.krs import router as krs_router
from app.routers.pmb import router as pmb_router
from app.services.exceptions import KRSError, ScheduleError

app = FastAPI(
    title="SEVIMA-Mini — Modul PMB, KRS, & Jadwal API",
    description=(
        "REST API Penerimaan Mahasiswa Baru, Pengisian & State Machine KRS, "
        "Approval/Revisi Dosen PA, Rekomendasi Jadwal CSP, dan Penjadwalan & Ruangan"
    ),
    version="1.3.0",
)


@app.exception_handler(RequestValidationError)
async def validasi_input(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Mengembalikan 422 pada rute /api/jadwal dan menyeragamkan 400 pada rute PMB/KRS."""
    status_code = 422 if request.url.path.startswith("/api/jadwal") else 400
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


app.include_router(pmb_router)
app.include_router(krs_router)
app.include_router(jadwal_router)


@app.get("/", tags=["Health"])
def root() -> dict[str, str]:
    """Endpoint informasi dasar untuk memastikan layanan API berjalan."""
    return {
        "message": "SEVIMA-Mini Modul PMB, KRS, & Jadwal API aktif",
        "docs": "/docs",
    }

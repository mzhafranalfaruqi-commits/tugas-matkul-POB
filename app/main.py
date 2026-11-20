"""Entrypoint aplikasi FastAPI untuk SEVIMA-Mini Modul PMB & KRS."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers.krs import router as krs_router
from app.routers.pmb import router as pmb_router
from app.services.exceptions import KRSError

app = FastAPI(
    title="SEVIMA-Mini — Modul PMB & KRS API",
    description=(
        "REST API Penerimaan Mahasiswa Baru, Pengisian & State Machine KRS, "
        "Approval/Revisi Dosen PA, dan Rekomendasi Jadwal CSP"
    ),
    version="1.2.0",
)


@app.exception_handler(RequestValidationError)
async def validasi_400(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Menyeragamkan error validasi Pydantic/FastAPI menjadi HTTP 400 Bad Request."""
    return JSONResponse(
        status_code=400,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(KRSError)
async def krs_error_handler(_request: Request, exc: KRSError) -> JSONResponse:
    """Handler polimorfik tunggal yang memetakan setiap subkelas KRSError ke status HTTP-nya."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)},
    )


app.include_router(pmb_router)
app.include_router(krs_router)


@app.get("/", tags=["Health"])
def root() -> dict[str, str]:
    """Endpoint informasi dasar untuk memastikan layanan API berjalan."""
    return {
        "message": "SEVIMA-Mini Modul PMB & KRS API aktif",
        "docs": "/docs",
    }

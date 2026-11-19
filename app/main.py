"""Entrypoint aplikasi FastAPI untuk SEVIMA-Mini Modul PMB."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers.pmb import router as pmb_router

app = FastAPI(
    title="SEVIMA-Mini — Modul PMB API",
    description="REST API Penerimaan Mahasiswa Baru dengan Generator NIM Otomatis",
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validasi_400(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Menyeragamkan error validasi Pydantic/FastAPI menjadi HTTP 400 Bad Request."""
    return JSONResponse(
        status_code=400,
        content={"detail": jsonable_encoder(exc.errors())},
    )


app.include_router(pmb_router)


@app.get("/", tags=["Health"])
def root() -> dict[str, str]:
    """Endpoint informasi dasar untuk memastikan layanan API berjalan."""
    return {
        "message": "SEVIMA-Mini Modul PMB API aktif",
        "docs": "/docs",
    }

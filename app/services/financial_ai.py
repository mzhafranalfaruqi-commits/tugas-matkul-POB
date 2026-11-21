"""Layanan AI Financial Insights untuk menganalisis data pembayaran CSV/DB menjadi laporan JSON."""

from datetime import date
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.keuangan import (
    HasilAnalisisKeuangan,
    analisis_keuangan_csv,
    format_rupiah,
)
from app.models.pmb import CalonMahasiswa
from app.services.billing_service import BillingService
from app.services.exceptions import BillingValidationError


class FinancialNarrativeClient(Protocol):
    """Port generator narasi ringkas laporan keuangan (dapat ditukar ke LLM eksternal)."""

    def generate_narrative(self, hasil: HasilAnalisisKeuangan) -> str:
        """Menghasilkan ringkasan narasi berbasis data analisis keuangan terverifikasi."""


class DeterministicNarrativeClient:
    """Generator narasi deterministik berbasis metrik aktual tanpa fabrikasi angka."""

    def generate_narrative(self, hasil: HasilAnalisisKeuangan) -> str:
        revenue_fmt = format_rupiah(hasil.total_revenue_bulan_ini)
        bagian = [
            (
                f"Pada periode {hasil.periode_bulan}, total pendapatan SPP tercatat "
                f"sebesar {revenue_fmt} dengan tingkat pelunasan (collection rate) "
                f"{hasil.collection_rate_persen}% ({hasil.mahasiswa_sudah_bayar} dari "
                f"{hasil.total_mahasiswa} mahasiswa)."
            )
        ]
        if hasil.top_10_tunggakan:
            teratas = hasil.top_10_tunggakan[0]
            label_mhs = (
                f"{teratas.nama} ({teratas.nim})"
                if teratas.nama
                else teratas.nim
            )
            bagian.append(
                f"Tunggakan tertinggi saat ini dipegang oleh {label_mhs} sebesar "
                f"{format_rupiah(teratas.total_tunggakan)}."
            )
        else:
            bagian.append("Seluruh mahasiswa tercatat bebas tunggakan SPP.")

        if hasil.rekomendasi:
            bagian.append(f"Prioritas aksi: {hasil.rekomendasi[0]}.")
        return " ".join(bagian)


class FinancialReportService:
    """Orkestrator analisis data pembayaran (CSV/database) menjadi laporan JSON untuk frontend."""

    def __init__(
        self, narrative_client: FinancialNarrativeClient | None = None
    ) -> None:
        self.narrative_client = narrative_client or DeterministicNarrativeClient()

    def analyze_csv(
        self,
        csv_text: str,
        as_of: date | None = None,
        nama_by_nim: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Mem-parsing CSV (nim,jumlah,tanggal,status) lalu mengembalikan JSON insights."""
        try:
            hasil = analisis_keuangan_csv(
                csv_text, as_of=as_of, nama_by_nim=nama_by_nim
            )
        except ValueError as exc:
            raise BillingValidationError(str(exc)) from exc

        narasi = self.narrative_client.generate_narrative(hasil)
        return {
            "periode_bulan": hasil.periode_bulan,
            "ringkasan": {
                "total_revenue_bulan_ini": f"{hasil.total_revenue_bulan_ini:.2f}",
                "total_revenue_bulan_ini_formatted": format_rupiah(
                    hasil.total_revenue_bulan_ini
                ),
                "collection_rate_persen": f"{hasil.collection_rate_persen:.2f}",
                "collection_rate_label": f"{hasil.collection_rate_persen}% mahasiswa sudah bayar",
                "total_mahasiswa": hasil.total_mahasiswa,
                "mahasiswa_sudah_bayar": hasil.mahasiswa_sudah_bayar,
                "tunggakan_lebih_2_bulan_count": hasil.tunggakan_lebih_2_bulan_count,
            },
            "top_10_tunggakan": [
                {
                    "nim": item.nim,
                    "nama": item.nama,
                    "total_tunggakan": f"{item.total_tunggakan:.2f}",
                    "total_tunggakan_formatted": format_rupiah(
                        item.total_tunggakan
                    ),
                    "tanggal_tertua": item.tanggal_tertua,
                    "hari_tunggakan": item.hari_tunggakan,
                }
                for item in hasil.top_10_tunggakan
            ],
            "rekomendasi": list(hasil.rekomendasi),
            "narasi_ai": narasi,
        }

    def analyze_from_db(
        self, db: Session, as_of: date | None = None
    ) -> dict[str, Any]:
        """Mengekspor data transaksi keuangan DB menjadi CSV lalu menghasilkan laporan JSON."""
        csv_text = BillingService(db).export_payment_csv()
        rows = db.execute(
            select(CalonMahasiswa.nim, CalonMahasiswa.nama_lengkap).where(
                CalonMahasiswa.nim.is_not(None)
            )
        ).all()
        nama_by_nim = {str(nim): str(nama) for nim, nama in rows if nim}
        return self.analyze_csv(csv_text, as_of=as_of, nama_by_nim=nama_by_nim)

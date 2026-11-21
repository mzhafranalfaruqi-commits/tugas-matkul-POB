"""Skema Pydantic v2 untuk Modul Keuangan (SPP), Webhook, Dashboard, Scheduler, & AI Report."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.keuangan import BillingStatus, PaymentStatus


class PaymentMethodOut(BaseModel):
    """DTO metode pembayaran SPP yang tersedia di sistem."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    provider: str
    is_active: bool


class PaymentOut(BaseModel):
    """DTO satu transaksi pembayaran SPP."""

    id: int
    billing_id: int
    payment_method_id: int
    method_code: str
    method_name: str
    transaction_id: str
    amount: str
    status: PaymentStatus
    source: str
    paid_at: datetime
    notes: str | None = None
    receipt_sent: bool


class BillingOut(BaseModel):
    """DTO tagihan SPP mahasiswa per semester beserta sisa dan daftar pembayaran."""

    id: int
    nim: str
    nama_lengkap: str | None = None
    program_studi: str | None = None
    semester: str
    amount: str
    denda: str
    total: str
    paid_amount: str
    remaining: str
    due_date: date
    status: BillingStatus
    reminder_count: int
    last_reminder_at: datetime | None = None
    krs_blocked: bool
    payments: list[PaymentOut] = Field(default_factory=list)


class GenerateBillingRequest(BaseModel):
    """Payload permintaan generate tagihan SPP massal per semester."""

    semester: str = Field(min_length=5, max_length=5, pattern=r"^\d{5}$")
    semester_start: date | None = None


class GenerateBillingOut(BaseModel):
    """Ringkasan hasil generate tagihan SPP massal."""

    semester: str
    due_date: date
    created_count: int
    skipped_count: int
    billings: list[BillingOut]


class ManualPaymentRequest(BaseModel):
    """Payload pencatatan pembayaran SPP manual oleh admin/keuangan."""

    billing_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0)
    method_code: str = Field(min_length=1, max_length=30)
    transaction_id: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)


class PaymentActionOut(BaseModel):
    """Respons hasil pemrosesan pembayaran manual maupun cicilan."""

    idempotent: bool
    payment: PaymentOut
    billing: BillingOut
    receipt_sent: bool


class WebhookPaymentIn(BaseModel):
    """Payload notifikasi webhook dari payment gateway (simulasi)."""

    transaction_id: str = Field(min_length=1, max_length=100)
    billing_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0)
    status: str = Field(min_length=1, max_length=30)
    method: str = Field(default="VA_BCA", min_length=1, max_length=30)
    notes: str | None = Field(default=None, max_length=500)


class WebhookPaymentOut(BaseModel):
    """Respons endpoint webhook payment gateway."""

    ok: bool
    action: str
    transaction_id: str
    billing_id: int
    billing_status: BillingStatus
    paid_amount: str
    remaining: str
    receipt_sent: bool


class WebhookSignPreviewOut(BaseModel):
    """Respons preview HMAC signature untuk simulasi webhook di dashboard."""

    header_name: str
    signature: str
    payload_json: str


class LateFeeRequest(BaseModel):
    """Payload opsional perhitungan denda keterlambatan per tanggal referensi."""

    as_of: date | None = None
    semester: str | None = Field(
        default=None, min_length=5, max_length=5, pattern=r"^\d{5}$"
    )


class LateFeeOut(BaseModel):
    """Hasil kalkulasi denda keterlambatan batch."""

    as_of: date
    updated_count: int
    total_denda_ditambahkan: str


class ReminderOut(BaseModel):
    """Hasil pengiriman reminder tunggakan SPP otomatis/manual."""

    as_of: date
    reminded_count: int
    nims: list[str]


class MahasiswaKeuanganOut(BaseModel):
    """Ringkasan kondisi tagihan dan pembayaran SPP per mahasiswa."""

    nim: str
    nama_lengkap: str
    program_studi: str
    total_tagihan: str
    sudah_bayar: str
    sisa: str
    status_ringkas: str
    krs_blocked: bool
    billings: list[BillingOut]


class ProdiCollectionRateOut(BaseModel):
    """Statistik collection rate pembayaran SPP per program studi."""

    kode_prodi: str
    nama_prodi: str
    total_mahasiswa: int
    mahasiswa_lunas: int
    total_tagihan: str
    total_terbayar: str
    collection_rate_persen: str


class MonthlyPaymentPointOut(BaseModel):
    """Titik data grafik pemasukan pembayaran SPP per bulan (YYYY-MM)."""

    bulan: str
    total_pembayaran: str
    jumlah_transaksi: int


class DashboardRingkasanOut(BaseModel):
    """Kartu KPI ringkasan keuangan institusi secara keseluruhan."""

    total_tagihan: str
    total_terbayar: str
    total_tunggakan: str
    collection_rate_persen: str
    jumlah_billing: int
    jumlah_paid: int
    jumlah_partial: int
    jumlah_unpaid: int
    jumlah_overdue: int
    jumlah_krs_blocked: int


class DashboardKeuanganOut(BaseModel):
    """Payload lengkap dashboard keuangan real-time (mahasiswa, prodi, grafik bulanan)."""

    generated_at: datetime
    ringkasan: DashboardRingkasanOut
    per_mahasiswa: list[MahasiswaKeuanganOut]
    per_program_studi: list[ProdiCollectionRateOut]
    grafik_bulanan: list[MonthlyPaymentPointOut]


class AIReportCSVRequest(BaseModel):
    """Payload input CSV langsung untuk menghasilkan AI Financial Insights."""

    csv_data: str = Field(min_length=1)
    as_of: date | None = None


class AIReportTopTunggakanOut(BaseModel):
    """Satu entri mahasiswa pada daftar Top 10 tunggakan terbesar."""

    nim: str
    nama: str | None = None
    total_tunggakan: str
    total_tunggakan_formatted: str
    tanggal_tertua: date
    hari_tunggakan: int


class AIReportRingkasanOut(BaseModel):
    """Ringkasan angka kunci laporan keuangan AI."""

    total_revenue_bulan_ini: str
    total_revenue_bulan_ini_formatted: str
    collection_rate_persen: str
    collection_rate_label: str
    total_mahasiswa: int
    mahasiswa_sudah_bayar: int
    tunggakan_lebih_2_bulan_count: int


class AIReportOut(BaseModel):
    """Format output JSON AI Financial Insights untuk dashboard frontend."""

    periode_bulan: str
    ringkasan: AIReportRingkasanOut
    top_10_tunggakan: list[AIReportTopTunggakanOut]
    rekomendasi: list[str]
    narasi_ai: str


class SchedulerJobOut(BaseModel):
    """Informasi satu scheduled cron job APScheduler."""

    id: str
    name: str
    trigger: str
    next_run_time: datetime | None = None


class SchedulerStatusOut(BaseModel):
    """Status runtime APScheduler beserta daftar job terdaftar."""

    running: bool
    timezone: str
    jobs: list[SchedulerJobOut]


class EmailReceiptOut(BaseModel):
    """Catatan email receipt atau reminder yang dikirim oleh sistem."""

    id: str
    jenis: str
    nim: str
    penerima_email: str
    subjek: str
    isi_ringkas: str
    sent_at: datetime

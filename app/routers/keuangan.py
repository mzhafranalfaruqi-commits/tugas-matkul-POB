"""Router FastAPI untuk Modul Keuangan (SPP), Webhook Payment Gateway, Dashboard, Scheduler, & AI Report."""

from datetime import date
from decimal import Decimal
import json
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain.keuangan import bulatkan_uang
from app.models.keuangan import Billing, BillingStatus, Payment
from app.schemas.keuangan import (
    AIReportCSVRequest,
    AIReportOut,
    BillingOut,
    DashboardKeuanganOut,
    EmailReceiptOut,
    GenerateBillingOut,
    GenerateBillingRequest,
    LateFeeOut,
    LateFeeRequest,
    MahasiswaKeuanganOut,
    ManualPaymentRequest,
    PaymentActionOut,
    PaymentMethodOut,
    PaymentOut,
    ReminderOut,
    SchedulerJobOut,
    SchedulerStatusOut,
    WebhookPaymentIn,
    WebhookPaymentOut,
    WebhookSignPreviewOut,
)
from app.services.billing_service import (
    BillingService,
    compute_webhook_signature,
    get_email_receipt_sender,
)
from app.services.financial_ai import FinancialReportService
from app.services.scheduler import get_billing_scheduler

_DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "keuangan_dashboard.html"
)

_STATUS_TUNGGAKAN = (
    BillingStatus.unpaid,
    BillingStatus.partial,
    BillingStatus.overdue,
)

router = APIRouter(prefix="/api/keuangan", tags=["Keuangan"])


def _to_payment_out(p: Payment) -> PaymentOut:
    """Mengubah entitas ORM Payment menjadi DTO PaymentOut."""
    method_code = p.payment_method.code if p.payment_method is not None else "-"
    method_name = p.payment_method.name if p.payment_method is not None else "-"
    return PaymentOut(
        id=p.id,
        billing_id=p.billing_id,
        payment_method_id=p.payment_method_id,
        method_code=method_code,
        method_name=method_name,
        transaction_id=p.transaction_id,
        amount=f"{bulatkan_uang(Decimal(p.amount)):.2f}",
        status=p.status,
        source=p.source,
        paid_at=p.paid_at,
        notes=p.notes,
        receipt_sent=p.receipt_sent,
    )


def _to_billing_out(b: Billing) -> BillingOut:
    """Mengubah entitas ORM Billing beserta pembayaran terkait menjadi DTO BillingOut."""
    nama_lengkap = b.mahasiswa.nama_lengkap if b.mahasiswa is not None else None
    prodi_nama = (
        b.mahasiswa.program_studi.nama
        if b.mahasiswa is not None and b.mahasiswa.program_studi is not None
        else None
    )
    return BillingOut(
        id=b.id,
        nim=b.nim,
        nama_lengkap=nama_lengkap,
        program_studi=prodi_nama,
        semester=b.semester,
        amount=f"{bulatkan_uang(Decimal(b.amount)):.2f}",
        denda=f"{bulatkan_uang(Decimal(b.denda)):.2f}",
        total=f"{b.total:.2f}",
        paid_amount=f"{bulatkan_uang(Decimal(b.paid_amount)):.2f}",
        remaining=f"{b.remaining:.2f}",
        due_date=b.due_date,
        status=b.status,
        reminder_count=b.reminder_count,
        last_reminder_at=b.last_reminder_at,
        krs_blocked=b.status in _STATUS_TUNGGAKAN,
        payments=[_to_payment_out(p) for p in b.payments],
    )


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Halaman Dashboard Keuangan (SPP), Grafik, Simulator Webhook, & AI Report",
    responses={200: {"description": "Halaman HTML Dashboard Keuangan SEVIMA-Mini"}},
)
def keuangan_dashboard_ui() -> HTMLResponse:
    """Menyajikan antarmuka web real-time Modul Keuangan (SPP)."""
    return HTMLResponse(content=_DASHBOARD_TEMPLATE.read_text(encoding="utf-8"))


@router.get(
    "/dashboard/data",
    response_model=DashboardKeuanganOut,
    summary="Data JSON real-time Dashboard Keuangan (per mahasiswa, prodi, & bulanan)",
    responses={200: {"description": "Ringkasan agregasi keuangan real-time"}},
)
def get_dashboard_data(
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> DashboardKeuanganOut:
    """Mengembalikan data dashboard keuangan real-time untuk frontend."""
    raw = BillingService(db).get_dashboard_data(as_of=as_of)
    per_mahasiswa = [
        MahasiswaKeuanganOut(
            nim=item["nim"],
            nama_lengkap=item["nama_lengkap"],
            program_studi=item["program_studi"],
            total_tagihan=item["total_tagihan"],
            sudah_bayar=item["sudah_bayar"],
            sisa=item["sisa"],
            status_ringkas=item["status_ringkas"],
            krs_blocked=item["krs_blocked"],
            billings=[_to_billing_out(b) for b in item["billings"]],
        )
        for item in raw["per_mahasiswa"]
    ]
    return DashboardKeuanganOut(
        generated_at=raw["generated_at"],
        ringkasan=raw["ringkasan"],
        per_mahasiswa=per_mahasiswa,
        per_program_studi=raw["per_program_studi"],
        grafik_bulanan=raw["grafik_bulanan"],
    )


@router.get(
    "/payment-methods",
    response_model=list[PaymentMethodOut],
    summary="Daftar metode pembayaran SPP yang tersedia",
    responses={200: {"description": "Daftar master metode pembayaran"}},
)
def list_payment_methods(
    db: Session = Depends(get_db),
) -> list[PaymentMethodOut]:
    """Mengembalikan seluruh metode pembayaran terdaftar."""
    methods = BillingService(db).list_payment_methods()
    return [PaymentMethodOut.model_validate(m) for m in methods]


@router.get(
    "/billings",
    response_model=list[BillingOut],
    summary="Daftar tagihan SPP dengan filter opsional NIM, semester, dan status",
    responses={200: {"description": "Daftar tagihan SPP beserta rincian pembayaran"}},
)
def list_billings(
    nim: str | None = Query(default=None),
    semester: str | None = Query(default=None, min_length=5, max_length=5),
    status_filter: BillingStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[BillingOut]:
    """Mengambil daftar tagihan SPP mahasiswa sesuai kriteria filter."""
    rows = BillingService(db).list_billings(
        nim=nim, semester=semester, status=status_filter
    )
    return [_to_billing_out(b) for b in rows]


@router.get(
    "/billings/{billing_id}",
    response_model=BillingOut,
    summary="Detail satu tagihan SPP beserta seluruh riwayat pembayarannya",
    responses={
        200: {"description": "Detail tagihan SPP ditemukan"},
        404: {"description": "Tagihan dengan ID terkait tidak ditemukan"},
    },
)
def get_billing(
    billing_id: int,
    db: Session = Depends(get_db),
) -> BillingOut:
    """Mengembalikan detail tagihan berdasarkan billing_id."""
    billing = BillingService(db).get_billing(billing_id)
    return _to_billing_out(billing)


@router.get(
    "/mahasiswa/{nim}",
    response_model=MahasiswaKeuanganOut,
    summary="Ringkasan total tagihan, sudah bayar, sisa, dan blokir KRS mahasiswa",
    responses={
        200: {"description": "Ringkasan keuangan mahasiswa ditemukan"},
        404: {"description": "Mahasiswa ber-NIM tidak ditemukan"},
    },
)
def get_mahasiswa_keuangan(
    nim: str,
    db: Session = Depends(get_db),
) -> MahasiswaKeuanganOut:
    """Mengambil ringkasan posisi keuangan SPP satu mahasiswa."""
    data = BillingService(db).get_mahasiswa_summary(nim)
    return MahasiswaKeuanganOut(
        nim=data["nim"],
        nama_lengkap=data["nama_lengkap"],
        program_studi=data["program_studi"],
        total_tagihan=data["total_tagihan"],
        sudah_bayar=data["sudah_bayar"],
        sisa=data["sisa"],
        status_ringkas=data["status_ringkas"],
        krs_blocked=data["krs_blocked"],
        billings=[_to_billing_out(b) for b in data["billings"]],
    )


@router.post(
    "/billing/generate",
    response_model=GenerateBillingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate tagihan SPP awal semester untuk semua mahasiswa aktif",
    responses={
        201: {"description": "Tagihan SPP semester berhasil dibuat secara idempoten"},
        422: {"description": "Parameter semester tidak valid"},
    },
)
def generate_billing(
    data_in: GenerateBillingRequest,
    db: Session = Depends(get_db),
) -> GenerateBillingOut:
    """Membuat tagihan SPP per semester sesuai tarif program studi dan due date +14 hari."""
    res = BillingService(db).generate_billing(
        semester=data_in.semester,
        semester_start=data_in.semester_start,
    )
    return GenerateBillingOut(
        semester=res.semester,
        due_date=res.due_date,
        created_count=res.created_count,
        skipped_count=res.skipped_count,
        billings=[_to_billing_out(b) for b in res.billings],
    )


@router.post(
    "/payments",
    response_model=PaymentActionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Catat pembayaran SPP manual (penuh atau cicilan partial)",
    responses={
        201: {"description": "Pembayaran berhasil dicatat dan status billing diperbarui"},
        400: {"description": "Nominal tidak valid atau metode pembayaran tidak aktif"},
        404: {"description": "Tagihan SPP tidak ditemukan"},
        409: {"description": "Tagihan sudah lunas atau transaction_id bentrok"},
        422: {"description": "Format payload permintaan tidak valid"},
    },
)
def record_manual_payment(
    data_in: ManualPaymentRequest,
    db: Session = Depends(get_db),
) -> PaymentActionOut:
    """Mencatat pembayaran manual di loket/admin dalam satu transaksi atomik."""
    res = BillingService(db).process_payment(
        billing_id=data_in.billing_id,
        amount=data_in.amount,
        method_code=data_in.method_code,
        transaction_id=data_in.transaction_id,
        source="manual",
        notes=data_in.notes,
        send_receipt=True,
    )
    return PaymentActionOut(
        idempotent=res.idempotent,
        payment=_to_payment_out(res.payment),
        billing=_to_billing_out(res.billing),
        receipt_sent=res.receipt_sent,
    )


@router.post(
    "/billing/calculate-late-fees",
    response_model=LateFeeOut,
    summary="Hitung denda keterlambatan dan tandai tagihan jatuh tempo menjadi overdue",
    responses={200: {"description": "Denda keterlambatan berhasil dihitung ulang"}},
)
def calculate_late_fees(
    data_in: LateFeeRequest = Body(default_factory=LateFeeRequest),
    db: Session = Depends(get_db),
) -> LateFeeOut:
    """Menghitung denda harian (0.5%/hari, maks 10%) untuk tagihan melewati due_date."""
    res = BillingService(db).calculate_late_fees(
        as_of=data_in.as_of,
        semester=data_in.semester,
    )
    return LateFeeOut(
        as_of=res.as_of,
        updated_count=res.updated_count,
        total_denda_ditambahkan=f"{res.total_denda_ditambahkan:.2f}",
    )


@router.post(
    "/billing/send-reminders",
    response_model=ReminderOut,
    summary="Kirim reminder tunggakan SPP ke mahasiswa terlambat atau mendekati jatuh tempo",
    responses={200: {"description": "Reminder tunggakan berhasil dicatat dan dikirim"}},
)
def send_overdue_reminders(
    data_in: LateFeeRequest = Body(default_factory=LateFeeRequest),
    db: Session = Depends(get_db),
) -> ReminderOut:
    """Menjalankan kalkulasi denda lalu mengirim reminder notifikasi & email."""
    res = BillingService(db).send_overdue_reminders(as_of=data_in.as_of)
    return ReminderOut(
        as_of=res.as_of,
        reminded_count=res.reminded_count,
        nims=res.nims,
    )


@router.post(
    "/webhook/payment",
    response_model=WebhookPaymentOut,
    summary="Endpoint webhook notifikasi pembayaran dari payment gateway (HMAC-SHA256)",
    responses={
        200: {"description": "Notifikasi webhook diterima, status billing diperbarui, & receipt terkirim"},
        400: {"description": "Payload JSON tidak valid atau metode pembayaran/status tidak dikenali"},
        401: {"description": "Header X-Webhook-Signature hilang atau tidak valid"},
        404: {"description": "Tagihan SPP terkait tidak ditemukan"},
        409: {"description": "Konflik idempotency transaction_id atau tagihan sudah lunas"},
    },
)
async def payment_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(
        default=None, alias="X-Webhook-Signature"
    ),
    db: Session = Depends(get_db),
) -> WebhookPaymentOut:
    """Menerima notifikasi webhook dari payment gateway, memverifikasi HMAC, lalu mencatat bayar."""
    raw_body = await request.body()
    res = BillingService(db).handle_webhook(raw_body, x_webhook_signature)
    return WebhookPaymentOut(
        ok=res.ok,
        action=res.action,
        transaction_id=res.transaction_id,
        billing_id=res.billing_id,
        billing_status=res.billing_status,
        paid_amount=f"{res.paid_amount:.2f}",
        remaining=f"{res.remaining:.2f}",
        receipt_sent=res.receipt_sent,
    )


@router.post(
    "/webhook/sign-preview",
    response_model=WebhookSignPreviewOut,
    summary="Helper simulator dev untuk menandatangani payload JSON webhook (HMAC-SHA256)",
    responses={200: {"description": "Payload JSON kanonik beserta signature HMAC-SHA256"}},
)
def preview_webhook_signature(
    data_in: WebhookPaymentIn,
) -> WebhookSignPreviewOut:
    """Menghasilkan HMAC-SHA256 signature untuk keperluan simulasi dashboard UI."""
    payload_json = json.dumps(
        data_in.model_dump(mode="json"),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    signature = compute_webhook_signature(payload_json.encode("utf-8"))
    return WebhookSignPreviewOut(
        header_name="X-Webhook-Signature",
        signature=signature,
        payload_json=payload_json,
    )


@router.get(
    "/ai-report",
    response_model=AIReportOut,
    summary="Generate AI Financial Insights dalam format JSON dari data keuangan live database",
    responses={200: {"description": "Laporan ringkas keuangan JSON beserta top 10 tunggakan"}},
)
def get_ai_financial_report(
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AIReportOut:
    """Menganalisis data transaksi pembayaran aktual di database menjadi insight keuangan JSON."""
    report = FinancialReportService().analyze_from_db(db, as_of=as_of)
    return AIReportOut.model_validate(report)


@router.post(
    "/ai-report/csv",
    response_model=AIReportOut,
    summary="Analisis data pembayaran CSV (nim,jumlah,tanggal,status) menjadi JSON insights",
    responses={
        200: {"description": "Hasil analisis keuangan CSV dalam format JSON dashboard"},
        400: {"description": "Struktur header atau isi baris CSV tidak valid"},
        422: {"description": "Payload permintaan tidak valid"},
    },
)
def analyze_csv_financial_report(
    data_in: AIReportCSVRequest,
) -> AIReportOut:
    """Menerima teks CSV payment_data dan mengembalikan JSON insights lengkap."""
    report = FinancialReportService().analyze_csv(
        data_in.csv_data, as_of=data_in.as_of
    )
    return AIReportOut.model_validate(report)


@router.get(
    "/scheduler/jobs",
    response_model=SchedulerStatusOut,
    summary="Daftar cron job APScheduler aktif (generate billing semester & reminder harian)",
    responses={200: {"description": "Status scheduler dan daftar job terdaftar"}},
)
def list_scheduler_jobs() -> SchedulerStatusOut:
    """Menampilkan status APScheduler serta jadwal cron yang terdaftar."""
    scheduler = get_billing_scheduler()
    return SchedulerStatusOut(
        running=scheduler.is_running,
        timezone=scheduler.timezone,
        jobs=[SchedulerJobOut(**job) for job in scheduler.list_jobs()],
    )


@router.get(
    "/receipts",
    response_model=list[EmailReceiptOut],
    summary="Log email kuitansi pembayaran dan reminder yang dikirim oleh sistem",
    responses={200: {"description": "Daftar riwayat email receipt/reminder terbaru"}},
)
def list_email_receipts() -> list[EmailReceiptOut]:
    """Mengembalikan riwayat pengiriman email receipt dan pengingat tunggakan."""
    records = get_email_receipt_sender().list_records()
    return [
        EmailReceiptOut(
            id=r.id,
            jenis=r.jenis,
            nim=r.nim,
            penerima_email=r.penerima_email,
            subjek=r.subjek,
            isi_ringkas=r.isi_ringkas,
            sent_at=r.sent_at,
        )
        for r in records
    ]

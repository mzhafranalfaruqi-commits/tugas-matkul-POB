"""Unit, integration, webhook, scheduler, KRS-blocking, & AI report tests untuk Modul Keuangan (SPP)."""

from collections.abc import Generator
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.keuangan import (
    analisis_keuangan_csv,
    format_rupiah,
    hitung_denda_keterlambatan,
    hitung_due_date,
    tentukan_semester_aktif,
    tentukan_tarif_spp,
)
from app.models import (
    Billing,
    BillingStatus,
    CalonMahasiswa,
    JalurMasuk,
    KRS,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    Payment,
    PaymentMethod,
    PaymentStatus,
    ProgramStudi,
    StatusPMB,
)
from app.services.billing_service import (
    BillingService,
    EmailReceiptRecord,
    compute_webhook_signature,
    get_email_receipt_sender,
)
from app.services.exceptions import (
    BillingNotFoundError,
    BillingValidationError,
    KRSBillingBlockedError,
    PaymentConflictError,
)
from app.services.financial_ai import FinancialReportService
from app.services.krs_manager import KRSManager
from app.services.scheduler import BillingScheduler
from seed import (
    seed_data,
    seed_jadwal_data,
    seed_keuangan_data,
    seed_krs_data,
    seed_nilai_demo_data,
    seed_transkrip_demo_data,
)


@pytest.fixture(autouse=True)
def _reset_email_log() -> Generator[None, None, None]:
    """Memastikan log email receipt/reminder bersih antar pengujian."""
    sender = get_email_receipt_sender()
    sender.reset()
    yield
    sender.reset()


def _setup_metode_bayar(db: Session) -> dict[str, PaymentMethod]:
    """Memastikan metode pembayaran dasar tersedia di database uji."""
    items = [
        ("VA_BCA", "Virtual Account BCA", "gateway_va", True),
        ("QRIS", "QRIS Nasional", "gateway_qris", True),
        ("TUNAI", "Loket Kampus", "manual", True),
        ("LEGACY", "Metode Nonaktif", "manual", False),
    ]
    hasil: dict[str, PaymentMethod] = {}
    for code, name, provider, active in items:
        pm = db.execute(
            select(PaymentMethod).where(PaymentMethod.code == code)
        ).scalar_one_or_none()
        if pm is None:
            pm = PaymentMethod(
                code=code, name=name, provider=provider, is_active=active
            )
            db.add(pm)
        hasil[code] = pm
    db.flush()
    return hasil


def _buat_mahasiswa(
    db: Session,
    *,
    nim: str | None,
    nama: str,
    email: str,
    prodi_id: int,
    status_pmb: StatusPMB = StatusPMB.approved,
) -> CalonMahasiswa:
    """Helper membuat record CalonMahasiswa pada skenario pengujian keuangan."""
    jalur = db.execute(select(JalurMasuk).limit(1)).scalar_one()
    mhs = CalonMahasiswa(
        nama_lengkap=nama,
        email=email,
        phone="081234567890",
        tanggal_lahir=date(2006, 1, 10),
        alamat="Jl. Merdeka No. 1, Bandung",
        program_studi_id=prodi_id,
        jalur_masuk_id=jalur.id,
        status=status_pmb,
        nim=nim,
        approved_at=datetime.now(timezone.utc) if status_pmb == StatusPMB.approved else None,
    )
    db.add(mhs)
    db.flush()
    return mhs


class _BrokenEmailSender:
    """Stub email sender yang selalu gagal untuk menguji isolasi pasca-commit."""

    def send_receipt(self, **_kwargs) -> EmailReceiptRecord:
        raise RuntimeError("SMTP gateway tidak dapat dihubungi")

    def send_reminder(self, **_kwargs) -> EmailReceiptRecord:
        raise RuntimeError("SMTP gateway tidak dapat dihubungi")

    def list_records(self) -> list[EmailReceiptRecord]:
        return []


def test_domain_murni_keuangan_tarif_denda_semester_format() -> None:
    """Uji fungsi murni tarif prodi, due date +14 hari, denda capped 10%, dan format Rupiah."""
    assert tentukan_tarif_spp("Teknik Informatika", "Fakultas Teknik") == Decimal("5000000.00")
    assert tentukan_tarif_spp("Ekonomi Pembangunan", "Fakultas Ekonomi") == Decimal("4000000.00")
    assert tentukan_tarif_spp("Akuntansi") == Decimal("4000000.00")
    assert tentukan_tarif_spp("Sistem Informasi", "Fakultas Ilmu Komputer") == Decimal("4500000.00")

    assert hitung_due_date(date(2026, 8, 1)) == date(2026, 8, 15)
    assert tentukan_semester_aktif(date(2026, 8, 1)) == "20261"
    assert tentukan_semester_aktif(date(2027, 1, 15)) == "20261"
    assert tentukan_semester_aktif(date(2027, 2, 1)) == "20262"

    assert format_rupiah(Decimal("5000000.00")) == "Rp 5.000.000"
    assert format_rupiah(Decimal("-1250000.50")) == "-Rp 1.250.000,50"

    due = date(2026, 8, 15)
    assert hitung_denda_keterlambatan(Decimal("5000000"), due, date(2026, 8, 15)) == Decimal("0.00")
    # 10 hari telat * 0.5%/hari = 5% * 5jt = 250.000
    assert hitung_denda_keterlambatan(Decimal("5000000"), due, date(2026, 8, 25)) == Decimal("250000.00")
    # 40 hari telat * 0.5%/hari = 20% -> terpotong batas maksimal 10% = 500.000
    assert hitung_denda_keterlambatan(Decimal("5000000"), due, date(2026, 9, 24)) == Decimal("500000.00")

    with pytest.raises(ValueError):
        hitung_denda_keterlambatan(Decimal("0"), due, date(2026, 9, 1))
    with pytest.raises(ValueError):
        hitung_denda_keterlambatan(Decimal("5000000"), due, date(2026, 9, 1), tarif_harian_persen=Decimal("-0.01"))


def test_keuangan_db_constraints(db_session: Session) -> None:
    """Verifikasi seluruh CHECK, UNIQUE, dan FK constraint pada tabel keuangan."""
    _setup_metode_bayar(db_session)
    _buat_mahasiswa(
        db_session, nim="2025001-0100", nama="Uji Constraint", email="uji@example.com", prodi_id=1
    )
    db_session.commit()

    # 1. Duplicate payment_method.code ditolak UNIQUE
    with pytest.raises(IntegrityError):
        db_session.add(PaymentMethod(code="VA_BCA", name="Duplikat", provider="manual"))
        db_session.commit()
    db_session.rollback()

    # 2. CHECK billing.amount > 0
    with pytest.raises(IntegrityError):
        db_session.add(
            Billing(
                nim="2025001-0100",
                semester="20261",
                amount=Decimal("0.00"),
                due_date=date(2026, 8, 15),
                status=BillingStatus.unpaid,
            )
        )
        db_session.commit()
    db_session.rollback()

    # 3. CHECK billing.denda >= 0
    with pytest.raises(IntegrityError):
        db_session.add(
            Billing(
                nim="2025001-0100",
                semester="20261",
                amount=Decimal("5000000.00"),
                denda=Decimal("-100.00"),
                due_date=date(2026, 8, 15),
                status=BillingStatus.unpaid,
            )
        )
        db_session.commit()
    db_session.rollback()

    # 4. UNIQUE (nim, semester) pada billing
    b_ok = Billing(
        nim="2025001-0100",
        semester="20261",
        amount=Decimal("5000000.00"),
        due_date=date(2026, 8, 15),
        status=BillingStatus.unpaid,
    )
    db_session.add(b_ok)
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.add(
            Billing(
                nim="2025001-0100",
                semester="20261",
                amount=Decimal("4000000.00"),
                due_date=date(2026, 8, 15),
                status=BillingStatus.unpaid,
            )
        )
        db_session.commit()
    db_session.rollback()

    # 5. CHECK payment.source valid dan UNIQUE transaction_id
    pm = db_session.execute(
        select(PaymentMethod).where(PaymentMethod.code == "VA_BCA")
    ).scalar_one()
    with pytest.raises(IntegrityError):
        db_session.add(
            Payment(
                billing_id=b_ok.id,
                payment_method_id=pm.id,
                transaction_id="TX-BAD-SRC",
                amount=Decimal("1000.00"),
                source="unknown",
            )
        )
        db_session.commit()
    db_session.rollback()

    db_session.add(
        Payment(
            billing_id=b_ok.id,
            payment_method_id=pm.id,
            transaction_id="TX-UNIQ-1",
            amount=Decimal("1000.00"),
            source="manual",
        )
    )
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.add(
            Payment(
                billing_id=b_ok.id,
                payment_method_id=pm.id,
                transaction_id="TX-UNIQ-1",
                amount=Decimal("1000.00"),
                source="webhook",
            )
        )
        db_session.commit()
    db_session.rollback()


def test_generate_billing_tarif_prodi_due_date_dan_idempoten(
    db_session: Session,
) -> None:
    """Generate billing membuat tagihan per prodi (Teknik 5jt, Ekonomi 4jt, SI 4.5jt), +14 hari, idempoten."""
    prodi_ekonomi = ProgramStudi(
        kode="004", nama="Ekonomi Pembangunan", fakultas="Fakultas Ekonomi"
    )
    db_session.add(prodi_ekonomi)
    db_session.flush()

    _buat_mahasiswa(
        db_session, nim="2025001-0011", nama="Mhs Teknik", email="tek@example.com", prodi_id=1
    )
    _buat_mahasiswa(
        db_session, nim="2025002-0011", nama="Mhs SI", email="si@example.com", prodi_id=2
    )
    _buat_mahasiswa(
        db_session, nim="2025004-0011", nama="Mhs Ekonomi", email="eko@example.com", prodi_id=prodi_ekonomi.id
    )
    # Pendaftar pending/rejected tidak boleh dibuatkan tagihan
    _buat_mahasiswa(
        db_session,
        nim=None,
        nama="Calon Pending",
        email="pending@example.com",
        prodi_id=1,
        status_pmb=StatusPMB.pending,
    )
    db_session.commit()

    svc = BillingService(db_session)
    with pytest.raises(BillingValidationError):
        svc.generate_billing(semester="BAD")

    res1 = svc.generate_billing(semester="20261", semester_start=date(2026, 8, 1))
    assert res1.created_count == 3
    assert res1.skipped_count == 0
    assert res1.due_date == date(2026, 8, 15)

    by_nim = {b.nim: b for b in res1.billings}
    assert by_nim["2025001-0011"].amount == Decimal("5000000.00")
    assert by_nim["2025002-0011"].amount == Decimal("4500000.00")
    assert by_nim["2025004-0011"].amount == Decimal("4000000.00")
    assert all(b.status == BillingStatus.unpaid for b in res1.billings)

    # Jalankan ulang untuk semester sama -> idempoten (0 dibuat, 3 dilewati)
    res2 = svc.generate_billing(semester="20261", semester_start=date(2026, 8, 1))
    assert res2.created_count == 0
    assert res2.skipped_count == 3


def test_process_payment_partial_paid_atomicity_dan_isolasi_email(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uji alur partial -> paid, idempotency tx_id, konflik 409, rollback atomik, & tahan error email."""
    _setup_metode_bayar(db_session)
    _buat_mahasiswa(
        db_session, nim="2025001-0020", nama="Budi Cicilan", email="cicil@example.com", prodi_id=1
    )
    db_session.commit()

    svc = BillingService(db_session)
    gen = svc.generate_billing("20261", date(2026, 8, 1))
    billing = gen.billings[0]

    # Cicilan 1: 2.000.000 < 5.000.000 -> partial
    r1 = svc.process_payment(
        billing.id, Decimal("2000000.00"), "TUNAI", transaction_id="TX-CICIL-1"
    )
    assert r1.idempotent is False
    assert r1.billing.status == BillingStatus.partial
    assert r1.billing.paid_amount == Decimal("2000000.00")
    assert r1.billing.remaining == Decimal("3000000.00")
    assert r1.receipt_sent is True

    # Replay transaction_id sama persis -> idempotent, tidak menduplikasi pembayaran
    r1_dup = svc.process_payment(
        billing.id, Decimal("2000000.00"), "TUNAI", transaction_id="TX-CICIL-1"
    )
    assert r1_dup.idempotent is True
    assert r1_dup.billing.paid_amount == Decimal("2000000.00")

    # transaction_id sama dengan nominal beda -> 409 Conflict
    with pytest.raises(PaymentConflictError):
        svc.process_payment(
            billing.id, Decimal("1000000.00"), "TUNAI", transaction_id="TX-CICIL-1"
        )

    # Metode nonaktif / nominal 0 / billing tidak ada
    with pytest.raises(BillingValidationError):
        svc.process_payment(billing.id, Decimal("1000.00"), "LEGACY")
    with pytest.raises(BillingValidationError):
        svc.process_payment(billing.id, Decimal("0"), "TUNAI")
    with pytest.raises(BillingNotFoundError):
        svc.process_payment(999999, Decimal("1000.00"), "TUNAI")

    # Simulasi kegagalan commit saat pelunasan -> rollback penuh (paid_amount tetap 2jt)
    def _boom_commit() -> None:
        raise RuntimeError("Simulasi disk I/O gagal saat commit")

    monkeypatch.setattr(db_session, "commit", _boom_commit)
    with pytest.raises(RuntimeError, match="Simulasi disk I/O"):
        svc.process_payment(
            billing.id, Decimal("3000000.00"), "QRIS", transaction_id="TX-ROLLBACK"
        )
    monkeypatch.undo()

    billing_after_rb = svc.get_billing(billing.id)
    assert billing_after_rb.status == BillingStatus.partial
    assert billing_after_rb.paid_amount == Decimal("2000000.00")

    # Pelunasan dengan email sender mati tetap sukses commit pembayaran
    svc_broken_email = BillingService(db_session, email_sender=_BrokenEmailSender())
    r2 = svc_broken_email.process_payment(
        billing.id, Decimal("3000000.00"), "QRIS", transaction_id="TX-LUNAS-2"
    )
    assert r2.billing.status == BillingStatus.paid
    assert r2.billing.remaining == Decimal("0.00")
    assert r2.receipt_sent is False

    # Sudah lunas -> bayar lagi ditolak 409
    with pytest.raises(PaymentConflictError):
        svc.process_payment(billing.id, Decimal("100000.00"), "TUNAI")


def test_late_fee_dan_reminder_otomatis(db_session: Session) -> None:
    """Uji kalkulasi denda keterlambatan dan pengiriman reminder notifikasi + email."""
    _setup_metode_bayar(db_session)
    _buat_mahasiswa(
        db_session, nim="2025001-0030", nama="Telat Bayar", email="telat@example.com", prodi_id=1
    )
    db_session.commit()

    svc = BillingService(db_session)
    gen = svc.generate_billing("20261", date(2026, 8, 1))  # due_date = 2026-08-15
    bid = gen.billings[0].id

    # 10 hari setelah due date -> denda 250.000 & status overdue
    lf = svc.calculate_late_fees(as_of=date(2026, 8, 25))
    assert lf.updated_count == 1
    assert lf.total_denda_ditambahkan == Decimal("250000.00")

    rem = svc.send_overdue_reminders(as_of=date(2026, 8, 25))
    assert rem.reminded_count == 1
    assert rem.nims == ["2025001-0030"]

    b = svc.get_billing(bid)
    assert b.status == BillingStatus.overdue
    assert b.denda == Decimal("250000.00")
    assert b.total == Decimal("5250000.00")
    assert b.reminder_count == 1
    assert b.last_reminder_at is not None

    notifs = db_session.scalars(
        select(Notifikasi).where(Notifikasi.nim == "2025001-0030")
    ).all()
    assert len(notifs) == 1
    receipts = get_email_receipt_sender().list_records()
    assert len(receipts) == 1
    assert receipts[0].jenis == "reminder"


def test_webhook_payment_signature_idempotency_dan_krs_unblock(
    client: TestClient, db_session: Session
) -> None:
    """End-to-end: mahasiswa tunggakan diblokir KRS 403 -> bayar via webhook -> email receipt -> KRS 201 & submit 200."""
    _setup_metode_bayar(db_session)
    _buat_mahasiswa(
        db_session, nim="2025001-0040", nama="Mahasiswa Uji Webhook", email="wh@example.com", prodi_id=1
    )
    mk = MataKuliah(
        kode_mk="IF101",
        nama="Algoritma",
        sks=3,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(10, 30),
    )
    db_session.add(mk)
    db_session.commit()

    billing = BillingService(db_session).generate_billing("20261", date(2026, 8, 1)).billings[0]
    assert billing.status == BillingStatus.unpaid

    # 1. Validasi KRS dan tambah MK diblokir 403 saat unpaid
    val_res = client.get("/api/krs/2025001-0040/validate?semester=20261")
    assert val_res.status_code == 200
    assert val_res.json()["valid"] is False
    assert "tunggakan SPP" in val_res.json()["errors"][0]["message"]

    add_blocked = client.post(
        "/api/krs/2025001-0040/courses?semester=20261",
        json={"kode_mk": "IF101"},
    )
    assert add_blocked.status_code == 403

    # Cek juga blokir ketika status partial & submit KRS ketika ada tagihan baru
    svc = BillingService(db_session)
    svc.process_payment(billing.id, Decimal("2000000.00"), "VA_BCA", transaction_id="TX-PARTIAL")
    add_partial_blocked = client.post(
        "/api/krs/2025001-0040/courses?semester=20261",
        json={"kode_mk": "IF101"},
    )
    assert add_partial_blocked.status_code == 403

    # 2. Webhook tanpa / salah signature -> 401
    bad_wh = client.post(
        "/api/keuangan/webhook/payment",
        json={
            "transaction_id": "GW-TEST-1",
            "billing_id": billing.id,
            "amount": "3000000.00",
            "status": "paid",
            "method": "VA_BCA",
        },
        headers={"X-Webhook-Signature": "signature-palsu"},
    )
    assert bad_wh.status_code == 401

    # 3. Webhook JSON rusak -> 400
    raw_bad = b"{bukan-json"
    res_bad_json = client.post(
        "/api/keuangan/webhook/payment",
        content=raw_bad,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": compute_webhook_signature(raw_bad),
        },
    )
    assert res_bad_json.status_code == 400

    # 4. Webhook pending diabaikan aman (200) tanpa mengubah paid_amount
    pending_payload = {
        "transaction_id": "GW-PEND-1",
        "billing_id": billing.id,
        "amount": "3000000.00",
        "status": "pending",
        "method": "VA_BCA",
    }
    raw_pend = json.dumps(pending_payload).encode("utf-8")
    res_pend = client.post(
        "/api/keuangan/webhook/payment",
        content=raw_pend,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": compute_webhook_signature(raw_pend),
        },
    )
    assert res_pend.status_code == 200
    assert res_pend.json()["action"] == "ignored_pending"
    assert res_pend.json()["billing_status"] == "partial"

    # 5. Webhook paid dengan signature dari /webhook/sign-preview -> 200 OK & lunas + receipt terkirim
    paid_req = {
        "transaction_id": "GW-LUNAS-1",
        "billing_id": billing.id,
        "amount": "3000000.00",
        "status": "paid",
        "method": "VA_BCA",
    }
    preview = client.post("/api/keuangan/webhook/sign-preview", json=paid_req)
    assert preview.status_code == 200
    signed = preview.json()

    wh_ok = client.post(
        "/api/keuangan/webhook/payment",
        content=signed["payload_json"],
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signed['signature']}",
        },
    )
    assert wh_ok.status_code == 200
    body_ok = wh_ok.json()
    assert body_ok["ok"] is True
    assert body_ok["action"] == "processed"
    assert body_ok["billing_status"] == "paid"
    assert body_ok["paid_amount"] == "5000000.00"
    assert body_ok["remaining"] == "0.00"
    assert body_ok["receipt_sent"] is True

    # Replay webhook sama persis -> idempotent, tidak ganda email/nominal
    wh_dup = client.post(
        "/api/keuangan/webhook/payment",
        content=signed["payload_json"],
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": signed["signature"],
        },
    )
    assert wh_dup.status_code == 200
    assert wh_dup.json()["action"] == "idempotent"
    assert len(get_email_receipt_sender().list_records()) == 2  # 1 dari partial manual + 1 dari GW-LUNAS-1

    # 6. Setelah lunas, KRS langsung terbuka (add 201 & submit 200)
    add_ok = client.post(
        "/api/krs/2025001-0040/courses?semester=20261",
        json={"kode_mk": "IF101"},
    )
    assert add_ok.status_code == 201
    submit_ok = client.post("/api/krs/2025001-0040/submit?semester=20261")
    assert submit_ok.status_code == 200
    assert submit_ok.json()["status"] == "SUBMITTED"

    # 7. Uji submit_krs diblokir 403 ketika tagihan semester baru terbit setelah KRS DRAFT terisi
    gen_next = svc.generate_billing("20262", date(2027, 2, 1))
    assert gen_next.created_count == 1
    krs_next = KRS(nim="2025001-0040", semester="20262", status=KRSStatus.DRAFT)
    db_session.add(krs_next)
    db_session.commit()
    with pytest.raises(KRSBillingBlockedError):
        KRSManager(db_session, semester="20262").submit_krs("2025001-0040")


def test_dashboard_keuangan_realtime_dan_endpoints(
    client: TestClient, db_session: Session
) -> None:
    """Uji endpoint HTML dashboard, data real-time per mahasiswa/prodi/bulanan, & detail billing."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    seed_transkrip_demo_data(db_session)
    seed_keuangan_data(db_session)

    html_res = client.get("/api/keuangan/dashboard")
    assert html_res.status_code == 200
    assert "Dashboard Keuangan &amp; Pembayaran SPP" in html_res.text

    pm_res = client.get("/api/keuangan/payment-methods")
    assert pm_res.status_code == 200
    assert len(pm_res.json()) == 5

    dash1 = client.get("/api/keuangan/dashboard/data")
    assert dash1.status_code == 200
    d1 = dash1.json()
    assert d1["ringkasan"]["jumlah_billing"] == 10
    assert d1["ringkasan"]["jumlah_paid"] == 4
    assert d1["ringkasan"]["jumlah_partial"] == 2
    assert d1["ringkasan"]["jumlah_unpaid"] == 1
    assert d1["ringkasan"]["jumlah_overdue"] == 3
    assert len(d1["per_program_studi"]) == 4
    assert len(d1["grafik_bulanan"]) == 4

    # Cek posisi Maya Putri (2025004-0002) sebelum bayar
    maya_before = client.get("/api/keuangan/mahasiswa/2025004-0002")
    assert maya_before.status_code == 200
    assert maya_before.json()["status_ringkas"] == "unpaid"
    assert maya_before.json()["krs_blocked"] is True
    maya_bill_id = maya_before.json()["billings"][0]["id"]

    # Bayar manual lunas -> dashboard langsung terbarui real-time
    pay_res = client.post(
        "/api/keuangan/payments",
        json={
            "billing_id": maya_bill_id,
            "amount": "4000000.00",
            "method_code": "TUNAI",
            "notes": "Pelunasan loket",
        },
    )
    assert pay_res.status_code == 201
    assert pay_res.json()["billing"]["status"] == "paid"

    dash2 = client.get("/api/keuangan/dashboard/data").json()
    assert dash2["ringkasan"]["jumlah_paid"] == 5
    assert dash2["ringkasan"]["jumlah_unpaid"] == 0
    maya_after = client.get("/api/keuangan/mahasiswa/2025004-0002").json()
    assert maya_after["krs_blocked"] is False
    assert maya_after["sisa"] == "0.00"

    bill_detail = client.get(f"/api/keuangan/billings/{maya_bill_id}")
    assert bill_detail.status_code == 200
    assert bill_detail.json()["status"] == "paid"
    assert client.get("/api/keuangan/billings/999999").status_code == 404
    assert client.get("/api/keuangan/mahasiswa/0000000-0000").status_code == 404

    rec_res = client.get("/api/keuangan/receipts")
    assert rec_res.status_code == 200
    assert len(rec_res.json()) == 1


def test_ai_financial_report_csv_dan_live_db(
    client: TestClient, db_session: Session
) -> None:
    """Uji AI Financial Insights pada CSV (>10 mahasiswa, >2 bulan) & data DB live."""
    # Buat 12 mahasiswa menunggak (4 di antaranya > 60 hari) + 4 mahasiswa lunas
    baris_csv = [
        "nim,jumlah,tanggal,status",
        "2025001-0001,5000000,2026-11-05,paid",
        "2025001-0002,4000000,2026-11-10,paid",
        "2025001-0003,4500000,2026-10-12,lunas",
        "2025001-0004,2000000,2026-11-15,partial",
    ]
    for idx in range(1, 13):
        tgl = "2026-08-15" if idx <= 4 else "2026-10-25"
        status_row = "overdue" if idx <= 4 else "unpaid"
        nominal = 1_000_000 * idx
        baris_csv.append(f"2025999-{idx:04d},{nominal},{tgl},{status_row}")

    res = client.post(
        "/api/keuangan/ai-report/csv",
        json={"csv_data": "\n".join(baris_csv), "as_of": "2026-11-21"},
    )
    assert res.status_code == 200
    body = res.json()

    # Revenue November 2026 = 5jt + 4jt + 2jt = 11.000.000.00
    assert body["periode_bulan"] == "2026-11"
    assert body["ringkasan"]["total_revenue_bulan_ini"] == "11000000.00"
    assert body["ringkasan"]["total_revenue_bulan_ini_formatted"] == "Rp 11.000.000"
    # 3 dari 16 mahasiswa lunas penuh (3/16 = 18.75%)
    assert body["ringkasan"]["mahasiswa_sudah_bayar"] == 3
    assert body["ringkasan"]["total_mahasiswa"] == 16
    assert body["ringkasan"]["collection_rate_persen"] == "18.75"
    # Top 10 diurutkan dari tunggakan terbesar (12jt .. 3jt)
    assert len(body["top_10_tunggakan"]) == 10
    assert body["top_10_tunggakan"][0]["nim"] == "2025999-0012"
    assert body["top_10_tunggakan"][0]["total_tunggakan"] == "12000000.00"
    assert body["ringkasan"]["tunggakan_lebih_2_bulan_count"] == 4
    assert body["rekomendasi"][0] == "Kirim reminder ke 4 mahasiswa dengan tunggakan >2 bulan"

    # CSV cacat -> 400
    bad_csv = client.post(
        "/api/keuangan/ai-report/csv",
        json={"csv_data": "nim,jumlah\n2025001-0001,5000"},
    )
    assert bad_csv.status_code == 400
    with pytest.raises(BillingValidationError):
        FinancialReportService().analyze_csv("nim,jumlah,tanggal,status\n,abc,2026-11-01,paid")

    # Live DB AI report dengan data seed
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    seed_transkrip_demo_data(db_session)
    seed_keuangan_data(db_session)

    live_res = client.get("/api/keuangan/ai-report?as_of=2026-11-21")
    assert live_res.status_code == 200
    live = live_res.json()
    assert live["ringkasan"]["total_mahasiswa"] == 10
    assert live["ringkasan"]["tunggakan_lebih_2_bulan_count"] == 3
    assert live["rekomendasi"][0] == "Kirim reminder ke 3 mahasiswa dengan tunggakan >2 bulan"
    # Memastikan nama mahasiswa termuat dari DB
    assert any(item["nama"] == "Sari Wulandari" for item in live["top_10_tunggakan"])


def test_apscheduler_dan_endpoint_operasi_keuangan(
    client: TestClient, db_session: Session
) -> None:
    """Uji APScheduler cron registration, start/shutdown, eksekusi job, & endpoint batch API."""
    seed_data(db_session)
    _buat_mahasiswa(
        db_session, nim="2025001-0050", nama="Cron Student", email="cron@example.com", prodi_id=1
    )
    db_session.commit()

    # Endpoint list scheduler jobs
    jobs_res = client.get("/api/keuangan/scheduler/jobs")
    assert jobs_res.status_code == 200
    jobs_body = jobs_res.json()
    assert jobs_body["running"] is True
    job_ids = {j["id"] for j in jobs_body["jobs"]}
    assert job_ids == {"semester_billing_generator", "daily_overdue_reminder"}

    # Uji langsung BillingScheduler dengan session factory database uji
    test_session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=db_session.get_bind()
    )
    sched = BillingScheduler(session_factory=test_session_factory)
    sched.start()
    assert sched.is_running is True
    try:
        gen_res = sched.run_semester_billing_job(
            semester="20261", semester_start=date(2026, 8, 1)
        )
        assert gen_res.created_count == 1
        rem_res = sched.run_daily_reminder_job(as_of=date(2026, 8, 25))
        assert rem_res.reminded_count == 1
    finally:
        sched.shutdown(wait=False)
        assert sched.is_running is False

    # Endpoint generate, calculate-late-fees, dan send-reminders via API
    gen_api = client.post(
        "/api/keuangan/billing/generate",
        json={"semester": "20262", "semester_start": "2027-02-01"},
    )
    assert gen_api.status_code == 201
    assert gen_api.json()["created_count"] == 1

    lf_api = client.post(
        "/api/keuangan/billing/calculate-late-fees",
        json={"as_of": "2027-02-20", "semester": "20262"},
    )
    assert lf_api.status_code == 200
    assert lf_api.json()["updated_count"] == 1

    rem_api = client.post(
        "/api/keuangan/billing/send-reminders",
        json={"as_of": "2027-02-20"},
    )
    assert rem_api.status_code == 200
    assert rem_api.json()["reminded_count"] >= 1


def test_seed_keuangan_data_idempotent(db_session: Session) -> None:
    """Menjalankan seed_keuangan_data dua kali tidak boleh menduplikasi prodi, metode, atau billing."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    seed_nilai_demo_data(db_session)
    seed_transkrip_demo_data(db_session)
    seed_keuangan_data(db_session)

    jumlah_billing_1 = db_session.query(Billing).count()
    jumlah_payment_1 = db_session.query(Payment).count()
    jumlah_method_1 = db_session.query(PaymentMethod).count()

    seed_keuangan_data(db_session)

    assert db_session.query(Billing).count() == jumlah_billing_1 == 10
    assert db_session.query(Payment).count() == jumlah_payment_1 == 7
    assert db_session.query(PaymentMethod).count() == jumlah_method_1 == 5

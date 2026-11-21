# Pull Request Minggu 11 — Modul Keuangan (SPP): Tagihan, Webhook Gateway, APScheduler, Blokir KRS, & AI Financial Insights (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan seluruh deliverable **Minggu 11 — Modul Keuangan (SPP)** pada `sevima-mini`:
  - **Skema Pembayaran & Migrasi `0008` (`app/models/keuangan.py`, `alembic/versions/0008_modul_keuangan_spp.py`):**
    - Menambahkan 3 tabel baru beserta *constraint* & indeks: `payment_method` (`code` unik), `billing` (`UNIQUE (nim, semester)`, `amount > 0`, `denda >= 0`, `paid_amount >= 0`, status enum `unpaid`/`partial`/`paid`/`overdue`), dan `payment` (`transaction_id` unik, `amount > 0`, `source IN ('manual', 'webhook')`, `receipt_sent`).
  - **Domain Murni Keuangan & Analitik CSV (`app/domain/keuangan.py`):**
    - Aritmetika `Decimal` (`ROUND_HALF_UP`) tanpa `float`: penentuan tarif prodi (`tentukan_tarif_spp`: Teknik `5jt`, Ekonomi `4jt`, lainnya `4.5jt`), `hitung_due_date` (+14 hari), `hitung_denda_keterlambatan` (`0.5%/hari` dengan batas maks `10%`), `tentukan_status_pembayaran` (`unpaid`/`partial`/`paid`), serta `analisis_keuangan_csv()` untuk laporan keuangan berbasis input CSV `(nim, jumlah, tanggal, status)`.
  - **Billing Service, Keamanan Webhook HMAC-SHA256, & Email Receipt (`app/services/billing_service.py`):**
    - `generate_billing()` idempoten per semester untuk seluruh mahasiswa aktif ber-status `approved`.
    - `process_payment()` atomik (`BEGIN IMMEDIATE` / `with_for_update()` + idempotency `transaction_id` + notifikasi mahasiswa + pengiriman email receipt pasca-commit lewat `EmailReceiptPort`).
    - `handle_webhook()` memvalidasi header `X-Webhook-Signature` dengan `hmac.compare_digest`, memproses status pembayaran `paid`/`settlement`/`capture`/`success`, mengabaikan status `pending`/`failed` secara aman, serta tahan terhadap pengiriman ulang duplikat.
    - `calculate_late_fees()` dan `send_overdue_reminders()` menghitung denda harian, menandai tagihan `overdue`, serta mencatat pengingat ke tabel `notifikasi` dan log email.
  - **APScheduler Cron Jobs (`app/services/scheduler.py`, `app/main.py`):**
    - Mendaftarkan `semester_billing_generator` (awal semester Februari & Agustus) dan `daily_overdue_reminder` (harian pukul 07:00 WIB) melalui `BackgroundScheduler(timezone="Asia/Jakarta")` pada `lifespan` FastAPI.
  - **Blokir KRS Jika Ada Tunggakan (`app/validators/krs.py`, `app/services/krs_manager.py`, `app/routers/krs.py`):**
    - Menambahkan `BillingArrearsValidator` dan `KRSManager._pastikan_bebas_tunggakan()` (`KRSBillingBlockedError` HTTP `403`) yang menolak penambahan mata kuliah maupun pengajuan KRS selama mahasiswa memiliki tagihan berstatus `unpaid`, `partial`, atau `overdue`, serta langsung terbuka kembali sesudah lunas.
  - **Dashboard Keuangan Real-Time, AI Financial Insights, & Seed Data (`app/routers/keuangan.py`, `app/templates/keuangan_dashboard.html`, `app/services/financial_ai.py`, `seed.py`):**
    - Menyajikan dashboard HTML `/api/keuangan/dashboard` & data JSON real-time `/api/keuangan/dashboard/data` (per mahasiswa, collection rate per program studi, grafik SVG bulanan, simulator pembayaran manual & webhook, status cron job, serta log email receipt).
    - Menyajikan `GET /api/keuangan/ai-report` dan `POST /api/keuangan/ai-report/csv` menghasilkan JSON insights terstruktur (revenue bulan ini, collection rate %, top 10 tunggakan terbesar, dan rekomendasi `'Kirim reminder ke Z mahasiswa dengan tunggakan >2 bulan'`).
    - Menambahkan `seed_keuangan_data()` idempoten mencakup 4 prodi, 5 metode bayar, dan 10 tagihan semester `20261` lintas seluruh status (`paid`, `partial`, `unpaid`, `overdue`).
    - Menambahkan **ADR-020**, **ADR-021**, dan **ADR-022**.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI membantu menyusun model domain `Decimal` di `app/domain/keuangan.py`, migrasi `0008`, `BillingService` beserta verifikasi webhook HMAC dan idempotency, integrasi `BillingArrearsValidator` ke KRS, layanan `FinancialReportService` & `BillingScheduler`, antarmuka HTML `keuangan_dashboard.html`, serta suite uji `tests/test_keuangan.py` & `tests/test_keuangan_property.py` ([prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- **Koreksi manual & temuan kritis mahasiswa:**
  1. **Deduplikasi `NimCounter` pada `seed_keuangan_data`:** `SessionLocal` memakai `autoflush=False`, sehingga pemeriksaan `db.get(NimCounter, ...)` di dalam loop mahasiswa pada prodi yang sama sempat mencoba menyisipkan baris counter ganda. Diperbaiki dengan menghitung nomor maksimum per kode prodi terlebih dahulu sebelum memperbarui `NimCounter`.
  2. **Isolasi `TestClient` dan Lifecycle `BackgroundScheduler`:** Di `APScheduler`, instance scheduler yang sudah di-`shutdown()` tidak dapat langsung di-`start()` ulang pada `TestClient` berikutnya; diperbaiki pada `BillingScheduler.shutdown()` dengan membuat ulang instance bersih setelah berhenti sehingga puluhan tes API di `pytest` berjalan lancar.
  3. **Pencegahan Penghitungan Ganda pada Ekspor CSV Live:** Saat mengekspor tagihan berstatus `partial` ke CSV `(nim, jumlah, tanggal, status)` untuk analisis AI, pembayaran masuk (`Payment`) diekspor sebagai `paid` sedangkan sisa tagihannya diekspor sebagai `unpaid`/`overdue` agar sisa utang tidak ikut terhitung sebagai *revenue bulan ini*.
- **3 Prompt Terbaik:**
  1. Rancang domain murni `app/domain/keuangan.py` (`Decimal` `ROUND_HALF_UP`), skema SQLAlchemy 2.0 `payment_method`, `billing`, dan `payment` beserta migrasi `0008_modul_keuangan_spp.py` yang aman untuk rollback `downgrade()`.
  2. Implementasikan `BillingService` dengan transaksi atomik (`BEGIN IMMEDIATE` / `with_for_update()`), keamanan webhook HMAC-SHA256 `compare_digest`, idempotency `transaction_id`, pengiriman email receipt pasca-commit via `EmailReceiptPort`, serta integrasi blokir KRS (`403 KRSBillingBlockedError`) di `KRSManager`.
  3. Bangun `BillingScheduler` (APScheduler cron awal semester & reminder harian), `FinancialReportService` untuk analisis CSV `(nim, jumlah, tanggal, status)` menjadi JSON insights, Dashboard HTML real-time `/api/keuangan/dashboard` dengan grafik SVG, serta suite uji `tests/test_keuangan.py` dan `tests/test_keuangan_property.py`.

## Risiko & Limitasi
1. **APScheduler pada Multi-Worker:** Di lingkungan produksi dengan beberapa worker proses (`uvicorn --workers N`), cron job di `BillingScheduler` perlu dijalankan pada satu proses scheduler terpisah atau dilindungi *distributed lock* agar tidak memicu reminder ganda.
2. **Transport Email & Webhook Secret Default:** `LogEmailReceiptSender` masih mencatat kuitansi dan reminder di log/memori (siap diganti adaptor SMTP/API melalui `EmailReceiptPort`), dan `PAYMENT_WEBHOOK_SECRET` menggunakan nilai default pengembangan bila environment variable belum disetel.
3. **Autentikasi Endpoint Keuangan:** Endpoint operasional (`/api/keuangan/billing/generate`, `/payments`, `/dashboard`) belum dibatasi token JWT/RBAC admin sebelum modul autentikasi terpasang.

## Cara Uji
```powershell
cd sevima-mini

# 1. Verifikasi Alembic head & seeding idempotent 2x
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh suite pengujian (Minggu 3–11) + coverage check >= 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Demo browser Dashboard Keuangan & Swagger API
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# Buka http://127.0.0.1:8000/api/keuangan/dashboard
```

## Log Hasil Uji
- **Alembic & Seeding (`0008_modul_keuangan_spp (head)`):**
  - Siklus `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` berhasil, `alembic current` menunjukkan `0008_modul_keuangan_spp (head)`, dan `seed.py` dijalankan **2x** berturut-turut dengan exit code `0`.
- **Full Pytest + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`189 passed, 1 warning in 35.27s`** (176 tes Minggu 3–10 tanpa regresi + 10 tes unit/integrasi/webhook/KRS/AI/scheduler di `tests/test_keuangan.py` + 3 tes *property-based* Hypothesis di `tests/test_keuangan_property.py`).
  - **Total Coverage: `95.82%` (`96%`)** (`app/models/keuangan.py` 100%, `app/schemas/keuangan.py` 100%, `app/services/scheduler.py` 100%, `app/services/exceptions.py` 100%, `app/main.py` 100%, `app/routers/keuangan.py` 98%, `app/services/financial_ai.py` 97%, `app/validators/krs.py` 96%, `app/domain/keuangan.py` 95%, `app/services/billing_service.py` 92%).
- **Live `curl.exe` End-to-End Verification (`uvicorn` port 8011 + salinan DB sementara):**
  - Sebelum bayar, `POST /api/krs/2025004-0002/courses?semester=20261` (Maya Putri, `unpaid` Rp 4.000.000) mengembalikan **`403 Forbidden`**.
  - `POST /api/keuangan/webhook/payment` dengan signature palsu mengembalikan **`401 Unauthorized`**.
  - `POST /api/keuangan/webhook/payment` dengan signature HMAC-SHA256 valid (`CURL-TRX-001`, `4000000.00`, `settlement`, `VA_BCA`) mengembalikan **`200 OK`** (`"billing_status":"paid"`, `"remaining":"0.00"`, `"receipt_sent":true`).
  - `GET /api/keuangan/dashboard/data` langsung menampilkan status Maya Putri `"paid"` (`krs_blocked: false`) secara real-time, dan `POST /api/krs/2025004-0002/courses?semester=20261` langsung berhasil **`201 Created`**.

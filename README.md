# SEVIMA-Mini — Implementasi Modul PMB, KRS, Jadwal, Nilai, Transkrip, Keuangan, & Presensi

Proyek ini merupakan implementasi sistem akademik **SEVIMA-Mini** untuk mata kuliah **Pemrograman Berorientasi Objek untuk Sistem AI Agenik**, yang mencakup:
1. **Modul PMB (Minggu 3–4):** Pendaftaran calon mahasiswa, persetujuan admin, generator NIM atomik bebas *race condition*, dan statistik pendaftar.
2. **Modul KRS Bagian 1 (Minggu 5):** Skema database 2 tingkat (`krs` + `krs_detail`), *self-referencing many-to-many* (`prerequisite`), tabel bobot `skala_nilai`, `KRSManager` Service, rantai validasi berpola **Chain of Responsibility**, query prasyarat berbasis `NOT EXISTS` yang terindeks (`EXPLAIN QUERY PLAN`), dan REST API `/api/krs/*`.
3. **Modul KRS Bagian 2 (Minggu 6):** Enkapsulasi *State Machine* KRS (`Actor` + `TRANSITIONS`), approval/revisi Dosen PA dalam satu transaksi atomik (`krs_log` + `notifikasi`), otorisasi kepemilikan (`403` vs `409`), *optimistic locking* (`version` + `expected_version`), *property-based testing* (`hypothesis` 1000x + transisi ilegal), exception handler polimorfik `KRSError`, serta *Optional Challenge* rekomendasi KRS berbasis **CSP Backtracking** dengan guardrail validator.
4. **Modul Jadwal & Ruangan Bagian 1 (Minggu 7):** Model domain 4 entitas (`Ruangan`, `Dosen`, `Kelas`, `Jadwal`) + `krs_detail.kelas_id` (*expand-contract*), perumusan *Constraint Satisfaction Problem* (hard vs soft constraint), detektor bentrok 3 dimensi *Grouping + Sort & Sweep* (`detect_schedule_conflict`) vs acuan naif (`detect_naive`), `SchedulingService` (`cek_kapasitas` `max(kuota, terdaftar)`, penguncian baris tetap `Ruangan -> Dosen`, anti-autoflush), REST API `/api/jadwal/*` (`422` validasi / `409` detail konflik), *differential property-based testing* Hypothesis (`500x`), serta **ADR-010..012** (termasuk benchmark penundaan *Interval Tree*).
5. **Modul Jadwal & Ruangan Bagian 2 (Minggu 8):** **Observer Pattern + Transactional Outbox** (`ScheduleSubject`, `StudentObserver`, `LecturerObserver`, `AdminObserver`, `LogChannel` `EMAIL`/`SMS`/`PUSH` idempoten, `Outbox` + `0006` + `OutboxDispatcher` pasca-commit maks. 5 retry/`SKIP LOCKED`), **integrasi State Machine KRS** (`Actor.SISTEM`, 48 kombinasi, `KRSInvalidator` atomik), **AI-Powered Rescheduling** (`LLMClient` + guardrail deterministik 4 lapis `saring_saran`), **Conflict Resolver UI** (`/api/jadwal/resolver` + proteksi `X-Role: admin`), **ekspor iCalendar RFC 5545** (`/api/mahasiswa/{nim}/jadwal.ics` dengan `CRLF` & kenaikan `SEQUENCE`), diagram sekuens Mermaid, serta **ADR-013..015**.
6. **Modul Nilai & Transkrip Bagian 1 (Minggu 9):** `skala_nilai.bobot Numeric(3,2)` + kolom data `lulus` + `grade_history` + SQL view `v_riwayat_nilai` (`0007`), **domain murni perhitungan IPS/IPK** berbasis `Decimal` & `ROUND_HALF_UP` ([app/domain/gpa.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/domain/gpa.py)), `NilaiRepo` + `GPACalculator` (*compute-on-read* & pembanding CTE SQL `ROW_NUMBER()`), `GradeService` berpenjaga ganda (`is_pengampu` `403` + `PresensiPort` `>= 75%` `400`, idempotency, wajib alasan saat edit, transaksi atomik `grade_history`), UI Form Input Nilai (`/api/kelas/nilai-form`), serta **ADR-016..017**.
7. **Modul Nilai & Transkrip Bagian 2 (Minggu 10):** `get_transcript(nim)` compute-on-read + **predikat kelulusan** (*Cum Laude* `>= 3.50`, *Sangat Memuaskan* `>= 3.00`, dst.), template HTML/CSS resmi bergaya ijazah ([app/templates/transkrip.html](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/templates/transkrip.html)), port `TranscriptPdfRenderer` & **`ReportLabTranscriptRenderer`** ([app/services/transcript_pdf.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/transcript_pdf.py)), endpoint JSON/HTML/PDF (`/api/mahasiswa/{nim}/transkrip*`), demo 3 semester Dina (`2025001-0004`, IPK `"3.82"`), serta **ADR-018..019**.
8. **Modul Keuangan (SPP) (Minggu 11):** Skema `payment_method`, `billing` (`unpaid`/`partial`/`paid`/`overdue`), & `payment` (`0008`), domain murni `Decimal` ([app/domain/keuangan.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/domain/keuangan.py)) untuk tarif per prodi (`Teknik 5jt`, `Ekonomi 4jt`, lainnya `4.5jt`), due date +14 hari, & denda keterlambatan (`0.5%/hari`, cap `10%`), `BillingService` (cicilan `partial -> paid` atomik, keamanan webhook HMAC-SHA256 + idempotency `transaction_id`, & email receipt pasca-commit via `EmailReceiptPort`), **APScheduler** cron jobs (`BillingScheduler`), integrasi **blokir KRS `403`** (`BillingArrearsValidator` + `KRSManager`), **Dashboard Keuangan Real-Time** (`/api/keuangan/dashboard` + grafik SVG bulanan & collection rate prodi), **AI Financial Insights** JSON (`/api/keuangan/ai-report*`), serta **ADR-020..022**.
9. **Modul Presensi (QR Code) (Minggu 12):** Skema `attendance_session` & `attendance_record` (`0009`), domain murni ([app/domain/presensi.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/domain/presensi.py)) untuk window kehadiran (`15 mnt` hadir / `30 mnt` terlambat), Haversine geofencing, & AI Pattern Analyzer, `PresensiService` (`qrcode` PNG + `PyJWT` HS256 15 menit dengan rotasi `jti` anti-replay, validasi hari/enrollment/geofence/duplikat/rate limit `429`, & ekspor Excel `.xlsx` 2 sheet `openpyxl`), integrasi nyata **`DBPresensiAdapter`** ke `PresensiPort` Minggu 9, endpoint `/attendance/*` & `/api/presensi/*`, dashboard HTML `/api/presensi/dashboard`, serta **ADR-023..025**.

---

## Pemetaan Desain UML ke Kode

| Artefak Desain | Implementasi Kode | Lokasi File |
| :--- | :--- | :--- |
| Class Diagram PMB (`CalonMahasiswa`, `ProgramStudi`, `JalurMasuk`, + `NimCounter`) | Model SQLAlchemy 2.0 (`Mapped`, constraint, counter atomik) | [app/models/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/pmb.py) |
| Class Diagram KRS (`MataKuliah`, `prerequisite`, `KRS`, `KRSDetail`, `SkalaNilai`) | Relasi 2-tingkat M2M & *self-referencing* FK ke `calon_mahasiswa.nim` | [app/models/krs.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/krs.py) |
| Model Domain Penjadwalan (`Ruangan`, `Dosen`, `Kelas`, `Jadwal`, `Outbox`) | 4 entitas jadwal terindeks + `sequence` + tabel `outbox` & `krs_detail.kelas_id` | [app/models/jadwal.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/jadwal.py) |
| Observer, Outbox, & Invalidasi KRS (`ScheduleSubject`, `OutboxDispatcher`, `KRSInvalidator`) | Notifikasi 3 observer (`EMAIL/SMS/PUSH`) idempoten pasca-commit & auto-revisi KRS | [app/services/observer.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/observer.py), [app/services/krs_invalidator.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/krs_invalidator.py), [docs/SEQUENCE_OBSERVER.md](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/docs/SEQUENCE_OBSERVER.md) |
| AI Rescheduling, Resolver UI, & Ekspor `.ics` | Guardrail 4 lapis `saring_saran`, UI HTML `/api/jadwal/resolver`, & RFC 5545 `.ics` | [app/services/rescheduler.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/rescheduler.py), [app/services/icalendar.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/icalendar.py), [app/templates/resolver.html](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/templates/resolver.html) |
| Domain Nilai, `GPACalculator`, `GradeService`, & Audit Trail (`GradeHistory`) | Fungsi murni `Decimal` IPS/IPK/predikat, `PresensiPort` (DIP), `is_pengampu`, view `v_riwayat_nilai`, & form HTML | [app/domain/gpa.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/domain/gpa.py), [app/services/gpa_calculator.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/gpa_calculator.py), [app/services/grade_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/grade_service.py), [app/models/nilai.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/nilai.py), [app/templates/nilai_form.html](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/templates/nilai_form.html) |
| Transkrip Akademik & Dual Renderer (HTML Jinja2 + ReportLab PDF) | `get_transcript(nim)`, preview HTML A4 resmi, dan generator PDF `ReportLabTranscriptRenderer` + logo & TTD Dekan | [app/services/transcript_pdf.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/transcript_pdf.py), [app/templates/transkrip.html](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/templates/transkrip.html) |
| Modul Keuangan (SPP), Webhook HMAC, APScheduler, Blokir KRS, & AI Report | `Billing`, `Payment`, `PaymentMethod` (`0008`), domain murni `Decimal`, `BillingService`, `BillingScheduler`, `BillingArrearsValidator` (`403`), `FinancialReportService`, & dashboard HTML | [app/domain/keuangan.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/domain/keuangan.py), [app/models/keuangan.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/keuangan.py), [app/services/billing_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/billing_service.py), [app/services/scheduler.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/scheduler.py), [app/services/financial_ai.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/financial_ai.py), [app/templates/keuangan_dashboard.html](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/templates/keuangan_dashboard.html) |
| Modul Presensi (QR Code), JWT 15m, Geofence, Excel, & AI Insights | `AttendanceSession`, `AttendanceRecord` (`0009`), domain murni `presensi.py`, `PresensiService`, `DBPresensiAdapter`, `AttendanceAIService`, & dashboard HTML | [app/domain/presensi.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/domain/presensi.py), [app/models/presensi.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/presensi.py), [app/services/presensi_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/presensi_service.py), [app/services/attendance_ai.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/attendance_ai.py), [app/templates/presensi_dashboard.html](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/templates/presensi_dashboard.html) |
| Chain of Responsibility & Template Method | `Validator(ABC)` (`BillingArrears → Duplicate → SKS → Prerequisite → Conflict`) | [app/validators/base.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/validators/base.py), [app/validators/krs.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/validators/krs.py) |
| Service Layer (`PMBService`, `KRSManager`, `KRSRecommender`, `SchedulingService`, `GradeService`, `BillingService`, `PresensiService`) | Pengendali alur, state machine atomik, locking, sweep, CSP, nilai, billing SPP, & presensi QR | [app/services/pmb_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/pmb_service.py), [app/services/krs_manager.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/krs_manager.py), [app/services/krs_recommender.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/krs_recommender.py), [app/services/scheduling_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/scheduling_service.py), [app/services/conflict.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/conflict.py), [app/services/billing_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/billing_service.py), [app/services/presensi_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/presensi_service.py) |
| Router REST API (`/api/pmb/*`, `/api/krs/*`, `/api/jadwal/*`, `/api/kelas/*`, `/api/mahasiswa/*`, `/api/keuangan/*`, `/api/presensi/*`, `/attendance/*`) | Router tipis + guard, OpenAPI `responses={...}`, `.ics`, nilai/IPK, transkrip PDF, keuangan SPP, & presensi QR | [app/routers/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/pmb.py), [app/routers/krs.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/krs.py), [app/routers/jadwal.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/jadwal.py), [app/routers/nilai.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/nilai.py), [app/routers/keuangan.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/keuangan.py), [app/routers/presensi.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/presensi.py) |
| Architecture Decision Record (ADR) | Keputusan arsitektural ADR-001 s.d. ADR-025 | [docs/ADR.md](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/docs/ADR.md) |

---

## Struktur Proyek

```text
sevima-mini/
├── .github/
│   └── pull_request_template.md     # Template PR sesuai rubrik kuliah
├── app/
│   ├── main.py                      # Entrypoint FastAPI (PMB, KRS, Jadwal, Nilai, Transkrip, Keuangan, & Presensi)
│   ├── database.py                  # Engine SQLAlchemy, PRAGMA foreign_keys=ON & busy_timeout
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── gpa.py                   # Fungsi murni hitung_ips, hitung_ipk, tentukan_predikat, & bangun_ringkasan_transkrip (Decimal)
│   │   ├── keuangan.py              # Fungsi murni tarif prodi, due_date, denda keterlambatan, & analisis_keuangan_csv (Decimal)
│   │   └── presensi.py              # Fungsi murni window hadir/terlambat, Haversine geofence, & analisis_pola_presensi
│   ├── models/
│   │   ├── __init__.py
│   │   ├── pmb.py                   # ProgramStudi, JalurMasuk, CalonMahasiswa, NimCounter
│   │   ├── krs.py                   # SkalaNilai (Numeric + lulus), MataKuliah, prerequisite, KRS (48-comb), KRSDetail, KRSLog, Notifikasi
│   │   ├── jadwal.py                # Ruangan, Dosen, Kelas, Jadwal (+ sequence), Outbox
│   │   ├── nilai.py                 # GradeHistory (append-only) + definisi view v_riwayat_nilai
│   │   ├── keuangan.py              # PaymentMethod, Billing (unpaid/partial/paid/overdue), & Payment
│   │   └── presensi.py              # AttendanceSession (active_jti, geofence) & AttendanceRecord
│   ├── schemas/
│   │   ├── pmb.py                   # Skema Pydantic v2 PMB
│   │   ├── krs.py                   # Skema Pydantic v2 KRS (+ approve, revise, recommend)
│   │   ├── jadwal.py                # JadwalIn, JadwalOut, JadwalDetailOut, ConflictOut, SaranOut, ApplySaranIn
│   │   ├── nilai.py                 # NilaiIn, NilaiOut, IPKOut, IPSOut, GradeHistoryOut, PesertaNilaiOut, TranskripOut
│   │   ├── keuangan.py              # BillingOut, PaymentOut, WebhookPaymentIn/Out, DashboardKeuanganOut, AIReportOut, SchedulerStatusOut
│   │   └── presensi.py              # QRGenerateOut, ScanRequest/Out, Mahasiswa/KelasPresensiReportOut, AIAttendanceInsightsOut
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── base.py                  # ValidationResult, KRSContext, Validator(ABC), build_chain
│   │   └── krs.py                   # BillingArrearsValidator, DuplicateValidator, SKSValidator, PrerequisiteValidator, ConflictValidator
│   ├── services/
│   │   ├── exceptions.py            # Domain exception PMB, KRSError, ScheduleError, GradeError, BillingError, & AttendanceError
│   │   ├── nim_generator.py         # format_nim() + generate_nim() via nim_counter & flush()
│   │   ├── pmb_service.py           # Kelas OOP PMBService
│   │   ├── krs_queries.py           # Query kompleks prasyarat NOT EXISTS + bobot skala_nilai
│   │   ├── krs_manager.py           # Workflow add/remove/validate/submit/approve/revise + locking + cek tunggakan SPP
│   │   ├── krs_recommender.py       # Rekomendasi paket KRS CSP Backtracking + guardrail validator
│   │   ├── conflict.py              # Deteksi bentrok 3D: detect_naive & detect_schedule_conflict (Grouping + Sort & Sweep)
│   │   ├── observer.py              # ScheduleSubject, Student/Lecturer/AdminObserver, LogChannel, OutboxDispatcher
│   │   ├── krs_invalidator.py       # KRSInvalidator (SUBMITTED/APPROVED -> REVISION oleh Actor.SISTEM)
│   │   ├── rescheduler.py           # AI Rescheduling (LLMClient, HeuristicLLMClient, guardrail 4 lapis saring_saran)
│   │   ├── icalendar.py             # Formatter RFC 5545 ke_vevent & export_jadwal_ics (CRLF, Asia/Jakarta, UTC UNTIL)
│   │   ├── scheduling_service.py    # SchedulingService (CRUD, cek_kapasitas, lock Ruangan -> Dosen, KRS invalidation, Outbox)
│   │   ├── gpa_calculator.py        # NilaiRepo (+ CTE SQL ROW_NUMBER()) & GPACalculator compute-on-read (+ get_transcript)
│   │   ├── grade_service.py         # GradeService (is_pengampu, PresensiPort -> DBPresensiAdapter, input_nilai atomik, v_riwayat_nilai)
│   │   ├── transcript_pdf.py        # Dual renderer Transkrip: render_transcript_html (Jinja2) & ReportLabTranscriptRenderer (PDF)
│   │   ├── billing_service.py       # BillingService (tagihan, bayar atomik, HMAC webhook, denda, reminder, dashboard, receipt email)
│   │   ├── financial_ai.py          # FinancialReportService (analisis CSV/DB -> AI Financial Insights JSON)
│   │   ├── scheduler.py             # BillingScheduler (APScheduler cron awal semester & reminder harian)
│   │   ├── presensi_service.py      # PresensiService (QR PNG + JWT HS256, rotasi jti, geofence, rate limit, Excel, DBPresensiAdapter)
│   │   └── attendance_ai.py         # AttendanceAIService (analisis pola absen & early warning <75% -> JSON)
│   ├── templates/
│   │   ├── resolver.html            # Dashboard UI HTML Conflict Resolver & AI Rescheduling
│   │   ├── nilai_form.html          # Form UI HTML Input Nilai Dosen & Audit Trail (+ link Transkrip/PDF)
│   │   ├── transkrip.html           # Template Jinja2 HTML/CSS resmi Transkrip Akademik (A4 siap cetak)
│   │   ├── keuangan_dashboard.html  # Dashboard UI HTML Keuangan (SPP), grafik SVG, simulator webhook, & AI Insights
│   │   └── presensi_dashboard.html  # Dashboard UI HTML Presensi QR Code, simulasi scan, laporan kelas, & AI Insights
│   └── routers/
│       ├── pmb.py                   # Endpoint /api/pmb/*
│       ├── krs.py                   # Endpoint /api/krs/*
│       ├── jadwal.py                # Endpoint /api/jadwal/* + /api/mahasiswa/{nim}/jadwal.ics
│       ├── nilai.py                 # Endpoint /api/kelas/* + /api/mahasiswa/{nim}/(ipk|ips|nilai/riwayat|transkrip*)
│       ├── keuangan.py              # Endpoint /api/keuangan/* (dashboard, billing, payments, webhook, ai-report, scheduler, receipts)
│       └── presensi.py              # Endpoint /api/presensi/* & /attendance/(qr|scan)
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 0001_tabel_pmb.py        # Skema PMB (3 tabel + constraints)
│       ├── 0002_tabel_nim_counter.py# Tabel nim_counter atomik
│       ├── 0003_tabel_krs.py        # Skema KRS (5 tabel + constraints + index)
│       ├── 0004_krs_workflow_audit.py # Kolom state/version pada krs + krs_log + notifikasi
│       ├── 0005_tabel_jadwal_ruangan.py # Tabel ruangan, dosen, kelas, jadwal + krs_detail.kelas_id
│       ├── 0006_outbox_dan_jadwal_sequence.py # Kolom jadwal.sequence + tabel Transactional Outbox
│       ├── 0007_nilai_grade_history_view.py   # skala_nilai (Numeric+lulus), grade_history, & view v_riwayat_nilai
│       ├── 0008_modul_keuangan_spp.py         # payment_method, billing, & payment untuk Modul Keuangan (SPP)
│       └── 0009_modul_presensi_qr.py          # attendance_session & attendance_record untuk Modul Presensi QR
├── tests/
│   ├── conftest.py
│   ├── test_pmb.py                  # Tests Modul PMB (30 skenario)
│   ├── test_krs.py                  # Tests Modul KRS Bag. 1–2 (18 skenario unit, integrasi, lock, CSP)
│   ├── test_krs_property.py         # Hypothesis (1000x SKS & Conflict) + 48 kombinasi State Machine (51 skenario)
│   ├── test_conflict.py             # Tests Modul Jadwal Bag. 1 (14 skenario bug klasik, kapasitas, API + 403, concurrency, seed)
│   ├── test_conflict_property.py    # Hypothesis (500x) anti-bentrok oracle independen & differential sweep vs naif
│   ├── test_jadwal_observer.py      # Tests Modul Jadwal Bag. 2 (11 skenario Observer, Outbox, KRSInvalidator, FakeLLM, UI, .ics)
│   ├── test_gpa.py                  # Tests Modul Nilai & Transkrip (38 kasus: IPK, IPS, predikat, ringkasan, & Hypothesis)
│   ├── test_grade_service.py        # Tests Modul Nilai (401/403/404, batas presensi 75%, idempotency, alasan, rollback, CTE SQL, UI)
│   ├── test_transcript.py           # Tests Modul Transkrip Bag. 2 (JSON/HTML/PDF, XSS escaping, pypdf parsing, acceptance 4 semester)
│   ├── test_keuangan.py             # Tests Modul Keuangan SPP (constraints, tarif, denda, webhook HMAC, blokir KRS, dashboard, AI, cron)
│   ├── test_keuangan_property.py    # Hypothesis (500x) denda bounded/monotonik, cicilan partial/paid, & persentase collection rate
│   ├── test_presensi.py             # Tests Modul Presensi QR (JWT 15m, rotasi jti, scan validation, geofence, rate limit, Excel, AI)
│   └── test_presensi_property.py    # Hypothesis (500x) persentase bounded/monotonik, Haversine simetri, & window 15/30 mnt
├── prompts/
│   └── ai-usage-log.md              # Log AI terstruktur + OPAR (Minggu 3–12)
├── docs/
│   ├── ADR.md                       # ADR-001 s.d. ADR-025
│   ├── AI_USAGE_LOG.md
│   ├── EXPLAIN_PRASYARAT.md         # Bukti verbatim EXPLAIN QUERY PLAN sebelum vs sesudah index
│   ├── SEQUENCE_OBSERVER.md         # Diagram sekuens Mermaid COMMIT sebelum notify + Observer vs Pub-Sub
│   ├── PR_MINGGU_4.md
│   ├── PR_MINGGU_6.md               # PR Minggu 6 (State Machine, Locking, Hypothesis, CSP)
│   ├── PR_MINGGU_7.md               # PR Minggu 7 (CSP, Detektor Sort & Sweep, SchedulingService, Benchmark)
│   ├── PR_MINGGU_8.md               # PR Minggu 8 (Observer, Outbox, KRSInvalidator, AI Rescheduler, UI, .ics)
│   ├── PR_MINGGU_9.md               # PR Minggu 9 (Domain Decimal GPA, GradeService, PresensiPort, Audit Trail, Form UI)
│   ├── PR_MINGGU_10.md              # PR Minggu 10 (get_transcript, Predikat, HTML Preview, & PDF Generator ReportLab)
│   ├── PR_MINGGU_11.md              # PR Minggu 11 (Billing SPP, Webhook HMAC, APScheduler, Blokir KRS, Dashboard, & AI Report)
│   └── PR_MINGGU_12.md              # PR Minggu 12 (QR Code JWT, Geofence, Rate Limit, DBPresensiAdapter, Excel, & AI Insights)
├── seed.py                          # Seeding idempotent PMB, KRS, Jadwal, Nilai, Transkrip, Keuangan, & Presensi
├── alembic.ini
├── requirements.txt
└── README.md
```

---

## Ringkasan Skema Database

### Modul PMB (`0001` & `0002`)
1. `program_studi`: `id` (PK), `kode` (`UNIQUE` 3 char), `nama`, `fakultas`.
2. `jalur_masuk`: `id` (PK), `nama` (`SNBP`/`SNBT`/`Mandiri`, `UNIQUE`).
3. `calon_mahasiswa`: `id` (PK), `nama_lengkap`, `email` (`UNIQUE`, indexed), `phone`, `tanggal_lahir`, `alamat`, `program_studi_id` (FK), `jalur_masuk_id` (FK), `status` (`pending`/`approved`/`rejected` + CHECK enum), `nim` (nullable, `UNIQUE`), `created_at`, `approved_at`.
4. `nim_counter`: composite PK `(tahun, kode_prodi)`, `last_number` (default `0`).

### Modul KRS (`0003`, `0004`, & `0007`)
5. `skala_nilai`: `huruf` (`A..E`, PK), `bobot` (`Numeric(3, 2)` -> `Decimal`), `lulus` (`Boolean` — aturan kelulusan sebagai data, diperbarui di `0007`).
6. `matakuliah`: `kode_mk` (PK), `nama`, `sks` (`CHECK 1..4`), `hari` (`CHECK 1..6`), `jam_mulai`, `jam_selesai` (`CHECK jam_mulai < jam_selesai`).
7. `prerequisite`: *self-referencing many-to-many* `(kode_mk, kode_prasyarat)` sebagai PK gabungan + `CHECK kode_mk <> kode_prasyarat`.
8. `krs`: `id` (PK), `nim` (FK -> `calon_mahasiswa.nim`), `semester` (`String(5)`), `status` (`DRAFT`/`SUBMITTED`/`APPROVED`/`REVISION` + CHECK enum), `dosen_pa_id`, `submitted_at`, `approved_at`, `catatan_revisi`, `diubah_pada`, `version` (optimistic locking `version_id_col`), `UNIQUE (nim, semester)`.
9. `krs_detail`: `id` (PK), `krs_id` (FK -> `krs.id` `ON DELETE CASCADE`), `kode_mk` (FK -> `matakuliah.kode_mk`), `kelas_id` (nullable FK -> `kelas.id`, indexed — ditambahkan pada `0005`), `nilai` (nullable FK -> `skala_nilai.huruf`), `UNIQUE (krs_id, kode_mk)`.
10. `krs_log`: `id` (PK), `krs_id` (FK -> `krs.id` `ON DELETE CASCADE`, indexed), `aksi`, `aktor_id`, `catatan`, `created_at`.
11. `notifikasi`: `id` (PK), `nim` (FK -> `calon_mahasiswa.nim`, indexed), `pesan`, `terbaca` (default `False`), `created_at`.

### Modul Jadwal & Ruangan (`0005` & `0006`)
12. `ruangan`: `kode` (`String(20)`, PK), `kapasitas` (`CHECK kapasitas >= 1`).
13. `dosen`: `id` (PK), `nidn` (`String(20)`, `UNIQUE`), `nama` (`String(100)`).
14. `kelas`: `id` (PK), `kode_mk` (FK -> `matakuliah.kode_mk`), `nama` (`String(50)`), `kuota` (`CHECK kuota >= 1`), `semester` (`String(5)`), `UNIQUE (kode_mk, nama, semester)`.
15. `jadwal`: `id` (PK), `kelas_id` (FK -> `kelas.id`), `hari` (`CHECK 1..6`), `jam_mulai` (`Time`), `jam_selesai` (`Time`, `CHECK jam_mulai < jam_selesai`), `ruangan_kode` (FK -> `ruangan.kode`), `dosen_id` (FK -> `dosen.id`), `sequence` (`Integer`, default `0` — ditambahkan di `0006`), index `ix_jadwal_ruang(hari, ruangan_kode)` & `ix_jadwal_dosen(hari, dosen_id)`.
16. `outbox`: `id` (PK), `event_id` (`String(32)`, `UNIQUE`), `payload` (`JSON`), `status` (`PENDING`/`SENT`/`FAILED`, terindeks), `attempts` (default `0`), `created_at` (ditambahkan di `0006`).

### Modul Nilai & Audit Trail (`0007`)
17. `grade_history`: `id` (PK), `grade_id` (FK -> `krs_detail.id` `ON DELETE CASCADE`, terindeks), `old_value` (nullable FK -> `skala_nilai.huruf`), `new_value` (FK -> `skala_nilai.huruf`), `changed_by` (FK -> `dosen.id`, terindeks), `changed_at` (UTC `DateTime`), `reason` (`String(500)`).
18. SQL View `v_riwayat_nilai`: gabungan `grade_history`, `krs_detail`, `krs`, dan `dosen` untuk membaca audit trail per `nim`.

### Modul Keuangan (SPP) (`0008`)
19. `payment_method`: `id` (PK), `code` (`String(30)`, `UNIQUE` terindeks), `name`, `provider`, `is_active` (default `True`), `created_at`.
20. `billing`: `id` (PK), `nim` (FK -> `calon_mahasiswa.nim`, terindeks), `semester` (`String(5)`, terindeks), `amount` (`Numeric(14, 2)` > 0), `denda` (`Numeric(14, 2)` >= 0), `paid_amount` (`Numeric(14, 2)` >= 0), `due_date` (`Date`, terindeks), `status` (`unpaid`/`partial`/`paid`/`overdue` + CHECK enum, terindeks), `reminder_count`, `last_reminder_at`, `UNIQUE (nim, semester)`.
21. `payment`: `id` (PK), `billing_id` (FK -> `billing.id` `ON DELETE CASCADE`, terindeks), `payment_method_id` (FK -> `payment_method.id`, terindeks), `transaction_id` (`String(100)`, `UNIQUE` terindeks), `amount` (`Numeric(14, 2)` > 0), `status` (`success`/`pending`/`failed` + CHECK enum), `source` (`manual`/`webhook`), `paid_at` (terindeks), `notes`, `receipt_sent`, `created_at`.

### Modul Presensi (QR Code) (`0009`)
22. `attendance_session`: `id` (PK), `jadwal_id` (FK -> `jadwal.id` `ON DELETE CASCADE`, terindeks), `pertemuan_ke` (`CHECK >= 1`), `tanggal` (`Date`, terindeks), `dosen_id` (FK -> `dosen.id`, terindeks), `active_jti` (`String(64)`, `UNIQUE` terindeks), `generated_at`, `expires_at`, `valid_minutes` (`CHECK 1..30`), `is_active`, `latitude`/`longitude`/`max_radius_meters` (`CHECK >= 10` opsional), `UNIQUE (jadwal_id, tanggal)`.
23. `attendance_record`: `id` (PK), `session_id` (FK -> `attendance_session.id` `ON DELETE CASCADE`, terindeks), `nim` (FK -> `calon_mahasiswa.nim`, terindeks), `status` (`hadir`/`terlambat`/`izin`/`alpha` + CHECK enum, terindeks), `scanned_at` (terindeks), `latitude`, `longitude`, `distance_meters`, `token_jti`, `notes`, `UNIQUE (session_id, nim)`.

---

## Endpoint REST API

### Modul PMB (`/api/pmb`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/pmb/register` | Daftar calon mahasiswa (`pending`) | `201`, `400`, `409` |
| `GET` | `/api/pmb/status/{pendaftar_id}` | Cek status pendaftaran & NIM | `200`, `404` |
| `PUT` | `/api/pmb/approve/{pendaftar_id}` | Setujui & generate NIM (idempotent) | `200`, `400`, `404`, `409` |
| `PUT` | `/api/pmb/reject/{pendaftar_id}` | Tolak pendaftar (idempotent) | `200`, `404`, `409` |
| `GET` | `/api/pmb/stats` | Statistik dashboard PMB | `200` |

### Modul KRS (`/api/krs`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/krs/{nim}?semester=20251` | Melihat isi KRS mahasiswa, total SKS, & `version` | `200`, `404` |
| `POST` | `/api/krs/{nim}/courses?semester=20251` | Tambah mata kuliah (lolos rantai validator *fail-fast*) | `201`, `400`, `404`, `409` |
| `DELETE` | `/api/krs/{nim}/courses/{kode_mk}?semester=20251` | Hapus mata kuliah dari KRS (`DRAFT`/`REVISION`) | `200`, `404`, `409` |
| `GET` | `/api/krs/{nim}/validate?semester=20251` | Validasi menyeluruh KRS (*collect-all* seluruh error) | `200`, `404` |
| `POST` | `/api/krs/{nim}/submit?semester=20251` | Ajukan KRS mahasiswa (`DRAFT`/`REVISION -> SUBMITTED`) | `200`, `400`, `404`, `409` |
| `POST` | `/api/krs/{nim}/approve?semester=20251` | Setujui KRS oleh Dosen PA atomik + *optimistic lock* | `200`, `400`, `403`, `404`, `409` |
| `POST` | `/api/krs/{nim}/revise?semester=20251` | Kembalikan KRS (`SUBMITTED -> REVISION`) + catatan | `200`, `400`, `403`, `404`, `409` |
| `POST` | `/api/krs/{nim}/recommend?semester=20251` | Rekomendasi paket KRS optimal CSP + guardrail validator | `200`, `400`, `404` |

### Modul Jadwal & Ruangan (`/api/jadwal` & `/api/mahasiswa`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/jadwal/resolver` | Dashboard UI HTML Conflict Resolver & AI Rescheduling | `200` |
| `GET` | `/api/jadwal/conflicts` | Daftar seluruh bentrok ruangan & dosen dari jadwal tersimpan | `200` |
| `GET` | `/api/jadwal` | Daftar seluruh jadwal lengkap dengan metadata MK, peserta, kapasitas, & dosen | `200` |
| `POST` | `/api/jadwal` | Buat jadwal kuliah baru (`X-Role: admin`, cek bentrok + kapasitas + row lock) | `201`, `403`, `404`, `409`, `422` |
| `GET` | `/api/jadwal/{jadwal_id}/suggestions` | Saran alternatif AI Rescheduler tervalidasi 4 lapis (`X-Role: admin`) | `200`, `403`, `404` |
| `POST` | `/api/jadwal/{jadwal_id}/apply` | Terapkan saran via satu pintu `SchedulingService.update` (`X-Role: admin`) | `200`, `403`, `404`, `409`, `422` |
| `PUT` | `/api/jadwal/{jadwal_id}` | Perbarui jadwal (`X-Role: admin`), naikkan `sequence`, invalidasi KRS, & outbox | `200`, `403`, `404`, `409`, `422` |
| `DELETE` | `/api/jadwal/{jadwal_id}` | Hapus jadwal (`X-Role: admin`), invalidasi KRS, & catat/dispatch outbox | `204`, `403`, `404` |
| `GET` | `/api/mahasiswa/{nim}/jadwal.ics` | Ekspor jadwal kuliah mahasiswa format iCalendar RFC 5545 (`text/calendar`) | `200`, `404` |

### Modul Nilai, Kalkulator IPK, & Transkrip PDF (`/api/kelas` & `/api/mahasiswa`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/kelas/nilai-form` | Form web HTML input nilai dosen & peninjauan audit `v_riwayat_nilai` | `200` |
| `GET` | `/api/kelas` | Daftar kelas beserta dosen pengampu terjadwal | `200` |
| `GET` | `/api/kelas/{kelas_id}/peserta` | Daftar peserta kelas (`X-Dosen-Id`), persentase presensi, nilai, & IPK live | `200`, `401`, `403`, `404` |
| `PUT` | `/api/kelas/{kelas_id}/nilai/{nim}` | Input/edit nilai huruf idempoten + audit `grade_history` (`X-Dosen-Id`) | `200`, `400`, `401`, `403`, `404`, `422` |
| `GET` | `/api/mahasiswa/{nim}/ipk` | Hitung IPK kumulatif compute-on-read (string 2 desimal `Decimal`) | `200`, `404` |
| `GET` | `/api/mahasiswa/{nim}/ips/{semester}` | Hitung IPS semester (string 2 desimal `Decimal`, termasuk D & E) | `200`, `404` |
| `GET` | `/api/mahasiswa/{nim}/nilai/riwayat` | Riwayat audit perubahan nilai mahasiswa dari SQL view `v_riwayat_nilai` | `200`, `404` |
| `GET` | `/api/mahasiswa/{nim}/transkrip` | Catatan akademik lengkap lintas semester + total SKS, IPK, & predikat kelulusan | `200`, `404` |
| `GET` | `/api/mahasiswa/{nim}/transkrip/preview` | Pratinjau halaman HTML/CSS resmi Transkrip Akademik siap cetak (Jinja2) | `200`, `404` |
| `GET` | `/api/mahasiswa/{nim}/transkrip.pdf` | Generate & unduh Transkrip Akademik resmi berformat PDF (`?inline=true` untuk pratinjau) | `200`, `404` |

### Modul Keuangan (SPP) (`/api/keuangan`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/keuangan/dashboard` | Halaman UI HTML Dashboard Keuangan real-time, grafik SVG, & simulator webhook | `200` |
| `GET` | `/api/keuangan/dashboard/data` | Agregasi JSON real-time (per mahasiswa, collection rate prodi, & bulanan) | `200` |
| `GET` | `/api/keuangan/payment-methods` | Daftar master metode pembayaran SPP | `200` |
| `GET` | `/api/keuangan/billings` | Daftar tagihan SPP (filter opsional `nim`, `semester`, `status`) | `200` |
| `GET` | `/api/keuangan/billings/{billing_id}` | Detail tagihan SPP beserta riwayat pembayaran | `200`, `404` |
| `GET` | `/api/keuangan/mahasiswa/{nim}` | Ringkasan total tagihan, sudah bayar, sisa, & status blokir KRS per NIM | `200`, `404` |
| `POST` | `/api/keuangan/billing/generate` | Generate tagihan SPP awal semester massal & idempoten | `201`, `422` |
| `POST` | `/api/keuangan/payments` | Catat pembayaran manual (`partial -> paid`) atomik + email receipt | `201`, `400`, `404`, `409`, `422` |
| `POST` | `/api/keuangan/billing/calculate-late-fees` | Hitung denda keterlambatan (0.5%/hari cap 10%) & tandai `overdue` | `200` |
| `POST` | `/api/keuangan/billing/send-reminders` | Kirim pengingat tunggakan ke tabel `notifikasi` & email | `200` |
| `POST` | `/api/keuangan/webhook/payment` | Terima notifikasi webhook gateway (verifikasi HMAC-SHA256 & idempoten) | `200`, `400`, `401`, `404`, `409` |
| `POST` | `/api/keuangan/webhook/sign-preview` | Helper dev penandatangan payload webhook untuk simulator dashboard UI | `200`, `422` |
| `GET` | `/api/keuangan/ai-report` | Generate AI Financial Insights JSON dari data live database | `200` |
| `POST` | `/api/keuangan/ai-report/csv` | Analisis CSV (`nim,jumlah,tanggal,status`) menjadi AI Financial Insights JSON | `200`, `400`, `422` |
| `GET` | `/api/keuangan/scheduler/jobs` | Status APScheduler dan daftar cron job terdaftar | `200` |
| `GET` | `/api/keuangan/receipts` | Log email kuitansi pembayaran dan pengingat yang dikirim sistem | `200` |

### Modul Presensi (QR Code) (`/api/presensi` & `/attendance`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/presensi/dashboard` | Halaman UI HTML Presensi QR Code, simulasi scan, laporan kelas, & AI Insights | `200` |
| `GET` | `/api/presensi/schedules` | Daftar seluruh jadwal kuliah untuk pemilih sesi pembuatan QR | `200` |
| `GET` | `/attendance/qr/{schedule_id}` (`& /api/presensi/qr/{schedule_id}`) | Generate gambar PNG QR code ber-JWT 15 menit (rotasi `active_jti` anti-replay) | `200`, `400`, `403`, `404` |
| `POST` | `/api/presensi/qr/{schedule_id}` | Generate QR sesi dalam JSON (`token` + `qr_base64` data URI PNG) | `200`, `400`, `403`, `404` |
| `POST` | `/attendance/scan` (`& /api/presensi/scan`) | Validasi scan QR (JWT `exp`/`jti`, hari, enrollment, geofence, duplikat, rate limit) | `200`, `400`, `401`, `403`, `404`, `409`, `429` |
| `GET` | `/api/presensi/mahasiswa/{nim}/report` | Persentase kehadiran mahasiswa per mata kuliah + flag warning `<75%` | `200`, `404` |
| `GET` | `/api/presensi/kelas/{kelas_id}/report` | Rekap presensi peserta kelas + daftar mahasiswa berisiko `<75%` | `200`, `404` |
| `GET` | `/api/presensi/kelas/{kelas_id}/export.xlsx` | Unduh laporan presensi 2 sheet Excel `.xlsx` (`openpyxl`) untuk dosen | `200`, `404` |
| `GET` | `/api/presensi/ai-insights` | Generate AI Attendance Insights & early warning JSON dari database live | `200` |
| `POST` | `/api/presensi/ai-insights/analyze` | Analisis JSON array `attendance_records` untuk deteksi pola absen & tindakan | `200`, `400`, `422` |

---

## Cara Menjalankan Proyek

```powershell
cd sevima-mini

# 1. Terapkan migrasi database terbaru & seeding data (idempotent)
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh suite pengujian (197 passed, total coverage 95.77%)
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Khusus property-based testing KRS, Jadwal, IPK/Transkrip, Keuangan, & Presensi
.\.venv\Scripts\pytest.exe tests/test_krs_property.py tests/test_conflict_property.py tests/test_gpa.py tests/test_transcript.py tests/test_keuangan_property.py tests/test_keuangan.py tests/test_presensi_property.py tests/test_presensi.py -v

# 4. Jalankan server lokal untuk Dashboard Presensi (/api/presensi/dashboard), Dashboard Keuangan (/api/keuangan/dashboard), Form Nilai UI (/api/kelas/nilai-form), Preview Transkrip (/api/mahasiswa/2025001-0004/transkrip/preview), Resolver UI (/api/jadwal/resolver), & Swagger (/docs)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

---

## Referensi

1. Tiangolo, S. *FastAPI Documentation — Dependencies, Additional Status Codes, Custom Response, & Handling Errors*. https://fastapi.tiangolo.com/
2. SQLAlchemy Project. *SQLAlchemy 2.0 Documentation — Relationships, Self-Referential M2M, `Select.with_for_update()`, & Configuring a Version Counter (`version_id_col`)*. https://docs.sqlalchemy.org/en/20/
3. Gamma, E., Helm, R., Johnson, R., & Vlissides, J. (1994). *Design Patterns: Elements of Reusable Object-Oriented Software* (Observer, Strategy, Chain of Responsibility, & Template Method).
4. Richardson, C. (2018). *Microservices Patterns — Pattern: Transactional Outbox*. https://microservices.io/patterns/data/transactional-outbox.html
5. Desruisseaux, B. (Ed.). (2009). *RFC 5545: Internet Calendaring and Scheduling Core Object Specification (iCalendar)*. IETF. https://datatracker.ietf.org/doc/html/rfc5545
6. ReportLab Project. *ReportLab User Guide — Platypus Flowables, Tables, & Graphics*. https://www.reportlab.com/docs/reportlab-userguide.pdf
7. Pallets Projects. *Jinja2 Documentation — Templates, Autoescaping, & Inheritance*. https://jinja.palletsprojects.com/
8. pypdf Contributors. *pypdf Documentation — Extracting Text from PDF*. https://pypdf.readthedocs.io/
9. Alembic Project. *Alembic Documentation — Creating & Running Migrations, Batch Mode for SQLite, and Downgrades*. https://alembic.sqlalchemy.org/
10. Pydantic Services Inc. *Pydantic v2 Documentation — Validators & EmailStr*. https://docs.pydantic.dev/latest/
11. SQLite Consortium. *SQLite Documentation — Foreign Keys, Transactions (`BEGIN IMMEDIATE`), & Query Planning (`EXPLAIN QUERY PLAN`)*. https://www.sqlite.org/eqp.html
12. Krekel, H., et al. *pytest Documentation — Fixtures, Parametrize, and pytest-cov*. https://docs.pytest.org/
13. MacIver, D. R., & Hatfield-Dodds, Z. *Hypothesis — Property-Based Testing for Python*. https://hypothesis.readthedocs.io/
14. Russell, S., & Norvig, P. (2020). *Artificial Intelligence: A Modern Approach* (4th ed., Chapter 6: Constraint Satisfaction Problems).
15. Cormen, T. H., Leiserson, C. E., Rivest, R. L., & Stein, C. (2022). *Introduction to Algorithms* (4th ed., Chapter 14: Augmenting Data Structures — Interval Trees & Chapter 33: Computational Geometry — Line-Segment Sweep).
16. Grönholm, A. *APScheduler Documentation — BackgroundScheduler & CronTrigger*. https://apscheduler.readthedocs.io/
17. Krawczyk, H., Bellare, M., & Canetti, R. (1997). *RFC 2104: HMAC: Keyed-Hashing for Message Authentication*. IETF. https://datatracker.ietf.org/doc/html/rfc2104
18. Jones, M., Bradley, J., & Sakimura, N. (2015). *RFC 7519: JSON Web Token (JWT)* & *RFC 7518: JSON Web Algorithms (JWA)*. IETF. https://datatracker.ietf.org/doc/html/rfc7519
19. PyJWT Contributors. *PyJWT Documentation — Encoding, Decoding, & Claims Validation*. https://pyjwt.readthedocs.io/
20. OpenPyXL & python-qrcode Contributors. *openpyxl Documentation* (https://openpyxl.readthedocs.io/) & *qrcode Documentation* (https://github.com/lincolnloop/python-qrcode).

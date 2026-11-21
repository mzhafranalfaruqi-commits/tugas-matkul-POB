# Pull Request Minggu 12 — Modul Presensi (QR Code): JWT 15 Menit, Validasi Scan & Geofence, Excel Export, Rate Limiter, & AI Attendance Insights (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan seluruh deliverable **Minggu 12 — Modul Presensi (QR Code)** pada `sevima-mini`:
  - **Domain Murni Presensi & AI Pattern Analyzer (`app/domain/presensi.py`, `app/domain/__init__.py`):**
    - Fungsi murni bebas I/O: `tentukan_status_kehadiran()` (`<= 15 mnt` → `"hadir"`, `15..30 mnt` → `"terlambat"`, `< 0` atau `> 30` ditolak), `hitung_persentase_kehadiran()` (`Decimal` `ROUND_HALF_UP`), `hitung_jarak_haversine_meter()` (geofencing), `normalisasi_hari()`, `label_slot_waktu()`, serta `analisis_pola_presensi()` untuk *early warning* `< 75%` dan deteksi pola absen hari/jam.
  - **Skema Database & Migrasi `0009` (`app/models/presensi.py`, `alembic/versions/0009_modul_presensi_qr.py`):**
    - Menambahkan tabel `attendance_session` (`UNIQUE (jadwal_id, tanggal)`, `active_jti` unik, `valid_minutes 1..30`, koordinat & radius geofence opsional) dan `attendance_record` (`UNIQUE (session_id, nim)`, status `hadir`/`terlambat`/`izin`/`alpha`, timestamp scan, dan `distance_meters`).
  - **QR Generation (`qrcode` + `PyJWT` HS256), Scan Validation, & Keamanan (`app/services/presensi_service.py`):**
    - `GET /attendance/qr/{schedule_id}` & `POST /api/presensi/qr/{schedule_id}` men-generate gambar PNG QR code dengan JWT HS256 masa berlaku 15 menit (secret 36 byte sesuai RFC 7518 Section 3.2) dan merotasi `active_jti` untuk menggugurkan QR lama (anti-replay).
    - `POST /attendance/scan` & `POST /api/presensi/scan` memvalidasi signature & masa kedaluwarsa JWT (`401`), kecocokan hari jadwal & tanggal sesi (`400`), kepesertaan kelas pada KRS aktif (`403`), radius GPS geofencing opsional (`400`/`403`), anti-duplikat scan (`409`), batas waktu 0–30 menit, serta `SlidingWindowRateLimiter` (`429 Too Many Requests`).
  - **Integrasi Nyata `PresensiPort` ke Modul Nilai Minggu 9 (`app/services/grade_service.py`):**
    - Memasang `DBPresensiAdapter(db)` pada `get_presensi_port()` sehingga input nilai di `GradeService` membaca persentase presensi nyata dari database (dengan *fallback* aman ke `DemoPresensiStub` bila kelas belum memiliki sesi presensi).
  - **Attendance Report, Excel Export (`.xlsx`), AI Attendance Insights, & UI (`app/routers/presensi.py`, `app/services/attendance_ai.py`, `app/templates/presensi_dashboard.html`):**
    - Rekap per mahasiswa (`/api/presensi/mahasiswa/{nim}/report`), rekap per kelas & warning `<75%` (`/api/presensi/kelas/{kelas_id}/report`), unduhan workbook Excel 2 sheet (`Rekap Presensi` + `Log Kehadiran`) lewat `/api/presensi/kelas/{kelas_id}/export.xlsx`, AI Insights live & JSON array (`/api/presensi/ai-insights*`), dan UI interaktif `/api/presensi/dashboard`.
  - **Seeding Idempoten & ADR (`seed.py`, `docs/ADR.md`):**
    - Menambahkan `seed_presensi_data()` (22 sesi & 66 rekord presensi di `IF204-A`, `IF102-A` Senin pagi, dan `IF201-B`) tanpa mengganggu asersi data demo Minggu 9–11, serta mendokumentasikan **ADR-023..025**.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI membantu menyusun fungsi murni di `app/domain/presensi.py`, skema `0009_modul_presensi_qr.py`, generator QR `qrcode` + `PyJWT`, logika validasi `PresensiService`, adaptor `DBPresensiAdapter`, generator Excel `openpyxl`, layanan `AttendanceAIService`, dashboard HTML `presensi_dashboard.html`, serta suite pengujian `tests/test_presensi.py` & `tests/test_presensi_property.py` ([prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- **Koreksi manual & temuan kritis mahasiswa:**
  1. **Peringatan Panjang Kunci RFC 7518 & Klaim `iat` pada PyJWT 2.15:** Saat pertama diuji, kunci dev 31 byte memicu `InsecureKeyLengthWarning` dan `jwt.decode(..., options={"verify_exp": False})` tetap melempar `ImmatureSignatureError` saat tes memakai timestamp simulasi di masa depan/lampau. Diperbaiki dengan kunci 36 byte serta menonaktifkan verifikasi `iat` bawaan (`verify_iat: False`) dan memeriksa `iat`/`exp` secara eksplisit terhadap `current_time` referensi.
  2. **Urutan Validasi `scan_qr`:** Memastikan pengecekan kepesertaan kelas (`403 Forbidden`) dijalankan sebelum pengecekan batas keterlambatan 30 menit agar mahasiswa yang men-scan QR kelas orang lain selalu mendapat `403`, tidak tertutup error jam kuliah berakhir (`400`).
  3. **Kompatibilitas Uji Nilai Minggu 9:** Mengarahkan `DBPresensiAdapter` agar melakukan *fallback* ke `DemoPresensiStub` hanya ketika `total_sesi == 0` untuk `kelas_id` tersebut, sehingga seluruh tes `GradeService` Minggu 9 tetap lulus tanpa regresi.
- **3 Prompt Terbaik:**
  1. Rancang domain murni `app/domain/presensi.py` (window `15/30` menit, Haversine geofencing, `analisis_pola_presensi`) serta model ORM `AttendanceSession`/`AttendanceRecord` dan migrasi `0009_modul_presensi_qr.py`.
  2. Implementasikan `PresensiService` (QR PNG + JWT HS256 15 menit, rotasi `active_jti` anti-replay, validasi jadwal/enrollment/geofence/duplikat/rate limit, ekspor Excel 2 sheet `openpyxl`) dan integrasikan `DBPresensiAdapter` ke `get_presensi_port` di `GradeService`.
  3. Bangun `AttendanceAIService`, router `/api/presensi/*` + `/attendance/*`, dashboard HTML `/api/presensi/dashboard`, `seed_presensi_data()`, serta suite uji `tests/test_presensi.py` & `tests/test_presensi_property.py`.

## Risiko & Limitasi
1. **Rate Limiter & Secret JWT pada Lingkungan Multi-Worker:** `SlidingWindowRateLimiter` masih menyimpan bucket di memori proses tunggal (di produksi perlu dipindah ke Redis), dan `DEFAULT_QR_SECRET` perlu diganti lewat environment variable `ATTENDANCE_JWT_SECRET`.
2. **Otorisasi Dosen & Mahasiswa Sebelum Modul Auth:** Endpoint `GET /attendance/qr/{schedule_id}` hanya memeriksa kecocokan pengampu apabila header `X-Dosen-Id` dikirim, dan `POST /attendance/scan` membaca `nim` dari payload sebelum integrasi autentikasi JWT mahasiswa.
3. **Spoofing GPS Sisi Klien:** Validasi koordinat Haversine bergantung pada data GPS yang dikirim klien dan belum dilengkapi deteksi *mock location* perangkat.

## Cara Uji
```powershell
cd sevima-mini

# 1. Verifikasi Alembic head & seeding idempotent 2x
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh suite pengujian (Minggu 3–12) + coverage check >= 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Demo browser Dashboard Presensi & unduh Excel
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# Buka http://127.0.0.1:8000/api/presensi/dashboard
```

## Log Hasil Uji
- **Alembic & Seeding (`0009_modul_presensi_qr (head)`):**
  - Siklus `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` berhasil, `alembic current` menunjukkan `0009_modul_presensi_qr (head)`, dan `seed.py` dijalankan **2x** berturut-turut dengan exit code `0`.
- **Full Pytest + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`197 passed, 1 warning in 43.46s`** (189 tes Minggu 3–11 tanpa regresi + 5 tes lengkap QR/JWT/scan/Excel/GradeService/AI di `tests/test_presensi.py` + 3 tes *property-based* Hypothesis di `tests/test_presensi_property.py`).
  - **Total Coverage: `95.77%` (`96%`)** (`app/models/presensi.py` 100%, `app/schemas/presensi.py` 100%, `app/routers/presensi.py` 100%, `app/services/exceptions.py` 100%, `app/main.py` 100%, `app/domain/presensi.py` 95%, `app/services/presensi_service.py` 94%, `app/services/attendance_ai.py` 90%).
- **Live `curl.exe` Verification (`uvicorn` port 8012 + salinan DB sementara):**
  - `GET /attendance/qr/39` → **`200 OK`** (`content-type: image/png`, header `x-attendance-token`, `x-session-id: 23`, `x-expires-at`).
  - `POST /attendance/scan` oleh mahasiswa non-peserta kelas (`2025001-0001` pada `IF207-A`) → **`403 Forbidden`**.
  - `GET /api/presensi/kelas/5/export.xlsx` (`IF102-A`) → **`200 OK`** (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, terbuka di `openpyxl` dengan 2 sheet `['Rekap Presensi', 'Log Kehadiran']`).
  - `GET /api/presensi/ai-insights` → **`200 OK`** menampilkan `3` mahasiswa warning `<75%`, pola absent `Senin pagi`, serta kelas `IF102-A` jam `08:00` dengan `absen_rate_persen: "55.56"`.

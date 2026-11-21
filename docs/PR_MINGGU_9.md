# Pull Request Minggu 9 — Modul Nilai & Transkrip Bagian 1: Grade Management, GPA Calculator, & Audit Trail (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan deliverable **Minggu 9 — Modul Nilai & Transkrip Bagian 1**:
  - **Domain & Migrasi `0007_nilai_grade_history_view.py` (`app/models/krs.py`, `app/models/nilai.py`):**
    - Mempertahankan `krs_detail.nilai` sebagai sumber kebenaran tunggal (*Single Source of Truth*, **ADR-016**) tanpa membuat tabel `grades` terpisah, meningkatkan tipe `skala_nilai.bobot` ke `Numeric(3, 2)` (`Decimal`), dan menambahkan kolom `skala_nilai.lulus` (`Boolean`) agar aturan kelulusan menjadi data.
    - Menambahkan tabel append-only `grade_history` (`grade_id -> krs_detail.id`, `old_value`, `new_value`, `changed_by -> dosen.id`, `changed_at` UTC, `reason`) beserta SQL view **`v_riwayat_nilai`** untuk membaca jejak riwayat lengkap dengan NIM, semester, kode MK, dan nama pengubah dalam 1 query.
  - **Fungsi Murni Kalkulator IPS/IPK & `GPACalculator` (`app/domain/gpa.py`, `app/services/gpa_calculator.py`):**
    - Mengimplementasikan domain murni `Skala`, `NilaiRecord`, `hitung_ips()`, dan `hitung_ipk()` bebas I/O menggunakan aritmetika **`Decimal`** (`ROUND_HALF_UP`, pembulatan **hanya sekali di akhir** `Decimal("0.01")`) serta mengurutkan logika IPK secara benar: pilih bobot terbaik per `kode_mk` dahulu, baru saring hanya yang `lulus == True`.
    - Mengimplementasikan `NilaiRepo` (termasuk `calculate_ipk_sql()` CTE Window Function `ROW_NUMBER()` untuk *differential test*) dan `GPACalculator` secara *compute-on-read* agar IPK tidak pernah basi.
  - **Grade Service, Dual Guards, `PresensiPort`, & Web Form UI (`app/services/grade_service.py`, `app/templates/nilai_form.html`, `app/routers/nilai.py`, `seed.py`):**
    - Mengimplementasikan `GradeService.input_nilai()` dengan dua penjaga: (1) `is_pengampu()` terhadap tabel `jadwal` (`403 Forbidden`), dan (2) `PresensiPort` (`MIN_PRESENSI = Decimal("75")`, `400 Bad Request` bila `< 75%`). Mendukung idempotency saat huruf tidak berubah, mewajibkan `alasan` saat mengubah nilai lama, serta menulis `krs_detail.nilai` dan `grade_history` dalam satu transaksi atomik (`BEGIN IMMEDIATE` / `with_for_update()`).
    - Menambahkan endpoint `GET /api/kelas/nilai-form` (UI HTML dosen), `GET /api/kelas`, `GET /api/kelas/{kelas_id}/peserta` (`X-Dosen-Id`), `PUT /api/kelas/{kelas_id}/nilai/{nim}`, `GET /api/mahasiswa/{nim}/ipk` (string 2 desimal), `GET /api/mahasiswa/{nim}/ips/{semester}`, `GET /api/mahasiswa/{nim}/nilai/riwayat`, exception handler `GradeError`, serta data demo Rina (`2025001-0002`, IPK `"3.08"`) & Sari (`2025001-0003`) di `seed.py`.
  - **Pengujian & ADR (`tests/test_gpa.py`, `tests/test_grade_service.py`, `tests/conftest.py`, `docs/ADR.md`):**
    - Menambahkan 21 unit & Hypothesis test di `tests/test_gpa.py` (`12` kasus `hitung_ipk` + tes `3.125 -> 3.13` `ROUND_HALF_UP` + `4` kasus `hitung_ips` + tes ubah data `skala.lulus` + `3` properti Hypothesis), 6 integrasi/guard/atomicity/CTE/UI test di `tests/test_grade_service.py`, serta **ADR-016** & **ADR-017**.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI membantu menyusun migrasi `0007`, modul domain murni `app/domain/gpa.py`, CTE window function `calculate_ipk_sql()`, `GradeService` + `PresensiPort`, template form HTML, suite uji Hypothesis + API, serta dokumentasi ADR-016/017 & OPAR ([prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- **Koreksi manual & temuan kritis mahasiswa:**
  1. **Deteksi Kontradiksi Spesifikasi `"≥ D (2.0)"`:** Menemukan konflik antara teks *"nilai ≥ D (2.0)"* pada bagian Business Rules dokumen tugas dan skala bobot baku (`D=1.0`, `C=2.0`) serta prasyarat Minggu 5 (`s.bobot >= 2.0`). Memutuskan tidak membiarkan AI menebak diam-diam: memindahkan status kelulusan ke kolom `skala_nilai.lulus` dengan asumsi sementara minimal `C` (`3.08` vs `2.67` pada contoh Rina) dan mencatat **open question** tertulis di ADR-016.
  2. **Pencegahan 7 Bug Klasik IPK & Konkurensi SQLite:** Memastikan pemakaian `Decimal` + `ROUND_HALF_UP` (bukan `float` + `round()` banker's rounding yang memberi `3.12`), membandingkan bobot `skala[huruf].bobot` (bukan `max(huruf)` string), memilih terbaik per `kode_mk` sebelum filter lulus, menghindari membulatkan IPS sebelum menghitung IPK, memulai `BEGIN IMMEDIATE` di `GradeService.input_nilai()` sebelum memanggil `is_pengampu()` agar SQLAlchemy tidak terlebih dulu membuka transaksi baca implisit, dan menghapus nilai sementara `IF204 = "B"` milik Rina di `20251` pada `seed_nilai_demo_data` setelah pengujian menangkap IPK seed Rina menjadi `"3.07"` alih-alih `"3.08"`.
- **3 Prompt Terbaik:**
  1. Sebutkan seluruh ambiguitas atau kontradiksi spesifikasi (khususnya *"Lulus MK jika nilai ≥ D (2.0)"* vs skala `D=1.0`/`C=2.0`) sebelum menulis kode, rancang migrasi `0007` menggunakan `skala_nilai.bobot Numeric(3,2)` + kolom `lulus`, serta `grade_history` yang merujuk `krs_detail.id` (tanpa tabel `grades` duplikat).
  2. Buat fungsi murni `app/domain/gpa.py` tanpa dependensi DB menggunakan `Decimal` + `ROUND_HALF_UP` (bulat 1x di akhir, pilih bobot terbaik per `kode_mk` dulu baru filter `lulus`), dilengkapi `NilaiRepo` + `calculate_ipk_sql` CTE `ROW_NUMBER()` untuk differential testing dan 12+ kasus + 3 properti Hypothesis.
  3. Implementasikan `GradeService` berpola Dependency Inversion (`PresensiPort`/`PresensiStub`) dengan penjaga ganda (`is_pengampu` `403` + presensi `>= 75%` `400`), idempotency `PUT` nilai sama, wajib alasan saat ubah nilai, pencatatan `GradeHistory` dalam satu transaksi atomik + view `v_riwayat_nilai`, serta UI HTML `/api/kelas/nilai-form`.

## Risiko & Limitasi
1. **Batas Lulus `D` vs `C` Menunggu Konfirmasi Stakeholder:** Asumsi sementara (`A/B/C` lulus, `D/E` tidak lulus) masih menunggu konfirmasi resmi dari dosen/bagian akademik sebagaimana dicatat di **ADR-016**.
2. **`PresensiPort` Masih Menggunakan Stub Lokal (`DemoPresensiStub` / `PresensiStub`):** Modul presensi nyata baru akan diintegrasikan pada Minggu 12, sehingga pemeriksaan `< 75%` saat ini mengandalkan stub demo yang dapat ditukar di DI FastAPI tanpa mengubah `GradeService`.
3. **Identitas Dosen (`X-Dosen-Id`) & Audit di Service Layer:** Identitas dosen login saat ini dibaca dari header demo `X-Dosen-Id` (bukan JWT terverifikasi), dan pencatatan `grade_history` berlangsung di layer service sehingga eksekusi `UPDATE` SQL mentah secara manual di luar API tidak otomatis masuk ke riwayat audit (mitigasi produksi: batasi privilege tulis SQL langsung per role DB).
4. **Cakupan Transkrip PDF (Minggu 10):** Endpoint `get_transcript(nim)`, generator transkrip PDF, predikat kelulusan (`Cum Laude`, dst.), tampilan historis nilai lanjutan, dan acceptance test multi-semester dijadwalkan pada Minggu 10.

## Cara Uji
```powershell
cd sevima-mini

# 1. Uji rantai migrasi Alembic 0007 & seeding idempotent (2x)
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed.py

# 2. Uji domain murni IPK/IPS & 3 properti Hypothesis
.\.venv\Scripts\pytest.exe tests/test_gpa.py -v

# 3. Jalankan seluruh suite pengujian (PMB + KRS + Jadwal + Nilai) beserta batas coverage 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 4. Demo form input nilai dosen & riwayat audit di browser
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# Buka http://127.0.0.1:8000/api/kelas/nilai-form dan http://127.0.0.1:8000/api/mahasiswa/2025001-0002/ipk
```

## Log Hasil Uji
- **Alembic Migration Chain (`0007_nilai_grade_history_view`):**
  - `upgrade head` -> `downgrade -1` -> `upgrade head` keluar kode `0` (`skala_nilai.bobot Numeric(3,2)`, `skala_nilai.lulus`, `grade_history`, dan SQL view `v_riwayat_nilai` berhasil dibuat dan di-rollback bersih di SQLite).
- **Seeding Idempotent (`seed.py` x2):**
  - Sukses 2x berturut-turut tanpa error/duplikasi, menghasilkan `SkalaNilai` ber-`Decimal` + `lulus`, serta dummy **Rina Pratama** (`2025001-0002`, IPK `"3.08"`) & **Sari Wulandari** (`2025001-0003`).
- **Pytest Pure Domain GPA (`pytest tests/test_gpa.py -v`):**
  - **`21 passed, 1 warning in 2.64s`** (12 kasus IPK, pembulatan `3.125 -> 3.13`, 4 kasus IPS, 1 tes ubah data `D.lulus`, dan 3 properti Hypothesis).
- **Full Pytest + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`153 passed, 1 warning in 33.60s`** (seluruh tes Minggu 3–9 lulus 100% tanpa regresi).
  - **Total Coverage: `95.50%` (`96%`)** (`app/domain/gpa.py` 100%, `app/models/nilai.py` 100%, `app/models/krs.py` 100%, `app/routers/nilai.py` 100%, `app/schemas/nilai.py` 100%, `app/services/exceptions.py` 100%, `app/main.py` 100%, `app/services/gpa_calculator.py` 96%, `app/services/grade_service.py` 96%).

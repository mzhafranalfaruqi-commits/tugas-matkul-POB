# Pull Request Minggu 6 — State Machine KRS, Approval Dosen PA, Property Testing, & CSP Recommender (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan deliverable **Minggu 6 — Modul KRS Bagian 2** (plus *Optional Challenge +10%* Rekomendasi KRS CSP):
  - **Enkapsulasi State Machine (`app/models/krs.py`):** Menambahkan enum `Actor` (`MAHASISWA`, `DOSEN_PA`), tabel transisi eksplisit `TRANSITIONS`, serta method `KRS.cek_transisi()` dan `KRS.transition()`. Tidak ada mutasi `krs.status = ...` langsung pada service maupun router.
  - **Migrasi `0004_krs_workflow_audit.py`:** Menambahkan kolom `submitted_at`, `approved_at`, `catatan_revisi`, `diubah_pada`, dan `version` (`__mapper_args__ = {"version_id_col": version}`) pada `krs`, serta membuat tabel `krs_log` dan `notifikasi` (persiapan pola *Observer* Minggu 7), lengkap dengan `downgrade()` berbasis `batch_alter_table` yang aman di SQLite.
  - **Unit of Work Atomik, Otorisasi Dua Lapis, & Optimistic Locking (`app/services/krs_manager.py`):**
    - Mengimplementasikan `submit_krs(nim)` (cek transisi dulu -> tolak KRS kosong -> jalankan ulang `validate_krs` -> log `SUBMIT`).
    - Mengimplementasikan `approve_krs(nim, dosen_pa_id, expected_version)` dan `revise_krs(nim, dosen_pa_id, catatan, expected_version)` dalam satu transaksi (`db.commit()` tunggal + `db.rollback()` penuh bila gagal).
    - Memisahkan HTTP `403 Forbidden` (`ForbiddenError`: aktor bukan Dosen PA pemilik mahasiswa) dari `409 Conflict` (`TransitionError`, `KRSLockedError`, `StaleVersionError`).
    - Memastikan `_sentuh_krs()` menaikkan `diubah_pada` setiap `add_course`/`remove_course` agar `version` selalu bertambah ketika detail KRS diubah.
  - **Exception Handler Polimorfik & 4 Endpoint Baru (`app/services/exceptions.py`, `app/main.py`, `app/routers/krs.py`):** Menambahkan satu handler `@app.exception_handler(KRSError)` serta endpoint `POST /api/krs/{nim}/submit`, `/approve`, `/revise`, dan `/recommend` lengkap dengan dokumentasi `responses={...}` OpenAPI.
  - **Optional Challenge (+10%) — CSP Recommender (`app/services/krs_recommender.py`):** Menyusun paket KRS optimal berbasis *CSP Backtracking + Branch-and-Bound* (prioritas `wajib > pilihan`, bebas bentrok jadwal, prasyarat lulus, `<= max_sks`) dengan *guardrail* wajib melewati rantai `default_krs_validators()` sebelum hasil dikembalikan.
  - **Property-Based Testing & Dokumentasi (`tests/test_krs_property.py`, `tests/test_krs.py`, `docs/ADR.md`):** Menambahkan uji `hypothesis` (`max_examples=1000`) untuk `SKSValidator` & `ConflictValidator` (dengan oracle independen `_slot()`), uji parametrik ke-28 kombinasi state transisi ilegal, serta mencatat `ADR-008` dan `ADR-009`.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI (Antigravity, Mistral, & Codeium) membantu menyusun struktur state machine, migrasi Alembic `0004`, kerangka CSP backtracking, dan test *property-based* `hypothesis`.
- **Koreksi manual & temuan kritis mahasiswa:**
  1. Menambahkan `_sentuh_krs()` (+1 mikrodetik monotonik) di `add_course()`/`remove_course()` karena perubahan pada tabel anak `krs_detail` tidak otomatis menaikkan `version` header `krs` dan resolusi `datetime` Windows dapat identik di eksekusi cepat.
  2. Memastikan test `hypothesis` memanggil validator produksi nyata (`SKSValidator` & `ConflictValidator`) tanpa memakai fungsi `bentrok()` sendiri di assertion maupun fixture DB di dalam `@given`.
  3. Memperbaiki test pembandingan versi yang awalnya terbaca sama karena SQLAlchemy Identity Map me-refresh objek ORM *in-place* seusai `commit()`, serta memfilter `ProgramStudi`/`JalurMasuk` agar tidak melempar `MultipleResultsFound`.
- **3 Prompt Terbaik:**
  1. Desain enkapsulasi state machine `KRS` (`Actor`, `TRANSITIONS`, `cek_transisi()`, `transition()`), kolom `version` optimistic lock, dan migrasi `0004` (`krs_log`, `notifikasi`) dengan `batch_alter_table` rollback aman.
  2. Implementasi `submit_krs`, `approve_krs`, dan `revise_krs` atomik dengan pemisahan `ForbiddenError` (`403`) vs `TransitionError`/`StaleVersionError` (`409`) melalui satu handler polimorfik `@app.exception_handler(KRSError)`.
  3. Perancangan `tests/test_krs_property.py` (`hypothesis` 1000x + oracle independen `_slot()`, serta 28 transisi ilegal `itertools.product` tanpa impor `TRANSITIONS`) dan `KRSRecommender` CSP dengan *guardrail* validator.

## Risiko & Limitasi
1. **Identitas Aktor `dosen_pa_id` via Request Body:** Endpoint `/api/krs/{nim}/approve` dan `/revise` saat ini menerima `dosen_pa_id` secara eksplisit di body JSON untuk menguji logika otorisasi kepemilikan (`403 Forbidden`) sebelum modul autentikasi JWT/session tersedia. Di produksi, nilai ini wajib diekstrak dari klaim token sesi terautentikasi.
2. **Engine Penguncian (SQLite vs MySQL/PostgreSQL):** Pengujian otomatis, concurrency test, dan `StaleDataError` dilakukan pada SQLite (`BEGIN IMMEDIATE`), bukan server MySQL InnoDB atau PostgreSQL. Perilaku *row-level lock* `SELECT ... FOR UPDATE` pada transaksi terdistribusi nyata perlu diverifikasi di DBMS produksi.
3. **Penyederhanaan Jadwal & Skala Katalog CSP:** Jadwal masih mengasumsikan 1 MK = 1 kelas di tabel `matakuliah`, sementara solver CSP backtracking diuji cepat pada ukuran katalog ~12–20 MK per semester dan memerlukan batas waktu atau heuristik lanjutan bila kandidat ratusan kelas paralel.

## Cara Uji
```powershell
cd sevima-mini

# 1. Uji rantai migrasi Alembic 0004 & seeding idempotent
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh suite pengujian (PMB + KRS + Hypothesis 1000x + 28 transisi ilegal + CSP)
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Jalankan server lokal & periksa Swagger UI (/docs) dan ReDoc (/redoc)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Log Hasil Uji
- **Alembic Migration Chain (`0004_krs_workflow_audit`):**
  - `upgrade head`: kolom `submitted_at`, `approved_at`, `catatan_revisi`, `diubah_pada`, `version` pada `krs` serta tabel `krs_log` dan `notifikasi` terbentuk di `sevima.db`.
  - `downgrade -1` -> `upgrade head` -> `seed.py` (2x idempotent): sukses keluar kode `0`.
- **Pytest + Hypothesis + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`83 passed, 1 warning in 25.56s`** (30 tes PMB + 18 tes KRS integrasi/concurrency/CSP + 35 tes `test_krs_property.py` mencakup 1000 contoh `SKSValidator`, 1000 contoh `ConflictValidator`, 28 transisi ilegal, & 4 transisi legal).
  - **Total Coverage: `96.00%` (`96%`)** (`app/models/krs.py` 100%, `app/routers/krs.py` 100%, `app/schemas/krs.py` 100%, `app/services/exceptions.py` 100%, `app/main.py` 100%, `app/services/krs_recommender.py` 98%, `app/services/krs_manager.py` 88%).
- **Live Server & OpenAPI Smoke Test (`uvicorn`):**
  - `/`, `/docs`, dan `/redoc` mengembalikan HTTP `200 OK`.
  - `/openapi.json` menampilkan semua 8 endpoint `/api/krs/*` (`/submit`, `/approve`, `/revise`, `/recommend`, dll.) lengkap dengan kode respons `403` dan `409`.

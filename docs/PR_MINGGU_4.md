# Pull Request Minggu 4 — Endpoint Approve, NIM Generator Anti Race Condition, & Testing (`sevima-mini`)

## Fitur & Isu
- Menindaklanjuti penyelarasan deliverable Minggu 3–4 Modul PMB (`#1 Skema DB & Migrasi`, `#2 Endpoint Approve, NIM Generator, & Testing`):
  - Menambahkan tabel atomik `nim_counter` (model `NimCounter` + migrasi Alembic [0002_tabel_nim_counter.py](../alembic/versions/0002_tabel_nim_counter.py)).
  - Menghapus jebakan arsitektural `threading.RLock()` dari `nim_generator.py` dan menggantinya dengan penguncian berbasis database (`SELECT ... FOR UPDATE` untuk MySQL/PostgreSQL serta `BEGIN IMMEDIATE` + `PRAGMA busy_timeout=30000` untuk SQLite), `db.flush()` atomik dalam satu transaksi, `UNIQUE` constraint + *retry* 3x.
  - Mengekstrak helper murni `format_nim(tahun, kode_prodi, nomor_urut)` beserta validasi batas maksimum `9999` (`ValueError("Nomor urut habis")`).
  - Merefaktor logika bisnis ke kelas OOP `PMBService` ([app/services/pmb_service.py](../app/services/pmb_service.py)), memisahkan HTTP `409 Conflict` (konflik status bukan `pending` / sudah `approved` saat reject) dari `400 Bad Request` (`DataNIMTidakValid`), dan melengkapi dokumentasi `responses={...}` OpenAPI pada [app/routers/pmb.py](../app/routers/pmb.py).
  - Mendokumentasikan resolusi ambiguitas format NIM (`2025001-0001`) di [docs/ADR.md](../docs/ADR.md) dan melengkapkan log AI + OPAR di [prompts/ai-usage-log.md](../prompts/ai-usage-log.md).

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI (Mistral, Codeium, & Antigravity) membantu menyusun kerangka awal model SQLAlchemy 2.0, endpoint FastAPI, migrasi Alembic, serta perluasan kasus uji `pytest`.
- **Revisi kritis oleh mahasiswa:** Menolak solusi AI berbasis `threading.Lock()` / `MAX(nim) + 1`, memindahkan penguncian ke level database (`nim_counter` + `FOR UPDATE`), memisahkan error status `409` vs data `400`, serta menjaga `generate_nim()` hanya memakai `db.flush()` bukan `db.commit()`.
- **3 Prompt Terbaik:**
  1. Prompt desain skema SQLAlchemy 2.0 `Mapped` + 5 constraint + rollback Alembic aman terhadap urutan FK (`prompts/ai-usage-log.md` — Minggu 3).
  2. Prompt refaktor kelas OOP `PMBService` + pemisahan kontrak HTTP `404` / `409 Conflict` / `400 Bad Request` + OpenAPI `responses={...}`.
  3. Prompt perancangan `generate_nim()` berbasis `nim_counter` tanpa `threading.Lock()`, lengkap dengan `format_nim()` murni dan transaksi atomik `db.flush()`.

## Risiko & Limitasi
- **Perbedaan Engine Database (SQLite vs MySQL/PostgreSQL):** Seluruh pengujian otomatis saat ini dijalankan menggunakan **SQLite** (in-memory `StaticPool` dan file sementara). Meskipun ORM sudah mengeluarkan klausa `SELECT ... FOR UPDATE` (`with_for_update()`), SQLite mengeksekusi penguncian pada level file/transaksi (`BEGIN IMMEDIATE`) dan mengabaikan `FOR UPDATE`. Perilaku *row-level locking* InnoDB MySQL atau PostgreSQL di bawah beban paralel nyata belum diuji langsung.
- **Belum Ada Uji Multi-Worker Process Nyata:** Uji concurrency memakai `ThreadPoolExecutor` (5 thread berbeda + 2 thread idempotency pada ID yang sama) dalam satu proses Python; benchmark multi-process (`uvicorn --workers N` / Gunicorn dengan Locust atau k6) tetap disarankan sebelum rilis produksi.
- **Kapasitas Penomoran Tahunan:** Format 4 digit running number membatasi maksimal `9999` mahasiswa baru yang disetujui per program studi per tahun (akan memunculkan `ValueError("Nomor urut habis")` jika terlampaui).

## Cara Uji
```powershell
cd sevima-mini

# 1. Uji rantai migrasi Alembic & seeding idempotent
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe downgrade base
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan unit, integration, & concurrency tests dengan batas minimal coverage 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Verifikasi server lokal, Swagger UI (/docs), & ReDoc (/redoc)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Log Hasil Uji
- **Alembic Migration Chain:**
  - `upgrade head`: `0001_tabel_pmb -> 0002_tabel_nim_counter` sukses (tabel `nim_counter` terbentuk dengan composite PK `tahun`, `kode_prodi`, dan default `last_number=0`).
  - `downgrade -1` & `downgrade base`: sukses menghapus tabel anak hingga bersih tanpa error FK.
  - `upgrade head` + `seed.py` (dijalankan 2x): sukses & idempotent (`3` prodi, `3` jalur masuk).
- **Pytest + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`30 passed, 1 warning in 5.33s`**
  - **Total Coverage: `96.75%` (`97%`)** — melewati ambang batas minimal `80%`.
  - Modul inti (`app/models/pmb.py`, `app/schemas/pmb.py`, `app/services/nim_generator.py`, `app/services/exceptions.py`, `app/routers/pmb.py`, `app/database.py`, `app/main.py`) mencapai **100% coverage**; `app/services/pmb_service.py` mencapai **91% coverage**.
- **Live Server & OpenAPI Smoke Test (`uvicorn`):**
  - `/`, `/docs`, `/redoc`, `/openapi.json`, dan `/api/pmb/stats` mengembalikan HTTP `200 OK`.
  - `/openapi.json` terverifikasi mencantumkan respons `['200', '400', '404', '409', '422']` untuk `PUT /api/pmb/approve/{pendaftar_id}` dan `['200', '404', '409', '422']` untuk `PUT /api/pmb/reject/{pendaftar_id}`.

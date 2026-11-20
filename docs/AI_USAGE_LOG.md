# AI Usage Log — Implementasi Modul PMB SEVIMA-Mini (Minggu 3–4)

Catatan ini mendokumentasikan penggunaan asisten AI selama perancangan skema database, implementasi REST API, perbaikan arsitektur NIM generator berbasis database lock pada Minggu 4, hingga penyusunan unit test dan evaluasi kritisnya. Versi terstruktur sesuai format silabus + kerangka **OPAR** (*Observe, Plan, Act, Reflect*) tersedia lengkap pada [prompts/ai-usage-log.md](../prompts/ai-usage-log.md).

## Kepatuhan AI-First Charter

1. **Perlindungan Data Pribadi (PII):** Seluruh prompt, fixture pengujian, dan contoh skema menggunakan data *dummy* fiktif (seperti `"Budi Santoso"`, `"budi1@example.com"`, `"081234567890"`). Tidak ada data pribadi mahasiswa asli yang dikirim ke layanan AI.
2. **Prinsip Validasi:** Tidak ada kode hasil generasi AI yang langsung disalin tanpa ditinjau, diperiksa kesesuaian arsitekturnya, disesuaikan dengan pustaka target (SQLAlchemy 2.0, Pydantic v2), dan diuji melalui Alembic serta `pytest`.

---

## Ringkasan Sesi Penggunaan AI

| Sesi | Tahap Tugas | Tools AI | Masalah / Temuan Kritis pada Output AI | Keputusan Mahasiswa |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Skema Database & Migrasi Alembic (`0001`) | Mistral (HF Inference) | Prompt awal tugas lupa mendeskripsikan tabel `jalur_masuk`, AI cenderung pakai gaya lama `declarative_base()`, mengusulkan `REGEXP` di SQLite, dan melewatkan `PRAGMA foreign_keys=ON`. | Merevisi prompt ke SQLAlchemy 2.0 `Mapped`, memisahkan `jalur_masuk` menjadi tabel FK, memakai `create_constraint=True`, serta menyalakan pragma FK SQLite. |
| 2 | REST API & Validasi Input | Mistral & Codeium | Default FastAPI memunculkan HTTP `422` untuk error Pydantic, sedangkan rubrik uji membutuhkan `400`; respons awal sempat berisiko mengembalikan field sensitif (`alamat`, `tanggal_lahir`). | Menambahkan exception handler `RequestValidationError` → `400`, memisahkan `RegisterRequest` dan `PendaftarOut`, serta memetakan `IntegrityError` ke `409 Conflict`. |
| 3 | Pembaruan Minggu 4: `PMBService`, `409 Conflict`, & NIM Generator Anti Race Condition | Mistral & Antigravity | Output awal Minggu 3 memakai `threading.RLock()` dan `MAX(nim) + 1`, padahal lock Python gagal di lingkungan multi-worker/multi-server; status conflict `rejected -> approve` sempat disamakan ke `400`. | **Menghapus `threading.Lock()`**, menambah tabel `nim_counter` (`0002_tabel_nim_counter.py`), memakai `with_for_update()` + `BEGIN IMMEDIATE` + `db.flush()` + `UNIQUE` + retry, memecah `format_nim()`, dan memetakan konflik status ke **`409 Conflict`**. |
| 4 | Strategi Pengujian `pytest` & OpenAPI Docs | Codeium & Antigravity | Tes awal belum menguji fungsi murni `format_nim()` tanpa DB, overflow batas `9999`, atomicity rollback bila commit gagal, race condition idempotency pada ID yang sama, maupun kode `400` untuk kode prodi tidak valid. | Menambahkan tes unit murni `format_nim()`, tes overflow & atomicity rollback, tes paralel 5 pendaftar + 2 thread idempotency pada file DB sementara, tes `400`/`409` pada approve/reject, dan validasi schema `/openapi.json` serta `/redoc`. |

---

## Detail Prompt Terbaik & Evaluasi Kritis

### Prompt Terbaik 1 — Skema SQLAlchemy 2.0 & Migrasi Rollback Aman
> "Desain skema database PMB untuk sistem akademik menggunakan SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`, `mapped_column`) dengan tabel `program_studi`, `jalur_masuk`, `calon_mahasiswa`, dan `nim_counter` (`tahun`, `kode_prodi`, `last_number`). Sertakan migrasi Alembic `upgrade()` dan `downgrade()` yang aman terhadap urutan foreign key, dan jelaskan constraint yang ditegakkan di DB vs Pydantic."

- **Evaluasi Kritis:** Memastikan kolom `phone` bertipe `String(15)` (bukan `Integer`), `PRAGMA foreign_keys=ON` aktif di SQLite, dan `create_constraint=True` dipasang pada `Enum` status agar constraint tersimpan eksplisit di skema DB.

### Prompt Terbaik 2 — Endpoint OOP `PMBService` & Kontrak HTTP Code
> "Refaktor service layer menjadi kelas OOP `PMBService` dan router tipis `/api/pmb/*` lengkap dengan anotasi OpenAPI `responses={...}`. Pisahkan HTTP status code pada `PUT /approve/{id}` dan `PUT /reject/{id}`: `404` bila ID tidak ada, `409 Conflict` bila konflik status (`StatusTidakValid`: bukan `pending` atau sudah `approved` saat reject), dan `400` bila data tidak valid untuk NIM (`DataNIMTidakValid`)."

- **Evaluasi Kritis:** Mencegah pencampuran kesalahan validasi payload (`400`) dengan pelanggaran alur status (`409`), sekaligus mendokumentasikan setiap skenario respons di Swagger UI `/docs` dan ReDoc `/redoc`.

### Prompt Terbaik 3 — NIM Generator Tanpa `threading.Lock()` (Database-Level Locking)
> "Refactor `generate_nim(tahun, kode_prodi, db)` agar tidak menggunakan `threading.Lock()` atau `MAX(nim) + 1`. Gunakan tabel `nim_counter` dengan `with_for_update()` untuk MySQL/PostgreSQL serta `BEGIN IMMEDIATE` dan `PRAGMA busy_timeout` untuk SQLite. Pastikan `generate_nim()` hanya memanggil `db.flush()` (bukan `db.commit()`), terbungkus satu transaksi bersama `PMBService.approve()`, dan lindungi dengan constraint `UNIQUE` + retry loop."

- **Evaluasi Kritis:** Jika `generate_nim()` memanggil `db.commit()` sendiri, kegagalan penyimpanan `calon_mahasiswa` tetap menyisakan kenaikan counter (nomor urut hilang/melompat). Menyatukan transaksi di `PMBService.approve()` dengan `db.flush()` memastikan sifat atomik (*all-or-nothing*).

---

## Ringkasan Verifikasi Akhir & OPAR

- **Migrasi Alembic:** `0001_tabel_pmb` → `0002_tabel_nim_counter` (`upgrade head`, `downgrade -1`, `downgrade base`, `upgrade head`, `seed.py` x2) berjalan tanpa error.
- **Test Suite & Coverage:** **`30 passed in 5.33s`**, total coverage **`96.75%`** (`97%`), memenuhi syarat minimal `--cov-fail-under=80`.
- **Refleksi Limitasi (OPAR — Reflect):** Uji paralel multi-thread berhasil membuktikan konsistensi penomoran di SQLite tanpa lock Python, namun perilaku *row lock* `SELECT ... FOR UPDATE` pada InnoDB MySQL/PostgreSQL tetap perlu diverifikasi di lingkungan DBMS client-server sebelum produksi. Detail OPAR lengkap terdokumentasi di [prompts/ai-usage-log.md](../prompts/ai-usage-log.md).

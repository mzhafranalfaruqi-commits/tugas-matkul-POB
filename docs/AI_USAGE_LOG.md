# AI Usage Log — Implementasi Modul PMB SEVIMA-Mini (Minggu 3–4)

Catatan ini mendokumentasikan penggunaan asisten AI selama perancangan skema database, implementasi REST API, pembuatan generator NIM *thread-safe*, hingga penyusunan unit test, beserta hasil evaluasi kritis terhadap setiap output AI.

## Kepatuhan AI-First Charter

1. **Perlindungan Data Pribadi (PII):** Seluruh prompt, fixture pengujian, dan contoh skema menggunakan data *dummy* fiktif (seperti `"Budi Santoso"`, `"budi1@example.com"`, `"081234567890"`). Tidak ada data pribadi mahasiswa asli yang dikirim ke layanan AI.
2. **Prinsip Validasi:** Tidak ada kode hasil generasi AI yang langsung disalin tanpa ditinjau, disesuaikan dengan versi pustaka terbaru (SQLAlchemy 2.0, Pydantic v2), dan diuji dengan Alembic serta `pytest`.

---

## Ringkasan Sesi Penggunaan AI

| Sesi | Tahap Tugas | Tools AI | Masalah / Temuan Kritis pada Output AI | Keputusan Mahasiswa |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Skema Database & Migrasi Alembic | Mistral (HF Inference) | Prompt awal tugas lupa mendeskripsikan tabel `jalur_masuk`, AI cenderung pakai gaya lama `declarative_base()`, mengusulkan `REGEXP` di SQLite, dan melewatkan `PRAGMA foreign_keys=ON`. | Merevisi prompt dengan gaya SQLAlchemy 2.0 `Mapped`, memisahkan `jalur_masuk` menjadi tabel FK, memakai `create_constraint=True`, serta menyalakan pragma FK SQLite. |
| 2 | REST API & Validasi Input | Mistral & Codeium | Default FastAPI memunculkan HTTP `422` untuk error Pydantic, sedangkan rubrik uji membutuhkan `400`; selain itu response awal sempat berisiko mengembalikan field sensitif (`alamat`, `tanggal_lahir`). | Menambahkan exception handler `RequestValidationError` → `400`, memisahkan skema `RegisterRequest` dan `PendaftarOut`, serta memetakan `IntegrityError` ke `409 Conflict`. |
| 3 | Thread-Safe NIM Generator | Mistral (HF Inference) | Implementasi awal hanya mengandalkan `MAX(nim) + 1` tanpa lock atau baru mengunci di dalam `generate_nim()` saja (sehingga celah *race condition* tetap muncul sebelum `commit()` di service). | Memindahkan `threading.RLock()` hingga mencakup siklus baca-generate-commit di `approve()`, menambahkan `with_for_update()` pada `ProgramStudi` untuk MySQL/PostgreSQL, dan constraint `UNIQUE` + retry. |
| 4 | Strategi Pengujian `pytest` | Codeium & Mistral | Tes awal hanya memakai happy path dan belum menguji constraint SQLite secara langsung maupun simulasi eksekusi paralel (`ThreadPoolExecutor`). | Menambahkan fixture in-memory `StaticPool` dengan FK aktif, tes parametrik format HP/email, tes idempotency, tes concurrency multi-thread pada file DB sementara, dan tes constraint DB langsung. |

---

## Detail Prompt & Evaluasi Kritis

### Sesi 1 — Perancangan Skema Database & Migrasi Alembic

- **Prompt Awal (dari modul tugas, dikritisi sebelum dipakai):**  
  Prompt pada modul menuliskan `jalur_masuk (SNBP/SNBT/Mandiri)` sebagai kolom, padahal deliverable tugas mewajibkan 3 tabel: `calon_mahasiswa`, `program_studi`, dan `jalur_masuk`. Selain itu tidak ada penyebutan versi SQLAlchemy 2.0.
- **Prompt Revisi (Prompt Terbaik Sesi 1):**
  > "Desain skema database PMB untuk sistem akademik menggunakan SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`, `mapped_column`) dengan 3 tabel: `program_studi` (id, kode 3 char unique, nama, fakultas), `jalur_masuk` (id, nama unique), dan `calon_mahasiswa` (id, nama_lengkap, email unique + index, phone string 15, tanggal_lahir, alamat, `program_studi_id` FK, `jalur_masuk_id` FK, status enum `pending`/`approved`/`rejected` dengan `create_constraint=True`, nim nullable unique, `created_at` server_default now, `approved_at` nullable). Sertakan skrip migrasi Alembic dengan `upgrade()` dan `downgrade()` yang memperhatikan urutan foreign key, serta jelaskan constraint mana yang ditegakkan di DB dan di Pydantic."
- **Hasil Verifikasi:**  
  - Tipe kolom `phone` dipastikan memakai `String(15)` (bukan `Integer` agar angka `0` di depan dan tanda `+62` tidak hilang).
  - SQLite tidak mendukung `REGEXP` bawaan pada `CHECK constraint`, sehingga pola regex nomor HP Indonesia (`^(\+62|62|0)8[1-9][0-9]{6,10}$`) diletakkan di Pydantic, sedangkan SQLite menegakkan `length(phone) BETWEEN 9 AND 15`, `email LIKE '%_@%_._%'`, `NOT NULL`, `UNIQUE`, enum `CHECK`, dan `FOREIGN KEY` (dengan `PRAGMA foreign_keys=ON`).
  - Urutan `downgrade()` diuji untuk menghapus `calon_mahasiswa` terlebih dahulu sebelum `jalur_masuk` dan `program_studi`.

### Sesi 2 — Implementasi Endpoint FastAPI & Error Handling

- **Prompt Terbaik Sesi 2:**
  > "Dengan model SQLAlchemy `app/models/pmb.py` dan skema Pydantic v2 `app/schemas/pmb.py` terlampir, buat struktur terpisah `app/services/pmb_service.py` dan router tipis `app/routers/pmb.py` untuk endpoint `/api/pmb/register` (201), `/api/pmb/status/{id}` (200/404), `/api/pmb/approve/{id}` (200/400/404), `/api/pmb/reject/{id}` (200/400/404), dan `/api/pmb/stats` (200). Gunakan dependency injection `Depends(get_db)`. Tangani duplicate email menjadi `409 Conflict` termasuk fallback `IntegrityError`, referensi prodi/jalur tidak valid menjadi `400`, dan ubah `RequestValidationError` FastAPI menjadi `400 Bad Request`."
- **Hasil Verifikasi:**  
  - Pemisahan router dan service (*Single Responsibility Principle*) membuat logika bisnis mudah diuji tanpa harus selalu menembak HTTP.
  - Email dinormalisasi menjadi huruf kecil di validator Pydantic sehingga `BUDI1@Example.COM` dan `budi1@example.com` tetap terdeteksi sebagai duplikat.
  - Respons error validasi tervalidasi mengembalikan kode `400` dan pesan ramah tanpa membocorkan *stack trace* internal.

### Sesi 3 — Implementasi Generator NIM Thread-Safe & Idempotent

- **Prompt Terbaik Sesi 3:**
  > "Buat fungsi `generate_nim(tahun: int, kode_prodi: str, db: Session) -> str` dengan format `[Tahun:4][Kode Prodi:3]-[Running Number:4]` (contoh: `2025001-0001`). Jelaskan mekanisme pencegahan *race condition* untuk SQLite maupun MySQL/PostgreSQL, serta integrasikan ke fungsi `approve()` agar bersifat *idempotent* (tidak men-generate NIM baru jika status sudah `approved`) dan menolak pendaftar berstatus `rejected`."
- **Hasil Verifikasi:**  
  - Mengamati bahwa bila kunci (`lock`) hanya dipasang di dalam `generate_nim()`, dua thread masih bisa mendapat nomor urut sama jika thread A belum melakukan `db.commit()`. Solusinya adalah mengunci seluruh transaksi baca-generate-commit menggunakan `threading.RLock()` di `approve()`, dibantu `with_for_update()` pada baris `program_studi` untuk DB production serta constraint `UNIQUE` + retry loop.

### Sesi 4 — Penyusunan Suite Pengujian `pytest`

- **Prompt Terbaik Sesi 4:**
  > "Buatkan test suite `pytest` di `tests/conftest.py` dan `tests/test_pmb.py` menggunakan SQLite in-memory (`StaticPool` dengan `PRAGMA foreign_keys=ON`) dan `TestClient` FastAPI via override `get_db`. Uji seluruh kasus wajib: registrasi sukses (201), duplikat email (409), validasi format HP dan email invalid (400), sequential NIM dan idempotency saat approve 2x, approve pada data invalid/rejected, reject, stats, uji paralel `ThreadPoolExecutor` untuk race condition NIM, dan uji constraint database langsung."
- **Hasil Verifikasi:**  
  - Seluruh kasus uji berhasil dijalankan dengan `pytest --cov=app --cov-report=term-missing` dengan seluruh test lulus dan coverage di atas ambang minimal 80%.

---

## Ringkasan Prompt Terbaik & Pembelajaran Utama

Prompt yang paling efektif adalah prompt yang **menyertakan konteks kode nyata (nama file, model, dan struktur folder)**, **menyebutkan versi teknologi secara spesifik** (SQLAlchemy 2.0 `Mapped`, Pydantic v2), **menjabarkan kontrak status code secara eksplisit**, serta **meminta penjelasan kompromi arsitektural** (misalnya batasan SQLite vs MySQL). Tanpa pengawasan manusia terhadap detail kecil seperti `create_constraint=True`, `PRAGMA foreign_keys=ON`, dan cakupan lock transaksi, kode hasil AI masih rentan lolos secara sintaks namun gagal menegakkan integritas data di lapangan.

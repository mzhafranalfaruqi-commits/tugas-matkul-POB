# Architecture Decision Records (ADR) — Modul PMB SEVIMA-Mini

Dokumen ini mencatat keputusan arsitektural dan teknis utama dalam mengimplementasikan modul Penerimaan Mahasiswa Baru (PMB) pada proyek **SEVIMA-Mini** (Minggu 3–4), sebagai kelanjutan dari artefak desain UML pada Minggu 1–2.

---

## ADR-001: Pemilihan FastAPI dan Pydantic v2 untuk REST API Modul PMB

- **Status:** Diterima
- **Konteks:**  
  Modul PMB membutuhkan REST API dengan dokumentasi interaktif (Swagger/OpenAPI), validasi payload JSON yang ketat (termasuk format email dan pola nomor seluler Indonesia), serta dependency injection untuk manajemen session database per request.
- **Keputusan:**  
  Menggunakan **FastAPI** sebagai web framework dan **Pydantic v2** untuk layer skema validasi (`app/schemas/pmb.py`), dipadukan dengan arsitektur berlapis (*router* tipis → *service* bisnis → *model* ORM) sesuai prinsip *Single Responsibility Principle* (SRP).
- **Konsekuensi & Pertimbangan:**  
  - FastAPI otomatis menghasilkan dokumentasi Swagger UI di `/docs` dan skema OpenAPI di `/openapi.json` tanpa konfigurasi tambahan.
  - Skema response terpisah (`PendaftarOut`, `StatusPendaftaranOut`, `ApproveOut`) mencegah kebocoran kolom sensitif seperti `alamat` dan `tanggal_lahir` saat respons pendaftaran dikembalikan.
  - Ketergantungan terhadap `pydantic[email]` (`email-validator`) harus dicantumkan eksplisit di `requirements.txt` agar tipe `EmailStr` dapat berjalan.

---

## ADR-002: Penggunaan SQLite (Development), SQLAlchemy 2.0 (`Mapped`), dan Alembic

- **Status:** Diterima
- **Konteks:**  
  Spesifikasi tugas mewajibkan 3 tabel (`calon_mahasiswa`, `program_studi`, `jalur_masuk`), 5 constraint utama (unique email, validasi format HP, status enum, `NOT NULL`, dan foreign key), serta skrip migrasi dengan kemampuan *rollback*.
- **Keputusan:**  
  1. Menggunakan **SQLite** untuk tahap pengembangan dan pengujian lokal karena ringan (berbasis berkas tunggal/in-memory) dan tidak memerlukan server database terpisah, sambil tetap menjaga kompatibilitas ke MySQL/PostgreSQL lewat SQLAlchemy ORM.
  2. Menggunakan sintaks **SQLAlchemy 2.0** (`DeclarativeBase`, `Mapped[...]`, `mapped_column(...)`) alih-alih gaya lama (`Column(...)` tanpa `Mapped`).
  3. Mengaktifkan `PRAGMA foreign_keys=ON` melalui *event listener* `connect` di `app/database.py` dan `alembic/env.py`, karena secara bawaan SQLite menonaktifkan penegakan *foreign key*.
  4. Menggunakan `SAEnum(StatusPMB, name="status_pmb", create_constraint=True)` agar SQLite tetap membentuk `CHECK constraint` pada kolom `status`, serta mengganti validasi `REGEXP` di database dengan `CheckConstraint` berbasis SQL standar (`length(phone)` dan `email LIKE '%_@%_._%'`) karena SQLite tidak memiliki fungsi `REGEXP` bawaan.
  5. Mengelola migrasi dengan **Alembic** (`0001_tabel_pmb.py`) yang menyediakan `upgrade()` (tabel induk dahulu baru tabel anak) dan `downgrade()` (tabel anak dihapus lebih dulu sebelum tabel induk).
- **Konsekuensi & Pertimbangan:**  
  - Validasi regex nomor HP seluler Indonesia (`^(\+62|62|0)8[1-9][0-9]{6,10}$`) dijalankan pada lapis pertama di Pydantic, sementara lapis kedua di SQLite menegakkan tipe teks, panjang (`9..15`), `NOT NULL`, `UNIQUE`, `CHECK` enum, dan `FOREIGN KEY`.
  - Kolom `nim` disimpan sebagai `String(15)` yang *nullable* dan *unique* sejak migrasi awal agar alur approval di Minggu 4 langsung siap tanpa perubahan tabel mendadak.

---

## ADR-003: Penyeragaman HTTP Status Code `400 Bad Request` untuk Error Validasi Input

- **Status:** Diterima
- **Konteks:**  
  Secara default, FastAPI mengembalikan kode status `422 Unprocessable Entity` ketika Pydantic gagal memvalidasi payload (`RequestValidationError`). Namun, spesifikasi pengujian pada dokumen tugas Minggu 3–4 secara eksplisit meminta `test_invalid_phone_format: return 400`.
- **Keputusan:**  
  Mendaftarkan custom exception handler `@app.exception_handler(RequestValidationError)` di `app/main.py` untuk mengembalikan HTTP `400 Bad Request` dengan struktur JSON `{"detail": ...}` yang tetap informatif, sekaligus menyamakan perilaku dengan error aturan bisnis/referensi tidak valid di service layer (`400 Bad Request`).
- **Konsekuensi & Pertimbangan:**  
  - Seluruh kegagalan validasi format input (nomor HP invalid, email invalid, tanggal lahir di masa depan, referensi prodi/jalur tidak ada) konsisten menghasilkan kode status `400`.
  - Duplikasi email dipisahkan secara tegas dengan kode status `409 Conflict`, dan ID pendaftar yang tidak ditemukan dikembalikan sebagai `404 Not Found`.

---

## ADR-004: Strategi Idempotency dan Penanganan Race Condition pada Generator NIM

- **Status:** Diterima
- **Konteks:**  
  Endpoint `PUT /api/pmb/approve/{id}` harus menghasilkan NIM berformat `[Tahun:4][Kode Prodi:3]-[Running Number:4]` (contoh: `2025001-0001`), harus *idempotent* (tidak membuat NIM baru bila pendaftar sudah berstatus `approved`), dan aman terhadap *race condition* ketika beberapa request approval datang bersamaan.
- **Keputusan:**  
  1. **Idempotency:** Sebelum memanggil `generate_nim()`, `pmb_service.approve()` memeriksa status pendaftar. Jika `status == StatusPMB.approved` dan `nim` sudah terisi, fungsi langsung mengembalikan data yang sama (`already_approved=True`) tanpa memodifikasi `nim` maupun `approved_at`. Jika pendaftar berstatus `rejected`, sistem menolak dengan `400 Bad Request`.
  2. **Thread-safety & Database Locking:** Menggunakan `threading.RLock()` (`_nim_lock`) di dalam proses Python yang melingkupi pembacaan nomor urut terakhir hingga `db.commit()`, ditambah query `SELECT ... FOR UPDATE` pada baris `program_studi` terkait untuk dialek non-SQLite (MySQL/PostgreSQL).
  3. **Pertahanan Lapis Terakhir:** Kolom `nim` diberi constraint `UNIQUE` di database, disertai mekanisme *retry* hingga 3 kali apabila terjadi `IntegrityError` antar-proses yang berbeda.
- **Konsekuensi & Pertimbangan:**  
  - Dua atau lebih thread yang menyetujui pendaftar pada prodi dan tahun yang sama secara bersamaan tetap memperoleh nomor urut yang terurut dan unik tanpa duplikasi NIM.
  - Karena menggunakan *row lock* pada `program_studi` di mode produksi (MySQL/PostgreSQL), antrean penguncian terjadi per program studi, sehingga prodi yang berbeda tetap dapat diproses paralel tanpa saling menghambat.

# Architecture Decision Records (ADR) — Modul PMB SEVIMA-Mini

Dokumen ini mencatat keputusan arsitektural dan teknis utama dalam mengimplementasikan modul Penerimaan Mahasiswa Baru (PMB) pada proyek **SEVIMA-Mini** (Minggu 3–4), sebagai kelanjutan dari artefak desain UML pada Minggu 1–2.

---

## ADR-001: Pemilihan FastAPI dan Pydantic v2 untuk REST API Modul PMB

- **Status:** Diterima
- **Konteks:**  
  Modul PMB membutuhkan REST API dengan dokumentasi interaktif (Swagger/OpenAPI `/docs` dan ReDoc `/redoc`), validasi payload JSON yang ketat (termasuk format email dan pola nomor seluler Indonesia), serta dependency injection untuk manajemen session database per request.
- **Keputusan:**  
  Menggunakan **FastAPI** sebagai web framework dan **Pydantic v2** untuk layer skema validasi (`app/schemas/pmb.py`), dipadukan dengan arsitektur berlapis (*router* tipis → *service* OOP `PMBService` → *model* ORM) sesuai prinsip *Single Responsibility Principle* (SRP).
- **Konsekuensi & Pertimbangan:**  
  - FastAPI otomatis menghasilkan dokumentasi Swagger UI di `/docs`, ReDoc di `/redoc`, dan skema OpenAPI di `/openapi.json` lengkap dengan anotasi `responses={...}` pada setiap endpoint.
  - Skema response terpisah (`PendaftarOut`, `StatusPendaftaranOut`, `ApproveOut`) mencegah kebocoran kolom sensitif seperti `alamat` dan `tanggal_lahir` saat respons pendaftaran dikembalikan.
  - Ketergantungan terhadap `pydantic[email]` (`email-validator`) harus dicantumkan eksplisit di `requirements.txt` agar tipe `EmailStr` dapat berjalan.

---

## ADR-002: Penggunaan SQLite (Development), SQLAlchemy 2.0 (`Mapped`), dan Alembic

- **Status:** Diterima
- **Konteks:**  
  Spesifikasi tugas mewajibkan tabel referensi dan transaksional (`calon_mahasiswa`, `program_studi`, `jalur_masuk`, serta diperkuat tabel `nim_counter` pada Minggu 4), 5 constraint utama (unique email, validasi format HP, status enum, `NOT NULL`, dan foreign key), serta skrip migrasi dengan kemampuan *rollback*.
- **Keputusan:**  
  1. Menggunakan **SQLite** untuk tahap pengembangan dan pengujian lokal karena ringan (berbasis berkas tunggal/in-memory) dan tidak memerlukan server database terpisah, sambil tetap menjaga kompatibilitas ke MySQL/PostgreSQL lewat SQLAlchemy ORM.
  2. Menggunakan sintaks **SQLAlchemy 2.0** (`DeclarativeBase`, `Mapped[...]`, `mapped_column(...)`) alih-alih gaya lama (`Column(...)` tanpa `Mapped`).
  3. Mengaktifkan `PRAGMA foreign_keys=ON` dan `PRAGMA busy_timeout=30000` melalui *event listener* `connect` di `app/database.py` (serta `PRAGMA foreign_keys=ON` di `alembic/env.py`), karena secara bawaan SQLite menonaktifkan penegakan *foreign key*.
  4. Menggunakan `SAEnum(StatusPMB, name="status_pmb", create_constraint=True)` agar SQLite tetap membentuk `CHECK constraint` pada kolom `status`, serta mengganti validasi `REGEXP` di database dengan `CheckConstraint` berbasis SQL standar (`length(phone)` dan `email LIKE '%_@%_._%'`) karena SQLite tidak memiliki fungsi `REGEXP` bawaan.
  5. Mengelola migrasi secara bertahap dengan **Alembic** (`0001_tabel_pmb.py` dan `0002_tabel_nim_counter.py`) yang mendukung `upgrade head` maupun `downgrade` yang aman terhadap urutan foreign key.
- **Konsekuensi & Pertimbangan:**  
  - Validasi regex nomor HP seluler Indonesia (`^(\+62|62|0)8[1-9][0-9]{6,10}$`) dijalankan pada lapis pertama di Pydantic, sementara lapis kedua di SQLite menegakkan tipe teks, panjang (`9..15`), `NOT NULL`, `UNIQUE`, `CHECK` enum, dan `FOREIGN KEY`.
  - Kolom `nim` disimpan sebagai `String(15)` yang *nullable* dan *unique* sejak migrasi awal, sementara penomoran berurutan atomik ditopang oleh tabel `nim_counter` pada migrasi `0002_tabel_nim_counter.py`.

---

## ADR-003: Penyeragaman HTTP Status Code `400 Bad Request` untuk Error Validasi Input

- **Status:** Diterima
- **Konteks:**  
  Secara default, FastAPI mengembalikan kode status `422 Unprocessable Entity` ketika Pydantic gagal memvalidasi payload atau query (`RequestValidationError`). Namun, spesifikasi pengujian pada dokumen tugas Minggu 3–4 secara eksplisit meminta `test_invalid_phone_format: return 400`.
- **Keputusan:**  
  Mendaftarkan custom exception handler `@app.exception_handler(RequestValidationError)` di `app/main.py` untuk mengembalikan HTTP `400 Bad Request` dengan struktur JSON `{"detail": ...}` yang tetap informatif, sekaligus menyamakan perilaku dengan error referensi atau data NIM tidak valid di service layer (`400 Bad Request`).
- **Konsekuensi & Pertimbangan:**  
  - Seluruh kegagalan validasi format input (nomor HP invalid, email invalid, tanggal lahir di masa depan, referensi prodi/jalur tidak ada, parameter `tahun` di luar rentang, atau kode prodi bukan 3 digit) konsisten menghasilkan kode status `400`.
  - Duplikasi email maupun konflik transisi status dipisahkan dengan kode status `409 Conflict`, dan ID pendaftar yang tidak ditemukan dikembalikan sebagai `404 Not Found`.

---

## ADR-004: Strategi Idempotency dan Pencegahan Race Condition Berbasis Database Lock (`nim_counter`)

- **Status:** Diperbarui pada Minggu 4 (menggantikan pendekatan awal berbasis `threading.RLock()`).
- **Konteks:**  
  Endpoint `PUT /api/pmb/approve/{id}` harus menghasilkan NIM secara berurutan, bersifat *idempotent*, dan bebas *race condition* ketika beberapa request approval datang bersamaan. Pendekatan awal yang mengandalkan `threading.RLock()` di Python hanya melindungi thread dalam **satu proses memori**, sehingga gagal mencegah nomor ganda apabila aplikasi dijalankan dengan multi-worker (`uvicorn --workers N` / Gunicorn) atau beberapa container.
- **Keputusan:**  
  1. **Hapus Lock Memori Proses (`threading.RLock`):** Memindahkan seluruh koordinasi antrean ke level database agar tetap aman untuk arsitektur multi-worker maupun single-worker.
  2. **Tabel Counter Atomik (`nim_counter`):** Menambahkan model `NimCounter` (melalui migrasi `0002_tabel_nim_counter.py`) dengan *composite primary key* `(tahun, kode_prodi)` dan kolom `last_number`.
  3. **Database Locking & Satu Transaksi Atomik:**
     - Pada DBMS client-server (MySQL InnoDB/PostgreSQL), `PMBService.approve()` mengunci baris `calon_mahasiswa` dengan `with_for_update=True` dan `generate_nim()` mengunci baris `nim_counter` dengan `SELECT ... FOR UPDATE` (`with_for_update()`).
     - Pada SQLite (yang mengabaikan sintaks `FOR UPDATE`), `PMBService.approve()` memulai transaksi tulis eksplisit `BEGIN IMMEDIATE` disertai `PRAGMA busy_timeout=30000` agar transaksi lain mengantre di level database sebelum membaca maupun menaikkan `last_number`.
     - Fungsi `generate_nim()` **hanya memanggil `db.flush()`** (bukan `db.commit()`), sehingga kenaikan `nim_counter.last_number` dan pembaruan `calon_mahasiswa` (`status`, `nim`, `approved_at`) berada dalam **satu transaksi atomik** milik `PMBService.approve()`. Bila `commit()` gagal, `rollback()` membatalkan keduanya sekaligus sehingga nomor urut tidak terbuang.
  4. **Pertahanan Berlapis:** Kolom `calon_mahasiswa.nim` tetap dilindungi `UNIQUE` constraint dan `PMBService.approve()` menerapkan *retry loop* hingga 3 kali saat terjadi `IntegrityError` atau `OperationalError` (lock/deadlock sementara).
  5. **Idempotency:** Bila `calon.status == StatusPMB.approved` dan `calon.nim` sudah terisi, `approve()` segera melepaskan transaksi dan mengembalikan data yang ada (`already_approved=True`) tanpa memanggil `generate_nim()`.
- **Konsekuensi & Pertimbangan:**  
  - Penguncian bersifat terisolasi per pasangan `(tahun, kode_prodi)` pada `nim_counter` di MySQL/PostgreSQL sehingga approval untuk program studi berbeda tidak saling memblokir.
  - Uji multi-thread di SQLite telah memverifikasi konsistensi penomoran tanpa lock Python, namun perilaku *row-level lock* InnoDB/PostgreSQL secara nyata tetap menjadi limitasi lingkungan pengujian hingga dijalankan di DBMS client-server.

---

## ADR-005: Keputusan Ambiguitas Format NIM (`2025001-0001`) dan Pemetaan HTTP `409 Conflict` vs `400 Bad Request`

- **Status:** Diterima (Minggu 4)
- **Konteks:**  
  Pada dokumen tugas Minggu 3–4 ditemukan dua detail yang perlu diperjelas:
  1. Format NIM pada bagian contoh menggunakan tanda hubung (`2025001-0001`, 12 karakter `[Tahun:4][Kode Prodi:3]-[Running Number:4]`), sedangkan contoh docstring fungsi menuliskan `YYYY[KODE]XXXX` (tanpa tanda hubung).
  2. Pada operasi `approve` dan `reject`, perlu dibedakan antara error akibat konflik transisi status (misalnya me-approve pendaftar yang sudah `rejected`, atau me-reject yang sudah `approved`) dan error akibat data internal/input yang tidak valid (misalnya `kode_prodi` bukan 3 digit angka).
- **Keputusan:**  
  1. **Format NIM Tanda Hubung (`YYYYKKK-NNNN`):** Menetapkan format **`[Tahun:4][Kode Prodi:3]-[Running Number:4]`** (contoh `2025001-0001`) pada fungsi murni `format_nim()`, karena lebih mudah dibaca manusia saat verifikasi akademik dan konsisten dengan contoh utama spesifikasi. Keputusan ini dikunci secara otomatis lewat unit test pola regex `^\d{4}001-\d{4}$`.
  2. **Semantik HTTP `409` vs `400`:**
     - `404 Not Found`: ID pendaftar tidak ditemukan.
     - `409 Conflict`: Konflik state/transisi status (`StatusTidakValid`: status pendaftar bukan `pending` saat approve, atau sudah `approved` saat reject; serta duplikasi email saat registrasi).
     - `400 Bad Request`: Data tidak valid untuk menghasilkan NIM (`DataNIMTidakValid`, misalnya kode prodi bukan 3 digit angka) atau parameter input/query tidak valid.
- **Konsekuensi & Pertimbangan:**  
  - Klien API dan sistem front-end dapat membedakan kesalahan *state workflow* (`409`) dari kesalahan validasi data (`400`) secara presisi melalui dokumentasi OpenAPI (`/docs` & `/redoc`).

---

## ADR-006: Strategi Rantai Validasi KRS — *Fail-Fast* di `add_course` vs *Collect-All* di `validate_krs`

- **Status:** Diterima (Minggu 5)
- **Konteks:**  
  Spesifikasi tugas Minggu 5 meminta pola *Chain of Responsibility* untuk memvalidasi pengisian KRS yang **berhenti pada kegagalan pertama**, sedangkan analisis pengalaman pengguna sejak Minggu 2 menyarankan agar saat validasi menyeluruh mahasiswa melihat **semua kesalahan sekaligus** tanpa harus memperbaiki dan mengirim ulang berkali-kali. Selain itu, urutan validator perlu ditentukan secara rasional.
- **Keputusan:**  
  1. **Jalan Tengah (*Fail-Fast* + *Collect-All*):**
     - `KRSManager.add_course(nim, kode_mk)` menjalankan `self.chain.validate(ctx)` secara **berhenti di error pertama (*fail-fast*)** karena mahasiswa hanya menambahkan satu mata kuliah dan tidak perlu menjalankan query prasyarat yang mahal bila duplikasi atau SKS sudah gagal.
     - `KRSManager.validate_krs(nim)` mengiterasi `for validator in self.validators: validator.check(ctx)` untuk setiap mata kuliah dalam KRS dan mendeduplikasi pesan guna mengumpulkan **semua pelanggaran sekaligus (*collect-all*)**.
  2. **Urutan Rantai Baku (`Duplicate → SKS → Prerequisite → Conflict`):**  
     Menempatkan `DuplicateValidator` di paling depan (paling murah di memori, tanpa query tambahan, dan mencegah mahasiswa mendapat pesan membingungkan "SKS berlebih" ketika sebenarnya hanya mengklik MK yang sama dua kali), disusul `SKSValidator`, `PrerequisiteValidator` (query `NOT EXISTS`), dan `ConflictValidator`.
- **Konsekuensi & Pertimbangan:**  
  - Penambahan aturan bisnis baru (misalnya `TunggakanValidator` untuk cek SPP) cukup membuat satu kelas turunan `Validator` baru dan menyisipkannya pada list yang disuntikkan ke `KRSManager`, tanpa mengubah logika `add_course()` maupun `validate_krs()` (*Open/Closed Principle*).
  - Validasi dan penyisipan di `add_course()` dibungkus dalam satu transaksi terkunci (`with_for_update()` pada MySQL/PostgreSQL dan `BEGIN IMMEDIATE` pada SQLite) untuk mencegah skenario *race condition* "dua tab, satu detik, 27 SKS".

---

## ADR-007: Deteksi Bentrok Interval (`<`), Bobot Numerik `skala_nilai`, dan Asumsi Jadwal Kelas Tunggal

- **Status:** Diterima (Minggu 5)
- **Konteks:**  
  Aturan bisnis KRS menyimpan tiga jebakan detail yang sering keliru: (1) definisi jadwal bentrok tidak cukup membandingkan `jam_mulai == jam_mulai`; (2) kuliah yang berakhir tepat saat kuliah berikutnya mulai (mis. `10:30` dan `10:30`) dapat diperbolehkan atau ditolak; (3) perbandingan nilai huruf `'B' >= 'C'` secara leksikografis pada SQL bernilai salah karena urutan ASCII (`'A' < 'B' < 'C' < 'D'`).
- **Keputusan:**  
  1. **Rumus Irisan Interval dengan `<` (Bukan `<=`):**  
     Dua mata kuliah bentrok bila dan hanya bila `a.hari == b.hari and a.jam_mulai < b.jam_selesai and b.jam_mulai < a.jam_selesai`. Dengan operator `<`, kuliah bersambung tepat (`08:00–10:30` diikuti `10:30–12:30`) **diizinkan**. (Bila institusi nanti mewajibkan jeda antar-kelas, cukup menambahkan margin menit di helper murni `bentrok()`).
  2. **Tabel Referensi `skala_nilai` (Bobot Numerik):**  
     Menyimpan `huruf -> bobot` (`A=4.0, B=3.0, C=2.0, D=1.0, E=0.0`) lalu membandingkan `s.bobot >= 2.0` bersama `k.semester < :semester` (`"YYYY1"` / `"YYYY2"`) di dalam subquery `NOT EXISTS` pada [app/services/krs_queries.py](../app/services/krs_queries.py).
  3. **Penyederhanaan Jadwal Kelas:**  
     Atribut jadwal (`hari`, `jam_mulai`, `jam_selesai`) disimpan sementara di tabel `matakuliah` (asumsi 1 MK = 1 kelas) agar rantai validasi dan query prasyarat fokus diuji pada Minggu 5–6, dan siap diekstrak ke tabel `kelas`/`jadwal` terpisah pada modul penjadwalan berikutnya.
- **Konsekuensi & Pertimbangan:**  
  - Lima pasangan kasus bentrok/bersambung dan perbandingan nilai `'A'..'E'` dapat diuji deterministik dan terbukti berjalan memakai indeks tanpa *full table scan* lewat `EXPLAIN QUERY PLAN` di [docs/EXPLAIN_PRASYARAT.md](EXPLAIN_PRASYARAT.md).

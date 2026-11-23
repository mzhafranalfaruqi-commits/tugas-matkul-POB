# Architecture Decision Records (ADR) — Modul PMB SEVIMA-Mini

Dokumen ini mencatat keputusan arsitektural dan teknis utama dalam mengimplementasikan modul Penerimaan Mahasiswa Baru (PMB) pada proyek **SEVIMA-Mini** (Minggu 3–4), sebagai kelanjutan dari artefak desain UML pada Minggu 1–2 (lihat [ADR-architecture-decisions.md](ADR-architecture-decisions.md) dan [ADR-architecture-decisions.pdf](ADR-architecture-decisions.pdf)).

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

---

## ADR-008: Enkapsulasi State Machine Sendiri (`TRANSITIONS` Dict) dan Strategi Optimistic + Pessimistic Locking

- **Status:** Diterima (Minggu 6)
- **Konteks:**  
  Siklus pengisian KRS memiliki 4 status (`DRAFT`, `SUBMITTED`, `APPROVED`, `REVISION`) dan 2 aktor (`MAHASISWA`, `DOSEN_PA`). Diperlukan pilihan apakah memakai library pihak ketiga (`transitions` / `python-statemachine`) atau tabel transisi eksplisit sendiri, serta bagaimana mencegah *race condition* ketika mahasiswa mengedit KRS bersamaan dengan Dosen PA yang sedang membuka layar persetujuan (*"tab lama menyetujui KRS yang diam-diam baru diubah mahasiswa"*).
- **Keputusan:**  
  1. **Tabel Transisi Eksplisit Sendiri (`TRANSITIONS` Dict + `KRS.transition()`):**  
     Dengan hanya 4 status dan 4 transisi sah dari 32 kombinasi `(status_awal, aktor, status_tujuan)`, kamus `TRANSITIONS` di [app/models/krs.py](../app/models/krs.py) jauh lebih transparan, nol dependensi eksternal, mudah diaudit saat *code review*, dan dapat dienkapsulasi penuh lewat `cek_transisi()` dan `transition()` tanpa membiarkan layer service/router menulis `krs.status = ...` secara langsung. Bila di semester lanjut jumlah state melebihi ~10–15 dengan sub-state hierarkis, barulah migrasi ke library `python-statemachine` dipertimbangkan.
  2. **Otorisasi Dua Lapis (`403 Forbidden` vs `409 Conflict`):**  
     Lapis 1 (peran pada tabel `TRANSITIONS`) dan transisi status ilegal/versi basi dipetakan ke **`409 Conflict`**, sedangkan Lapis 2 (kepemilikan `krs.dosen_pa_id == dosen_pa_id`) dipetakan secara eksplisit ke **`403 Forbidden`** lewat hierarki exception polimorfik `KRSError`.
  3. **Kombinasi *Pessimistic* (`FOR UPDATE` / `BEGIN IMMEDIATE`) + *Optimistic Locking* (`version` + `expected_version`):**  
     Operasi tulis menggunakan `with_for_update()` (dan `BEGIN IMMEDIATE` di SQLite) untuk mengisolasi transaksi paralel pendek, sementara header `KRS` memakai kolom `version` dengan `__mapper_args__ = {"version_id_col": version}` (ditambah sentuhan ketat `diubah_pada` setiap `add_course`/`remove_course`) serta parameter `expected_version` agar aksi Dosen PA yang datang dari layar lama ditolak dengan HTTP `409 StaleVersionError` (*"KRS sudah berubah, muat ulang"*).
- **Konsekuensi & Pertimbangan:**  
  - Keseluruhan 28 kombinasi transisi ilegal terverifikasi otomatis lewat `@pytest.mark.parametrize` tanpa mengimpor `TRANSITIONS` ke definisi oracle test.
  - Seluruh efek samping `approve_krs` dan `revise_krs` (perubahan status, timestamp/catatan, `krs_log`, dan `notifikasi`) berjalan dalam satu *Unit of Work* (`db.commit()` tunggal) dan terbukti melakukan *rollback* utuh bila commit gagal.

---

## ADR-009: Rekomendasi Paket KRS Berbasis CSP Backtracking + Mandatory Validator Guardrail

- **Status:** Diterima (Minggu 6 — Tantangan Opsional)
- **Konteks:**  
  Sistem memerlukan fitur rekomendasi kombinasi mata kuliah (`POST /api/krs/{nim}/recommend`) yang memaksimalkan terpenuhinya mata kuliah wajib serta total SKS tanpa melanggar aturan prasyarat, bentrok jadwal, maupun batas maksimal 24 SKS. Mengingat kendala utama bersifat deterministik dan kombinatorial dengan jumlah kandidat per semester yang relatif kecil (~10–20 MK), pemilihan algoritma solver dan jaminan kepatuhan aturan menjadi krusial.
- **Keputusan:**  
  1. **CSP *Backtracking* dengan *Branch-and-Bound Pruning*:**  
     Diimplementasikan di [app/services/krs_recommender.py](../app/services/krs_recommender.py). Solver terlebih dahulu menyaring prasyarat lewat query `prasyarat_belum_lulus()`, mengurutkan MK wajib dan SKS besar di depan, lalu mencari himpunan bagian yang memaksimalkan `(jumlah_wajib_terpilih, total_sks)` subject to `total_sks <= max_sks` dan bebas irisan jadwal `bentrok()`.
  2. **Prinsip Guardrail Deterministik (*"Solver Menyampaikan Saran, Validator yang Memutuskan"*):**  
     Setiap kombinasi keluaran solver **wajib** diputar ulang melalui rantai `build_chain(default_krs_validators())` (`Duplicate -> SKS -> Prerequisite -> Conflict`) sebelum dikembalikan ke pengguna.
- **Konsekuensi & Pertimbangan:**  
  - Menjamin hasil rekomendasi deterministik, dapat dijelaskan per mata kuliah (`ditolak` berisi alasan spesifik prasyarat/bentrok/SKS), bebas halusinasi LLM, serta siap dihubungkan dengan agen AI penjelas tanpa risiko melanggar aturan akademik.

---

## ADR-010: Model Domain 4 Entitas Penjadwalan, `krs_detail.kelas_id`, Pola *Expand-Contract*, dan Kontrak HTTP `422`

- **Status:** Diterima (Minggu 7)
- **Konteks:**  
  Pada Modul KRS (Minggu 5–6), jadwal kuliah (`hari`, `jam_mulai`, `jam_selesai`) masih disederhanakan langsung di tabel `matakuliah` (ADR-007: asumsi 1 MK = 1 kelas, tanpa ruangan maupun dosen). Asumsi ini tidak mampu memodelkan kelas paralel (mis. Basis Data A dan Basis Data B), satu kelas dengan lebih dari satu sesi mingguan (mis. teori Senin di ruang kelas dan praktikum Kamis di laboratorium), maupun bentrok ruangan dan dosen pengampu. Di sisi lain, penghapusan langsung kolom jadwal di `matakuliah` akan memutus 83 pengujian Modul PMB & KRS yang sudah ada, serta terdapat perbedaan kontrak status HTTP validasi Pydantic antara `/api/pmb` & `/api/krs` (`400` sesuai ADR-003) dengan `/api/jadwal` (`422` sesuai spesifikasi Minggu 7 untuk kesalahan format seperti `jam_mulai >= jam_selesai`).
- **Keputusan:**  
  1. **Pemisahan 4 Entitas Baru (`app/models/jadwal.py`, migrasi `0005`):**  
     Menambahkan tabel `ruangan` (`kode` PK, `kapasitas >= 1`), `dosen` (`id` PK, `nidn` UNIQUE, `nama`), `kelas` (`id` PK, FK `kode_mk`, `nama`, `kuota >= 1`, `semester`, `UNIQUE(kode_mk, nama, semester)`), dan `jadwal` (`id` PK, FK `kelas_id`, `hari 1..6`, `jam_mulai < jam_selesai` bertipe `TIME`, FK `ruangan_kode`, FK `dosen_id`, beserta index komposit `ix_jadwal_ruang(hari, ruangan_kode)` dan `ix_jadwal_dosen(hari, dosen_id)`).
  2. **Pola *Expand-Contract* pada `matakuliah` & `krs_detail`:**  
     Kolom `hari`, `jam_mulai`, dan `jam_selesai` pada `matakuliah` dipertahankan sementara agar seluruh API dan pengujian KRS Minggu 5–6 tetap berjalan tanpa regresi, sembari menambahkan kolom nullable `krs_detail.kelas_id` (FK -> `kelas.id`, terindeks) untuk menghitung mahasiswa terdaftar (`COUNT`) saat pemeriksaan kapasitas dan menjadi jembatan integrasi penuh invalidasi KRS pada Minggu 8.
  3. **Kontrak HTTP `422` Khusus `/api/jadwal`:**  
     Memperbarui handler `RequestValidationError` di [app/main.py](../app/main.py) agar rute berawalan `/api/jadwal` mengembalikan `422 Unprocessable Entity` untuk payload invalid (`jam_mulai >= jam_selesai`, `hari` di luar `1..6`, `ruangan_kode` kosong), sedangkan `/api/pmb/*` dan `/api/krs/*` tetap mengembalikan `400 Bad Request`. Error bisnis domain jadwal dibungkus melalui hierarki polimorfik `ScheduleError` (`NotFoundError -> 404`, `CapacityError -> 409`, `ScheduleConflictError -> 409` lengkap dengan field `conflicts`).
- **Konsekuensi & Pertimbangan:**  
  - Tipe `datetime.time` pada model ORM dan skema Pydantic mencegah bug perbandingan string leksikografis seperti `"9:00" < "10:00" -> False`.
  - Transisi penuh KRS ke `kelas_id` (fase *contract*) dijadwalkan pada integrasi Minggu 8 bersama Observer invalidasi KRS.

---

## ADR-011: Pemilihan *Grouping + Sort & Sweep* dan Penundaan *Interval Tree* dengan Bukti Benchmark

- **Status:** Diterima (Minggu 7)
- **Konteks:**  
  Dokumen tugas Langkah 1 menyebutkan *"Optimize dengan interval tree untuk jam overlap check"* untuk fungsi `detect_schedule_conflict`. Implementasi *Interval Tree* penuh menambah kompleksitas kode dan/atau dependensi eksternal (`intervaltree`), sehingga perlu dinilai apakah struktur pohon tersebut memang memberikan keuntungan nyata dibandingkan algoritma *Grouping + Sort & Sweep* pada ukuran data kampus SEVIMA-Mini.
- **Keputusan:**  
  1. Mempertahankan dua implementasi di [app/services/conflict.py](../app/services/conflict.py): `detect_naive()` ($O(n^2)$ berbasis `itertools.combinations`) sebagai acuan kebenaran untuk *differential testing*, dan `detect_schedule_conflict()` memakai **Grouping + Sort & Sweep** ($O(n \log n + k)$) untuk produksi.
  2. Menunda adopsi *Interval Tree* hingga beban data benar-benar membutuhkannya, berdasarkan analisis ukuran masalah dan benchmark aktual berikut:

| Skenario | Ukuran Data | Rata-rata Waktu Eksekusi (`seed=42`, 10x) | Keputusan Algoritma |
| :--- | :--- | :--- | :--- |
| Satu kampus, satu semester (padat: 12 ruang, 16 dosen, 6 hari) | `n = 600` jadwal (`1167` konflik) | Naif: `25.94 ms` vs Sweep: **`2.84 ms`** (~9.1x lebih cepat) | **Grouping + Sort & Sweep** memadai |
| Satu kampus, satu semester (menyebar: 30 ruang, 40 dosen, 6 hari) | `n = 600` jadwal (`455` konflik) | Naif: `39.61 ms` vs Sweep: **`2.40 ms`** (~16.5x lebih cepat) | **Grouping + Sort & Sweep** memadai |
| Satu ruangan pada satu hari | `6–8` jadwal | `< 0.1 ms` (termasuk overhead loop Python) | Apa pun memadai |
| Cek 1 jadwal baru saat `POST`/`PUT` | `1` vs tabel `jadwal` | Query SQL terindeks (`ix_jadwal_ruang`, `ix_jadwal_dosen`) | Query DB berindeks |
| Sistem booking ruang multi-tahun / solver ribuan kandidat per detik | `10^4+` kueri rentang dinamis | — | **Interval Tree** baru layak |

- **Konsekuensi & Pertimbangan:**  
  - Interval waktu dimodelkan setengah-terbuka `[jam_mulai, jam_selesai)` dengan operator `<` (bukan `<=`), dan kondisi aktif pada *sweep* memakai `x.jam_selesai > j.jam_mulai` (bukan `>=`), sehingga kuliah bersambung tepat (mis. `08:00–09:40` dan `09:40–11:20`) di ruangan dan dosen yang sama sah.
  - Baik `detect_naive` maupun `detect_schedule_conflict` hanya melaporkan dua tipe konflik (`"room_conflict"` dan `"lecturer_conflict"`); irisan jam pada ruangan dan dosen yang berbeda adalah kondisi normal, sedangkan satu pasangan yang melanggar keduanya tetap dilaporkan dua kali (sekali per tipe) tanpa duplikasi `(A, B)` / `(B, A)`.
  - Keputusan ini dibuktikan ekuivalen oleh *differential property-based test* Hypothesis (`test_sweep_sama_dengan_naif`, 500 contoh acak) dan siap diganti ke *Interval Tree* bila kelak muncul kebutuhan kueri rentang dinamis $10^4+$ per detik.

---

## ADR-012: Strategi *Capacity Check* `max(kuota, terdaftar)` dan Penguncian Baris Berurutan Anti-Deadlock

- **Status:** Diterima (Minggu 7)
- **Konteks:**  
  Pada awal semester ketika admin menyusun jadwal kuliah, mahasiswa belum mengisi KRS sehingga jumlah baris `krs_detail` untuk suatu kelas bernilai `0`. Jika `cek_kapasitas` hanya menghitung `COUNT(krs_detail)`, kelas berkuota `50` akan lolos dimasukkan ke ruang berkapasitas `30` lalu gagal saat pengisian KRS. Selain itu, operasi `create`/`update` jadwal oleh dua admin secara bersamaan pada ruang atau jam yang sama rentan terhadap *race condition* (TOCTOU: keduanya membaca database kosong, lalu keduanya menyimpan jadwal bentrok), dan penguncian dua tabel (`ruangan` dan `dosen`) tanpa urutan tetap berisiko menimbulkan *deadlock*.
- **Keputusan:**  
  1. **Pemeriksaan Kapasitas Ganda (`max(kelas.kuota, terdaftar)`):**  
     Fungsi `cek_kapasitas()` di [app/services/scheduling_service.py](../app/services/scheduling_service.py) menghitung jumlah pendaftar aktual dari `krs_detail.kelas_id` lalu membandingkan `max(kelas.kuota, terdaftar) > ruang.kapasitas`, dengan operator `>` (kapasitas tepat sama, misalnya `40 == 40`, tetap diizinkan).
  2. **Penguncian Pesimis Berurutan Tetap (`Ruangan` lalu `Dosen`) & Anti-Autoflush:**  
     `SchedulingService._kunci()` selalu mengunci baris `Ruangan` lebih dulu lalu baris `Dosen` dengan `SELECT ... FOR UPDATE` (`with_for_update()`), dan pada SQLite memulai transaksi tulis eksplisit `BEGIN IMMEDIATE` (sebelum membaca baris apa pun, termasuk sebelum `db.get()` pada `update()` dan `delete()`) disertai `PRAGMA busy_timeout=30000` dan retry hingga 3x untuk `OperationalError` sementara. Objek `Jadwal` baru hanya ditambahkan lewat `db.add(jadwal)` paling akhir sebelum `db.commit()` agar mekanisme *autoflush* SQLAlchemy tidak membaca jadwal baru sebelum validasi bentrok selesai.
- **Konsekuensi & Pertimbangan:**  
  - Penguncian baris berurutan konsisten mencegah *deadlock* siklus antar dua transaksi konkuren pada DBMS *client-server* (MySQL InnoDB/PostgreSQL), dan skenario balapan dua admin di ruang dan jam sama teruji pada file SQLite temporer (`test_scheduling_concurrency_dua_admin_satu_ruangan`: tepat 1 sukses dan 1 `ScheduleConflictError`).
  - Sama seperti ADR-004 dan ADR-008, karena SQLite mengabaikan klausa `FOR UPDATE` dan mengandalkan kunci tulis level berkas (`BEGIN IMMEDIATE`), pembuktian *row-level lock* spesifik ruangan/dosen pada konkurensi tinggi tetap memerlukan verifikasi di MySQL InnoDB atau PostgreSQL pada tahap deploy.

---

## ADR-013: Observer Pattern + Transactional Outbox vs Pub-Sub & Retensi Tabel `notifikasi`

- **Status:** Diterima (Minggu 8)
- **Konteks:**  
  Perubahan atau penghapusan jadwal kuliah oleh admin wajib memberi tahu mahasiswa peserta kelas, dosen pengampu (baik dosen baru maupun dosen sebelumnya bila terjadi pergantian pengampu), serta admin akademik melalui beberapa kanal (`EMAIL`, `SMS`, `PUSH`). Namun, memanggil pengirim notifikasi langsung di dalam transaksi SQL memiliki dua risiko fatal: (1) bila transaksi *rollback* akibat bentrok atau error DB, notifikasi palsu sudah terlanjur terkirim; (2) bila *gateway* notifikasi gagal atau melambat, transaksi database tertahan atau ikut gagal. Di sisi lain, Minggu 6 sudah memiliki tabel `notifikasi` di database sebagai *in-app inbox* riwayat revisi KRS mahasiswa.
- **Keputusan:**  
  1. **Observer Pattern In-Process + Transactional Outbox (`app/services/observer.py`, migrasi `0006`):**  
     Memilih **Observer Pattern** (`ScheduleSubject` + `StudentObserver`, `LecturerObserver`, `AdminObserver`) alih-alih langsung memasang *message broker* eksternal (Redis/RabbitMQ/Kafka), namun tetap memisahkan fase penyimpanan event dan pengirimannya memakai tabel **`outbox`** (`PENDING` -> `SENT` / `FAILED` maksimal 5 percobaan) dan `OutboxDispatcher`. Baris `Outbox` ditulis **di dalam transaksi yang sama** dengan `UPDATE/DELETE jadwal` + `KRSInvalidator`, lalu `OutboxDispatcher.run()` baru dijalankan **setelah `db.commit()` berhasil**.
  2. **Singleton Wiring & Idempotency Key:**  
     Observer dipasang **sekali saat inisialisasi modul** (bukan di handler HTTP agar tidak terjadi kebocoran memori maupun pengiriman berlipat), `ScheduleSubject.notify()` membungkus setiap observer dalam `try/except` terisolasi, dan setiap pengiriman memakai kunci deterministik `{event_id}:{penerima}:{channel}` pada `LogChannel` + `MemoryIdemStore`.
  3. **Mempertahankan Tabel `notifikasi` Minggu 6:**  
     Tabel `notifikasi` tetap dipertahankan sebagai *in-app notification inbox* bagi mahasiswa (khususnya saat KRS mereka terinvalidasi ke `REVISION`), sedangkan tabel `outbox` bertugas sebagai antrean pengiriman event lintas kanal (`Email`/`SMS`/`Push`).
- **Konsekuensi & Pertimbangan:**  
  - Nol dependensi broker eksternal di tahap kuliah, namun bila kelak arsitektur berubah menjadi *microservice*, hanya `OutboxDispatcher` yang perlu diubah untuk menerbitkan pesan ke RabbitMQ/Kafka.
  - Limitasi lingkungan lokal: `OutboxDispatcher` dipanggil sinkron tepat sesudah `commit()` dan `MemoryIdemStore` hidup di memori proses; pada produksi berskala besar, *dispatcher* dipindah ke *background worker* terpisah dan `IdemStore` dipindah ke Redis atau tabel idempotency DB.

---

## ADR-014: Perluasan State Machine KRS dengan `Actor.SISTEM` & Guardrail 4 Lapis AI Rescheduling

- **Status:** Diterima (Minggu 8)
- **Konteks:**  
  Ketika jadwal kuliah berubah atau dihapus, KRS mahasiswa yang sudah `SUBMITTED` atau `APPROVED` pada kelas tersebut berpotensi kini bertabrakan dengan jadwal mata kuliah lain, sehingga wajib dikembalikan ke status `REVISION` agar mahasiswa dan Dosen PA meninjau ulang. Selain itu, fitur AI Rescheduling membutuhkan saran slot alternatif dari LLM tanpa membuka peluang halusinasi ruang fiktif, ruangan terlalu sempit, atau slot yang tetap bentrok.
- **Keputusan:**  
  1. **Menambahkan `Actor.SISTEM` pada State Machine KRS (`app/models/krs.py`):**  
     Menambah aktor `SISTEM` beserta dua transisi sah baru: `(SUBMITTED, SISTEM) -> REVISION` dan `(APPROVED, SISTEM) -> REVISION`. Ruang kombinatorial *exhaustive property test* di [tests/test_krs_property.py](../tests/test_krs_property.py) diperbarui dari `4 × 2 × 4 = 32` (4 sah, 28 ilegal) menjadi **`4 × 3 × 4 = 48`** (**6 sah, 42 ilegal**). KRS `DRAFT` dan `REVISION` sengaja tidak disentuh oleh `KRSInvalidator`.
  2. **Guardrail AI Rescheduling 4 Lapis (`"AI Suggests, Deterministic Validator Decides"`):**  
     Sebelum memanggil LLM (`LLMClient`), kode terlebih dahulu menghitung daftar slot yang benar-benar bebas bentrok dan cukup kursi (`hitung_slot_tersedia`) sebagai konteks prompt. Keluaran JSON dari LLM (`EnvLLMClient` atau fallback deterministik `HeuristicLLMClient` saat offline/tanpa API key) kemudian **wajib** disaring oleh `saring_saran()` melalui 4 lapis: (1) ekstraksi & parsing JSON aman (`[]` bila rusak), (2) validasi skema Pydantic `Saran`, (3) pengecekan eksistensi ruangan & `kapasitas >= peserta`, dan (4) uji `detect_schedule_conflict()` dengan ID kandidat `-1` serta cek batas tengah malam. Penerapan saran lewat `POST /api/jadwal/{id}/apply` **wajib masuk satu pintu** melalui `SchedulingService.update()`.
- **Konsekuensi & Pertimbangan:**  
  - Invalidasi KRS, pembuatan `KRSLog(aksi="INVALIDATE")`, `Notifikasi`, pembaruan `Jadwal`, dan penulisan `Outbox` berjalan dalam satu *Unit of Work* (`commit()` tunggal).
  - Meskipun LLM menghasilkan JSON rusak atau ruangan fiktif, aplikasi tidak pernah *crash* dan tidak pernah meneruskan saran tidak valid ke database.

---

## ADR-015: Ekspor iCalendar RFC 5545 Tanpa Library Eksternal & Proteksi Role Admin

- **Status:** Diterima (Minggu 8)
- **Konteks:**  
  Mahasiswa memerlukan endpoint ekspor jadwal ke aplikasi kalender (`GET /api/mahasiswa/{nim}/jadwal.ics`), serta pengubahan jadwal maupun fitur AI Conflict Resolver (`POST/PUT/DELETE /api/jadwal`, `/suggestions`, `/apply`) harus dibatasi hanya untuk aktor admin agar tidak dapat dipicu sembarang mahasiswa.
- **Keputusan:**  
  1. **Generator iCalendar RFC 5545 Murni (`app/services/icalendar.py`):**  
     Membuat formatter `ke_vevent()` dan `export_jadwal_ics()` tanpa menambah pustaka eksternal `icalendar`, menggunakan baris wajib `CRLF` (`\r\n`), blok `VTIMEZONE` `Asia/Jakarta`, `DTSTART`/`DTEND;TZID=Asia/Jakarta`, aturan pengulangan mingguan `RRULE:FREQ=WEEKLY;UNTIL=...Z` (UTC sesuai syarat RFC 5545), `UID` stabil (`jadwal-{id}@sevima-mini`), serta kolom `jadwal.sequence` (migrasi `0006`) yang selalu bertambah setiap pembaruan agar impor ulang kalender memperbarui jadwal lama dan bukan membuat duplikat.
  2. **Dependensi `require_admin` (`X-Role: admin`) untuk Demo Lokal:**  
     Melindungi endpoint mutasi dan resolver jadwal dengan `require_admin` yang memverifikasi header `X-Role: admin` (mengembalikan HTTP `403 Forbidden` bila tidak sesuai), disertai selektor peran pada UI [resolver.html](../app/templates/resolver.html) agar mahasiswa dan dosen dapat mendemonstrasikan kontrol akses secara langsung.
- **Konsekuensi & Pertimbangan:**  
  - Penambahan `require_admin` bersifat eksplisit sebagai kontrol akses demo sebelum modul autentikasi penuh (JWT/OAuth2 + RBAC tervalidasi tanda tangan kriptografis) diimplementasikan; header `X-Role` **tidak boleh** dianggap aman di lingkungan produksi tanpa token terverifikasi.

---

## ADR-016: Penyimpanan Nilai di `krs_detail`, `skala_nilai` Berbasis `Numeric`/`lulus`, & Open Question `"≥ D (2.0)"`

- **Status:** Diterima (Minggu 9) — *menunggu konfirmasi stakeholder terkait batas lulus `D` vs `C`*
- **Konteks:**  
  Dokumen tugas Minggu 9–10 menyebut tabel `grades`, namun sejak migrasi `0003` (Minggu 5) proyek sudah memiliki kolom `krs_detail.nilai` (ber-FK ke `skala_nilai.huruf`) yang dibaca langsung oleh query prasyarat `NOT EXISTS` di [app/services/krs_queries.py](../app/services/krs_queries.py). Selain itu, dokumen tugas pada bagian Business Rules memuat kalimat kontradiktif: *"Lulus MK jika nilai ≥ D (2.0)"*, padahal pada tabel skala nilai kita `D = 1.00` dan `2.00 = C` (selaras aturan prasyarat minimal `2.0` di Minggu 5).
- **Keputusan:**  
  1. **Satu Sumber Kebenaran di `krs_detail`:**  
     Tidak membuat tabel `grades` terpisah guna mencegah dua sumber kebenaran (*split-brain*) antara nilai pada KRS dan modul nilai. Kolom `grade_history.grade_id` tetap memakai penamaan dokumen tugas dengan FK langsung ke `krs_detail.id` (`ON DELETE CASCADE`).
  2. **Tipe `Numeric(3, 2)` & Aturan Kelulusan sebagai Data (`skala_nilai.lulus`):**  
     Memperbarui `skala_nilai` pada migrasi `0007` menjadi `bobot Numeric(3, 2)` (dipetakan ke Python `Decimal`) serta menambah kolom `lulus Boolean` agar aturan batas lulus hidup di data, bukan di-*hardcode* dalam `hitung_ipk()`.
  3. **Asumsi Sementara & Pertanyaan Terbuka ke Stakeholder:**  
     Dengan mempertimbangkan keselarasan aturan prasyarat `bobot >= 2.0` dari Minggu 5, sistem sementara mengasumsikan **batas lulus minimal `C` (`A/B/C: lulus=True`, `D/E: lulus=False`)**, dan mencatat pertanyaan resmi ke dosen/bagian akademik: *"Apakah batas lulus mata kuliah adalah nilai minimal `D` (`1.00`), atau minimal `C` (`2.00`) sesuai aturan prasyarat dan angka `(2.0)` di dokumen?"*. Jika jawabannya minimal `D`, perubahan cukup memperbarui 1 baris data di `skala_nilai` tanpa mengubah satu baris kode pun.
- **Konsekuensi & Pertimbangan:**  
  - Dampak konversi ini terbukti signifikan secara kuantitatif (contoh Rina di [tests/test_gpa.py](../tests/test_gpa.py): `3.08` dengan minimal `C` vs `2.67` dengan minimal `D`, selisih `0.41` poin).
  - Query prasyarat di Minggu 5 (`s.bobot >= 2.0`) dapat diselaraskan memakai `s.lulus = 1` setelah keputusan stakeholder final.

---

## ADR-017: Compute-on-Read IPK (`Decimal` + `ROUND_HALF_UP`), `PresensiPort` (DIP), & Audit Trail di Service Layer

- **Status:** Diterima (Minggu 9)
- **Konteks:**  
  Perhitungan IPK menuntut presisi tinggi tanpa galat *floating-point* atau salah pembulatan (*banker's rounding*) serta harus selalu akurat ketika nilai baru masuk atau dikoreksi. Di saat yang sama, aturan blokir presensi `< 75%` bergantung pada modul presensi yang baru dibangun di Minggu 12, sedangkan audit perubahan nilai menuntut pencatatan dosen pengubah (`changed_by`) dan `reason`.
- **Keputusan:**  
  1. **Compute-on-Read & `Decimal` (`ROUND_HALF_UP`) + Output JSON String:**  
     IPK dan IPS tidak disimpan sebagai kolom cache pada tabel mahasiswa, melainkan dihitung langsung dari record bernilai saat dibaca oleh fungsi murni [app/domain/gpa.py](../app/domain/gpa.py) melalui `NilaiRepo`. Perhitungan menggunakan `Decimal`, membulatkan **hanya sekali di akhir** (`Decimal("0.01")`, `ROUND_HALF_UP`), mengambil bobot terbaik per `kode_mk` sebelum menyaring kelulusan, dan mengembalikan nilai di API (`IPKOut`/`IPSOut`) sebagai string (`"3.08"`). Bila kelak laporan ribuan mahasiswa butuh cache, *outbox event* `NILAI_CHANGED` berpola Minggu 8 siap ditambahkan.
  2. **Port Presensi Berpola *Dependency Inversion* (`PresensiPort`):**  
     Mendefinisikan `PresensiPort(Protocol)` di [app/services/grade_service.py](../app/services/grade_service.py) dengan implementasi sementara `PresensiStub` / `DemoPresensiStub`. Ketika modul presensi Minggu 12 selesai, cukup menyuntikkan adaptor nyata tanpa memodifikasi `GradeService`.
  3. **Audit Trail di Service Layer (`GradeService`) + View `v_riwayat_nilai` vs DB Trigger:**  
     Memilih menuliskan `GradeHistory` dan perubahan `krs_detail.nilai` dalam **satu transaksi atomik** di `GradeService.input_nilai()` (bukan DB trigger SQL), sehingga identitas `changed_by`, `reason` wajib saat edit, idempotency ketika huruf sama, serta portabilitas SQLite–MySQL/PostgreSQL tetap terjaga. Untuk kemudahan pembacaan riwayat mahasiswa, migrasi `0007` membuat SQL view `v_riwayat_nilai`.
- **Konsekuensi & Pertimbangan:**  
  - Limitasi lingkungan pengujian: perubahan nilai langsung lewat query SQL manual di luar `GradeService` tidak otomatis tercatat di `grade_history` (konsekuensi disadari dari memilih service-layer audit alih-alih DB trigger); di produksi, hak akses tulis langsung ke `krs_detail.nilai` dan `UPDATE`/`DELETE` pada `grade_history` harus dibatasi per role DB.

---

## ADR-018: Aturan Predikat Kelulusan & `get_transcript(nim)` Compute-on-Read

- **Status:** Diterima (Minggu 10) — *mencatat ekstensi syarat masa studi sebagai konfigurasi lanjutan*
- **Konteks:**  
  Modul transkrip menuntut `get_transcript(nim)` menghasilkan rekap lengkap seluruh semester beserta **predikat kelulusan** (*Cum Laude* bila `IPK >= 3.50`, *Sangat Memuaskan* `3.00–3.49`, dst.) sekaligus tetap konsisten ketika dosen baru saja menginput atau memperbaiki nilai.
- **Keputusan:**  
  1. **Fungsi Murni `bangun_ringkasan_transkrip()` & `tentukan_predikat()` (`app/domain/gpa.py`):**  
     Menempatkan pengelompokan semester menaik, penandaan `dipakai_ipk` (tepat satu rekord terbaik yang `lulus == True` per `kode_mk` memakai urutan deterministik `record_id`), agregasi SKS/mutu, dan penentuan predikat pada fungsi murni berbasis `Decimal` (`ROUND_HALF_UP`): `total_sks_lulus <= 0` → *"Belum Memenuhi Predikat"*; `>= 3.50` → *"Cum Laude"*; `>= 3.00` → *"Sangat Memuaskan"*; `>= 2.50` → *"Memuaskan"*; `>= 2.00` → *"Cukup"*; di bawah `2.00` → *"Belum Memenuhi Syarat Kelulusan"*.
  2. **Orkestrasi Compute-on-Read (`GPACalculator.get_transcript`):**  
     Memperluas `NilaiRepo` dengan `biodata_mahasiswa(nim)` dan `records_lengkap(nim)` agar biodata + seluruh catatan mata kuliah ber-nilai diambil saat diminta dan langsung diolah menjadi `TranskripAkademik`, meneruskan kebijakan compute-on-read pada **ADR-017**.
- **Konsekuensi & Pertimbangan:**  
  - Setiap perubahan nilai via `PUT /api/kelas/{kelas_id}/nilai/{nim}` langsung tercermin seketika pada `/transkrip`, `/transkrip/preview`, dan `/transkrip.pdf` tanpa *cache invalidation*.
  - Peraturan akademik riil sebagian perguruan tinggi mensyaratkan ketentuan tambahan untuk *Cum Laude* (mis. tidak pernah mengulang MK / lama studi maksimal 8 semester); aturan saat ini mengikuti batas IPK pada spesifikasi modul dan dicatat agar mudah diperluas pada parameter `tentukan_predikat()` bila stakeholder menginginkannya.

---

## ADR-019: Dual Renderer (`ReportLab` PDF + `Jinja2` HTML Preview) vs `WeasyPrint`

- **Status:** Diterima (Minggu 10)
- **Konteks:**  
  Spesifikasi Minggu 9–10 mengarahkan pembuatan generator PDF (*"ReportLab/WeasyPrint"*) sekaligus pembuatan template HTML bergaya CSS profesional menyerupai ijazah resmi. Pada lingkungan Windows maupun container Linux minimal, **WeasyPrint** bergantung pada pustaka native C (`GTK3`, `Pango`, `Cairo`, `HarfBuzz`) yang sering gagal terpasang atau menghasilkan tata letak berbeda lintas mesin.
- **Keputusan:**  
  1. **Satu Model Domain, Dua Renderer (`app/services/transcript_pdf.py`):**  
     Memisahkan port abstrak `TranscriptPdfRenderer(Protocol)` dan memilih **`ReportLabTranscriptRenderer`** (Pure-Python `reportlab` Platypus) sebagai implementasi default untuk `GET /api/mahasiswa/{nim}/transkrip.pdf`, sementara template **Jinja2** ([app/templates/transkrip.html](../app/templates/transkrip.html)) melayani pratinjau web & mode cetak peramban (`GET /api/mahasiswa/{nim}/transkrip/preview`) dari objek `TranskripAkademik` yang sama.
  2. **Keamanan & Ketahanan Tata Letak:**  
     Template Jinja2 mengaktifkan `autoescape=select_autoescape(["html", "xml"])`, ReportLab melakukan `xml.sax.saxutils.escape()` sebelum membuat `Paragraph`, NIM pada header `Content-Disposition` disanitasi (`sanitize_filename_segment`), tabel semester memakai `repeatRows=1` untuk transkrip multi-halaman tanpa pernah membentuk `Table([])` kosong, dan blok ringkasan + TTD Dekan dibungkus `KeepTogether`.
- **Konsekuensi & Pertimbangan:**  
  - Generator PDF berjalan 100% deterministik tanpa dependensi biner OS eksternal dan dapat diekstrak langsung oleh `pypdf` saat pengujian.
  - Trade-off: perubahan desain visual dokumen resmi perlu disinkronkan di dua tempat (`transkrip.html` dan `ReportLabTranscriptRenderer`). Bila kelak server produksi menjalankan Linux standar dengan WeasyPrint atau Chromium *headless*, tinggal mengganti implementasi `TranscriptPdfRenderer` lewat DI `get_transcript_pdf_renderer()`.

---

## ADR-020: Skema Keuangan `Numeric(14, 2)`, Tarif SPP Berbasis Prodi, & Kebijakan Denda Keterlambatan

- **Status:** Diterima (Minggu 11)
- **Konteks:**  
  Modul Keuangan (SPP) membutuhkan tabel `payment_method`, `billing`, dan `payment` dengan 4 status (`unpaid`, `partial`, `paid`, `overdue`), pembuatan tagihan otomatis per semester berdasarkan program studi (Teknik `Rp 5.000.000`, Ekonomi `Rp 4.000.000`), jatuh tempo 2 minggu setelah semester mulai, serta perhitungan denda keterlambatan tanpa kesalahan pembulatan *floating-point*.
- **Keputusan:**  
  1. **Presisi `Numeric(14, 2)` & Fungsi Murni `Decimal` (`app/domain/keuangan.py`):**  
     Seluruh kolom nominal uang (`billing.amount`, `billing.denda`, `billing.paid_amount`, `payment.amount`) memakai tipe SQL `Numeric(14, 2)` yang dipetakan ke Python `Decimal` dan dibulatkan dengan `ROUND_HALF_UP`.
  2. **Penentuan Tarif Prodi dengan Fallback Aman:**  
     `tentukan_tarif_spp(nama_prodi, fakultas)` memetakan program studi Teknik → `5.000.000,00`, Ekonomi/Manajemen/Akuntansi → `4.000.000,00`, serta prodi lainnya (mis. Sistem Informasi) ke tarif default `4.500.000,00`, dengan `due_date = semester_start + 14 hari` dan status awal `unpaid`.
  3. **Kebijakan Denda Keterlambatan Terbatas:**  
     Denda keterlambatan dihitung sebesar `0,5%` per hari setelah `due_date` dengan batas maksimum `10%` dari pokok tagihan (`DEFAULT_TARIF_DENDA_HARIAN = 0.005`, `DEFAULT_MAKS_DENDA_PERSEN = 0.10`).
- **Konsekuensi & Pertimbangan:**  
  - Perhitungan nominal, cicilan `partial -> paid`, dan batas denda menjadi 100% deterministik serta mudah diuji dengan *property-based testing* (`tests/test_keuangan_property.py`).
  - Apabila institusi kelak menerapkan tarif per angkatan atau tabel master tarif terpisah, cukup mengganti fungsi penentu tarif di service layer tanpa mengubah model transaksi `Billing`/`Payment`.

---

## ADR-021: Keamanan Webhook HMAC-SHA256, Idempotency `transaction_id`, & Receipt Pasca-Commit

- **Status:** Diterima (Minggu 11)
- **Konteks:**  
  Endpoint webhook notifikasi pembayaran (`POST /api/keuangan/webhook/payment`) rentan terhadap pemalsuan request pihak ketiga, duplikasi pengiriman (*webhook retry* dari gateway), serta kegagalan I/O layanan email yang tidak boleh membatalkan pencatatan dana yang sudah masuk.
- **Keputusan:**  
  1. **Verifikasi Signature HMAC-SHA256 `hmac.compare_digest`:**  
     Request webhook membaca *raw body* mentah dan memverifikasi header `X-Webhook-Signature` (mendukung prefiks opsional `sha256=`) secara *constant-time* sebelum parsing payload; kegagalan ditolak dengan HTTP `401 Unauthorized`.
  2. **Transaksi Atomik & Idempotency `transaction_id`:**  
     `BillingService.process_payment()` mengunci transaksi (`BEGIN IMMEDIATE` pada SQLite dan `with_for_update()` pada engine SQL lain), memeriksa keunikan `payment.transaction_id` (mengembalikan hasil idempoten bila `billing_id` dan nominal identik, atau `409 Conflict` bila berbeda), lalu memperbarui `billing.paid_amount`, status (`partial`/`paid`), catatan `Payment`, dan `Notifikasi` dalam satu `commit()`.
  3. **Pengiriman Email Receipt Pasca-Commit (`EmailReceiptPort`):**  
     Pengiriman email kuitansi dijalankan setelah `commit()` berhasil melalui abstraksi `EmailReceiptPort` (`LogEmailReceiptSender`) di dalam blok `try/except`, sehingga gangguan server email tidak pernah me-rollback pembayaran terkonfirmasi.
- **Konsekuensi & Pertimbangan:**  
  - Pengulangan webhook dari gateway tidak menimbulkan *double-credit* maupun pengiriman kuitansi ganda.
  - Penggantian ke penyedia SMTP/SendGrid di produksi cukup dengan menyuntikkan adaptor baru yang memenuhi `EmailReceiptPort`.

---

## ADR-022: Penjadwalan Cron APScheduler, Integrasi Blokir KRS (`403`), & AI Financial Insights

- **Status:** Diterima (Minggu 11)
- **Konteks:**  
  Tagihan SPP harus dapat dibuat otomatis setiap awal semester dan pengingat tunggakan harus dikirim berkala lewat APScheduler; mahasiswa bertunggakan wajib diblokir dari pengisian KRS; serta manajemen membutuhkan laporan AI Financial Insights berformat JSON.
- **Keputusan:**  
  1. **APScheduler Lifespan (`app/services/scheduler.py`):**  
     Mengelola `BillingScheduler` berbasiskan `BackgroundScheduler(timezone="Asia/Jakarta")` dengan dua cron job (`semester_billing_generator` tiap 1 Februari & 1 Agustus pukul 00:05 WIB; `daily_overdue_reminder` tiap hari pukul 07:00 WIB) yang didaftarkan melalui FastAPI `lifespan` dan dapat dinonaktifkan dengan `DISABLE_SCHEDULER=1`.
  2. **Integrasi Penjagaan Ganda pada Modul KRS:**  
     Menambahkan `BillingArrearsValidator` ke rantai `default_krs_validators()` (dilewati aman saat `ctx.db is None` untuk *pure unit/property test*) dan pemeriksaan eksplisit `KRSManager._pastikan_bebas_tunggakan()` yang mengangkat `KRSBillingBlockedError` (HTTP `403`) pada `add_course` dan `submit_krs` selama mahasiswa memiliki tagihan `unpaid`, `partial`, atau `overdue`.
  3. **AI Financial Insights Berbasis Agregasi Deterministik (`app/services/financial_ai.py`):**  
     Seluruh metrik numerik (*total revenue bulan ini*, *collection rate %*, *Top 10 tunggakan terbesar*, dan jumlah penunggak `> 2 bulan` / `> 60 hari`) dihitung secara murni dan eksak oleh `analisis_keuangan_csv()` sebelum disusun menjadi narasi via port `FinancialNarrativeClient`, mencegah halusinasi angka keuangan.
- **Konsekuensi & Pertimbangan:**  
  - Pelunasan melalui webhook maupun manual seketika membuka akses KRS mahasiswa tanpa jeda sinkronisasi.
  - Pada deployment multi-worker (`uvicorn --workers > 1`), scheduler sebaiknya dipindah ke satu proses worker khusus atau memakai *distributed job lock* agar cron job tidak berjalan ganda di tiap worker.

---

## ADR-023: Resolusi Window QR 15 Menit vs Batas Terlambat 30 Menit, JWT HS256 >= 32 Byte, & Rotasi `jti` Anti-Replay

- **Status:** Diterima (Minggu 12)
- **Konteks:**  
  Spesifikasi Minggu 12 menetapkan QR code hanya berlaku 15 menit (untuk mencegah penyalahgunaan foto QR di luar kelas), namun juga menetapkan status `"hadir"` bila scan dalam 15 menit pertama dan `"terlambat"` bila scan setelah 15 menit (maksimal 30 menit dari awal kuliah). Selain itu, QR lama harus tidak bisa dipakai ulang apabila dosen memperbarui QR sesi.
- **Keputusan:**  
  1. **Pemodelan Sesi + Rotasi Token `jti` Unik (`AttendanceSession`):**  
     Setiap pertemuan kuliah pada pasangan `(jadwal_id, tanggal)` direpresentasikan oleh satu baris `AttendanceSession` yang menyimpan `active_jti`, `generated_at`, dan `expires_at`. Dosen dapat memanggil `create_or_rotate_qr()` kembali pada sesi yang sama (misalnya di menit ke-15 untuk mahasiswa terlambat hingga menit ke-30) sehingga QR baru memiliki masa hidup 15 menit segar dengan `active_jti` baru, sementara token QR sebelumnya seketika tertolak (`401 AttendanceExpiredError`).
  2. **Secret HMAC-SHA256 >= 32 Byte (RFC 7518 Section 3.2) & Verifikasi Klaim Deterministik:**  
     Secret default `DEFAULT_QR_SECRET` memakai kunci 36 byte (menghilangkan `InsecureKeyLengthWarning`), dan `decode_attendance_token()` memverifikasi tanda tangan HS256 lalu memeriksa `iat` serta `exp` secara deterministik terhadap timestamp referensi (mendukung pengujian waktu terkendali tanpa `time.sleep()`).
- **Konsekuensi & Pertimbangan:**  
  - Replay attack memakai foto token QR sesi lama atau QR yang sudah diganti tertolak `401`.
  - Di produksi, `ATTENDANCE_JWT_SECRET` wajib diisi kunci acak minimal 32 byte dari *secret manager*.

---

## ADR-024: Integrasi Nyata `DBPresensiAdapter` ke `PresensiPort` Minggu 9, Geofencing Haversine, & Rate Limiting

- **Status:** Diterima (Minggu 12)
- **Konteks:**  
  Pada Minggu 9 (**ADR-017**), `GradeService` memblokir input nilai `< 75%` melalui abstraksi `PresensiPort` yang sementara menggunakan `DemoPresensiStub`. Kini Modul Presensi menyediakan data kehadiran riil di database, sekaligus membutuhkan opsi validasi lokasi (geofencing) dan pencegahan *spam scan* (`rate limiting`).
- **Keputusan:**  
  1. **Adaptor Nyata `DBPresensiAdapter` dengan Fallback Kompatibel (`app/services/presensi_service.py`):**  
     `get_presensi_port(db)` kini mengembalikan `DBPresensiAdapter(db)`. Bila `kelas_id` sudah memiliki baris `AttendanceSession` (`total_sesi > 0`), persentase dihitung langsung dari rekord `hadir`/`terlambat` pada database; apabila `total_sesi == 0` (misalnya pada skenario tes Minggu 9 yang belum menginisialisasi modul presensi), adaptor mendelegasikan secara transparan ke `DemoPresensiStub`.
  2. **Geofencing Opsional Berbasis Haversine & Sliding-Window Rate Limiter:**  
     Bila dosen mengisi `latitude`, `longitude`, dan `max_radius_meters` saat generate QR, scan memvalidasi jarak permukaan bumi via `hitung_jarak_haversine_meter()` (`400` jika koordinat mahasiswa kosong, `403` jika di luar radius). Endpoint scan dilindungi `SlidingWindowRateLimiter` (`5` request/menit per kunci host + NIM, mengembalikan `429`).
- **Konsekuensi & Pertimbangan:**  
  - Kehadiran di Modul Presensi langsung memengaruhi kelayakan input nilai di Modul Nilai tanpa mengubah satu baris pun kode `GradeService`.
  - Pada deployment multi-instance di produksi, `SlidingWindowRateLimiter` memori proses perlu diganti ke Redis rate limiter.

---

## ADR-025: Ekspor Excel 2-Sheet (`openpyxl`) & AI Attendance Pattern Analyzer Deterministik

- **Status:** Diterima (Minggu 12)
- **Konteks:**  
  Dosen membutuhkan file Excel laporan presensi yang menyoroti mahasiswa berisiko (`< 75%`), dan sistem membutuhkan AI Attendance Insights yang menghasilkan peringatan dini serta pola absen hari/jam (`Senin pagi`, `jam 07:00`) dalam format JSON terstruktur.
- **Keputusan:**  
  1. **Workbook Excel Multi-Sheet (`openpyxl`):**  
     `GET /api/presensi/kelas/{kelas_id}/export.xlsx` menghasilkan workbook 2 sheet: `Rekap Presensi` (ringkasan total sesi, hadir, terlambat, izin, alpha, persentase, dan penanda merah `WARNING (<75%)`) serta `Log Kehadiran` (riwayat timestamp scan dan jarak GPS per pertemuan).
  2. **Analisis Pola & Rekomendasi Deterministik (`app/domain/presensi.py` + `app/services/attendance_ai.py`):**  
     Perhitungan persentase per mahasiswa, deteksi *early warning* `< 75%`, identifikasi pola ketidakhadiran berulang pada hari & slot waktu tertentu, serta perhitungan *absen rate* kelas/jam dijalankan oleh fungsi murni deterministik `analisis_pola_presensi()` sebelum dirangkum oleh `DeterministicAttendanceNarrativeClient`, menjaga keakuratan angka 100%.
- **Konsekuensi & Pertimbangan:**  
  - Ekspor `.xlsx` langsung kompatibel dengan Microsoft Excel dan LibreOffice Calc serta dapat diverifikasi otomatis di `pytest` menggunakan `openpyxl.load_workbook`.
  - Port `AttendanceNarrativeClient` memungkinkan penyambungan LLM eksternal kelak tanpa mengorbankan kebenaran statistik kehadiran.

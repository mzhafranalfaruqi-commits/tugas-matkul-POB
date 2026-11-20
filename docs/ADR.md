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

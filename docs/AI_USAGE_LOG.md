# AI Usage Log — Implementasi Modul PMB, KRS, & Jadwal SEVIMA-Mini (Minggu 3–7)

Catatan ini mendokumentasikan penggunaan asisten AI selama perancangan skema database, implementasi REST API, perbaikan arsitektur NIM generator berbasis database lock (Minggu 4), Modul KRS bagian 1 (*Chain of Responsibility*, query prasyarat terindeks, dan `KRSManager` di Minggu 5), Modul KRS bagian 2 (State Machine, Approval Dosen PA Atomik, Optimistic Locking, *Property-Based Testing*, dan CSP Recommender di Minggu 6), serta Modul Jadwal & Ruangan bagian 1 (model 4 entitas, detektor bentrok *Grouping + Sort & Sweep*, `SchedulingService` ber-lock, dan ADR *Interval Tree* di Minggu 7). Versi terstruktur sesuai format silabus + kerangka **OPAR** (*Observe, Plan, Act, Reflect*) tersedia lengkap pada [prompts/ai-usage-log.md](../prompts/ai-usage-log.md).

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
| 5 | Modul KRS Bag. 1: Skema 2-Tingkat, Chain of Responsibility, Query `NOT EXISTS`, & `KRSManager` | Antigravity & Mistral | Potensi terbalik arah *self-referencing* `prerequisite`, jebakan string `'B' >= 'C'`, cek bentrok naif (`jam_mulai == jam_mulai`), N+1 query / tanpa index pada cek prasyarat, serta celah *race condition* 2 tab 27 SKS saat `add_course`. | Membuat model `SkalaNilai`, `MataKuliah`, `prerequisite`, `KRS`, `KRSDetail` (`0003_tabel_krs.py`); membangun rantai `Duplicate -> SKS -> Prerequisite -> Conflict` dengan interval `<`; memakai query `NOT EXISTS` terverifikasi `EXPLAIN QUERY PLAN`; serta mengunci baris KRS dengan `with_for_update()` / `BEGIN IMMEDIATE`. |
| 6 | Modul KRS Bag. 2: State Machine, Approval/Revisi Atomik, Optimistic Lock, Property Testing (`hypothesis`), & CSP Recommender | Antigravity, Mistral, & Codeium | Pengubahan `krs.status = ...` langsung tanpa enkapsulasi, lupa menaikkan `version` header saat `KRSDetail` diubah, mencampur `403` vs `409`, serta *property test* yang hanya menghitung angka di memori atau memakai `bentrok()` sendiri sebagai oracle. | Mengenkapsulasi transisi lewat `Actor` + `TRANSITIONS` + `KRS.transition()`; menyentuh `diubah_pada` di `add_course`/`remove_course` agar `version_id_col` naik; membuat 1 handler polimorfik `KRSError`; membuktikan invarian SKS & bentrok via `hypothesis` (`1000` contoh + oracle `_slot()`); menguji ke-28 transisi ilegal; serta menambah `KRSRecommender` CSP + guardrail validator (ADR-008 & ADR-009). |
| 7 | Modul Jadwal & Ruangan Bag. 1: Skema `0005`, Detektor *Sort & Sweep*, `SchedulingService`, & Benchmark ADR-011 | Antigravity | Potensi 5 bug klasik AI (`<=` menggagalkan kuliah bersambung `09:40`, perbandingan jam sebagai string, lupa cek `hari`, pasangan ganda & `elif` bentrok ruang+dosen, serta laporan `"time_overlap"` palsu), jebakan *autoflush* sebelum cek bentrok, dan klaim optimasi *Interval Tree* tanpa pengukuran. | Menegakkan interval setengah-terbuka `[mulai, selesai)` bertipe `datetime.time`, 2 tipe konflik `Conflict(frozen=True)`, penguncian tetap `Ruangan -> Dosen` + `BEGIN IMMEDIATE` sebelum `db.get()`, `db.add(jadwal)` paling akhir, kontrak HTTP `422` pada `/api/jadwal`, uji Hypothesis differential `500x`, serta penundaan *Interval Tree* berdasar benchmark nyata `n=600` (ADR-010..012). |

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

### Prompt Terbaik 4 — Rantai Validasi KRS & Query Prasyarat Anti-Jebakan (Minggu 5)
> "Dengan model `SkalaNilai`, `MataKuliah`, `prerequisite`, `KRS`, dan `KRSDetail` pada SQLAlchemy 2.0, implementasikan pola Chain of Responsibility (`Validator(ABC)`, `ValidationResult`, `KRSContext`, `build_chain`) untuk urutan `DuplicateValidator -> SKSValidator -> PrerequisiteValidator -> ConflictValidator`. Gunakan rumus irisan interval (`jam_mulai < jam_selesai`), query `NOT EXISTS` dengan bobot `skala_nilai >= 2.0` (`C`) di `semester < aktif`, serta `KRSManager.add_course()` yang mengunci baris KRS dalam satu transaksi."

- **Evaluasi Kritis:** Menolak perbandingan string nilai huruf (`nilai >= 'C'`) yang keliru di SQLite/MySQL dan memastikan kuliah bersambung (misalnya `08:00–10:30` dan `10:30–12:30`) diizinkan dengan operator `<`, serta membuktikan penghapusan *full table scan* lewat [docs/EXPLAIN_PRASYARAT.md](EXPLAIN_PRASYARAT.md).

### Prompt Terbaik 5 — State Machine KRS, Optimistic Lock, Hypothesis & CSP Guardrail (Minggu 6)
> "Enkapsulasi state machine `KRS` memakai enum `Actor` dan kamus `TRANSITIONS` pada `app/models/krs.py`, tambah migrasi `0004` (`version`, `krs_log`, `notifikasi`), serta implementasikan `submit_krs`, `approve_krs`, dan `revise_krs` atomik (1 commit + rollback penuh) dengan otorisasi PA `403` vs konflik status/versi basi `409`. Tambahkan test `hypothesis` (`max_examples=1000`) yang menguji `SKSValidator` & `ConflictValidator` (oracle `_slot` independen), ke-28 transisi ilegal `itertools.product`, dan `KRSRecommender` CSP dengan guardrail validator."

- **Evaluasi Kritis:** Memastikan tidak ada `krs.status = ...` langsung di service/router, memaksa naik `version` lewat `_sentuh_krs()` setiap `add_course`/`remove_course`, menghindari tautologi *property test* dengan oracle independen `_slot()`, serta menjaga prinsip bahwa rekomendasi CSP selalu divalidasi ulang oleh rantai validator sebelum keluar ke API.

### Prompt Terbaik 6 — Detektor Bentrok 3 Dimensi, Anti-Bug Klasik AI, & `SchedulingService` (Minggu 7)
> "Bangun model `Ruangan`, `Dosen`, `Kelas`, `Jadwal` + `krs_detail.kelas_id` (`0005`), fungsi `detect_naive` ($O(n^2)$) dan `detect_schedule_conflict` (*Grouping + Sort & Sweep* $O(n \log n + k)$) dengan interval setengah-terbuka `[mulai, selesai)` bertipe `datetime.time`, `Conflict(frozen=True)` khusus `'room_conflict'` & `'lecturer_conflict'`, serta `SchedulingService` dengan `cek_kapasitas(max(kuota, terdaftar))`, lock berurutan `Ruangan -> Dosen`, `BEGIN IMMEDIATE`, dan router `/api/jadwal` (`422` validasi / `409` detail konflik)."

- **Evaluasi Kritis:** Menutup seluruh 5 bug klasik AI pada deteksi bentrok, menjaga kompatibilitas mundur *expand-contract* pada `matakuliah` sehingga 83 tes PMB/KRS tidak regresi, menguji ekuivalensi sweep vs naif lewat 500x Hypothesis *differential testing*, serta mendokumentasikan penundaan *Interval Tree* secara empiris di `ADR-011` (`2.40–2.84 ms` vs `25.94–39.61 ms` pada `n=600`).

---

## Ringkasan Verifikasi Akhir & OPAR

- **Migrasi Alembic:** `0001_tabel_pmb` → `0002_tabel_nim_counter` → `0003_tabel_krs` → `0004_krs_workflow_audit` → `0005_tabel_jadwal_ruangan` (`upgrade head`, `downgrade -1` via `batch_alter_table`, `upgrade head`, `seed.py` x2) berjalan tanpa error.
- **Test Suite & Coverage:** **`99 passed, 1 warning in 39.17s`** (14 tes unit/constraint/API/concurrency/seed Minggu 7 + 2 tes Hypothesis `500x` + 83 tes PMB & KRS tanpa regresi), total coverage **`95.81%`** (`96%`), melampaui syarat minimal `--cov-fail-under=80`.
- **Refleksi Limitasi (OPAR — Reflect):** Seluruh uji atomicity, optimistic lock, concurrency jadwal, dan `99/99` skenario berjalan lancar di SQLite, sementara perilaku row lock MySQL InnoDB/PostgreSQL, autentikasi token JWT untuk `dosen_pa_id`, filter `kelas.semester` aktif pada pencarian bentrok, serta Observer/AI rescheduling/invalidasi KRS dijadwalkan pada [docs/PR_MINGGU_7.md](PR_MINGGU_7.md) dan [prompts/ai-usage-log.md](../prompts/ai-usage-log.md).

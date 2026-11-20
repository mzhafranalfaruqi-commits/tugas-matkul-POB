# SEVIMA-Mini — Implementasi Modul PMB & Modul KRS

Proyek ini merupakan implementasi sistem akademik **SEVIMA-Mini** untuk mata kuliah **Pemrograman Berorientasi Objek untuk Sistem AI Agenik**, yang mencakup:
1. **Modul PMB (Minggu 3–4):** Pendaftaran calon mahasiswa, persetujuan admin, generator NIM atomik bebas *race condition*, dan statistik pendaftar.
2. **Modul KRS Bagian 1 (Minggu 5):** Skema database 2 tingkat (`krs` + `krs_detail`), *self-referencing many-to-many* (`prerequisite`), tabel bobot `skala_nilai`, `KRSManager` Service, rantai validasi berpola **Chain of Responsibility**, query prasyarat berbasis `NOT EXISTS` yang terindeks (`EXPLAIN QUERY PLAN`), dan REST API `/api/krs/*`.
3. **Modul KRS Bagian 2 (Minggu 6):** Enkapsulasi *State Machine* KRS (`Actor` + `TRANSITIONS`), approval/revisi Dosen PA dalam satu transaksi atomik (`krs_log` + `notifikasi`), otorisasi kepemilikan (`403` vs `409`), *optimistic locking* (`version` + `expected_version`), *property-based testing* (`hypothesis` 1000x + 28 transisi ilegal), exception handler polimorfik `KRSError`, serta *Optional Challenge* rekomendasi KRS berbasis **CSP Backtracking** dengan guardrail validator.

---

## Pemetaan Desain UML ke Kode

| Artefak Desain | Implementasi Kode | Lokasi File |
| :--- | :--- | :--- |
| Class Diagram PMB (`CalonMahasiswa`, `ProgramStudi`, `JalurMasuk`, + `NimCounter`) | Model SQLAlchemy 2.0 (`Mapped`, constraint, counter atomik) | [app/models/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/pmb.py) |
| Class Diagram KRS (`MataKuliah`, `prerequisite`, `KRS`, `KRSDetail`, `SkalaNilai`) | Relasi 2-tingkat M2M & *self-referencing* FK ke `calon_mahasiswa.nim` | [app/models/krs.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/krs.py) |
| Chain of Responsibility & Template Method | `Validator(ABC)` (`Duplicate → SKS → Prerequisite → Conflict`) | [app/validators/base.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/validators/base.py), [app/validators/krs.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/validators/krs.py) |
| Service Layer (`PMBService`, `KRSManager`, `KRSRecommender`) | Pengendali alur, state machine atomik, locking, & CSP | [app/services/pmb_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/pmb_service.py), [app/services/krs_manager.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/krs_manager.py), [app/services/krs_recommender.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/krs_recommender.py) |
| Router REST API (`/api/pmb/*` & `/api/krs/*`) | Router tipis + OpenAPI `responses={...}` & handler polimorfik | [app/routers/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/pmb.py), [app/routers/krs.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/krs.py) |
| Architecture Decision Record (ADR) | Keputusan arsitektural ADR-001 s.d. ADR-009 | [docs/ADR.md](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/docs/ADR.md) |

---

## Struktur Proyek

```text
sevima-mini/
├── .github/
│   └── pull_request_template.md     # Template PR sesuai rubrik kuliah
├── app/
│   ├── main.py                      # Entrypoint FastAPI (router PMB + KRS, handler 400 & KRSError)
│   ├── database.py                  # Engine SQLAlchemy, PRAGMA foreign_keys=ON & busy_timeout
│   ├── models/
│   │   ├── __init__.py
│   │   ├── pmb.py                   # ProgramStudi, JalurMasuk, CalonMahasiswa, NimCounter
│   │   └── krs.py                   # SkalaNilai, MataKuliah, prerequisite, KRS (+ State Machine), KRSDetail, KRSLog, Notifikasi
│   ├── schemas/
│   │   ├── pmb.py                   # Skema Pydantic v2 PMB
│   │   └── krs.py                   # Skema Pydantic v2 KRS (+ approve, revise, recommend)
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── base.py                  # ValidationResult, KRSContext, Validator(ABC), build_chain
│   │   └── krs.py                   # DuplicateValidator, SKSValidator, PrerequisiteValidator, ConflictValidator
│   ├── services/
│   │   ├── exceptions.py            # Domain exception PMB & hierarki KRSError (400, 403, 404, 409)
│   │   ├── nim_generator.py         # format_nim() + generate_nim() via nim_counter & flush()
│   │   ├── pmb_service.py           # Kelas OOP PMBService
│   │   ├── krs_queries.py           # Query kompleks prasyarat NOT EXISTS + bobot skala_nilai
│   │   ├── krs_manager.py           # Workflow add/remove/validate/submit/approve/revise + locking
│   │   └── krs_recommender.py       # Rekomendasi paket KRS CSP Backtracking + guardrail validator
│   └── routers/
│       ├── pmb.py                   # Endpoint /api/pmb/*
│       └── krs.py                   # Endpoint /api/krs/*
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 0001_tabel_pmb.py        # Skema PMB (3 tabel + constraints)
│       ├── 0002_tabel_nim_counter.py# Tabel nim_counter atomik
│       ├── 0003_tabel_krs.py        # Skema KRS (5 tabel + constraints + index)
│       └── 0004_krs_workflow_audit.py # Kolom state/version pada krs + krs_log + notifikasi
├── tests/
│   ├── conftest.py
│   ├── test_pmb.py                  # Tests Modul PMB (30 skenario)
│   ├── test_krs.py                  # Tests Modul KRS Bag. 1–2 (18 skenario unit, integrasi, lock, CSP)
│   └── test_krs_property.py         # Hypothesis (1000x SKS & Conflict) + 32 kombinasi State Machine (35 skenario)
├── prompts/
│   └── ai-usage-log.md              # Log AI terstruktur + OPAR (Minggu 3–6)
├── docs/
│   ├── ADR.md                       # ADR-001 s.d. ADR-009
│   ├── AI_USAGE_LOG.md
│   ├── EXPLAIN_PRASYARAT.md         # Bukti verbatim EXPLAIN QUERY PLAN sebelum vs sesudah index
│   ├── PR_MINGGU_4.md
│   └── PR_MINGGU_6.md               # PR Minggu 6 (State Machine, Locking, Hypothesis, CSP)
├── seed.py                          # Seeding idempotent data PMB & KRS
├── alembic.ini
├── requirements.txt
└── README.md
```

---

## Ringkasan Skema Database

### Modul PMB (`0001` & `0002`)
1. `program_studi`: `id` (PK), `kode` (`UNIQUE` 3 char), `nama`, `fakultas`.
2. `jalur_masuk`: `id` (PK), `nama` (`SNBP`/`SNBT`/`Mandiri`, `UNIQUE`).
3. `calon_mahasiswa`: `id` (PK), `nama_lengkap`, `email` (`UNIQUE`, indexed), `phone`, `tanggal_lahir`, `alamat`, `program_studi_id` (FK), `jalur_masuk_id` (FK), `status` (`pending`/`approved`/`rejected` + CHECK enum), `nim` (nullable, `UNIQUE`), `created_at`, `approved_at`.
4. `nim_counter`: composite PK `(tahun, kode_prodi)`, `last_number` (default `0`).

### Modul KRS (`0003` & `0004`)
5. `skala_nilai`: `huruf` (`A..E`, PK), `bobot` (`4.0..0.0`).
6. `matakuliah`: `kode_mk` (PK), `nama`, `sks` (`CHECK 1..4`), `hari` (`CHECK 1..6`), `jam_mulai`, `jam_selesai` (`CHECK jam_mulai < jam_selesai`).
7. `prerequisite`: *self-referencing many-to-many* `(kode_mk, kode_prasyarat)` sebagai PK gabungan + `CHECK kode_mk <> kode_prasyarat`.
8. `krs`: `id` (PK), `nim` (FK -> `calon_mahasiswa.nim`), `semester` (`String(5)`), `status` (`DRAFT`/`SUBMITTED`/`APPROVED`/`REVISION` + CHECK enum), `dosen_pa_id`, `submitted_at`, `approved_at`, `catatan_revisi`, `diubah_pada`, `version` (optimistic locking `version_id_col`), `UNIQUE (nim, semester)`.
9. `krs_detail`: `id` (PK), `krs_id` (FK -> `krs.id` `ON DELETE CASCADE`), `kode_mk` (FK -> `matakuliah.kode_mk`), `nilai` (nullable FK -> `skala_nilai.huruf`), `UNIQUE (krs_id, kode_mk)`.
10. `krs_log`: `id` (PK), `krs_id` (FK -> `krs.id` `ON DELETE CASCADE`, indexed), `aksi`, `aktor_id`, `catatan`, `created_at`.
11. `notifikasi`: `id` (PK), `nim` (FK -> `calon_mahasiswa.nim`, indexed), `pesan`, `terbaca` (default `False`), `created_at`.

---

## Endpoint REST API

### Modul PMB (`/api/pmb`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/pmb/register` | Daftar calon mahasiswa (`pending`) | `201`, `400`, `409` |
| `GET` | `/api/pmb/status/{pendaftar_id}` | Cek status pendaftaran & NIM | `200`, `404` |
| `PUT` | `/api/pmb/approve/{pendaftar_id}` | Setujui & generate NIM (idempotent) | `200`, `400`, `404`, `409` |
| `PUT` | `/api/pmb/reject/{pendaftar_id}` | Tolak pendaftar (idempotent) | `200`, `404`, `409` |
| `GET` | `/api/pmb/stats` | Statistik dashboard PMB | `200` |

### Modul KRS (`/api/krs`)
| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/krs/{nim}?semester=20251` | Melihat isi KRS mahasiswa, total SKS, & `version` | `200`, `404` |
| `POST` | `/api/krs/{nim}/courses?semester=20251` | Tambah mata kuliah (lolos rantai validator *fail-fast*) | `201`, `400`, `404`, `409` |
| `DELETE` | `/api/krs/{nim}/courses/{kode_mk}?semester=20251` | Hapus mata kuliah dari KRS (`DRAFT`/`REVISION`) | `200`, `404`, `409` |
| `GET` | `/api/krs/{nim}/validate?semester=20251` | Validasi menyeluruh KRS (*collect-all* seluruh error) | `200`, `404` |
| `POST` | `/api/krs/{nim}/submit?semester=20251` | Ajukan KRS mahasiswa (`DRAFT`/`REVISION -> SUBMITTED`) | `200`, `400`, `404`, `409` |
| `POST` | `/api/krs/{nim}/approve?semester=20251` | Setujui KRS oleh Dosen PA atomik + *optimistic lock* | `200`, `400`, `403`, `404`, `409` |
| `POST` | `/api/krs/{nim}/revise?semester=20251` | Kembalikan KRS (`SUBMITTED -> REVISION`) + catatan | `200`, `400`, `403`, `404`, `409` |
| `POST` | `/api/krs/{nim}/recommend?semester=20251` | Rekomendasi paket KRS optimal CSP + guardrail validator | `200`, `400`, `404` |

---

## Cara Menjalankan Proyek

```powershell
cd sevima-mini

# 1. Terapkan migrasi database terbaru & seeding data PMB + KRS (idempotent)
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh suite pengujian (PMB + KRS + Hypothesis 1000x + State Machine + CSP)
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Khusus property-based testing & exhaustive 32 kombinasi state machine
.\.venv\Scripts\pytest.exe tests/test_krs_property.py -v

# 4. Jalankan server lokal untuk mencoba Swagger UI (/docs) atau ReDoc (/redoc)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

---

## Referensi

1. Tiangolo, S. *FastAPI Documentation — Dependencies, Additional Status Codes, & Handling Errors*. https://fastapi.tiangolo.com/
2. SQLAlchemy Project. *SQLAlchemy 2.0 Documentation — Relationships, Self-Referential M2M, `Select.with_for_update()`, & Configuring a Version Counter (`version_id_col`)*. https://docs.sqlalchemy.org/en/20/
3. Gamma, E., Helm, R., Johnson, R., & Vlissides, J. (1994). *Design Patterns: Elements of Reusable Object-Oriented Software* (Chain of Responsibility & Template Method).
4. Alembic Project. *Alembic Documentation — Creating & Running Migrations, Batch Mode for SQLite, and Downgrades*. https://alembic.sqlalchemy.org/
5. Pydantic Services Inc. *Pydantic v2 Documentation — Validators & EmailStr*. https://docs.pydantic.dev/latest/
6. SQLite Consortium. *SQLite Documentation — Foreign Keys, Transactions (`BEGIN IMMEDIATE`), & Query Planning (`EXPLAIN QUERY PLAN`)*. https://www.sqlite.org/eqp.html
7. Krekel, H., et al. *pytest Documentation — Fixtures, Parametrize, and pytest-cov*. https://docs.pytest.org/
8. MacIver, D. R., & Hatfield-Dodds, Z. *Hypothesis — Property-Based Testing for Python*. https://hypothesis.readthedocs.io/
9. Russell, S., & Norvig, P. (2020). *Artificial Intelligence: A Modern Approach* (4th ed., Chapter 6: Constraint Satisfaction Problems).

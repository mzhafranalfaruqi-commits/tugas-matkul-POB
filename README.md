# SEVIMA-Mini — Implementasi Modul PMB (Penerimaan Mahasiswa Baru)

Proyek ini merupakan implementasi **Modul Penerimaan Mahasiswa Baru (PMB)** untuk tugas **Minggu 3–4** mata kuliah **Pemrograman Berorientasi Objek untuk Sistem AI Agenik**. Fokus utamanya adalah menerjemahkan artefak desain UML (Class Diagram, Use Case Diagram, Sequence Diagram, dan ADR) dari Minggu 1–2 menjadi kode backend berorientasi objek yang berjalan menggunakan **FastAPI**, **SQLAlchemy 2.0**, **Alembic**, **Pydantic v2**, dan **pytest**.

---

## Pemetaan Desain UML ke Kode

| Artefak Desain (Minggu 1–2) | Implementasi Kode (Minggu 3–4) | Lokasi File |
| :--- | :--- | :--- |
| Class Diagram (`CalonMahasiswa`, `ProgramStudi`, `JalurMasuk`, + `NimCounter`) | Model SQLAlchemy 2.0 (`Mapped`, relasi `ForeignKey`, constraint, counter atomik) | [app/models/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/pmb.py) |
| Use Case Diagram (`Daftar`, `Cek Status`, `Approve`, `Reject`, `Statistik`) | Endpoint REST API `/api/pmb/*` lengkap dengan dokumen `responses={...}` OpenAPI | [app/routers/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/pmb.py) |
| Sequence Diagram (`Router -> PMBService -> Database`) | Pemisahan Router tipis, Service class OOP `PMBService`, & Dependency Injection `get_db()` | [app/services/pmb_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/pmb_service.py), [app/database.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/database.py) |
| Architecture Decision Record (ADR) | Dokumentasi keputusan teknis, resolusi ambiguitas NIM, & migrasi lock ke database | [docs/ADR.md](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/docs/ADR.md) |

---

## Struktur Proyek

```text
sevima-mini/
├── .github/
│   └── pull_request_template.md   # Template PR sesuai rubrik Minggu 4 (AI + Risiko & Limitasi)
├── app/
│   ├── main.py                    # Entrypoint FastAPI + handler RequestValidationError -> 400
│   ├── database.py                # Engine SQLAlchemy, PRAGMA foreign_keys=ON & busy_timeout, get_db()
│   ├── models/
│   │   ├── __init__.py
│   │   └── pmb.py                 # Model ORM SQLAlchemy 2.0 + StatusPMB + NimCounter
│   ├── schemas/
│   │   └── pmb.py                 # Skema Pydantic v2 (validasi email, regex HP ID, response DTO)
│   ├── services/
│   │   ├── exceptions.py          # Domain exception (409, 404, 400)
│   │   ├── nim_generator.py       # format_nim() murni + generate_nim() berbasis nim_counter & flush()
│   │   └── pmb_service.py         # Class OOP PMBService (register, status, approve, reject, stats)
│   └── routers/
│       └── pmb.py                 # Router tipis /api/pmb/* + dokumentasi OpenAPI responses
├── alembic/
│   ├── env.py                     # Konfigurasi target_metadata & PRAGMA FK
│   └── versions/
│       ├── 0001_tabel_pmb.py      # Migrasi awal 3 tabel PMB + downgrade aman FK
│       └── 0002_tabel_nim_counter.py  # Migrasi tabel nim_counter atomik + downgrade
├── tests/
│   ├── conftest.py                # Pytest fixtures (in-memory DB + override TestClient)
│   └── test_pmb.py                # Unit, integration, concurrency, & constraint tests Modul PMB
├── prompts/
│   └── ai-usage-log.md            # Log AI Minggu 3–4 sesuai format silabus + kerangka OPAR
├── docs/
│   ├── ADR.md                     # Architecture Decision Records (ADR-001 s.d. ADR-005)
│   ├── AI_USAGE_LOG.md            # Catatan ringkas AI & kepatuhan AI-First Charter
│   └── PR_MINGGU_4.md             # Draft ringkasan PR Minggu 4 siap tempel beserta log uji
├── seed.py                        # Seeding idempotent program_studi & jalur_masuk
├── alembic.ini
├── requirements.txt
└── README.md
```

---

## Skema Database & Lima Constraint Utama

1. **Tabel `program_studi`**: `id` (PK), `kode` (3 karakter, `UNIQUE`), `nama`, `fakultas`.
2. **Tabel `jalur_masuk`**: `id` (PK), `nama` (`SNBP`, `SNBT`, `Mandiri`, `UNIQUE`).
3. **Tabel `calon_mahasiswa`**: `id` (PK), `nama_lengkap`, `email` (`UNIQUE`, terindeks), `phone`, `tanggal_lahir`, `alamat`, `program_studi_id` (FK), `jalur_masuk_id` (FK), `status` (`Enum`: `pending`, `approved`, `rejected`), `nim` (nullable, `UNIQUE`), `created_at` (`server_default=func.now()`), `approved_at` (nullable).
4. **Tabel `nim_counter`**: *composite primary key* `(tahun, kode_prodi)` dan `last_number` (`INTEGER`, default `0`) untuk menjaga urutan nomor NIM secara atomik di level database.

**Penegakan 5 Constraint:**
- **Unique Email & NIM:** Dijamin di DB melalui `UNIQUE` constraint + index pada `email`, `UNIQUE` pada `nim`, serta pengecekan awal dan tangkapan `IntegrityError` di `PMBService`.
- **Validasi Format Nomor HP Indonesia & Email:** Lapis 1 di Pydantic (`EmailStr` dan pola `^(\+62|62|0)8[1-9][0-9]{6,10}$`), Lapis 2 di DB (`CheckConstraint` panjang `phone` 9–15 karakter dan pola dasar `email LIKE '%_@%_._%'`).
- **Status Enum:** Dibatasi oleh `StatusPMB` di Python/Pydantic dan `CHECK` constraint di SQLite (`create_constraint=True`).
- **NOT NULL:** Diterapkan langsung oleh anotasi `Mapped[T]` tanpa `None` pada SQLAlchemy 2.0.
- **Foreign Key:** Relasi ke `program_studi` dan `jalur_masuk` dijaga aktif di SQLite melalui `PRAGMA foreign_keys=ON`.

---

## Endpoint REST API (`/api/pmb`)

| Method | Endpoint | Fungsi | Status Code |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/pmb/register` | Mendaftarkan calon mahasiswa (status awal `pending`) | `201`, `400`, `409` |
| `GET` | `/api/pmb/status/{pendaftar_id}` | Melihat status pendaftaran dan detail prodi/jalur/NIM | `200`, `404` |
| `PUT` | `/api/pmb/approve/{pendaftar_id}` | Menyetujui pendaftar dan meng-generate NIM otomatis (idempotent) | `200`, `400`, `404`, `409` |
| `PUT` | `/api/pmb/reject/{pendaftar_id}` | Menolak pendaftar yang belum di-approve (idempotent jika sudah `rejected`) | `200`, `404`, `409` |
| `GET` | `/api/pmb/stats` | Menyajikan statistik pendaftar per status, prodi, dan jalur masuk | `200` |

### Format & Cara Kerja NIM Generator
- **Keputusan Format (Resolusi Ambiguitas):** Spesifikasi tugas mencantumkan contoh `2025001-0001` (dengan tanda hubung) dan docstring `YYYY[KODE]XXXX` (tanpa tanda hubung). Proyek ini secara eksplisit memilih format **`[Tahun:4][Kode Prodi:3]-[Running Number:4]`** (contoh: **`2025001-0001`**, Teknik Informatika kode `001`, pendaftar pertama tahun `2025`), didokumentasikan di [ADR-005](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/docs/ADR.md) dan dikunci dengan tes regex `^\d{4}001-\d{4}$`.
- **Helper Murni & Batas Kapasitas:** Pemformatan dipisahkan ke fungsi murni `format_nim(tahun, kode_prodi, nomor_urut)` agar dapat diuji tanpa DB, termasuk validasi overflow saat `nomor_urut > 9999` (`ValueError("Nomor urut habis")`).
- **Idempotent:** Pemanggilan `PUT /api/pmb/approve/{id}` berulang kali pada pendaftar yang sudah `approved` tidak men-generate NIM baru, tidak menambah `nim_counter`, dan tetap mengembalikan NIM yang sama (`already_approved: true`).
- **Anti Race Condition Berbasis Database Lock (Tanpa `threading.Lock`):** Pendekatan `threading.Lock()` di Python sengaja **tidak digunakan** karena hanya mengunci satu proses memori dan gagal pada deployment multi-worker. Sebagai gantinya, proyek memakai tabel `nim_counter` dengan `SELECT ... FOR UPDATE` (`with_for_update()`) untuk MySQL/PostgreSQL serta `BEGIN IMMEDIATE` + `PRAGMA busy_timeout=30000` untuk SQLite, dijalankan dalam **satu transaksi atomik** (`generate_nim()` hanya memanggil `db.flush()`, sedangkan `PMBService.approve()` memegang `db.commit()` / `db.rollback()`), ditambah `UNIQUE` constraint di kolom `nim` dan *retry* maksimal 3x pada `IntegrityError`/lock error.

---

## Cara Menjalankan Proyek

Masuk ke direktori proyek `sevima-mini`, lalu gunakan Python dari virtual environment `.venv`:

### 1. Setup Environment & Instalasi Dependensi
```powershell
cd sevima-mini
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Migrasi Database (Upgrade & Uji Rollback)
```powershell
# Menerapkan seluruh migrasi (0001_tabel_pmb -> 0002_tabel_nim_counter)
.\.venv\Scripts\alembic.exe upgrade head

# Menguji rollback migrasi (downgrade 1 langkah & penuh)
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe downgrade base

# Menerapkan kembali migrasi dan mengisi data referensi awal secara idempotent
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
```

### 3. Menjalankan Server API & Mengakses Dokumentasi OpenAPI
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
Akses dokumentasi interaktif Swagger UI di `http://127.0.0.1:8000/docs`, ReDoc di `http://127.0.0.1:8000/redoc`, atau skema OpenAPI JSON di `http://127.0.0.1:8000/openapi.json`.

### 4. Menjalankan Unit & Integration Tests (`pytest`)
```powershell
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v
```

---

## Referensi

1. Tiangolo, S. *FastAPI Documentation — Dependencies, Additional Status Codes, & Handling Errors*. https://fastapi.tiangolo.com/
2. SQLAlchemy Project. *SQLAlchemy 2.0 Documentation — ORM Mapped Class Configuration, Transactions, & `Select.with_for_update()`*. https://docs.sqlalchemy.org/en/20/
3. SQLAlchemy / Alembic Project. *Alembic Documentation — Creating & Running Migrations and Downgrades*. https://alembic.sqlalchemy.org/
4. Pydantic Services Inc. *Pydantic v2 Documentation — Field Validators & EmailStr*. https://docs.pydantic.dev/latest/
5. SQLite Consortium. *SQLite Documentation — Foreign Key Support (`PRAGMA foreign_keys`), Locking & `BEGIN IMMEDIATE`*. https://www.sqlite.org/lang_transaction.html
6. Krekel, H., et al. *pytest Documentation — Fixtures, Parametrize, and pytest-cov*. https://docs.pytest.org/

# SEVIMA-Mini — Implementasi Modul PMB (Penerimaan Mahasiswa Baru)

Proyek ini merupakan implementasi **Modul Penerimaan Mahasiswa Baru (PMB)** untuk tugas **Minggu 3–4** mata kuliah **Pemrograman Berorientasi Objek untuk Sistem AI Agenik**. Fokus utamanya adalah menerjemahkan artefak desain UML (Class Diagram, Use Case Diagram, Sequence Diagram, dan ADR) dari Minggu 1–2 menjadi kode backend berorientasi objek yang berjalan menggunakan **FastAPI**, **SQLAlchemy 2.0**, **Alembic**, **Pydantic v2**, dan **pytest**.

---

## Pemetaan Desain UML ke Kode

| Artefak Desain (Minggu 1–2) | Implementasi Kode (Minggu 3–4) | Lokasi File |
| :--- | :--- | :--- |
| Class Diagram (`CalonMahasiswa`, `ProgramStudi`, `JalurMasuk`) | Model SQLAlchemy 2.0 (`Mapped`, relasi `ForeignKey`, constraint) | [app/models/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/models/pmb.py) |
| Use Case Diagram (`Daftar`, `Cek Status`, `Approve`, `Reject`, `Statistik`) | Endpoint REST API `/api/pmb/*` | [app/routers/pmb.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/routers/pmb.py) |
| Sequence Diagram (`Router -> Service -> Database`) | Pemisahan Router tipis, Service layer aturan bisnis, & Dependency Injection `get_db()` | [app/services/pmb_service.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/services/pmb_service.py), [app/database.py](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/app/database.py) |
| Architecture Decision Record (ADR) | Dokumentasi keputusan teknis & trade-off implementasi | [docs/ADR.md](file:///c:/Users/Lenovo/OneDrive/Dokumen/tugas%20matkul%20POB/sevima-mini/docs/ADR.md) |

---

## Struktur Proyek

```text
sevima-mini/
├── app/
│   ├── main.py                    # Entrypoint FastAPI + handler RequestValidationError -> 400
│   ├── database.py                # Engine SQLAlchemy, PRAGMA foreign_keys=ON, get_db()
│   ├── models/
│   │   └── pmb.py                 # Model ORM SQLAlchemy 2.0 + StatusPMB Enum + Constraints
│   ├── schemas/
│   │   └── pmb.py                 # Skema Pydantic v2 (validasi email, regex HP ID, response DTO)
│   ├── services/
│   │   ├── exceptions.py          # Domain exception (409, 404, 400)
│   │   ├── nim_generator.py       # Generator NIM thread-safe YYYY[KODE]-XXXX
│   │   └── pmb_service.py         # Logika bisnis register, status, approve, reject, stats
│   └── routers/
│       └── pmb.py                 # Router tipis /api/pmb/*
├── alembic/
│   ├── env.py                     # Konfigurasi target_metadata & PRAGMA FK
│   └── versions/
│       └── 0001_tabel_pmb.py      # Migration upgrade & downgrade (rollback aman FK)
├── tests/
│   ├── conftest.py                # Pytest fixtures (in-memory DB + override TestClient)
│   └── test_pmb.py                # Unit & integration tests Modul PMB
├── docs/
│   ├── ADR.md                     # Architecture Decision Records
│   └── AI_USAGE_LOG.md            # Log penggunaan AI & evaluasi kritis prompt
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

**Penegakan 5 Constraint:**
- **Unique Email & NIM:** Dijamin di DB melalui `UNIQUE` constraint + index pada `email`, serta pengecekan awal + tangkapan `IntegrityError` di `pmb_service.register()`.
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
| `PUT` | `/api/pmb/approve/{pendaftar_id}` | Menyetujui pendaftar dan meng-generate NIM otomatis (idempotent) | `200`, `400`, `404` |
| `PUT` | `/api/pmb/reject/{pendaftar_id}` | Menolak pendaftar yang belum di-approve | `200`, `400`, `404` |
| `GET` | `/api/pmb/stats` | Menyajikan statistik pendaftar per status, prodi, dan jalur masuk | `200` |

### Format & Cara Kerja NIM Generator
Format NIM mengikuti aturan institusi: **`[Tahun:4][Kode Prodi:3]-[Running Number:4]`**  
Contoh: **`2025001-0001`** (Teknik Informatika kode `001`, pendaftar disetujui pertama pada tahun `2025`).
- **Idempotent:** Pemanggilan `PUT /api/pmb/approve/{id}` berulang kali pada pendaftar yang sudah `approved` tidak men-generate NIM baru dan tetap mengembalikan NIM yang sama (`already_approved: true`).
- **Thread-safe & Anti Race Condition:** Dilindungi `threading.RLock()` pada siklus baca-generate-commit, penguncian baris `SELECT ... FOR UPDATE` pada `program_studi` untuk DB produksi (MySQL/PostgreSQL), serta constraint `UNIQUE` di kolom `nim` dengan retry otomatis.

---

## Cara Menjalankan Proyek

Masuk ke direktori proyek `sevima-mini`, lalu gunakan Python dari virtual environment `.venv`:

### 1. Setup Environment & Instalasi Dependensi
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Migrasi Database (Upgrade & Uji Rollback)
```powershell
# Menerapkan migrasi awal
.\.venv\Scripts\alembic.exe upgrade head

# Menguji rollback migrasi (downgrade)
.\.venv\Scripts\alembic.exe downgrade -1

# Menerapkan kembali migrasi dan mengisi data referensi awal
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
```

### 3. Menjalankan Server API & Mengakses Swagger UI
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
Akses dokumentasi interaktif Swagger UI di `http://127.0.0.1:8000/docs` atau skema OpenAPI di `http://127.0.0.1:8000/openapi.json`.

### 4. Menjalankan Unit & Integration Tests (`pytest`)
```powershell
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing -v
```

---

## Referensi

1. Tiangolo, S. *FastAPI Documentation — Dependencies, Handling Errors, & Request Validation*. https://fastapi.tiangolo.com/
2. SQLAlchemy Project. *SQLAlchemy 2.0 Documentation — ORM Mapped Class Configuration & Declarative Mapping*. https://docs.sqlalchemy.org/en/20/
3. SQLAlchemy / Alembic Project. *Alembic Documentation — Auto Generating Migrations & Downgrade Scripts*. https://alembic.sqlalchemy.org/
4. Pydantic Services Inc. *Pydantic v2 Documentation — Validators & EmailStr*. https://docs.pydantic.dev/latest/
5. SQLite Consortium. *SQLite Documentation — Foreign Key Support (`PRAGMA foreign_keys`) & CHECK Constraints*. https://www.sqlite.org/foreignkeys.html
6. Krekel, H., et al. *pytest Documentation — Fixtures, Parametrize, and pytest-cov*. https://docs.pytest.org/

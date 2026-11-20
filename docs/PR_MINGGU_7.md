# Pull Request Minggu 7 — Modul Jadwal & Ruangan Bagian 1: CSP, Deteksi Bentrok, & Scheduling Service (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan deliverable **Minggu 7 — Modul Jadwal & Ruangan Bagian 1**:
  - **Model Domain & Migrasi `0005_tabel_jadwal_ruangan.py` (`app/models/jadwal.py`, `app/models/krs.py`):**
    - Menambahkan 4 model ORM SQLAlchemy 2.0 (`Ruangan`, `Dosen`, `Kelas`, `Jadwal`) lengkap dengan constraint `kapasitas >= 1`, `kuota >= 1`, `hari BETWEEN 1 AND 6`, `jam_mulai < jam_selesai`, `UNIQUE(nidn)`, `UNIQUE(kode_mk, nama, semester)`, serta index `ix_jadwal_ruang` dan `ix_jadwal_dosen`.
    - Menambahkan kolom nullable terindeks `krs_detail.kelas_id` (FK -> `kelas.id`) melalui `batch_alter_table` agar `downgrade -1` aman di SQLite, sambil mempertahankan sementara atribut jadwal lama di `matakuliah` (*expand-contract*, ADR-010).
  - **Detektor Bentrok 3 Dimensi (`app/services/conflict.py`):**
    - Mengimplementasikan `Conflict(frozen=True)` dengan `ConflictType = Literal["room_conflict", "lecturer_conflict"]`, `JadwalSlot` + `JadwalLike(Protocol)`, detektor acuan `detect_naive()` ($O(n^2)$ berbasis `itertools.combinations`), dan detektor utama `detect_schedule_conflict()` berbasis **Grouping + Sort & Sweep** ($O(n \log n + k)$).
    - Menegakkan interval setengah-terbuka `[jam_mulai, jam_selesai)` dengan `<` (`>` di *sweep*) agar kuliah bersambung tepat (`08:00–09:40` & `09:40–11:20`) tetap sah.
  - **Scheduling Service & Capacity Check (`app/services/scheduling_service.py`):**
    - Mengimplementasikan `cek_kapasitas()` memakai `max(kelas.kuota, terdaftar)` terhadap `ruangan.kapasitas`.
    - Mengimplementasikan `create()`, `update()`, `delete()`, dan `list_conflicts()` dengan penguncian baris tetap **`Ruangan` -> `Dosen`** (`with_for_update()` + `BEGIN IMMEDIATE` di SQLite), mencegah *autoflush* sebelum pemeriksaan selesai (`db.add` paling akhir), serta menyiapkan *hook* untuk pola Observer Minggu 8.
  - **Exception Polimorfik, Skema Pydantic, & Router `/api/jadwal` (`app/services/exceptions.py`, `app/schemas/jadwal.py`, `app/routers/jadwal.py`, `app/main.py`):**
    - Menambahkan `ScheduleError` (`NotFoundError -> 404`, `CapacityError -> 409`, `ScheduleConflictError -> 409` dengan `conflicts`), skema `JadwalIn` (`jam_mulai < jam_selesai`), `JadwalOut`, `ConflictOut`, dan 4 endpoint (`GET /api/jadwal/conflicts`, `POST /api/jadwal`, `PUT /api/jadwal/{jadwal_id}`, `DELETE /api/jadwal/{jadwal_id}`).
    - Memetakan error validasi Pydantic rute `/api/jadwal/*` ke HTTP `422` sambil menjaga `400` pada rute `/api/pmb/*` & `/api/krs/*`.
  - **Seed Data, Test Suite, Benchmark, & ADR (`seed.py`, `tests/test_conflict.py`, `tests/test_conflict_property.py`, `docs/ADR.md`):**
    - Menambahkan `seed_jadwal_data()` idempotent (12 ruangan, 16 dosen, 24 kelas paralel, 44 jadwal dengan 6 bentrok historis sengaja).
    - Menambahkan 14 tes unit/constraint/API/concurrency/seed di `tests/test_conflict.py`, 2 tes *property-based* & *differential* Hypothesis (`max_examples=500`) di `tests/test_conflict_property.py`, serta **ADR-010, ADR-011, & ADR-012**.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI (Antigravity) membantu menyusun struktur model SQLAlchemy 2.0, migrasi Alembic `0005`, fungsi `detect_naive` vs `detect_schedule_conflict`, `SchedulingService`, router `/api/jadwal`, serta skenario uji dan dokumentasi ADR/OPAR ([prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- **Koreksi manual & temuan kritis mahasiswa:**
  1. Memastikan 5 bug klasik AI tertutup: operator `<` (bukan `<=`), tipe `datetime.time` (bukan `str`), pemeriksaan `hari` sama, tidak ada duplikasi `(A, B)/(B, A)` maupun `elif` yang menghilangkan konflik ganda, serta tidak ada tipe palsu `"time_overlap"`.
  2. Menempatkan `_mulai_transaksi_terkunci()` (`BEGIN IMMEDIATE`) sebelum `db.get()` di `update()`/`delete()` dan `db.add(jadwal)` paling akhir sebelum `db.commit()` agar bebas jebakan *autoflush* dan transaksi baca implisit SQLite.
  3. Memperbaiki test case bentrok API `08:30–10:00` yang ternyata memang bertabrakan dengan **dua** jadwal bersambung (`08:00–09:40` dan `09:40–11:20`), lalu memisahkan assertion untuk tabrakan tunggal (`08:30–09:30`) vs tabrakan ganda (`08:30–10:00`).
  4. Menjalankan benchmark nyata pada `n=600` jadwal (`2.40–2.84 ms` sweep vs `25.94–39.61 ms` naif) sebagai dasar empiris ADR-011 menunda *Interval Tree*.
- **3 Prompt Terbaik:**
  1. Desain model 4 entitas jadwal (`Ruangan`, `Dosen`, `Kelas`, `Jadwal`) + `krs_detail.kelas_id` dengan migrasi `0005` `batch_alter_table` rollback-safe dan pola *expand-contract* menjaga kompatibilitas 83 tes sebelumnya.
  2. Implementasi `detect_naive` dan `detect_schedule_conflict` (*Grouping + Sort & Sweep*) yang bebas 5 bug klasik AI, serta `tests/test_conflict_property.py` dengan oracle slot 1-jam independen dan differential testing Hypothesis.
  3. Implementasi `SchedulingService` (`cek_kapasitas` `max(kuota, terdaftar)`, penguncian baris tetap `Ruangan -> Dosen`, anti-autoflush) dan router `/api/jadwal` dengan handler polimorfik `ScheduleError` (`404`/`409`) serta HTTP `422` validasi.

## Risiko & Limitasi
1. **Engine Penguncian (SQLite vs MySQL/PostgreSQL):** Uji konkurensi dan transaksi berjalan pada **SQLite** (`BEGIN IMMEDIATE` + `PRAGMA busy_timeout=30000`), karena SQLite mengabaikan klausa `SELECT ... FOR UPDATE`. Perilaku *row-level lock* per ruangan/dosen di MySQL InnoDB atau PostgreSQL nyata tetap perlu diverifikasi pada tahap deployment.
2. **Filter Semester Aktif Belum Diterapkan di Pencarian Bentrok:** Sesuai batasan cakupan Minggu 7, `_bentrok_di_db()` dan `list_conflicts()` saat ini memeriksa seluruh baris di tabel `jadwal` tanpa memfilter `kelas.semester` tertentu; bila data lintas semester sudah disimpan bersamaan pada tabel `jadwal`, diperlukan *join* dan filter `Kelas.semester == aktif`.
3. **Ruang Lingkup Minggu 8 (Bagian 2):** Implementasi *Observer pattern* notifikasi perubahan jadwal (`Email/SMS/Push` via log + sequence diagram UML), saran jadwal alternatif berbasis AI, integrasi invalidasi KRS terdampak saat jadwal berubah/dihapus, serta *Conflict Resolver UI* dijadwalkan pada Minggu 8.

## Cara Uji
```powershell
cd sevima-mini

# 1. Uji rantai migrasi Alembic 0005 & seeding idempotent (2x)
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed.py

# 2. Uji property-based testing & differential testing (500 contoh acak)
.\.venv\Scripts\pytest.exe tests/test_conflict_property.py -v

# 3. Jalankan seluruh suite pengujian (PMB + KRS + Jadwal) beserta batas coverage 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v
```

## Log Hasil Uji
- **Alembic Migration Chain (`0005_tabel_jadwal_ruangan`):**
  - `upgrade head` -> `downgrade -1` -> `upgrade head` sukses keluar kode `0` tanpa error SQLite `batch_alter_table`.
- **Seeding Idempotent (`seed.py` x2):**
  - Menghasilkan **12 ruangan**, **16 dosen**, **24 kelas**, dan **44 jadwal** secara idempotent (jumlah baris identik pada eksekusi kedua) dengan **6 konflik disengaja** (`3 room_conflict`, `3 lecturer_conflict` termasuk 1 pasangan bentrok ganda).
- **Benchmark Nyata (`n = 600` jadwal, `seed=42`, rata-rata 10x jalan):**
  - Padat (12 ruang, 16 dosen, `1167` konflik): `detect_naive` **`25.94 ms`** vs `detect_schedule_conflict` **`2.84 ms`** (~9.1x lebih cepat, hasil identik).
  - Menyebar (30 ruang, 40 dosen, `455` konflik): `detect_naive` **`39.61 ms`** vs `detect_schedule_conflict` **`2.40 ms`** (~16.5x lebih cepat, hasil identik).
- **Pytest + Hypothesis + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`99 passed, 1 warning in 39.17s`** (14 tes unit/constraint/API/concurrency/seed di `tests/test_conflict.py` + 2 tes Hypothesis 500x di `tests/test_conflict_property.py` + 83 tes PMB & KRS tanpa regresi).
  - **Total Coverage: `95.81%` (`96%`)** (`app/models/jadwal.py` 100%, `app/models/krs.py` 100%, `app/services/conflict.py` 100%, `app/schemas/jadwal.py` 100%, `app/routers/jadwal.py` 100%, `app/services/exceptions.py` 100%, `app/main.py` 100%, `app/services/scheduling_service.py` 88%).

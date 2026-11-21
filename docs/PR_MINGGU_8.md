# Pull Request Minggu 8 — Modul Jadwal & Ruangan Bagian 2: Observer, Outbox, KRS Integration, AI Rescheduling, Conflict Resolver UI, & iCalendar (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan deliverable **Minggu 8 — Modul Jadwal & Ruangan Bagian 2**:
  - **Observer Pattern + Transactional Outbox (`app/services/observer.py`, `app/models/jadwal.py`, migrasi `0006_outbox_dan_jadwal_sequence.py`):**
    - Mengimplementasikan `EventType` (`SCHEDULE_CHANGED`, `SCHEDULE_DELETED`), `ScheduleEvent(frozen=True)`, `Observer(Protocol)`, dan `ScheduleSubject` (deduplikasi `attach()`, aman `detach()`, serta isolasi `try/except` per observer di `notify() -> list[str]`).
    - Mengimplementasikan 3 concrete observer (`StudentObserver`, `LecturerObserver` yang memberi tahu dosen baru maupun dosen sebelumnya saat terjadi pergantian pengampu, serta `AdminObserver`) dengan `Channel(Protocol)` dan `LogChannel` (`EMAIL`, `SMS`, `PUSH`) berbasis kunci idempotensi `{event_id}:{penerima}:{channel}` di `MemoryIdemStore`.
    - Menambahkan model `Outbox` (`PENDING` / `SENT` / `FAILED`, `attempts`) dan kolom `jadwal.sequence` pada migrasi `0006` dengan `batch_alter_table`, serta `OutboxDispatcher` (`MAX_ATTEMPTS = 5`, `with_for_update(skip_locked=True)`) yang hanya berjalan **setelah `db.commit()` sukses**. Observer dipasang **sekali** saat inisialisasi modul (singleton) agar tidak terjadi kebocoran memori atau pengiriman duplikat per HTTP request.
  - **Integrasi State Machine KRS (`app/models/krs.py`, `app/services/krs_invalidator.py`, `app/services/scheduling_service.py`):**
    - Menambahkan `Actor.SISTEM` beserta 2 transisi legal baru `(SUBMITTED, SISTEM) -> REVISION` dan `(APPROVED, SISTEM) -> REVISION`, sehingga ruang uji state machine bertambah dari `32` kombinasi menjadi **`48`** (**6 sah, 42 ilegal**).
    - Mengimplementasikan `KRSInvalidator.invalidate(kelas_id, alasan)` tanpa memanggil `commit()` sendiri agar invalidasi KRS (`SUBMITTED`/`APPROVED` -> `REVISION`, `catatan_revisi = "Otomatis: ..."`, kenaikan `version`, `KRSLog(aksi="INVALIDATE")`, dan `Notifikasi`), pembaruan/penghapusan jadwal (`sequence += 1`), dan penulisan baris `Outbox` berlangsung atomik dalam 1 transaksi `SchedulingService`.
  - **AI-Powered Rescheduling & Conflict Resolver UI (`app/services/rescheduler.py`, `app/templates/resolver.html`, `app/routers/jadwal.py`, `seed.py`):**
    - Menghitung slot bebas deterministik (`hitung_slot_tersedia`), menyusun prompt terstruktur (`bangun_prompt`), menyediakan `LLMClient(Protocol)` (`EnvLLMClient` adaptif via HTTP jika API key env tersedia + fallback deterministik `HeuristicLLMClient`), serta mengeksekusi guardrail 4 lapis `saring_saran()` (parse JSON aman `raw_decode`, skema Pydantic `Saran`, cek eksistensi ruangan & `kapasitas >= peserta`, dan `detect_schedule_conflict` kandidat `id=-1` maksimal 3 saran).
    - Menambahkan `ReschedulerService.apply_saran()` lewat satu pintu `SchedulingService.update()`, endpoint `GET /api/jadwal/resolver` (halaman HTML dashboard mandiri), `GET /api/jadwal`, `GET /api/jadwal/{id}/suggestions`, `POST /api/jadwal/{id}/apply`, proteksi `require_admin` (`X-Role: admin` -> `403 Forbidden`), serta KRS aktif `20251` Budi (`2025001-0001`) di `seed.py`.
  - **Ekspor iCalendar RFC 5545 & Dokumentasi (`app/services/icalendar.py`, `docs/SEQUENCE_OBSERVER.md`, `docs/ADR.md`, `tests/test_jadwal_observer.py`):**
    - Menambahkan formatter `ke_vevent()` & `export_jadwal_ics()` berakhiran `CRLF` (`\r\n`), `VTIMEZONE Asia/Jakarta`, `DTSTART`/`DTEND;TZID=Asia/Jakarta`, `RRULE:FREQ=WEEKLY;UNTIL=...Z`, `UID` stabil `jadwal-{id}@sevima-mini`, dan `SEQUENCE` sinkron dengan pembaruan jadwal pada endpoint `GET /api/mahasiswa/{nim}/jadwal.ics`.
    - Menyusun diagram sekuens Mermaid di `docs/SEQUENCE_OBSERVER.md` (`COMMIT` sebelum `notify`) dan **ADR-013, ADR-014, serta ADR-015**.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI (Antigravity) membantu menyusun implementasi Observer + Transactional Outbox, perluasan State Machine KRS (`Actor.SISTEM`), guardrail 4 lapis AI Rescheduler, generator `.ics` RFC 5545, UI Conflict Resolver HTML, diagram sekuens Mermaid, ADR-013..015, dan suite pengujian `tests/test_jadwal_observer.py` ([prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- **Koreksi manual & temuan kritis mahasiswa:**
  1. **Bug `rfind("]")` di `HeuristicLLMClient` & `parse_saran`:** Pengujian `test_heuristic_llm_client_fallback_tanpa_api_key` menangkap kegagalan parsing karena `bangun_prompt()` menyertakan contoh JSON `[{"hari": 3, ...}]` setelah blok `SLOT_TERSEDIA_JSON:`, sehingga `rfind("]")` menangkap penutup JSON contoh. Diperbaiki menggunakan `json.JSONDecoder().raw_decode()` (dan pencarian iteratif `[` di `parse_saran`).
  2. **Ekspektasi 6 `VEVENT` pada Seed Budi `20251`:** Verifikasi tes `.ics` end-to-end menunjukkan bahwa 3 kelas yang diambil Budi (`IF201-B`, `IF102-A`, `IF204-A`) masing-masing memiliki 2 pertemuan mingguan di `seed.py`, sehingga dokumen `.ics` yang benar memuat 6 blok `VEVENT` stabil berurutan.
  3. **Status HTTP `422` pada `apply_saran` Melewati Tengah Malam & Backward Compatibility:** Menambahkan `ScheduleValidationError` (`status_code = 422`) pada `app/services/exceptions.py` agar ditangani otomatis oleh handler polimorfik `ScheduleError` di `app/main.py`, dan menjaga `SchedulingService(db)` tetap dapat dipanggil 1 argumen oleh kode & tes lama.
  4. **Isolasi Session pada Singleton Subject:** Menggunakan `ContextVar` (`_dispatch_session_var`) di `OutboxDispatcher` dan `DBPesertaRepo` agar singleton `ScheduleSubject` (dipasang sekali saat startup) tetap membaca transaksi DB aktif, termasuk database SQLite in-memory di `pytest`.
- **3 Prompt Terbaik:**
  1. Implementasikan `ScheduleSubject` (`attach` anti-duplikat, `notify` terisolasi `try/except`), 3 observer (`Student`, `Lecturer` termasuk dosen lama+baru, `Admin`), `LogChannel` (`EMAIL/SMS/PUSH`) + idempotency key, serta model `Outbox` (`0006`) + `OutboxDispatcher` (`SKIP LOCKED`, max 5 retry -> `FAILED`) yang hanya berjalan sesudah `commit()`.
  2. Tambahkan `Actor.SISTEM` pada state machine KRS (`SUBMITTED/APPROVED -> REVISION`), perbarui uji komprehensif state machine menjadi `48` kombinasi (`6` sah + `42` ilegal), dan hubungkan `KRSInvalidator` (tanpa commit internal) ke transaksi tunggal `SchedulingService.update/delete`.
  3. Bangun AI Rescheduler (`hitung_slot_tersedia`, `bangun_prompt`, `parse_saran`, `saring_saran` 4 lapis, `HeuristicLLMClient` fallback offline, & `apply_saran` satu pintu via `SchedulingService.update`), UI HTML `/api/jadwal/resolver`, guard `X-Role: admin` (`403`), serta ekspor RFC 5545 `.ics` (`CRLF`, `Asia/Jakarta`, UTC `UNTIL`, `SEQUENCE` naik).

## Risiko & Limitasi
1. **Engine Database Lock (SQLite vs MySQL/PostgreSQL):** Pengujian berjalan pada SQLite (`BEGIN IMMEDIATE` + `PRAGMA busy_timeout=30000`), sedangkan klausa `with_for_update(skip_locked=True)` pada `OutboxDispatcher` hanya aktif secara nyata di MySQL 8+ / PostgreSQL dan diabaikan oleh SQLite.
2. **Eksekusi `OutboxDispatcher` Sinkron & `MemoryIdemStore` In-Memory:** Di proyek kuliah ini, `_dispatch_after_commit()` memanggil `OutboxDispatcher.run()` secara sinkron tepat setelah `db.commit()` dan `MemoryIdemStore` menyimpan kunci dedup di RAM proses Python. Untuk produksi multi-worker atau *traffic* tinggi, *dispatcher* perlu dijalankan sebagai *background worker* terpisah (atau dipublish ke broker) dan `IdemStore` dipindah ke Redis atau tabel DB persisten.
3. **Autentikasi Role Demo (`X-Role: admin`):** Pembatasan akses admin pada `/api/jadwal/*` saat ini mengandalkan header `X-Role` untuk simulasi lokal UI dan API sebelum sistem autentikasi JWT/OAuth2 terintegrasi; tidak aman dipakai di produksi tanpa token terverifikasi.
4. **Cakupan Tanggal Semester pada `.ics`:** Parameter `awal` dan `akhir` semester pada `export_jadwal_ics()` memakai rentang default kalender `2025-09-01` s.d. `2025-12-20` karena tabel kalender akademik semester belum dimodelkan.

## Cara Uji
```powershell
cd sevima-mini

# 1. Uji migrasi Alembic 0006 (naik, rollback -1, naik lagi) & seeding idempotent (2x)
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh unit, property-based, state machine, integrasi, UI, & .ics tests
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Demo interaktif UI Conflict Resolver & ekspor .ics di browser
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# Buka http://127.0.0.1:8000/api/jadwal/resolver dan http://127.0.0.1:8000/api/mahasiswa/2025001-0001/jadwal.ics
```

## Log Hasil Uji
- **Alembic Migration Chain (`0006_outbox_dan_jadwal_sequence`):**
  - `upgrade head` -> `downgrade -1` -> `upgrade head` selesai dengan exit code `0` (`jadwal.sequence` & tabel `outbox` berhasil dibuat dan di-rollback bersih di SQLite).
- **Seeding Idempotent (`seed.py` x2):**
  - Eksekusi ke-1 & ke-2 selesai tanpa error, menghasilkan KRS `20251` (`APPROVED`) tertaut `kelas_id` untuk `2025001-0001` serta jumlah baris `KRS`/`KRSDetail`/`Jadwal` identik pada eksekusi berulang.
- **Pytest + Hypothesis + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`126 passed, 1 warning in 21.42s`** (11 test komprehensif Minggu 8 di `tests/test_jadwal_observer.py` + `tests/test_krs_property.py` yang diperbarui ke 48 kombinasi state machine + `tests/test_conflict.py` & `tests/test_conflict_property.py` + `tests/test_krs.py` + `tests/test_pmb.py` tanpa regresi).
  - **Total Coverage: `95.04%` (`95%`)** (`app/models/jadwal.py` 100%, `app/models/krs.py` 100%, `app/services/icalendar.py` 100%, `app/services/exceptions.py` 100%, `app/routers/jadwal.py` 99%, `app/schemas/jadwal.py` 98%, `app/services/krs_invalidator.py` 96%, `app/services/observer.py` 95%, `app/services/rescheduler.py` 90%, `app/services/scheduling_service.py` 88%).

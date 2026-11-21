# Pull Request Minggu 10 — Modul Nilai & Transkrip Bagian 2: `get_transcript`, Predikat Kelulusan, & Generator PDF (`sevima-mini`)

## Fitur & Isu
- Menyelesaikan deliverable **Minggu 10 — Modul Nilai & Transkrip Bagian 2** secara lengkap:
  - **Domain Murni Transkrip & Predikat (`app/domain/gpa.py`, `app/domain/__init__.py`):**
    - Menambahkan struktur domain beku `RekordNilaiLengkap`, `BarisNilaiTranskrip`, `SemesterTranskrip`, dan `RingkasanTranskrip` yang 100% bebas I/O dengan aritmetika `Decimal` (`ROUND_HALF_UP`).
    - Mengimplementasikan `format_label_semester()` (mis. `"20241"` -> `"2024/2025 Ganjil"`), `tentukan_predikat()` (`"Cum Laude"` >= `3.50`, `"Sangat Memuaskan"` >= `3.00`, `"Memuaskan"` >= `2.50`, `"Cukup"` >= `2.00`, atau belum memenuhi syarat/predikat bila `total_sks_lulus == 0`), dan `bangun_ringkasan_transkrip()` (urutan semester menaik, penandaan tepat satu `dipakai_ipk=True` per MK lulus terbaik, total SKS tempuh vs lulus, serta predikat).
  - **Layanan `get_transcript(nim)` Compute-on-Read (`app/services/gpa_calculator.py`):**
    - Menambahkan `BiodataTranskrip`, `TranskripAkademik`, metode `NilaiRepo.biodata_mahasiswa()` & `NilaiRepo.records_lengkap()`, serta `GPACalculator.get_transcript(nim)` sehingga setiap input atau koreksi nilai langsung memperbarui data transkrip, IPK, dan predikat saat dibaca (`GradeNotFoundError` `404` bila NIM tidak ada).
  - **Template HTML/CSS Resmi & Generator PDF ReportLab (`app/templates/transkrip.html`, `app/services/transcript_pdf.py`):**
    - Membangun template Jinja2 profesional bergaya dokumen resmi/ijazah (`@page A4`, kop & logo SVG universitas, judul `TRANSKRIP AKADEMIK`, biodata 2 kolom, tabel per semester `[Kode MK | Nama MK | SKS | Nilai | Mutu]` + rekap IPS, ringkasan SKS/IPK/predikat, blok TTD Dekan, serta toolbar cetak `.no-print`).
    - Mengimplementasikan port `TranscriptPdfRenderer` dan **`ReportLabTranscriptRenderer`** (Pure-Python tanpa dependensi biner C WeasyPrint di Windows) dengan logo vektor, bingkai halaman + nomor halaman otomatis, tabel `repeatRows=1` yang aman untuk multi-halaman, sanitasi nama file header `Content-Disposition`, dan escaping XML `xml_escape` pada seluruh teks dinamis `Paragraph`.
  - **API Endpoints, Integrasi UI Nilai, Demo Seed 3 Semester, & ADRs (`app/routers/nilai.py`, `app/schemas/nilai.py`, `app/templates/nilai_form.html`, `seed.py`, `docs/ADR.md`):**
    - Menambahkan `GET /api/mahasiswa/{nim}/transkrip` (JSON), `GET /api/mahasiswa/{nim}/transkrip/preview` (HTML resmi), dan `GET /api/mahasiswa/{nim}/transkrip.pdf` (`attachment` default maupun `?inline=true`), serta tautan pratinjau `Transkrip` dan `PDF` pada tiap baris peserta di `/api/kelas/nilai-form`.
    - Menambahkan `seed_transkrip_demo_data()` secara idempoten untuk mahasiswa 3 semester **Dina Kartika** (`2025001-0004`, 28 SKS lulus, mutu `107.00`, IPK `"3.82"`, `"Cum Laude"`) tanpa mengganggu data Rina (`"3.08"`).
    - Menambahkan **ADR-018** & **ADR-019**.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Asisten AI membantu menyusun fungsi agregasi domain murni di `app/domain/gpa.py`, desain tata letak HTML/CSS `transkrip.html`, renderer PDF `ReportLabTranscriptRenderer`, perluasan endpoint & skema Pydantic, serta suite pengujian parsing PDF + multi-semester ([prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- **Koreksi manual & temuan kritis mahasiswa:**
  1. **Jebakan Escaping XML ReportLab & `Table([])` Kosong:** Memastikan seluruh field dinamis (nama mahasiswa/MK berisi `&` atau `<script>`) di-escape lewat `xml.sax.saxutils.escape` sebelum masuk ke `Paragraph`, mencegah `Table([])` kosong bagi mahasiswa semester 1 tanpa nilai, dan mencegah penggunaan glif Unicode non-WinAnsi agar font bawaan PDF bebas karakter kotak.
  2. **Isolasi Fixture TestClient di Multi-Step Acceptance Test:** Memperbaiki `finally: app.dependency_overrides.clear()` menjadi `app.dependency_overrides.pop(get_presensi_port, None)` di `tests/test_transcript.py` agar request verifikasi transkrip/PDF setelah `PUT /nilai` tetap memakai database uji `db_session` (bukan fallback ke `sevima.db` disk).
  3. **Kompatibilitas Uji Rina Minggu 9:** Memisahkan data demo 3 semester (`2025001-0004` Dina Kartika) ke `seed_transkrip_demo_data()` terpisah dari `seed_nilai_demo_data()` sehingga asersi IPK seed Rina `"3.08"` tetap 100% lulus.
- **3 Prompt Terbaik:**
  1. Rancang fungsi domain murni `app/domain/gpa.py` (`tentukan_predikat`, `format_label_semester`, `bangun_ringkasan_transkrip`) berbasis `Decimal` `ROUND_HALF_UP` dan perluas `NilaiRepo`/`GPACalculator` dengan `get_transcript(nim)` secara compute-on-read.
  2. Implementasikan dual renderer pada `TranskripAkademik`: template Jinja2 resmi bergaya ijazah (`transkrip.html` ber-autoescape & CSS `@page A4`) serta port `TranscriptPdfRenderer` dengan `ReportLabTranscriptRenderer` (logo vektor, tabel `repeatRows=1`, `KeepTogether` ringkasan + TTD Dekan, XML escaping, dan header `Content-Disposition` tersanitasi).
  3. Tambahkan endpoint JSON/HTML/PDF di router nilai serta suite uji `tests/test_gpa.py` & `tests/test_transcript.py` (mahasiswa belum ada nilai, escaping XSS `&`/`<script>`, ekstraksi isi PDF lewat `pypdf`, idempotency seed 3 semester Dina, dan acceptance test 4 semester dengan MK ulang + edit nilai ber-alasan + PDF `>= 2` halaman).

## Risiko & Limitasi
1. **Aturan Tambahan Predikat `Cum Laude`:** Sebagian perguruan tinggi mensyaratkan masa studi maksimal (mis. `<= 8` semester) atau tanpa nilai ulang untuk predikat *Cum Laude*; saat ini `tentukan_predikat()` mengacu pada ambang IPK di dokumen modul dan disiapkan untuk diperluas (**ADR-018**).
2. **Pemeliharaan Dual Renderer (`HTML` vs `ReportLab`):** Desain tata letak dokumen HTML pratinjau dan biner PDF perlu dijaga selaras secara manual saat ada revisi format kop/tanda tangan sebelum potensi migrasi ke renderer *headless browser* atau WeasyPrint di server Linux (**ADR-019**).
3. **Integrasi Autentikasi Mahasiswa:** Endpoint `/api/mahasiswa/{nim}/transkrip*` saat ini terbuka untuk demo lokal; pada produksi perlu validasi JWT/RBAC agar mahasiswa hanya dapat mengakses transkrip miliknya sendiri.

## Cara Uji
```powershell
cd sevima-mini

# 1. Verifikasi Alembic head & seeding idempotent 2x (termasuk Dina 3 semester)
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed.py

# 2. Uji domain murni IPK/IPS, predikat, & ringkasan transkrip
.\.venv\Scripts\pytest.exe tests/test_gpa.py -v

# 3. Uji endpoint transkrip, parsing PDF (pypdf), & acceptance 4 semester
.\.venv\Scripts\pytest.exe tests/test_transcript.py -v

# 4. Jalankan seluruh suite pengujian (Minggu 3–10) + coverage check >= 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 5. Demo browser preview & unduh PDF resmi
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# Buka http://127.0.0.1:8000/api/mahasiswa/2025001-0004/transkrip/preview
# atau http://127.0.0.1:8000/api/mahasiswa/2025001-0004/transkrip.pdf
```

## Log Hasil Uji
- **Alembic & Seeding (`0007_nilai_grade_history_view (head)`):**
  - `alembic current` menunjukkan `0007_nilai_grade_history_view (head)` dan `seed.py` dijalankan **2x** berturut-turut dengan keluar kode `0` (`Seeding data PMB, KRS, Jadwal, Nilai, dan Transkrip selesai.`).
- **Pytest Pure Domain (`pytest tests/test_gpa.py -v`):**
  - **`38 passed, 1 warning in 7.14s`** (21 tes IPK/IPS/Hypothesis Minggu 9 + 17 tes baru predikat, format label semester, dan ringkasan transkrip).
- **Full Pytest + Coverage (`pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v`):**
  - **`176 passed, 1 warning in 35.86s`** (seluruh tes Minggu 3–10 lulus tanpa regresi, termasuk 6 tes baru `tests/test_transcript.py` dengan verifikasi teks PDF via `pypdf` dan skenario multi-halaman).
  - **Total Coverage: `95.88%` (`96%`)** (`app/domain/gpa.py` 100%, `app/domain/__init__.py` 100%, `app/routers/nilai.py` 100%, `app/schemas/nilai.py` 100%, `app/main.py` 100%, `app/services/transcript_pdf.py` 99%, `app/services/grade_service.py` 96%, `app/services/gpa_calculator.py` 94%).

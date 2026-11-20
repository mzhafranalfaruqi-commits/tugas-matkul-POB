# Pull Request — Modul PMB SEVIMA-Mini

## Fitur & Isu
- Menutup isu / deliverable: `#...` (isi nomor issue terkait, misalnya `#1 Skema DB & Migrasi`, `#2 Endpoint Approve, NIM Generator, & Testing`)
- Ringkasan perubahan:
  - Jelaskan secara singkat komponen model, service, router, migrasi, atau pengujian yang ditambahkan/diubah.

## Apa yang Dibantu AI (+ 3 Prompt Terbaik)
- Ringkasan peran asisten AI pada PR ini (sertakan referensi ke [prompts/ai-usage-log.md](../prompts/ai-usage-log.md)).
- Koreksi manual mahasiswa terhadap output AI (misalnya penyesuaian HTTP status code, penghapusan *anti-pattern*, dan validasi constraint database).
- **3 Prompt Terbaik:**
  1. *(Isi ringkasan prompt terbaik #1)*
  2. *(Isi ringkasan prompt terbaik #2)*
  3. *(Isi ringkasan prompt terbaik #3)*

## Risiko & Limitasi
- Cantumkan secara jujur keterbatasan lingkungan pengujian (misalnya pengujian `pytest` berjalan pada SQLite lokal/in-memory sehingga perilaku *row lock* `SELECT ... FOR UPDATE` InnoDB MySQL/PostgreSQL baru terjamin secara mekanisme query dan perlu uji beban pada DBMS produksi).
- Cantumkan asumsi atau kasus batas yang belum diuji secara penuh (misalnya simulasi multi-worker Uvicorn/Gunicorn di Docker).

## Cara Uji
```powershell
# 1. Terapkan migrasi database terbaru & seed referensi
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py

# 2. Jalankan seluruh unit & integration tests beserta batas minimal coverage 80%
.\.venv\Scripts\pytest.exe --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# 3. Verifikasi Swagger UI / ReDoc
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Log Hasil Uji
- Tempelkan ringkasan output `alembic upgrade head` / `downgrade`, jumlah tes `pytest` yang lulus, dan persentase coverage aktual setelah edit terakhir.

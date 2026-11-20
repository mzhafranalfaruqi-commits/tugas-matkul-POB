# Bukti Verifikasi Query Prasyarat & Optimasi Index (`EXPLAIN QUERY PLAN`)

Dokumen ini mencatat bukti eksekusi `EXPLAIN QUERY PLAN` di SQLite untuk query prasyarat berbasis `NOT EXISTS` pada [app/services/krs_queries.py](../app/services/krs_queries.py), membandingkan kondisi **sebelum index** (tabel tanpa Primary Key/`UNIQUE` index) dan **sesudah index** pada skema aktual hasil migrasi [0003_tabel_krs.py](../alembic/versions/0003_tabel_krs.py) (`sevima.db`).

---

## Query yang Diuji

```sql
EXPLAIN QUERY PLAN
SELECT mk.kode_mk, mk.nama
FROM prerequisite p
JOIN matakuliah mk ON mk.kode_mk = p.kode_prasyarat
WHERE p.kode_mk = :kode_mk
  AND NOT EXISTS (
      SELECT 1
      FROM krs k
      JOIN krs_detail d ON d.krs_id = k.id
      JOIN skala_nilai s ON s.huruf = d.nilai
      WHERE k.nim = :nim
        AND k.semester < :semester
        AND d.kode_mk = p.kode_prasyarat
        AND s.bobot >= :min_bobot
  )
ORDER BY mk.kode_mk;
```

Parameter uji: `('MA102', '2025001-0001', '20251', 2.0)`.

---

## 1. Output Verbatim Sebelum Index (Tabel Polos Tanpa PK / `UNIQUE`)

```text
(4, 0, 0, 'SCAN p')
(9, 0, 0, 'CORRELATED SCALAR SUBQUERY 1')
(15, 9, 0, 'SCAN k')
(31, 9, 0, 'SEARCH d USING AUTOMATIC COVERING INDEX (kode_mk=? AND krs_id=?)')
(49, 9, 0, 'SEARCH s USING AUTOMATIC COVERING INDEX (huruf=?)')
(73, 0, 0, 'SEARCH mk USING AUTOMATIC COVERING INDEX (kode_mk=?)')
(84, 0, 0, 'USE TEMP B-TREE FOR ORDER BY')
```

**Analisis Sebelum Index:**
- Tabel `prerequisite` (`SCAN p`) dan `krs` (`SCAN k`) dibaca penuh baris demi baris (*full table scan*).
- Untuk `krs_detail`, `skala_nilai`, dan `matakuliah`, SQLite terpaksa membangun *automatic covering index* sementara di memori pada setiap eksekusi query, yang boros CPU dan I/O saat jumlah mahasiswa dan `krs_detail` membesar pada masa pengisian KRS.

---

## 2. Daftar Index Bawaan Skema Aktual `0003_tabel_krs` (`sevima.db`)

```text
('krs', 'sqlite_autoindex_krs_1', None)
('krs_detail', 'sqlite_autoindex_krs_detail_1', None)
('matakuliah', 'sqlite_autoindex_matakuliah_1', None)
('prerequisite', 'sqlite_autoindex_prerequisite_1', None)
('skala_nilai', 'sqlite_autoindex_skala_nilai_1', None)
```

Kelima index di atas terbentuk otomatis dari definisi Primary Key dan `UNIQUE` constraint pada skema SQLAlchemy & Alembic (`pk_prerequisite(kode_mk, kode_prasyarat)`, `uq_krs_nim_semester(nim, semester)`, `uq_krs_detail_krs_mk(krs_id, kode_mk)`, `pk_skala_nilai(huruf)`, `pk_matakuliah(kode_mk)`).

---

## 3. Output Verbatim Sesudah Index (Skema Aktual `0003_tabel_krs`)

```text
(5, 0, 0, 'SEARCH p USING COVERING INDEX sqlite_autoindex_prerequisite_1 (kode_mk=?)')
(12, 0, 0, 'CORRELATED SCALAR SUBQUERY 1')
(20, 12, 0, 'SEARCH k USING COVERING INDEX sqlite_autoindex_krs_1 (nim=? AND semester<?)')
(29, 12, 0, 'SEARCH d USING INDEX sqlite_autoindex_krs_detail_1 (krs_id=? AND kode_mk=?)')
(35, 12, 0, 'SEARCH s USING INDEX sqlite_autoindex_skala_nilai_1 (huruf=?)')
(49, 0, 0, 'SEARCH mk USING INDEX sqlite_autoindex_matakuliah_1 (kode_mk=?)')
(59, 0, 0, 'USE TEMP B-TREE FOR ORDER BY')
```

**Analisis Sesudah Index:**
1. **Tanpa Full Table Scan:** Seluruh `SCAN` hilang dan berubah menjadi pencarian berbasis indeks B-Tree (`SEARCH ... USING COVERING INDEX` / `SEARCH ... USING INDEX`).
2. **Urutan Kolom Optimal pada `krs(nim, semester)`:** Kolom kesetaraan `nim = ?` ditempatkan di posisi awal dan kolom rentang `semester < ?` di belakang, sehingga `sqlite_autoindex_krs_1` langsung melayani filter dua kolom tersebut sekaligus sebagai *covering index* tanpa perlu membaca tabel utama berulang-ulang.
3. **Lookup Langsung pada `krs_detail` dan `prerequisite`:** `uq_krs_detail_krs_mk(krs_id, kode_mk)` memangkas pencarian detail riwayat lulus menjadi pencarian tunggal O(log N) per pasangan `(krs_id, kode_mk)`. (Catatan: `USE TEMP B-TREE FOR ORDER BY` hanya mengurutkan 0–N nama MK prasyarat hasil akhir yang berukuran sangat kecil).

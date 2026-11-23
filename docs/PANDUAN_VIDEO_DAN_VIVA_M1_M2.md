# Panduan Video Tutorial, Git Incremental Commits, & Persiapan Viva (Minggu 1–2)

Dokumen ini menjadi panduan praktis untuk memenuhi ketentuan pengumpulan video YouTube, *incremental commits* GitHub, pengumpulan EDLINK, dan kesiapan *viva* (ujian lisan tanpa AI) untuk tugas **Sesi 1–2: Desain Sistem Akademis dengan UML dengan Bantuan AI**.

---

## 1. Script & Rundown Rekaman Video Tutorial (YouTube)

> **Ketentuan Rubrik:** Rekam layar + kamera (*facecam*) + suara (*voice-over*) yang menjelaskan langkah demi langkah pembuatan prompt, eksekusi prompt, validasi/revisi manual, dan penyusunan diagram UML + ADR PDF.

### A. Video Minggu 1 — Eksplorasi, Prompt Engineering, Class Diagram, & ADR (Durasi Target: 7–10 menit)
1. **Pembukaan & Konteks Sistem (00:00 – 01:00):**
   - Perkenalkan diri dan jelaskan tujuan proyek semester **SEVIMA-Mini** (6 modul: PMB, KRS, Jadwal, Nilai/Transkrip, SPP, Presensi QR).
   - Jelaskan mengapa desain UML didahulukan sebelum menulis kode (mencegah *god object* dan ketergantungan semrawut).
2. **Analisis Domain: Kata Benda & Kata Kerja (01:00 – 02:30):**
   - Tunjukkan contoh kalimat kebutuhan (PMB, KRS maks 24 SKS + prasyarat, Jadwal, Nilai, SPP) dan identifikasi kata benda menjadi class/atribut (`CalonMahasiswa`, `Course`, `Enrollment`, `Schedule`, `Grade`, `Payment`) serta kata kerja menjadi method (`daftarPMB()`, `isiKRS()`, `isBentrok()`, `hitungIPK()`, `bayar()`).
3. **Demonstrasi Prompt Engineering: Prompt Buruk vs Prompt 5 Unsur (02:30 – 05:00):**
   - Tunjukkan prompt buruk 1 kalimat (*"Buatkan class diagram sistem kampus"*) dan tunjukkan kekurangannya (atribut *public*, entitas halusinasi `Kantin`/`Gedung`, tanpa `Payment`).
   - Susun **Prompt Terbaik #1** menggunakan 5 unsur (*Role, Konteks, Komponen, Constraint, Format Mermaid*) lalu jalankan di AI LLM dan tempel ke Mermaid Live Editor / VS Code Preview.
4. **Audit & Validasi Manual Output AI (05:00 – 08:00):**
   - Jelaskan **5 perbaikan kritis** langsung di [diagrams/class-diagram.mmd](../diagrams/class-diagram.mmd):
     1. *Visibility modifier:* `-password` dan `-ipk` wajib **private (`-`)** demi enkapsulasi.
     2. `User` menjadi `<<abstract>>` dan `CalonMahasiswa` dikonversi menjadi objek `Mahasiswa` baru lewat `NIMFactory` (bukan inheritance).
     3. Dekomposisi *many-to-many* memakai `KRS` + `Enrollment`, serta pelekatan `Grade` ke `Enrollment`.
     4. Pembedaan *Composition* (`KRS *-- Enrollment`, `Enrollment *-- Grade`, `Course *-- Schedule`) vs *Aggregation* (`ProgramStudi o-- Dosen`, `KRSManager o-- ValidationRule`).
     5. Penghapusan *God Object* `Mahasiswa` & *circular dependency* (`Course -> Schedule -> Dosen -> Course`) dengan pola **Strategy (`ValidationRule`)**, **Factory (`NIMFactory`)**, dan **Observer (`NotificationObserver`)**.
5. **Penutup Minggu 1 — ADR PDF & AI Usage Log (08:00 – 09:30):**
   - Tunjukkan [docs/ADR-architecture-decisions.pdf](ADR-architecture-decisions.pdf) dan [prompts/ai-usage-log.md](../prompts/ai-usage-log.md), lalu tunjukkan commit bertahap ke GitHub.

### B. Video Minggu 2 — Use Case, Sequence Diagram, Refactoring, & Laporan Final (Durasi Target: 7–10 menit)
1. **Use Case Diagram & Koreksi Arah Panah (00:00 – 02:30):**
   - Tunjukkan [diagrams/usecase-diagram.mmd](../diagrams/usecase-diagram.mmd) (5 aktor eksternal di luar kotak `Sistem Akademis SEVIMA-Mini` dan 21 use case).
   - Jelaskan perbedaan arah panah `«include»` (`Base -.-> Included`, mis. `Isi KRS` -> `Validasi KRS`) vs `«extend»` (`Extending -.-> Base`, mis. `Kirim Notifikasi Revisi` -> `Approve / Revisi KRS` dan `Hitung Denda` -> `Bayar Tagihan SPP`).
2. **Sequence Diagram 1 — PMB ([diagrams/sequence-pmb.mmd](../diagrams/sequence-pmb.mmd)) (02:30 – 04:45):**
   - Jelaskan alur pendaftaran hingga persetujuan admin, lock DB (`BEGIN IMMEDIATE / FOR UPDATE`), `NIMFactory.generateNIM()`, dan semua cabang `alt` (`400`, `409` duplikat/konflik, `404`, idempotent `200`, overflow `> 9999`, rollback).
3. **Sequence Diagram 2 — Validasi KRS ([diagrams/sequence-krs.mmd](../diagrams/sequence-krs.mmd)) & Bonus Presensi ([diagrams/sequence-presensi.mmd](../diagrams/sequence-presensi.mmd)) (04:45 – 07:30):**
   - Jelaskan rantai `ValidationRule` (`BillingArrearsRule` `403`, `DuplicateEnrollmentRule`, `PrerequisiteValidationRule` `NOT EXISTS`, `SKSValidationRule <= 24`, `ScheduleConflictRule`), *optimistic lock* `409`, notifikasi ke Dosen PA, serta `opt` review PA (`approve`/`revise`).
   - Tunjukkan skenario bonus **Scan QR Presensi** lengkap dengan `alt` JWT `401`, bukan peserta `403`, replay/`jti`/hari `400`, geofence `400`, duplikat `409`, & notifikasi Dosen.
4. **Laporan Final PDF & Checklist Pengumpulan (07:30 – 09:00):**
   - Buka [docs/Final-UML-diagram.pdf](Final-UML-diagram.pdf) halaman 1–7, sorot sinkronisasi antar-diagram dan tabel *Before–After*, lalu tunjukkan tautan GitHub + PDF siap unggah ke **EDLINK**.

---

## 2. Urutan Incremental Commits GitHub (Jangan 1 Commit Besar!)

Jalankan commit bertahap berikut di dalam folder `sevima-mini/` (menandai kontribusi AI sesuai *AI-First Charter*):

```powershell
# Commit 1: Class Diagram awal + struktur folder diagrams/
git add diagrams/class-diagram.mmd
git commit -m "docs(uml): add initial and SOLID-refactored class diagram for SEVIMA-Mini [AI-assisted]"

# Commit 2: Use Case Diagram lintas 6 modul & 5 aktor eksternal
git add diagrams/usecase-diagram.mmd
git commit -m "docs(uml): add use case diagram with 5 actors and include/extend relations [AI-assisted]"

# Commit 3: Sequence Diagrams (PMB, Validasi KRS, & Bonus Scan QR Presensi)
git add diagrams/sequence-pmb.mmd diagrams/sequence-krs.mmd diagrams/sequence-presensi.mmd
git commit -m "docs(uml): add sequence diagrams for PMB, KRS validation, and QR attendance with alt flows [AI-assisted]"

# Commit 4: Dokumentasi 7 Prompt Terbaik, Perbandingan Before-After, & OPAR
git add prompts/ai-usage-log.md
git commit -m "docs(ai-log): document M1-M2 best prompts, manual UML revisions, and OPAR cycle"

# Commit 5: ADR Minggu 1-2 & Laporan Final UML Diagram (Markdown + PDF)
git add docs/ADR-architecture-decisions.md docs/ADR-architecture-decisions.pdf docs/Final-UML-diagram.pdf docs/ADR.md
git commit -m "docs(adr): add architecture decision record PDF and final 7-page UML report"

# Commit 6: Panduan Video/Viva & Pembaruan README ringkasan desain
git add docs/PANDUAN_VIDEO_DAN_VIVA_M1_M2.md README.md
git commit -m "docs(readme): link M1-M2 UML artifacts and add video/viva preparation guide"
```

---

## 3. Kisi-Kisi Pertanyaan Viva (Ujian Lisan Tanpa AI) & Poin Jawaban Inti

1. **Mengapa `User` dijadikan `<<abstract>>` dan atribut `-password` serta `-ipk` dibuat *private*?**
   - Tidak ada pengguna tanpa peran spesifik (`CalonMahasiswa`, `Mahasiswa`, `Dosen`, `Admin`), sehingga `User` hanya sebagai cetak biru induk (*abstraction*). Atribut `-password` dan `-ipk` wajib *private* (`-`) agar dilindungi enkapsulasi: IPK tidak boleh ditulis sembarangan dari luar (`mhs.ipk = 4.0`), melainkan harus dihitung lewat `+getIPK()` / `TranscriptService` dari nilai sah.
2. **Saat `CalonMahasiswa` lulus PMB, apakah objeknya diubah menjadi `Mahasiswa`?**
   - Tidak. Dalam OOP, objek yang sudah diinstansiasi tidak dapat berganti class di *runtime*, dan `Mahasiswa` bukan turunan *is-a* dari `CalonMahasiswa`. `PMBService` memanggil `NIMFactory.createMahasiswa(calon, nim)` untuk membuat objek `Mahasiswa` baru dan menyimpan tautan asal (`1 --> 0..1`).
3. **Bagaimana membedakan *Composition* (`*--`) dan *Aggregation* (`o--`) pada diagram Anda?**
   - Gunakan uji siklus hidup: *"Jika wadah dihapus, apakah bagiannya ikut hilang?"*
     - Ya -> **Composition (`*--`)**: `KRS *-- Enrollment`, `Enrollment *-- Grade`, `Course *-- Schedule`.
     - Tidak -> **Aggregation (`o--`)**: `ProgramStudi o-- Dosen`, `ProgramStudi o-- Mahasiswa`, `KRSManager o-- ValidationRule`.
4. **Mengapa `Grade` menempel ke `Enrollment`, bukan langsung ke `Mahasiswa` atau `Course`?**
   - Karena nilai selalu melekat pada kombinasi spesifik **1 mahasiswa + 1 mata kuliah + 1 semester** (yang direpresentasikan oleh `Enrollment`), sekaligus mendukung riwayat mengulang mata kuliah pada semester berbeda untuk perhitungan IPS/IPK yang akurat.
5. **Bagaimana Anda memperbaiki *God Object* `Mahasiswa` dan *circular dependency* `Course -> Schedule -> Dosen -> Course`?**
   - Menerapkan *Single Responsibility Principle* (SRP): memindahkan logika bisnis dari `Mahasiswa` ke `PMBService`, `KRSManager`, `TranscriptService`, dan `NotificationService` (tiap class `<= 5` method inti). Siklus diputus menjadi graf asiklik (DAG): `Course *-- Schedule <-- Dosen`. Mengisolasi aturan KRS ke `ValidationRule <<interface>>` juga memenuhi *Open/Closed Principle* (OCP) dan *Dependency Inversion* (DIP).
6. **Bagaimana membedakan arah panah `«include»` dan `«extend»` pada Use Case Diagram?**
   - `«include»` (wajib selalu dijalankan) diarahkan dari **Base -> Included** (contoh: `Isi KRS -.-> Validasi KRS`, `Scan QR Presensi -.-> Validasi Token QR & Jadwal`).
   - `«extend»` (opsional/kondisional) diarahkan dari **Extending -> Base** (contoh: `Kirim Notifikasi Revisi -.-> Approve / Revisi KRS`, `Hitung Denda Keterlambatan -.-> Bayar Tagihan SPP`).
7. **Mengapa Sequence Diagram tidak boleh hanya berisi jalur sukses (*happy path*)?**
   - Sistem akademis memiliki banyak aturan penolakan bisnis dan risiko transaksi konkurensi. Frame `alt`/`opt` memetakan eksplisit kegagalan validasi (`400`), token invalid (`401`), blokir tunggakan SPP/otorisasi PA (`403`), ID tidak ditemukan (`404`), konflik versi/duplikat/status (`409`), idempotency (`200`), dan `rollback()` database agar perilaku kode di Minggu 3–12 deterministik.

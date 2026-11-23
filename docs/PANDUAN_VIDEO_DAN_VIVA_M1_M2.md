# Panduan Video Tutorial, Git Incremental Commits, & Persiapan Viva (Minggu 1–2)

Dokumen ini menjadi panduan praktis untuk memenuhi ketentuan pengumpulan video YouTube, *incremental commits* GitHub (`tugas-1` & `tugas-2`), pengumpulan EDLINK, dan kesiapan *viva* (ujian lisan tanpa AI) untuk tugas **Sesi 1–2: Desain Sistem Akademis dengan UML dengan Bantuan AI**.

---

## 1. Script & Rundown Rekaman Video Tutorial (YouTube)

> **Ketentuan Rubrik:** Rekam layar + kamera (*facecam*) + suara (*voice-over*) yang menjelaskan langkah demi langkah pembuatan prompt, *self-critique* & validasi manual, refactoring 5 pilar SOLID + Design Patterns, hingga sinkronisasi antar-diagram dan ADR PDF 5-bagian.

### A. Video Minggu 1 — Eksplorasi, Prompt Engineering, Class Diagram Baseline, & ADR (7–10 menit)
1. **Pembukaan & Konteks Sistem (00:00 – 01:00):**
   - Perkenalkan diri dan jelaskan tujuan proyek semester **SEVIMA-Mini** (6 modul: PMB, KRS, Jadwal, Nilai/Transkrip, SPP, Presensi QR).
   - Jelaskan mengapa desain UML didahulukan sebelum menulis kode (mencegah *god object* dan *circular dependency*).
2. **Analisis Domain: Kata Benda & Kata Kerja (01:00 – 02:30):**
   - Identifikasi kata benda menjadi class/atribut (`CalonMahasiswa`, `ProgramStudi`, `Course`, `KRS`, `Enrollment`, `Schedule`, `Grade`, `Payment`) dan kata kerja menjadi method (`daftarCalon()`, `ajukanKRS()`, `cekBentrokWaktu()`, `getIPK()`, `prosesPembayaran()`).
3. **Prompt Engineering: Prompt Buruk vs Prompt 5 Unsur (02:30 – 05:00):**
   - Bandingkan prompt buruk 1 kalimat dengan **Prompt 5 Unsur** (*Role, Konteks, Komponen, Constraint, Format Mermaid*).
4. **Audit Manual Baseline UML (05:00 – 08:30):**
   - Jelaskan enkapsulasi `-passwordHash` & `-ipk`, `User <<abstract>>`, dekomposisi M2M lewat `KRS *-- Enrollment *-- Grade`, dan uji siklus hidup (*Composition* `*--` vs *Aggregation* `o--`).

### B. Video Minggu 2 — Refinement Use Case, Sequence Skenario Lengkap, Audit 5 Pilar SOLID, & Laporan Final 8 Halaman (8–10 menit)
1. **Use Case Diagram Refinement ([diagrams/usecase-diagram.mmd](../diagrams/usecase-diagram.mmd)) (00:00 – 02:00):**
   - Tunjukkan 5 aktor eksternal di luar kotak `Sistem Akademis SEVIMA-Mini` dan **22 use case**.
   - Jelaskan pemisahan `Approve KRS` dan `Ajukan Revisi KRS` (`UC_RevKRS -.->|"«extend»"| UC_AppKRS`, lalu `UC_RevKRS -.->|"«include»"| UC_NotifRev`), serta penamaan eksplisit `Bayar Denda Keterlambatan` (`«extend»` ke `Bayar Tagihan SPP`).
2. **Audit 5 Pilar SOLID & Pemecahan *God Object* `SistemAkademik` ([diagrams/class-diagram.mmd](../diagrams/class-diagram.mmd)) (02:00 – 05:00):**
   - **SRP:** Pecah *god object* `SistemAkademik` (>30 method) menjadi service terfokus (`SistemPMB`, `KRSManager`, `JadwalService`, `KeuanganService`, `PresensiService`, `KRSValidator`, `NotificationService`) dengan `<= 6` method per class.
   - **OCP:** Aturan validasi KRS dimodelkan sebagai `ValidationRule <<interface>>` (`PrasyaratRule`, `BatasSKSRule`, `BentrokJadwalRule`, `KuotaKelasRule`, `StatusPembayaranRule`).
   - **LSP:** Seluruh 4 turunan `User <<abstract>>` memenuhi kontrak `+getPeran() String`.
   - **ISP:** Pecah hak peran menjadi `PengisiKRS` (`Mahasiswa`), `PenyetujuKRS`, dan `Penilai` (`Dosen`).
   - **DIP:** `KRSManager` & `KRSValidator` bergantung pada `KRSRepository <<interface>>`, bukan driver database konkrit (`PostgresKRSRepository`).
   - **Design Patterns:** Sorot **Factory (`UserFactory.buat(peran, data)`)**, **Strategy (`ValidationRule`)**, dan **Observer (`KRSEventBus` + `NotificationObserver`)**.
3. **Sequence Diagrams Skenario Lengkap & Panah Asinkron `-)` (05:00 – 08:00):**
   - **PMB ([diagrams/sequence-pmb.mmd](../diagrams/sequence-pmb.mmd)):** `UserFactory.generateNIM()` + `UserFactory.buat("mahasiswa", dataCalon)`, penolakan `400` bila berkas belum lengkap, dan fallback antrekan retry SMTP saat email gagal tanpa membatalkan approval.
   - **Validasi KRS ([diagrams/sequence-krs.mmd](../diagrams/sequence-krs.mmd)):** `loop Setiap mata kuliah di KRS` memanggil `KRSRepository.cekPrasyaratLulus()`, *self-call* `KRSValidator.validasiBatasSKS(totalSKS, 24)` dan `cekJadwalBentrok()`, error *collect-all* spesifik (`SPP`, `IF101`, `26 > 24 SKS`, `IF201 vs IF203`), notifikasi asinkron `-)` ke `NotificationService`, dan `opt` review PA (`403` / `APPROVED` / `REVISION`).
   - **Bonus Presensi QR ([diagrams/sequence-presensi.mmd](../diagrams/sequence-presensi.mmd)):** Sinkronisasi dengan `Schedule` (`terapkanTokenQR`, `cocokkanTokenQR`), `Enrollment` (`cekPesertaAktif`, `catatKehadiran`), 5 cabang `alt` (`401`/`403`/`400`/`409`), & push asinkron `-)`.
4. **ADR 5-Bagian, Self-Critique AI Log, & Laporan Final 8 Halaman (08:00 – 09:30):**
   - Tunjukkan template 5 bagian pada [docs/ADR-architecture-decisions.pdf](ADR-architecture-decisions.pdf), tabel **Self-Critique** pada [prompts/ai-usage-log.md](../prompts/ai-usage-log.md), dan [docs/Final-UML-diagram.pdf](Final-UML-diagram.pdf) halaman 1–8 (Class Diagram terbagi bersih di Halaman 2–3).

---

## 2. Urutan Incremental Commits GitHub (Branch `tugas-2`)

> Branch `tugas-1` sudah menyimpan 6 *incremental commits* baseline Minggu 1 (`46c0499`..`6d6844a`). Saat siap mengunggah pembaruan Minggu 2 ke branch `tugas-2`, jalankan commit bertahap di folder `sevima-mini/` berikut:

```powershell
# Buat branch baru untuk Tugas 2 dari tugas-1 (jika belum dibuat)
git checkout -b tugas-2

# Commit 1: Refinement Class Diagram (35 node SOLID: ISP, DIP, UserFactory, KRSEventBus)
git add diagrams/class-diagram.mmd
git commit -m "refactor(uml): apply full 5 SOLID pillars, ISP, DIP, UserFactory, and KRSEventBus in class diagram [AI-assisted]"

# Commit 2: Refinement Use Case Diagram (22 use cases, extend Ajukan Revisi KRS & Bayar Denda)
git add diagrams/usecase-diagram.mmd
git commit -m "docs(uml): refine use case extend relations for KRS revision and late payment fee [AI-assisted]"

# Commit 3: Refinement 3 Sequence Diagrams (loop, self-call, collect-all error, async -), retry email)
git add diagrams/sequence-pmb.mmd diagrams/sequence-krs.mmd diagrams/sequence-presensi.mmd
git commit -m "docs(uml): sync sequence diagrams with loop, fallback flows, and async notifications [AI-assisted]"

# Commit 4: Log Self-Critique Minggu 2, Before-After SistemAkademik, & OPAR M2
git add prompts/ai-usage-log.md
git commit -m "docs(ai-log): add Week 2 self-critique prompt, God Object refactor diff, and OPAR cycle"

# Commit 5: ADR 5-Bagian (ADR-M2-01..04) & Laporan Final UML Diagram 8 Halaman
git add docs/ADR-architecture-decisions.md docs/ADR-architecture-decisions.pdf docs/Final-UML-diagram.pdf
git commit -m "docs(adr): update 5-part ADR PDF and generate 8-page synchronized Final UML report"

# Commit 6: Pembaruan Panduan Viva & README
git add docs/PANDUAN_VIDEO_DAN_VIVA_M1_M2.md README.md
git commit -m "docs(readme): update README and Week 2 video/viva checklist"

# Push branch tugas-2 ke GitHub (saat diminta)
git push -u origin tugas-2
```

---

## 3. Kisi-Kisi Pertanyaan Viva (Ujian Lisan Tanpa AI) & Poin Jawaban Inti

1. **Mengapa `User` dijadikan `<<abstract>>` dan `-passwordHash` serta `-ipk` dibuat *private*?**
   - Tidak ada aktor sistem tanpa peran spesifik (`CalonMahasiswa`, `Mahasiswa`, `Dosen`, `Admin`), sehingga `User` menjadi cetak biru induk yang memaksa implementasi `+getPeran() String` (**LSP**). `-passwordHash` dan `-ipk` bersifat *private* agar tidak dapat dimodifikasi langsung dari luar class melainkan melalui mekanisme autentikasi dan perhitungan nilai sah.
2. **Mengapa `SistemAkademik` (*god object* >30 method) harus dipecah dan bagaimana cara memecahnya?**
   - Satu class yang menangani PMB, KRS, Jadwal, Nilai, Keuangan, dan Presensi sekaligus melanggar **SRP** (*Single Responsibility Principle*) dan menjadi sumber bug lintas modul. Pemecahan dilakukan menjadi service per modul (`SistemPMB`, `KRSManager`, `JadwalService`, `KeuanganService`, `PresensiService`), `KRSValidator`, dan `NotificationService` dengan maksimal `<= 6` method per class.
3. **Apa fungsi `PengisiKRS`, `PenyetujuKRS`, dan `Penilai` pada Class Diagram Minggu 2?**
   - Ini menerapkan **Interface Segregation Principle (ISP)**: klien (`KRSManager`) hanya perlu bergantung pada kontrak sempit sesuai peran aksinya (`Mahasiswa` mengimplementasikan `PengisiKRS`; `Dosen` mengimplementasikan `PenyetujuKRS` dan `Penilai`), sehingga `Mahasiswa` secara struktural tidak pernah terekspos ke method `setujuiKRS()` atau `inputNilai()`.
4. **Mengapa `KRSManager` memakai `KRSRepository <<interface>>` alih-alih langsung memanggil `PostgresKRSRepository`?**
   - Itu penerapan **Dependency Inversion Principle (DIP)**: modul bisnis berlevel tinggi (`KRSManager`, `KRSValidator`) bergantung pada abstraksi kontrak (`getKRS`, `cekPrasyaratLulus`, `simpanKRS`), bukan implementasi DB konkrit. Saat unit testing, repository konkrit dapat diganti *mock repository* tanpa koneksi database.
5. **Apa peran `UserFactory` dan `KRSEventBus` di sistem ini?**
   - `UserFactory` (**Factory Pattern**) menstandarkan pembuatan objek `User` (`buat(peran, data)`) dan penomoran unik NIM (`generateNIM(tahun, kodeProdi)`) saat `CalonMahasiswa` lulus PMB—bukan mengubah class objek di runtime.
   - `KRSEventBus` (**Observer / Pub-Sub Pattern**) menyimpan daftar `NotificationObserver` (`EmailNotifier`, `WhatsAppNotifier`) sehingga penambahan kanal notifikasi baru tidak mengubah kode `KRSManager` atau `SistemPMB`.
6. **Mengapa panah notifikasi di Sequence Diagram memakai `-)` (asinkron) dan mengapa gagal kirim email tidak men-rollback PMB?**
   - Panah `-)` (*asynchronous message*) memastikan pengguna langsung menerima respons HTTP (`200 OK` / `PENDING_APPROVAL`) tanpa diblokir oleh latensi server SMTP/Push eksternal. Jika pengiriman email gagal sementara, data kelulusan `Mahasiswa` + NIM di database tetap sah (*committed*) dan pengiriman notifikasi hanya diantrekan ke `antrekanRetry()`.
7. **Bagaimana Anda membedakan `«include»` vs `«extend»` serta *Composition* `*--` vs *Aggregation* `o--`?**
   - `«include»` wajib dijalankan (`Base -> Included`, mis. `Isi KRS -.-> Validasi KRS`, `Ajukan Revisi KRS -.-> Kirim Notifikasi Revisi`), sedangkan `«extend»` kondisional/opsional (`Extending -> Base`, mis. `Ajukan Revisi KRS -.-> Approve KRS`, `Bayar Denda Keterlambatan -.-> Bayar Tagihan SPP`).
   - *Composition* (`*--`) berarti bagian ikut mati jika induk dihapus (`KRS *-- Enrollment`, `Enrollment *-- Grade`, `Course *-- Schedule`); *Aggregation* (`o--`) berarti anggota tetap hidup terpisah (`ProgramStudi o-- Mahasiswa`, `ProgramStudi o-- Dosen`, `KRSValidator o-- ValidationRule`).

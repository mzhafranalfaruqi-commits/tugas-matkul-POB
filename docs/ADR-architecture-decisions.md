# Architecture Decision Record (ADR) — Desain Sistem Akademis SEVIMA-Mini (Minggu 1–2)

- **Tanggal:** Minggu 1–2 (Fase Desain Arsitektur UML)
- **Status:** Diterima — Menjadi cetak biru arsitektural implementasi Minggu 3–16
- **Konteks Proyek:** Perancangan sistem akademis **SEVIMA-Mini** mencakup 6 modul terintegrasi: **PMB**, **KRS**, **Jadwal & Ruangan**, **Nilai & Transkrip**, **Keuangan (SPP)**, serta **Presensi QR Code**.

---

## 1. Keputusan Struktur Class & Enkapsulasi

1. **Hierarki `User` sebagai `<<abstract>>` dengan 4 Subclass Sejajar:**
   - Atribut dan perilaku bersama (`#id`, `#username`, `-password`, `#nama`, `#email`, `+login()`, `+logout()`, `+tampilkanDashboard()*`) dinaikkan ke `User <<abstract>>`, sementara atribut dan perilaku spesifik tetap di turunan (`CalonMahasiswa`, `Mahasiswa`, `Dosen`, `Admin`).
   - Tidak ada pengguna yang hanya berstatus "user" tanpa peran, sehingga `User` tidak boleh diinstansiasi langsung.
   - Atribut sensitif seperti `-password` (`User`) dan `-ipk` (`Mahasiswa`) wajib **`private` (`-`)** untuk menjaga *encapsulation*: IPK hanya dihitung melalui `+getIPK()` / `TranscriptService` berdasarkan `Grade` sah, bukan diubah bebas dari luar.

2. **Konversi `CalonMahasiswa` Menjadi `Mahasiswa` (Tanpa Mengganti Class Objek):**
   - Di OOP, sebuah objek yang sudah dibuat tidak bisa berganti class di *runtime*, dan `Mahasiswa` bukanlah spesialisasi (*is-a*) dari `CalonMahasiswa` karena `Mahasiswa` tidak mewarisi `noDaftar`/`statusSeleksi` sebagai perilaku operasional.
   - **Keputusan:** Saat `Admin` menyetujui pendaftar, `PMBService` memanggil `NIMFactory.createMahasiswa(calon, nim)` untuk membuat objek `Mahasiswa` baru dan menyimpan tautan asal (`CalonMahasiswa "1" --> "0..1" Mahasiswa : dikonversiMenjadi`).

3. **Dekomposisi Many-to-Many & Pelekatan `Grade` pada `Enrollment`:**
   - Hubungan banyak-ke-banyak antara `Mahasiswa` dan `Course` dipecah memakai `KRS` (per mahasiswa per semester) dan class perantara `Enrollment` (`KRS "1" *-- "0..*" Enrollment` dan `Enrollment "0..*" --> "1" Course`).
   - `Grade` dilekatkan langsung ke `Enrollment` (`Enrollment "1" *-- "0..1" Grade`), bukan ke `Mahasiswa`, karena satu nilai selalu milik tepat satu mahasiswa, satu mata kuliah, dan satu semester tertentu.

4. **Pemisahan Ketat `Composition (*--)` vs `Aggregation (o--)` & Penghapusan Siklus:**
   - **Composition (`*--`):** `KRS *-- Enrollment`, `Enrollment *-- Grade`, dan `Course *-- Schedule` (jika wadah dihapus, bagian kehilangan makna dan ikut musnah).
   - **Aggregation (`o--`):** `ProgramStudi o-- Dosen`, `ProgramStudi o-- Mahasiswa`, `KRSManager o-- ValidationRule`, dan `KRSManager o-- NotificationObserver` (jika prodi/manager ditutup, dosen, mahasiswa, atau rule tetap hidup mandiri).
   - **Bebas Circular Dependency (DAG):** Siklus `Course -> Schedule -> Dosen -> Course` dihindari dengan arah asiklik `Course *-- Schedule <-- Dosen`.

---

## 2. Trade-off Arsitektural

| Keputusan | Opsi yang Dipilih | Alternatif yang Ditolak | Trade-off & Alasan |
| :--- | :--- | :--- | :--- |
| **Transisi Calon ke Mahasiswa** | Membuat objek `Mahasiswa` baru via `NIMFactory` + relasi tautan | Pewarisan `CalonMahasiswa <|-- Mahasiswa` atau *type-state mutating* | **Pro:** Enkapsulasi atribut bersih dan aman secara tipe statis; **Kontra:** Sedikit duplikasi identitas awal saat konversi, dimitigasi dengan relasi referensi ke data pendaftar. |
| **Aturan Validasi KRS** | Pemisahan ke antarmuka `ValidationRule` (5 kelas terpisah) | Metode tunggal panjang di `KRSManager` atau `Mahasiswa` (*God Object*) | **Pro:** Mematuhi *SRP* & *OCP*, aturan baru (seperti `BillingArrearsRule`) tinggal disuntikkan; **Kontra:** Jumlah class bertambah, dikelola lewat pengelompokan package `validators/`. |
| **Pengelolaan Nilai (`Grade`)** | Class `Grade` terikat `1 : 0..1` pada `Enrollment` | Atribut nilai langsung di `Mahasiswa` atau relasi terpisah tanpa `Enrollment` | **Pro:** Mendukung riwayat mengulang mata kuliah per semester & perhitungan IPS/IPK deterministik; **Kontra:** Membutuhkan join `Enrollment` -> `KRS` -> `Mahasiswa` saat mencetak transkrip. |
| **Notifikasi Lintas Modul** | Interface `NotificationObserver` (Observer Pattern) | Pemanggilan langsung modul email/SMS di dalam setiap service | **Pro:** *Loose coupling* (*DIP*), tahan gagal & mudah diganti kanal; **Kontra:** Alur eksekusi menjadi tidak langsung, diatasi lewat Sequence Diagram & logging idempoten. |

---

## 3. Design Patterns & Prinsip SOLID yang Diterapkan

- **Factory Method (`NIMFactory`):** Mengenkapsulasi logika pembuatan NIM berformat `[Tahun][KodeProdi]-[Urut]` beserta konstruksi objek `Mahasiswa` baru yang terhubung ke `CalonMahasiswa`.
- **Strategy / Chain of Responsibility (`ValidationRule`):** `KRSManager` mendelegasikan pemeriksaan ke daftar `ValidationRule` (`DuplicateEnrollmentRule`, `SKSValidationRule`, `PrerequisiteValidationRule`, `ScheduleConflictRule`, `BillingArrearsRule`) sehingga penambahan aturan baru tidak memodifikasi inti `KRSManager` (**Open/Closed Principle**).
- **Observer (`NotificationObserver` -> `NotificationService`):** Memisahkan peristiwa bisnis (persetujuan PMB, pengajuan/revisi KRS, scan presensi) dari mekanisme pengiriman notifikasi (`EMAIL`/`SMS`/`PUSH`) (**Dependency Inversion Principle**).
- **Single Responsibility & Anti-God-Object:** `Mahasiswa` tidak lagi menampung `validasiKRS()`, `hitungIPK()`, `cetakTranskripPDF()`, maupun `kirimEmailTagihan()`, melainkan dipecah ke `KRSManager`, `TranscriptService`, `Payment`, dan `NotificationService` (setiap class <= 5 method inti).

---

## 4. Keselarasan Desain ke Implementasi (Minggu 3–16)
Cetak biru UML Minggu 1–2 ini langsung memandu implementasi backend **SEVIMA-Mini** (Python + SQLAlchemy 2.0 + FastAPI):
- `CalonMahasiswa`, `ProgramStudi`, `PMBService`, & `NIMFactory` -> Modul PMB (Minggu 3–4).
- `KRS`, `Enrollment` (`krs_detail`), `KRSManager`, & `ValidationRule` -> Chain of Responsibility + State Machine KRS (Minggu 5–6).
- `Course`, `Schedule`, & `isBentrok()` -> Detektor Sort & Sweep + Observer Outbox (Minggu 7–8).
- `Grade` & `TranscriptService` -> `GradeService`, Kalkulator `Decimal` IPS/IPK, & ReportLab PDF (Minggu 9–10).
- `Payment` & `BillingArrearsRule` -> Modul Keuangan SPP, Webhook HMAC, & Blokir KRS `403` (Minggu 11).
- `Schedule.isAktifHariIni()` & `PresensiService` -> Modul Presensi QR JWT & Geofence (Minggu 12).

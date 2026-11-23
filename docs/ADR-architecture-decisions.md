# Architecture Decision Records — Desain Sistem Akademis SEVIMA-Mini (Minggu 1–2)

Dokumen ini merupakan sumber Markdown untuk deliverables [ADR-architecture-decisions.pdf](ADR-architecture-decisions.pdf) sesuai standar template 5 bagian pada perkuliahan Minggu 2 (*Refinement & Skenario: Desain SEVIMA-Mini yang Matang*): **Konteks, Keputusan, Alternatif & Trade-off, Konsekuensi Positif/Negatif, dan Pattern**.

---

## Ringkasan Keputusan Arsitektur

| ID | Judul Keputusan | Pilar SOLID / Konsep | Pattern Utama | Realisasi Kode (Minggu 3–12) |
| :--- | :--- | :--- | :--- | :--- |
| **ADR-M2-01** | Pemecahan *God Object* `SistemAkademik` Menjadi Service per Modul & `KRSValidator` | **SRP** & **OCP** | Strategy Pattern (`ValidationRule`) | `app/services/`, `app/patterns/krs_rules.py` |
| **ADR-M2-02** | Hierarki `User <<abstract>>`, *Interface Segregation*, & `UserFactory` | **LSP**, **ISP**, & Encapsulation | Factory Pattern (`UserFactory`) | `app/models/user.py`, `app/services/pmb_service.py` |
| **ADR-M2-03** | Pemodelan M2M via Entitas Asosiatif & Audit *Composition* vs *Aggregation* | Domain Integrity & Lifecycle DAG | Entity Ownership & Composite Key | `app/models/academic.py`, `app/models/billing.py` |
| **ADR-M2-04** | Injeksi `KRSRepository <<interface>>`, `KRSEventBus`, & Notifikasi Asinkron `(-)` | **DIP** & Low Coupling | Repository Pattern + Observer Pattern | `app/patterns/observer.py`, `app/services/krs_service.py` |

---

## ADR-M2-01: Pemecahan *God Object* `SistemAkademik` Menjadi Modular Service & Aturan Validasi Strategy

- **1. Konteks:**  
  Draft awal AI sering mengumpulkan lebih dari 30 method lintas domain (PMB, pengisian KRS, penjadwalan kelas, input nilai, pembayaran SPP, hingga presensi QR) ke dalam satu class raksasa `SistemAkademik` atau menaruh seluruh logika validasi ke dalam class `Mahasiswa`. Hal ini menciptakan *single point of failure*, konflik merge saat pengembangan tim, serta kesulitan saat kampus menambah aturan validasi KRS baru.
- **2. Keputusan:**  
  Memecah tanggung jawab sistem menjadi 5 domain service berfokus tunggal (**Single Responsibility Principle / SRP**): `SistemPMB`, `KRSManager`, `JadwalService`, `KeuanganService`, dan `PresensiService`, serta memisahkan mesin evaluasi aturan ke `KRSValidator` yang membungkus daftar aturan bermuka `ValidationRule <<interface>>` (`PrasyaratRule`, `BatasSKSRule`, `BentrokJadwalRule`, `KuotaKelasRule`, `StatusPembayaranRule`). Setiap class dibatasi `<= 6` method.
- **3. Alternatif & Trade-off:**  
  - *Alternatif A:* Satu class `SistemAkademik` terpusat atau method bertipe `if/elif` di `KRSManager`. Cepat ditulis di awal, namun melanggar SRP dan OCP serta sulit diuji unit secara terisolasi.  
  - *Trade-off Pilihan Ini:* Jumlah file dan class bertambah sehingga membutuhkan pemahaman struktur paket dan injeksi antarmuka, tetapi setiap modul dapat berevolusi, diuji, dan diskalakan secara independen.
- **4. Konsekuensi:**  
  - **Positif:** Menambah syarat validasi KRS baru (misalnya batas minimal IPK praktikum) cukup menambah class turunan `ValidationRule` tanpa menyentuh `KRSManager` (**Open/Closed Principle / OCP**); hasil validasi mendukung mode *collect-all* pesan error spesifik sekaligus.  
  - **Negatif:** Koordinasi antar-modul memerlukan kontrak interface yang disiplin dan pencatatan alur di Sequence Diagram agar tim tetap sinkron.
- **5. Pattern:**  
  **Strategy Pattern** (dan ekstensi **Chain of Responsibility** pada modul implementasi `app/patterns/krs_rules.py`).

---

## ADR-M2-02: Hierarki `User <<abstract>>`, *Interface Segregation* (`PengisiKRS`, `PenyetujuKRS`, `Penilai`), & `UserFactory`

- **1. Konteks:**  
  Sistem memiliki 4 tipe aktor pengguna (`CalonMahasiswa`, `Mahasiswa`, `Dosen`, `Admin`) dengan atribut autentikasi bersama (`id`, `username`, `-passwordHash`, `email`, `isActive`) sekaligus hak aksi yang sangat berbeda dalam siklus KRS dan penilaian. Tanpa batasan antarmuka, service berisiko mengakses method milik peran lain atau melakukan instansiasi manual dengan format NIM yang rawan duplikat.
- **2. Keputusan:**  
  Menjadikan `User` sebagai `<<abstract>>` class (tidak dapat diinstansiasi langsung) dengan `-passwordHash` privat, memastikan 4 subclass memenuhi **Liskov Substitution Principle (LSP)** melalui kontrak `+getPeran() String`. Menambahkan 3 interface khusus sesuai **Interface Segregation Principle (ISP)**: `PengisiKRS` (diimplementasikan `Mahasiswa`), serta `PenyetujuKRS` dan `Penilai` (diimplementasikan `Dosen`). Seluruh pembuatan akun baru beserta generasi NIM (`YYYYKKK-NNNN`) dipusatkan di `UserFactory`.
- **3. Alternatif & Trade-off:**  
  - *Alternatif A:* Satu tabel/class `User` datar berisi semua kolom nullable (`nim`, `nidn`, `noPendaftaran`) plus atribut `role`. Skema sederhana namun merusak enkapsulasi, memaksa banyak null-check, dan melanggar ISP.  
  - *Trade-off Pilihan Ini:* Membutuhkan pemetaan pewarisan (*joined-table / concrete class*) serta factory `UserFactory.buat(peran, data)`, namun menjaga keamanan tipe dan kejelasan hak akses.
- **4. Konsekuensi:**  
  - **Positif:** `KRSManager` hanya menerima kontrak `PengisiKRS` saat pengajuan KRS dan `PenyetujuKRS` saat approval PA, sehingga mahasiswa tidak pernah secara struktural bisa memanggil `setujuiKRS()`. Format NIM seragam dan aman dari race condition.  
  - **Negatif:** Perubahan payload registrasi user harus disinkronkan di `UserFactory.buat()`.
- **5. Pattern:**  
  **Factory Pattern** (`UserFactory.buat(peran, data)` dan `generateNIM(tahun, kodeProdi)`).

---

## ADR-M2-03: Entitas Asosiatif pada Relasi Many-to-Many & Audit *Composition* vs *Aggregation*

- **1. Konteks:**  
  Hubungan antara mahasiswa, KRS, mata kuliah (`Course`), kelas terjadwal (`Schedule`), nilai (`Grade`), dan program studi mengandung kardinalitas banyak-ke-banyak sekaligus atribut riwayat transaksi (*statusPresensi*, *nilaiAngka*, *nilaiHuruf*, *bobot*). Selain itu, UML hasil AI sering tertukar simbol komposisi (`*--`) vs agregasi (`o--`) serta menimbulkan siklus dependensi (*circular dependency*).
- **2. Keputusan:**  
  Menolak relasi M2M langsung antara `KRS` dan `Course/Schedule`, lalu menyisipkan entitas asosiatif `Enrollment`. Menerapkan uji siklus hidup (*lifecycle delete test*): memakai **Composition (`*--`)** untuk `KRS *-- Enrollment`, `Enrollment *-- Grade`, `Course *-- Schedule`, dan `ProgramStudi *-- Course`; memakai **Aggregation (`o--`)** untuk `ProgramStudi o-- Mahasiswa` dan `ProgramStudi o-- Dosen` karena keduanya tetap eksis meski prodi direstrukturisasi. Mengurutkan seluruh relasi antar-class membentuk **Directed Acyclic Graph (DAG)** murni tanpa siklus.
- **3. Alternatif & Trade-off:**  
  - *Alternatif A:* Relasi M2M murni tanpa `Enrollment` dan membiarkan `Course <-> Schedule <-> Dosen` dua arah agar navigasi ORM instan. Rentan duplikasi data nilai dan menciptakan *circular import* saat pengkodean.  
  - *Trade-off Pilihan Ini:* Query transkrip memerlukan join `KRS -> Enrollment -> Grade`, namun terhindar total dari *circular dependency* dan mendukung audit nilai historis secara rapi.
- **4. Konsekuensi:**  
  - **Positif:** Aturan *cascading delete* basis data (`Enrollment` ikut terhapus bila `KRS` dihapus; `Dosen` tidak ikut terhapus bila prodi berubah) menjadi eksplisit sebelum migrasi Alembic ditulis.  
  - **Negatif:** Penelusuran jadwal yang diampu dosen perlu kueri terarah `Schedule` berdasarkan `dosen_id` alih-alih daftar siklik bolak-balik.
- **5. Pattern:**  
  **Associative Entity Pattern** & **Strict Dependency DAG**.

---

## ADR-M2-04: Abstraksi `KRSRepository`, `KRSEventBus`, & Notifikasi Asinkron `(-)` di Sequence Diagram

- **1. Konteks:**  
  Pada baseline `tugas-1`, alur pengajuan KRS langsung menembak kelas konkrit `Database` dan memanggil layanan email/push secara sinkron (`->>`). Jika server SMTP melambat atau gagal (seperti kasus email kelulusan PMB atau approval KRS), transaksi utama ikut terhambat atau berisiko di-*rollback*.
- **2. Keputusan:**  
  Menerapkan **Dependency Inversion Principle (DIP)**: `KRSManager` dan `KRSValidator` bergantung pada kontrak abstrak `KRSRepository <<interface>>` (`getKRS`, `cekPrasyaratLulus`, `simpanKRS`), sementara detail PostgreSQL/SQLite ditempatkan di `PostgresKRSRepository`. Untuk pengiriman notifikasi di seluruh domain (`SistemPMB`, `KRSManager`, `KeuanganService`, `PresensiService`), diterapkan `NotificationService` yang mendelegasikan ke `KRSEventBus` dan interface `NotificationObserver` (`EmailNotifier`, `WhatsAppNotifier`) dengan panah **asinkron `-)`** pada Sequence Diagram serta antrean *retry* (`antrekanRetry`).
- **3. Alternatif & Trade-off:**  
  - *Alternatif A:* Service langsung mengimpor SQLAlchemy Session dan memanggil `smtplib` secara sinkron di tengah request HTTP. Lebih sedikit lapisan abstraksi, namun mustahil di-mock secara murni saat unit testing cepat dan menyebabkan latensi API tinggi ketika SMTP lambat.  
  - *Trade-off Pilihan Ini:* Membutuhkan penambahan interface repository dan mekanisme outbox/retry untuk menjamin notifikasi tetap terkirim bila worker gagal sesaat.
- **4. Konsekuensi:**  
  - **Positif:** `KRSValidator` dapat diuji unit dalam hitungan milidetik memakai *in-memory/mock repository*; kegagalan SMTP pada PMB atau KRS tidak pernah membatalkan commit kelulusan/KRS yang sudah sah; penambahan kanal baru (misal Telegram/FCM) cukup dengan mendaftarkan observer ke `KRSEventBus`.  
  - **Negatif:** Sifat *eventual consistency* pada pesan notifikasi memerlukan log status retry (`notification_outbox`) agar mudah dipantau Admin.
- **5. Pattern:**  
  **Repository Pattern (DIP)** + **Observer / Publish-Subscribe Pattern** (`KRSEventBus` & `NotificationObserver`).

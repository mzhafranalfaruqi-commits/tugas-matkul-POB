# Diagram Sekuens Observer, Outbox, & Invalidasi KRS — SEVIMA-Mini

Dokumen ini memodelkan alur nyata pada [app/routers/jadwal.py](../app/routers/jadwal.py), [app/services/scheduling_service.py](../app/services/scheduling_service.py), [app/services/krs_invalidator.py](../app/services/krs_invalidator.py), dan [app/services/observer.py](../app/services/observer.py) saat Admin memperbarui (atau menerapkan saran AI terhadap) jadwal kuliah.

---

## Sequence Diagram (COMMIT Sebelum `notify`)

```mermaid
sequenceDiagram
    autonumber
    actor Admin
    participant API as FastAPI (/api/jadwal)
    participant Svc as SchedulingService
    participant Inv as KRSInvalidator
    participant DB as Database (SQLite/SQL)
    participant Disp as OutboxDispatcher
    participant Subj as ScheduleSubject
    participant Obs as Observers (Student/Lecturer/Admin)
    participant Ch as LogChannel (EMAIL/SMS/PUSH + IdemStore)

    Admin->>API: PUT /api/jadwal/{id} atau POST /apply (X-Role: admin)
    API->>API: require_admin() cek header X-Role
    API->>Svc: update(jadwal_id, data)

    Svc->>DB: BEGIN IMMEDIATE + SELECT FOR UPDATE (Ruangan -> Dosen)
    Svc->>DB: Cek bentrok (_bentrok_di_db) & cek_kapasitas(max(kuota, terdaftar))

    alt Bentrok atau kapasitas tidak cukup
        Svc->>DB: ROLLBACK (0 Outbox, 0 KRS berubah, 0 notifikasi)
        Svc-->>API: ScheduleConflictError / CapacityError
        API-->>Admin: HTTP 409 Conflict
    else Validasi lolos
        Svc->>Svc: Snapshot before -> update field & sequence += 1 -> after
        Svc->>Inv: invalidate(kelas_id, alasan) [TANPA commit]
        Inv->>DB: UPDATE krs SET status='REVISION', version+=1 (SUBMITTED/APPROVED saja)
        Inv->>DB: INSERT krs_log (aksi='INVALIDATE', aktor='SISTEM') & notifikasi
        Svc->>DB: INSERT outbox (event_id, payload, status='PENDING')
        Svc->>DB: COMMIT [Transaksi Utama Selesai Atomik]

        Note over Svc,Disp: Pengiriman notifikasi HANYA dimulai SETELAH COMMIT sukses

        Svc->>Disp: run(batch=50)
        Disp->>DB: SELECT outbox WHERE status='PENDING' FOR UPDATE SKIP LOCKED
        Disp->>Subj: notify(event)

        loop Untuk tiap observer di salinan list(_observers) [try/except per observer]
            Subj->>Obs: update(event)
            alt StudentObserver
                Obs->>DB: nim_di_kelas(kelas_id) via _dispatch_session_var
            end
            loop Untuk tiap penerima & channel (EMAIL, SMS, PUSH)
                Obs->>Ch: send(penerima, pesan, key="{event_id}:{penerima}:{channel}")
                Ch->>Ch: Cek IdemStore.sudah(key); kirim log + catat(key) jika baru
            end
            Note over Subj,Obs: Jika 1 observer raise Exception, dicatat ke gagal[] & loop lanjut
        end

        alt Semua observer sukses (gagal == [])
            Disp->>DB: UPDATE outbox SET status='SENT', attempts+=1 -> COMMIT
        else Ada observer gagal
            Disp->>DB: UPDATE outbox SET attempts+=1, status=(FAILED jika attempts>=5) -> COMMIT
        end

        Svc-->>API: Jadwal terbarui (SEQUENCE baru)
        API-->>Admin: HTTP 200 OK
    end
```

---

## Mengapa `COMMIT` Wajib Sebelum `notify()`?

1. **Mencegah Notifikasi Palsu (*Ghost Notification*):** Jika `notify()` dipanggil sebelum `COMMIT` lalu transaksi database gagal atau *rollback* karena bentrok/constraint, mahasiswa dan dosen akan terlanjur menerima Email/SMS perubahan jadwal yang tidak pernah tersimpan di database.
2. **Menjaga Keterlihatan Data (*Visibility*):** Worker atau pembaca lain hanya melihat perubahan jadwal dan status `REVISION` pada KRS setelah transaksi utama benar-benar `COMMIT`.
3. **Ketahanan Terhadap Kegagalan Gateway (*Transactional Outbox*):** Baris `outbox` ditulis di transaksi yang sama dengan `UPDATE jadwal` + `UPDATE krs`. Jika *gateway* Email/SMS sedang mati saat `OutboxDispatcher.run()` berjalan pasca-`COMMIT`, jadwal yang sudah sah tidak ikut ter-rollback; `OutboxDispatcher` mencatat `attempts += 1` dan dapat me-retry hingga `MAX_ATTEMPTS = 5` secara idempoten.

---

## Observer Pattern vs Publish-Subscribe (Pub-Sub)

| Aspek | Observer Pattern (Diaplikasikan di SEVIMA-Mini) | Publish-Subscribe (Event Broker) |
| :--- | :--- | :--- |
| **Kopling Komponen** | `ScheduleSubject` memegang daftar referensi objek `Observer` langsung (*in-process*) melalui kontrak `Protocol`. | Publisher dan Subscriber tidak saling mengenal; dipisahkan *message broker* (Redis Streams, RabbitMQ, Kafka). |
| **Eksekusi** | Sinkron dalam proses Python yang sama (`notify` memanggil `update()` berurutan). | Asinkron lintas proses/servis melalui topik dan antrean persisten. |
| **Kebutuhan Infrastruktur** | Nol komponen eksternal; sederhana untuk modul monolitik modular. | Memerlukan server broker terpisah, serialisasi pesan, dan pengelolaan consumer group. |
| **Jembatan Evolusi** | Tabel `outbox` + `OutboxDispatcher` sudah memisahkan penulisan event dari pengiriman, sehingga kelak `OutboxDispatcher` bisa mem-publish event ke RabbitMQ/Kafka tanpa menyentuh `SchedulingService`. | Cocok jika SEVIMA-Mini dipecah menjadi beberapa *microservice* terpisah di kemudian hari. |

---

## 4 Jebakan Klasik Observer yang Dicegah di Kode

1. **`notify()` dipanggil sebelum `commit()`** → Dicegah dengan menulis ke tabel `outbox` dalam transaksi utama lalu menjalankan `OutboxDispatcher.run()` **hanya setelah `db.commit()`**.
2. **Satu observer melempar exception menghentikan observer lain** → Dicegah lewat `for observer in list(self._observers): try ... except Exception:` pada `ScheduleSubject.notify()`.
3. **Memanggil `subject.attach()` per HTTP request (kebocoran memori & notifikasi N kali)** → Dicegah dengan *wiring singleton* `_default_subject` **sekali** saat inisialisasi modul [app/services/observer.py](../app/services/observer.py), plus deduplikasi `if observer not in self._observers` di `attach()`.
4. **Retry mengirim ulang notifikasi duplikat** → Dicegah oleh kunci idempotensi `{event_id}:{penerima}:{channel}` di `LogChannel` + `IdemStore`.

"""Pengujian Observer, Outbox, KRSInvalidator, AI Rescheduler, UI, & iCalendar Minggu 8."""

from datetime import date, datetime, time, timezone
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    CalonMahasiswa,
    Dosen,
    Jadwal,
    JalurMasuk,
    Kelas,
    KRS,
    KRSDetail,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    Outbox,
    ProgramStudi,
    Ruangan,
    StatusPMB,
)
from app.services.icalendar import export_jadwal_ics, ke_vevent
from app.services.observer import (
    AdminObserver,
    EventType,
    LecturerObserver,
    LogChannel,
    MemoryIdemStore,
    OutboxDispatcher,
    ScheduleEvent,
    ScheduleSubject,
    StudentObserver,
    get_default_channels,
)
from app.services.rescheduler import (
    EnvLLMClient,
    HeuristicLLMClient,
    get_llm_client,
    parse_saran,
    saring_saran,
)
from app.services.scheduling_service import SchedulingService
from seed import seed_data, seed_jadwal_data, seed_krs_data

ADMIN_HEADERS = {"X-Role": "admin"}


class _ListPesertaRepo:
    """Stub PesertaRepo di memori untuk unit test StudentObserver."""

    def __init__(self, mapping: dict[int, list[str]]) -> None:
        self.mapping = mapping

    def nim_di_kelas(self, kelas_id: int) -> list[str]:
        return list(self.mapping.get(kelas_id, []))


class _FakeLLM:
    """Mock deterministik LLMClient untuk mengunci perilaku guardrail AI."""

    def __init__(self, respons: str) -> None:
        self.respons = respons
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.respons


def _setup_kampus_mini(
    db: Session,
) -> tuple[Kelas, Kelas, Ruangan, Ruangan, Dosen, Dosen, Jadwal, Jadwal]:
    """Menyiapkan 2 MK, 2 kelas, 2 ruangan, 2 dosen, & 2 jadwal bersih."""
    mk1 = MataKuliah(
        kode_mk="IF301",
        nama="Pemrograman Sistem AI",
        sks=3,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
    )
    mk2 = MataKuliah(
        kode_mk="IF302",
        nama="Arsitektur Perangkat Lunak",
        sks=3,
        hari=2,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
    )
    r_besar = Ruangan(kode="B201", kapasitas=50)
    r_kecil = Ruangan(kode="A104", kapasitas=30)
    d1 = Dosen(nidn="0009018501", nama="Dr. Andi")
    d2 = Dosen(nidn="0009018502", nama="Dr. Budi")
    db.add_all([mk1, mk2, r_besar, r_kecil, d1, d2])
    db.flush()

    k1 = Kelas(kode_mk="IF301", nama="A", kuota=40, semester="20251")
    k2 = Kelas(kode_mk="IF302", nama="A", kuota=25, semester="20251")
    db.add_all([k1, k2])
    db.flush()

    j1 = Jadwal(
        kelas_id=k1.id,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
        ruangan_kode=r_besar.kode,
        dosen_id=d1.id,
    )
    j2 = Jadwal(
        kelas_id=k2.id,
        hari=2,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
        ruangan_kode=r_kecil.kode,
        dosen_id=d2.id,
    )
    db.add_all([j1, j2])
    db.commit()
    return k1, k2, r_besar, r_kecil, d1, d2, j1, j2


def _tambah_mahasiswa_krs(
    db: Session,
    nim: str,
    kode_mk: str,
    kelas_id: int,
    status: KRSStatus,
    catatan_revisi: str | None = None,
) -> KRS:
    """Membuat mahasiswa fiktif beserta header & 1 baris KRSDetail tertaut kelas_id."""
    prodi = db.execute(select(ProgramStudi).limit(1)).scalar_one()
    jalur = db.execute(select(JalurMasuk).limit(1)).scalar_one()
    mhs = CalonMahasiswa(
        nama_lengkap=f"Mahasiswa {nim}",
        email=f"{nim}@example.com",
        phone="081234567890",
        tanggal_lahir=date(2006, 2, 10),
        alamat="Bandung",
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status=StatusPMB.approved,
        nim=nim,
    )
    db.add(mhs)
    db.flush()

    krs = KRS(
        nim=nim,
        semester="20251",
        status=status,
        dosen_pa_id=101,
        catatan_revisi=catatan_revisi,
        details=[KRSDetail(kode_mk=kode_mk, kelas_id=kelas_id)],
    )
    db.add(krs)
    db.commit()
    return krs


# ---------------------------------------------------------------------------
# 1. Unit Tests Observer Pattern & Channel Idempotency
# ---------------------------------------------------------------------------


def test_subject_attach_duplikat_detach_dan_isolasi_observer_gagal() -> None:
    """Memastikan attach duplikat diabaikan, detach aman, dan 1 observer error tidak memutus lainnya."""
    panggilan_sukses: list[str] = []

    class _ObserverSukses:
        def update(self, event: ScheduleEvent) -> None:
            panggilan_sukses.append(event.event_id)

    class _ObserverGagal:
        def update(self, _event: ScheduleEvent) -> None:
            raise RuntimeError("SMTP server down")

    subject = ScheduleSubject()
    obs_sukses = _ObserverSukses()
    obs_gagal = _ObserverGagal()

    subject.attach(obs_gagal)
    subject.attach(obs_sukses)
    # Attach ulang objek yang sama harus diabaikan (mencegah notifikasi ganda).
    subject.attach(obs_sukses)
    assert len(subject.observers) == 2

    ev = ScheduleEvent(
        event_type=EventType.SCHEDULE_CHANGED,
        jadwal_id=10,
        before={"kelas_id": 1, "hari": 1, "jam_mulai": "08:00", "jam_selesai": "09:40", "ruangan_kode": "A101", "dosen_id": 1},
        after={"kelas_id": 1, "hari": 3, "jam_mulai": "13:00", "jam_selesai": "14:40", "ruangan_kode": "B201", "dosen_id": 1},
    )
    gagal = subject.notify(ev)

    assert gagal == ["_ObserverGagal"]
    assert panggilan_sukses == [ev.event_id]

    subject.detach(obs_gagal)
    subject.detach(obs_gagal)  # detach objek yang sudah lepas tidak boleh error
    gagal_kedua = subject.notify(ev)
    assert gagal_kedua == []
    assert panggilan_sukses == [ev.event_id, ev.event_id]


def test_tiga_observer_kirim_email_sms_push_dan_idempotency() -> None:
    """Student, Lecturer (dosen lama + baru), dan Admin mengirim via Email/SMS/Push tanpa duplikasi."""
    store = MemoryIdemStore()
    email = LogChannel("EMAIL", store)
    sms = LogChannel("SMS", store)
    push = LogChannel("PUSH", store)
    channels = [email, sms, push]

    peserta = _ListPesertaRepo({1: ["2025001-0001", "2025001-0002"]})
    subject = ScheduleSubject()
    subject.attach(StudentObserver(peserta, channels))
    subject.attach(LecturerObserver(channels))
    subject.attach(AdminObserver(channels))

    ev = ScheduleEvent(
        event_type=EventType.SCHEDULE_CHANGED,
        jadwal_id=7,
        before={"kelas_id": 1, "hari": 1, "jam_mulai": "08:00", "jam_selesai": "09:40", "ruangan_kode": "A101", "dosen_id": 1},
        after={"kelas_id": 1, "hari": 2, "jam_mulai": "13:00", "jam_selesai": "14:40", "ruangan_kode": "B201", "dosen_id": 2},
    )
    assert subject.notify(ev) == []

    # 2 mahasiswa + 2 dosen (baru & lama) + 1 admin = 5 penerima per channel.
    penerima_harap = {
        "2025001-0001",
        "2025001-0002",
        "dosen-2",
        "dosen-1",
        "admin-akademik",
    }
    for ch in channels:
        assert {item[0] for item in ch.terkirim} == penerima_harap
        assert len(ch.terkirim) == 5

    # Pengiriman ulang event dengan event_id sama harus terdeduplikasi penuh.
    assert subject.notify(ev) == []
    for ch in channels:
        assert len(ch.terkirim) == 5


# ---------------------------------------------------------------------------
# 2. Transactional Outbox & Dispatcher Retry
# ---------------------------------------------------------------------------


def test_outbox_kosong_bila_transaksi_rollback(db_session: Session) -> None:
    """Rollback (bentrok atau gagal commit) tidak boleh meninggalkan Outbox maupun mengirim notifikasi."""
    k1, k2, r_besar, r_kecil, d1, d2, j1, j2 = _setup_kampus_mini(db_session)
    _ = r_kecil, j1

    email_ch = get_default_channels()[0]
    awal_count = len(email_ch.terkirim)

    svc = SchedulingService(db_session)
    from app.schemas.jadwal import JadwalIn
    from app.services.exceptions import ScheduleConflictError

    # Update j2 agar menabrak j1 di hari 1 08:00-09:40 -> ScheduleConflictError + rollback
    with pytest.raises(ScheduleConflictError):
        svc.update(
            j2.id,
            JadwalIn(
                kelas_id=k2.id,
                hari=1,
                jam_mulai=time(8, 0),
                jam_selesai=time(9, 40),
                ruangan_kode=r_besar.kode,
                dosen_id=d2.id,
            ),
        )

    assert db_session.query(Outbox).count() == 0
    assert len(email_ch.terkirim) == awal_count


def test_outbox_dispatcher_retry_idempotent_lalu_failed_setelah_5_kali(
    db_session: Session,
) -> None:
    """OutboxDispatcher menandai FAILED setelah 5 gagal tanpa mengulang kanal yang sudah sukses."""
    store = MemoryIdemStore()
    email = LogChannel("EMAIL", store)

    class _ObserverRusak:
        def update(self, _event: ScheduleEvent) -> None:
            raise ConnectionError("SMS gateway timeout")

    subject = ScheduleSubject()
    subject.attach(AdminObserver([email]))
    subject.attach(_ObserverRusak())

    ev = ScheduleEvent(
        event_type=EventType.SCHEDULE_CHANGED,
        jadwal_id=99,
        before={"kelas_id": 1, "hari": 1, "jam_mulai": "08:00", "jam_selesai": "09:40", "ruangan_kode": "A101", "dosen_id": 1},
        after={"kelas_id": 1, "hari": 3, "jam_mulai": "13:00", "jam_selesai": "14:40", "ruangan_kode": "B201", "dosen_id": 1},
    )
    row = Outbox.dari_event(ev)
    db_session.add(row)
    db_session.commit()

    dispatcher = OutboxDispatcher(db_session, subject)
    for attempt in range(1, 5):
        processed = dispatcher.run()
        assert processed == 1
        db_session.refresh(row)
        assert row.attempts == attempt
        assert row.status == "PENDING"

    # Attempt ke-5 mencapai MAX_ATTEMPTS=5 -> FAILED.
    assert dispatcher.run() == 1
    db_session.refresh(row)
    assert row.attempts == 5
    assert row.status == "FAILED"

    # Meski di-retry 5x, AdminObserver + LogChannel hanya mengirim TEPAT 1 kali (idempotent).
    assert len(email.terkirim) == 1
    assert dispatcher.run() == 0  # FAILED tidak diproses ulang.


# ---------------------------------------------------------------------------
# 3. Integrasi SchedulingService + KRSInvalidator + Outbox Atomik
# ---------------------------------------------------------------------------


def test_update_dan_delete_invalidasi_krs_dan_tulis_outbox_atomik(
    db_session: Session,
) -> None:
    """update/delete jadwal memindahkan APPROVED & SUBMITTED ke REVISION, menjaga DRAFT/kelas lain, & kirim outbox."""
    k1, k2, r_besar, _, d1, _, j1, _ = _setup_kampus_mini(db_session)

    krs_approved = _tambah_mahasiswa_krs(
        db_session, "2025001-0011", "IF301", k1.id, KRSStatus.APPROVED
    )
    krs_submitted = _tambah_mahasiswa_krs(
        db_session, "2025001-0012", "IF301", k1.id, KRSStatus.SUBMITTED
    )
    krs_draft = _tambah_mahasiswa_krs(
        db_session, "2025001-0013", "IF301", k1.id, KRSStatus.DRAFT
    )
    krs_revision_lama = _tambah_mahasiswa_krs(
        db_session,
        "2025001-0014",
        "IF301",
        k1.id,
        KRSStatus.REVISION,
        catatan_revisi="Catatan PA lama",
    )
    krs_kelas_lain = _tambah_mahasiswa_krs(
        db_session, "2025001-0015", "IF302", k2.id, KRSStatus.APPROVED
    )

    email_ch, sms_ch, push_ch = get_default_channels()
    awal_email = len(email_ch.terkirim)
    awal_sms = len(sms_ch.terkirim)
    awal_push = len(push_ch.terkirim)

    from app.schemas.jadwal import JadwalIn

    svc = SchedulingService(db_session)
    terbarui = svc.update(
        j1.id,
        JadwalIn(
            kelas_id=k1.id,
            hari=3,
            jam_mulai=time(13, 0),
            jam_selesai=time(14, 40),
            ruangan_kode=r_besar.kode,
            dosen_id=d1.id,
        ),
    )
    assert terbarui.sequence == 1

    for obj in (krs_approved, krs_submitted, krs_draft, krs_revision_lama, krs_kelas_lain):
        db_session.refresh(obj)

    assert krs_approved.status == KRSStatus.REVISION
    assert krs_submitted.status == KRSStatus.REVISION
    assert krs_approved.version == 2
    assert krs_submitted.version == 2
    assert krs_approved.catatan_revisi is not None
    assert krs_approved.catatan_revisi.startswith("Otomatis:")

    # DRAFT, REVISION sebelumnya, dan KRS kelas lain tidak disentuh.
    assert krs_draft.status == KRSStatus.DRAFT
    assert krs_revision_lama.status == KRSStatus.REVISION
    assert krs_revision_lama.catatan_revisi == "Catatan PA lama"
    assert krs_kelas_lain.status == KRSStatus.APPROVED

    # Audit trail KRSLog + Notifikasi tersimpan atomik.
    logs = db_session.scalars(
        select(KRSLog).where(KRSLog.aksi == "INVALIDATE")
    ).all()
    assert {l.krs_id for l in logs} == {krs_approved.id, krs_submitted.id}
    assert all(l.aktor_id == "SISTEM" for l in logs)

    notifs = db_session.scalars(select(Notifikasi)).all()
    assert {n.nim for n in notifs} == {"2025001-0011", "2025001-0012"}

    # Outbox tercatat dan sudah berstatus SENT pasca-commit.
    outbox_rows = db_session.scalars(select(Outbox)).all()
    assert len(outbox_rows) == 1
    assert outbox_rows[0].status == "SENT"
    assert outbox_rows[0].attempts == 1

    # Email, SMS, & Push mengirim ke peserta kelas + dosen + admin.
    assert len(email_ch.terkirim) > awal_email
    assert len(sms_ch.terkirim) > awal_sms
    assert len(push_ch.terkirim) > awal_push

    # Sekarang set krs_approved menjadi APPROVED lagi lalu uji delete().
    krs_approved.status = KRSStatus.APPROVED
    db_session.commit()

    svc.delete(j1.id)
    db_session.refresh(krs_approved)
    assert krs_approved.status == KRSStatus.REVISION
    assert krs_approved.catatan_revisi is not None
    assert "dihapus" in krs_approved.catatan_revisi.lower()
    assert db_session.query(Outbox).count() == 2


def test_kegagalan_observer_pasca_commit_tidak_batalkan_update(db_session: Session) -> None:
    """Bila semua/sebagian observer gagal pasca-commit, update jadwal & KRS tetap tersimpan."""
    k1, _, r_besar, _, d1, _, j1, _ = _setup_kampus_mini(db_session)
    krs = _tambah_mahasiswa_krs(
        db_session, "2025001-0020", "IF301", k1.id, KRSStatus.APPROVED
    )

    class _BoomObserver:
        def update(self, _event: ScheduleEvent) -> None:
            raise RuntimeError("Gateway mati")

    bad_subject = ScheduleSubject()
    bad_subject.attach(_BoomObserver())

    from app.schemas.jadwal import JadwalIn

    svc = SchedulingService(db_session, subject=bad_subject)
    updated = svc.update(
        j1.id,
        JadwalIn(
            kelas_id=k1.id,
            hari=4,
            jam_mulai=time(13, 0),
            jam_selesai=time(14, 40),
            ruangan_kode=r_besar.kode,
            dosen_id=d1.id,
        ),
    )
    assert updated.hari == 4
    assert updated.sequence == 1
    db_session.refresh(krs)
    assert krs.status == KRSStatus.REVISION

    outbox = db_session.scalar(select(Outbox))
    assert outbox is not None
    assert outbox.status == "PENDING"
    assert outbox.attempts == 1


# ---------------------------------------------------------------------------
# 4. AI Rescheduling (`FakeLLM` + 4-Layer Guardrail) & Conflict Resolver UI
# ---------------------------------------------------------------------------


def test_saring_saran_empat_lapis_dengan_fake_llm() -> None:
    """FakeLLM memberi 1 valid + 1 ruangan fiktif + 1 bentrok (+ kapasitas/overflow) -> hanya 1 lolos."""
    from app.services.conflict import JadwalSlot

    jadwal_target = JadwalSlot(
        id=1,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
        ruangan_kode="A101",
        dosen_id=1,
    )
    jadwal_lain = [
        JadwalSlot(
            id=2,
            hari=2,
            jam_mulai=time(13, 0),
            jam_selesai=time(14, 40),
            ruangan_kode="B201",
            dosen_id=2,
        )
    ]
    ruang_map = {
        "B201": Ruangan(kode="B201", kapasitas=50),
        "A104": Ruangan(kode="A104", kapasitas=30),
    }

    fake_json = json.dumps(
        [
            {"hari": 3, "jam_mulai": "13:00", "ruangan": "B201", "reason": "Kosong total"},
            {"hari": 4, "jam_mulai": "13:00", "ruangan": "Z999", "reason": "Ruang fiktif"},
            {"hari": 2, "jam_mulai": "13:30", "ruangan": "B201", "reason": "Bentrok dengan #2"},
            {"hari": 5, "jam_mulai": "08:00", "ruangan": "A104", "reason": "Kapasitas 30 < 40"},
            {"hari": 5, "jam_mulai": "23:30", "ruangan": "B201", "reason": "Lewat tengah malam"},
            {"hari": 3, "jam_mulai": "13:00", "ruangan": "B201", "reason": "Duplikat"},
        ]
    )
    fake_llm = _FakeLLM(f"Berikut saran terbaik:\n{fake_json}")
    raw = fake_llm.complete("prompt")
    hasil = saring_saran(raw, jadwal_target, peserta=40, lain=jadwal_lain, ruang=ruang_map)

    assert len(hasil) == 1
    assert hasil[0].hari == 3
    assert hasil[0].jam_mulai == time(13, 0)
    assert hasil[0].ruangan == "B201"

    assert parse_saran("bukan json valid sama sekali") == []
    assert parse_saran('[{"hari": 9, "jam_mulai": "xx"}]') == []


def test_resolver_api_suggestions_apply_ui_dan_role_guard(
    client: TestClient, db_session: Session
) -> None:
    """Uji endpoint suggestions, apply (satu pintu + 409/422), UI HTML, & proteksi 403 admin."""
    k1, k2, r_besar, r_kecil, d1, d2, j1, j2 = _setup_kampus_mini(db_session)
    _ = r_kecil, d1

    # Sisipkan bentrok sengaja langsung di DB (j_konflik menabrak j1 di hari 1 B201)
    j_konflik = Jadwal(
        kelas_id=k2.id,
        hari=1,
        jam_mulai=time(8, 30),
        jam_selesai=time(10, 10),
        ruangan_kode=r_besar.kode,
        dosen_id=d2.id,
    )
    db_session.add(j_konflik)
    db_session.commit()

    krs = _tambah_mahasiswa_krs(
        db_session, "2025001-0030", "IF302", k2.id, KRSStatus.APPROVED
    )

    fake_llm = _FakeLLM(
        json.dumps(
            [
                {"hari": 4, "jam_mulai": "13:00", "ruangan": "B201", "reason": "Bebas bentrok"},
                {"hari": 1, "jam_mulai": "08:00", "ruangan": "GHOST", "reason": "Halusinasi"},
                {"hari": 2, "jam_mulai": "08:00", "ruangan": "B201", "reason": "Bentrok dosen d2 dengan j2"},
            ]
        )
    )
    app.dependency_overrides[get_llm_client] = lambda: fake_llm

    # Role guard 403 untuk non-admin
    assert client.get(f"/api/jadwal/{j_konflik.id}/suggestions").status_code == 403
    assert (
        client.get(
            f"/api/jadwal/{j_konflik.id}/suggestions",
            headers={"X-Role": "mahasiswa"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/jadwal/{j_konflik.id}/apply",
            json={"hari": 4, "jam_mulai": "13:00:00", "ruangan": "B201"},
        ).status_code
        == 403
    )

    # GET /api/jadwal & GET /api/jadwal/resolver HTML UI
    res_list = client.get("/api/jadwal")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 3
    assert res_list.json()[0]["kode_mk"] in {"IF301", "IF302"}

    res_ui = client.get("/api/jadwal/resolver")
    assert res_ui.status_code == 200
    assert "text/html" in res_ui.headers["content-type"]
    assert "Conflict Resolver" in res_ui.text

    # GET suggestions dengan admin role -> tepat 1 saran tervalidasi
    res_sug = client.get(
        f"/api/jadwal/{j_konflik.id}/suggestions", headers=ADMIN_HEADERS
    )
    assert res_sug.status_code == 200
    saran_list = res_sug.json()
    assert len(saran_list) == 1
    assert saran_list[0]["hari"] == 4
    assert saran_list[0]["jam_mulai"] == "13:00:00"
    assert saran_list[0]["jam_selesai"] == "14:40:00"
    assert saran_list[0]["ruangan"] == "B201"
    assert client.get("/api/jadwal/9999/suggestions", headers=ADMIN_HEADERS).status_code == 404

    # POST apply ke slot bentrok (ditabrak oleh j1) -> 409
    res_apply_409 = client.post(
        f"/api/jadwal/{j_konflik.id}/apply",
        headers=ADMIN_HEADERS,
        json={"hari": 1, "jam_mulai": "08:00:00", "ruangan": "B201"},
    )
    assert res_apply_409.status_code == 409

    # POST apply melewati tengah malam -> 422
    res_apply_422 = client.post(
        f"/api/jadwal/{j_konflik.id}/apply",
        headers=ADMIN_HEADERS,
        json={"hari": 4, "jam_mulai": "23:30:00", "ruangan": "B201"},
    )
    assert res_apply_422.status_code == 422

    # POST apply saran valid -> 200, sequence naik, bentrok hilang, KRS -> REVISION
    res_apply_ok = client.post(
        f"/api/jadwal/{j_konflik.id}/apply",
        headers=ADMIN_HEADERS,
        json={
            "hari": 4,
            "jam_mulai": "13:00:00",
            "ruangan": "B201",
            "reason": "Bebas bentrok",
        },
    )
    assert res_apply_ok.status_code == 200
    assert res_apply_ok.json()["hari"] == 4
    assert res_apply_ok.json()["sequence"] == 1
    assert client.get("/api/jadwal/conflicts").json() == []

    db_session.refresh(krs)
    assert krs.status == KRSStatus.REVISION


def test_heuristic_llm_client_fallback_tanpa_api_key(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EnvLLMClient memakai HeuristicLLMClient bila API key absen atau request HTTP gagal."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _, _, _, _, _, _, j1, _ = _setup_kampus_mini(db_session)
    from app.services.rescheduler import ReschedulerService

    llm = EnvLLMClient()
    _, hasil = ReschedulerService(db_session, llm=llm).saran_alternatif(j1.id)
    assert 1 <= len(hasil) <= 3
    assert HeuristicLLMClient().complete("prompt tanpa marker") == "[]"

    # Uji fallback saat HTTP LLM gagal + parse_saran tahan teks berkurung siku.
    import httpx

    def _gagal_post(*_args: object, **_kwargs: object) -> object:
        raise httpx.ConnectError("offline")

    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    monkeypatch.setattr(httpx, "post", _gagal_post)
    _, hasil_fallback = ReschedulerService(db_session, llm=EnvLLMClient()).saran_alternatif(j1.id)
    assert 1 <= len(hasil_fallback) <= 3

    terparse = parse_saran(
        '[Info Awal] [{"hari": 3, "jam_mulai": "13:00", "ruangan": "B201", "reason": "OK [1]"}] [Catatan]'
    )
    assert len(terparse) == 1
    assert terparse[0].ruangan == "B201"


# ---------------------------------------------------------------------------
# 5. Ekspor iCalendar (.ics) & Seed End-to-End Minggu 8
# ---------------------------------------------------------------------------


def test_export_ics_format_crlf_sequence_dan_404(
    client: TestClient, db_session: Session
) -> None:
    """Uji format RFC 5545 (CRLF, TZID Asia/Jakarta, UTC UNTIL), kenaikan SEQUENCE, & 404 NIM."""
    from app.services.conflict import JadwalSlot

    slot = JadwalSlot(
        id=42,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
        ruangan_kode="A101;Lt1",
        dosen_id=1,
    )
    vevent = ke_vevent(
        slot,
        judul="IF101-A Algoritma, Dasar",
        awal=date(2025, 9, 1),
        akhir=date(2025, 12, 20),
        sequence=2,
        dtstamp=datetime(2025, 9, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert "\r\n" in vevent
    assert "UID:jadwal-42@sevima-mini" in vevent
    assert "SEQUENCE:2" in vevent
    assert "DTSTART;TZID=Asia/Jakarta:20250901T080000" in vevent
    assert "DTEND;TZID=Asia/Jakarta:20250901T094000" in vevent
    assert "RRULE:FREQ=WEEKLY;UNTIL=20251220T165959Z" in vevent
    assert "SUMMARY:IF101-A Algoritma\\, Dasar" in vevent
    assert "LOCATION:A101\\;Lt1" in vevent

    ics_kosong = export_jadwal_ics([])
    assert ics_kosong.startswith("BEGIN:VCALENDAR\r\n")
    assert ics_kosong.endswith("END:VCALENDAR\r\n")

    # End-to-end API mahasiswa .ics + kenaikan SEQUENCE saat jadwal diubah.
    k1, _, r_besar, _, d1, _, j1, _ = _setup_kampus_mini(db_session)
    _tambah_mahasiswa_krs(
        db_session, "2025001-0050", "IF301", k1.id, KRSStatus.APPROVED
    )

    assert client.get("/api/mahasiswa/TIDAK-ADA/jadwal.ics").status_code == 404
    assert (
        client.get("/api/mahasiswa/2025001-0050/jadwal.ics?semester=20991").status_code
        == 404
    )

    res1 = client.get("/api/mahasiswa/2025001-0050/jadwal.ics")
    assert res1.status_code == 200
    assert res1.headers["content-type"].startswith("text/calendar")
    body1 = res1.content.decode("utf-8")
    assert "\r\n" in body1
    assert f"UID:jadwal-{j1.id}@sevima-mini\r\n" in body1
    assert "SEQUENCE:0\r\n" in body1

    # Ubah jadwal -> SEQUENCE naik menjadi 1 dan ruangan terbarui di .ics.
    res_put = client.put(
        f"/api/jadwal/{j1.id}",
        headers=ADMIN_HEADERS,
        json={
            "kelas_id": k1.id,
            "hari": 3,
            "jam_mulai": "13:00:00",
            "jam_selesai": "14:40:00",
            "ruangan_kode": r_besar.kode,
            "dosen_id": d1.id,
        },
    )
    assert res_put.status_code == 200

    res2 = client.get("/api/mahasiswa/2025001-0050/jadwal.ics?semester=20251")
    assert res2.status_code == 200
    body2 = res2.content.decode("utf-8")
    assert "SEQUENCE:1\r\n" in body2
    assert "DTSTART;TZID=Asia/Jakarta:20250903T130000\r\n" in body2


def test_seed_minggu_8_krs_20251_idempotent_dan_ics_budi(
    client: TestClient, db_session: Session
) -> None:
    """Seed lengkap menghasilkan KRS 20251 untuk Budi dan ekspor .ics memuat 3 VEVENT stabil."""
    seed_data(db_session)
    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    jumlah_krs_1 = db_session.query(KRS).count()
    jumlah_detail_1 = db_session.query(KRSDetail).count()

    seed_krs_data(db_session)
    seed_jadwal_data(db_session)
    assert db_session.query(KRS).count() == jumlah_krs_1
    assert db_session.query(KRSDetail).count() == jumlah_detail_1

    res = client.get("/api/mahasiswa/2025001-0001/jadwal.ics")
    assert res.status_code == 200
    body = res.content.decode("utf-8")
    # 3 kelas (IF102-A, IF201-B, IF204-A) masing-masing memiliki 2 sesi/minggu = 6 VEVENT.
    assert body.count("BEGIN:VEVENT") == 6
    assert body.count("END:VEVENT") == 6
    assert "SUMMARY:IF201-B Basis Data" in body
    assert "SUMMARY:IF102-A Struktur Data" in body
    assert "SUMMARY:IF204-A Jaringan Komputer" in body

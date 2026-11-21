"""Service AI-Powered Rescheduling dengan guardrail deterministik 4 lapis."""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
import json
import logging
import os
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.jadwal import Jadwal, Kelas, Ruangan
from app.models.krs import KRSDetail
from app.schemas.jadwal import JadwalIn
from app.services.conflict import JadwalLike, JadwalSlot, detect_schedule_conflict
from app.services.exceptions import NotFoundError, ScheduleValidationError
from app.services.scheduling_service import SchedulingService

logger = logging.getLogger("sevima.rescheduler")

SLOT_MULAI_STANDAR: tuple[time, ...] = (
    time(7, 0),
    time(8, 0),
    time(9, 40),
    time(11, 20),
    time(13, 0),
    time(14, 40),
    time(16, 20),
)

NAMA_HARI: dict[int, str] = {
    1: "Senin",
    2: "Selasa",
    3: "Rabu",
    4: "Kamis",
    5: "Jumat",
    6: "Sabtu",
}

_MARKER_SLOT = "SLOT_TERSEDIA_JSON:"
_REF_DATE = date(2025, 1, 1)


def hitung_durasi(jadwal: JadwalLike) -> timedelta:
    """Menghitung durasi pertemuan dari selisih jam_selesai dan jam_mulai."""
    mulai_dt = datetime.combine(_REF_DATE, jadwal.jam_mulai)
    selesai_dt = datetime.combine(_REF_DATE, jadwal.jam_selesai)
    return selesai_dt - mulai_dt


def tambah_durasi(mulai: time, durasi: timedelta) -> time | None:
    """Menambahkan durasi ke jam_mulai dan mengembalikan None jika melewati tengah malam."""
    if durasi <= timedelta(0):
        return None
    selesai_dt = datetime.combine(_REF_DATE, mulai) + durasi
    if selesai_dt.date() != _REF_DATE or selesai_dt.time() <= mulai:
        return None
    return selesai_dt.time()


def hitung_peserta(db: Session, kelas: Kelas) -> int:
    """Menghitung kebutuhan kursi aktual: max(kuota kelas, mahasiswa terdaftar)."""
    terdaftar = (
        db.scalar(
            select(func.count())
            .select_from(KRSDetail)
            .where(KRSDetail.kelas_id == kelas.id)
        )
        or 0
    )
    return max(kelas.kuota, terdaftar)


def hitung_slot_tersedia(
    jadwal: JadwalLike,
    peserta: int,
    semua_jadwal: Sequence[JadwalLike],
    semua_ruang: Sequence[Ruangan],
    max_slots: int = 24,
) -> list[dict[str, Any]]:
    """Menghitung slot bebas konflik secara deterministik sebagai konteks prompt LLM."""
    lain: list[JadwalLike] = [item for item in semua_jadwal if item.id != jadwal.id]
    durasi = hitung_durasi(jadwal)
    if durasi <= timedelta(0):
        return []

    ruang_layak = sorted(
        (r for r in semua_ruang if r.kapasitas >= peserta),
        key=lambda r: (r.kapasitas - peserta, r.kode),
    )

    hasil: list[dict[str, Any]] = []
    for hari in range(1, 7):
        for jam_mulai in SLOT_MULAI_STANDAR:
            jam_selesai = tambah_durasi(jam_mulai, durasi)
            if jam_selesai is None:
                continue

            per_waktu = 0
            for r in ruang_layak:
                if (
                    hari == jadwal.hari
                    and jam_mulai == jadwal.jam_mulai
                    and r.kode == jadwal.ruangan_kode
                ):
                    continue
                calon = JadwalSlot(
                    id=-1,
                    hari=hari,
                    jam_mulai=jam_mulai,
                    jam_selesai=jam_selesai,
                    ruangan_kode=r.kode,
                    dosen_id=jadwal.dosen_id,
                )
                konflik = detect_schedule_conflict([*lain, calon])
                if any(-1 in k.affected for k in konflik):
                    continue

                hasil.append(
                    {
                        "hari": hari,
                        "nama_hari": NAMA_HARI.get(hari, f"Hari {hari}"),
                        "jam_mulai": jam_mulai.strftime("%H:%M"),
                        "jam_selesai": jam_selesai.strftime("%H:%M"),
                        "ruangan": r.kode,
                        "kapasitas": r.kapasitas,
                    }
                )
                per_waktu += 1
                if len(hasil) >= max_slots:
                    return hasil
                if per_waktu >= 2:
                    break
    return hasil


class Saran(BaseModel):
    """Skema Pydantic v2 untuk satu saran slot penjadwalan ulang dari LLM."""

    hari: int = Field(ge=1, le=6)
    jam_mulai: time
    ruangan: str = Field(min_length=1, max_length=20)
    reason: str = ""

    @field_validator("ruangan", mode="after")
    @classmethod
    def strip_ruangan(cls, value: str) -> str:
        """Membersihkan spasi di pinggir kode ruangan dan menolak string kosong."""
        bersih = value.strip()
        if not bersih:
            raise ValueError("ruangan tidak boleh kosong")
        return bersih


class LLMClient(Protocol):
    """Kontrak klien LLM untuk memberi saran peringkat slot jadwal alternatif."""

    def complete(self, prompt: str) -> str:
        """Menghasilkan teks respons dari prompt terstruktur."""


class HeuristicLLMClient:
    """Fallback deterministik lokal ketika API key LLM eksternal tidak dikonfigurasi."""

    @staticmethod
    def _skor_slot(slot: dict[str, Any]) -> tuple[int, int, int, int, str]:
        hari = int(slot["hari"])
        jam_str = str(slot["jam_mulai"])
        jam_int = int(jam_str.split(":", maxsplit=1)[0])
        kapasitas = int(slot["kapasitas"])

        # Prioritaskan hari kerja (Senin-Jumat), jam inti kuliah (08:00-14:59), dan ruang pas.
        penalti_sabtu = 1 if hari == 6 else 0
        penalti_jam = 0 if 8 <= jam_int <= 14 else 1
        return (penalti_sabtu, penalti_jam, hari, kapasitas, str(slot["ruangan"]))

    def complete(self, prompt: str) -> str:
        """Memilih hingga 3 slot terbaik dari daftar terhitung pada prompt dalam JSON."""
        if _MARKER_SLOT not in prompt:
            return "[]"

        setelah = prompt.split(_MARKER_SLOT, maxsplit=1)[1].lstrip()
        if not setelah.startswith("["):
            return "[]"

        try:
            kandidat, _ = json.JSONDecoder().raw_decode(setelah)
        except json.JSONDecodeError:
            return "[]"

        if not isinstance(kandidat, list):
            return "[]"

        urut = sorted(kandidat, key=self._skor_slot)[:3]
        keluaran: list[dict[str, Any]] = []
        for idx, slot in enumerate(urut, start=1):
            nama_hari = NAMA_HARI.get(int(slot["hari"]), f"Hari {slot['hari']}")
            keluaran.append(
                {
                    "hari": int(slot["hari"]),
                    "jam_mulai": str(slot["jam_mulai"]),
                    "ruangan": str(slot["ruangan"]),
                    "reason": (
                        f"Opsi #{idx}: {nama_hari} {slot['jam_mulai']}-{slot['jam_selesai']} "
                        f"di {slot['ruangan']} (kapasitas {slot['kapasitas']}) bebas bentrok."
                    ),
                }
            )
        return json.dumps(keluaran)


class EnvLLMClient:
    """Klien LLM adaptif: memanggil Gemini/OpenAI via HTTP bila env tersedia, else heuristik."""

    def __init__(self) -> None:
        self._fallback = HeuristicLLMClient()

    def _panggil_openai_compatible(self, api_key: str, prompt: str) -> str:
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    def _panggil_gemini(self, api_key: str, prompt: str) -> str:
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={api_key}"
        )
        resp = httpx.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["candidates"][0]["content"]["parts"][0]["text"])

    def complete(self, prompt: str) -> str:
        """Memanggil API LLM jika tersedia, dan jatuh kembali aman ke HeuristicLLMClient."""
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        try:
            if gemini_key:
                return self._panggil_gemini(gemini_key, prompt)
            if openai_key:
                return self._panggil_openai_compatible(openai_key, prompt)
        except Exception:
            logger.warning("Pemanggilan LLM eksternal gagal; memakai fallback heuristik")
        return self._fallback.complete(prompt)


def get_llm_client() -> LLMClient:
    """Dependency FastAPI penyedia klien LLM (mudah di-override dengan FakeLLM di pytest)."""
    return EnvLLMClient()


def bangun_prompt(
    jadwal: Jadwal,
    kelas: Kelas,
    peserta: int,
    slots: list[dict[str, Any]],
) -> str:
    """Menyusun prompt terstruktur berisi jadwal bermasalah, aturan, & daftar slot bebas."""
    kode_mk = kelas.kode_mk
    hari_nama = NAMA_HARI.get(jadwal.hari, f"Hari {jadwal.hari}")
    slot_json = json.dumps(slots, ensure_ascii=False)
    return (
        "Anda adalah asisten penjadwalan akademik universitas.\n"
        f"Jadwal #{jadwal.id} untuk kelas {kode_mk}-{kelas.nama} (semester {kelas.semester}, "
        f"kebutuhan {peserta} kursi, dosen_id={jadwal.dosen_id}) saat ini dijadwalkan pada "
        f"{hari_nama} pukul {jadwal.jam_mulai.strftime('%H:%M')}-"
        f"{jadwal.jam_selesai.strftime('%H:%M')} di ruang {jadwal.ruangan_kode} "
        "dan mengalami bentrok.\n\n"
        "ATURAN KERAS (WAJIB):\n"
        "- Hanya pilih slot dari daftar SLOT_TERSEDIA_JSON di bawah.\n"
        "- Kapasitas ruangan minimal >= kebutuhan kursi.\n"
        "- Jangan memindahkan ke slot yang bentrok ruangan atau dosen.\n\n"
        "PREFERENSI (SOFT CONSTRAINT):\n"
        "- Utamakan hari Senin-Jumat jam kuliah inti (08:00-15:00) dan ruang paling pas.\n\n"
        f"{_MARKER_SLOT}\n{slot_json}\n\n"
        "Kembalikan HANYA JSON array berisi maksimal 3 objek dengan format persis:\n"
        '[{"hari": 3, "jam_mulai": "13:00", "ruangan": "B201", "reason": "..."}]'
    )


def parse_saran(raw: str) -> list[Saran]:
    """Mem-parse JSON array saran dari teks keluaran LLM tanpa crash bila cacat."""
    decoder = json.JSONDecoder()
    data: Any = None
    idx = raw.find("[")
    while idx != -1:
        try:
            kandidat, _ = decoder.raw_decode(raw, idx)
            if isinstance(kandidat, list):
                data = kandidat
                break
        except json.JSONDecodeError:
            pass
        idx = raw.find("[", idx + 1)

    if not isinstance(data, list):
        return []

    hasil: list[Saran] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            hasil.append(Saran.model_validate(item))
        except ValidationError:
            continue
    return hasil


def saring_saran(
    raw: str,
    jadwal: JadwalLike,
    peserta: int,
    lain: Sequence[JadwalLike],
    ruang: dict[str, Ruangan],
) -> list[Saran]:
    """Guardrail deterministik 4 lapis terhadap hasil saran LLM (AI suggests, Validator decides)."""
    durasi = hitung_durasi(jadwal)
    if durasi <= timedelta(0):
        return []

    valid: list[Saran] = []
    terlihat: set[tuple[int, time, str]] = set()
    lain_list = list(lain)

    for saran in parse_saran(raw):
        target_ruang = ruang.get(saran.ruangan)
        if target_ruang is None or target_ruang.kapasitas < peserta:
            continue

        jam_selesai = tambah_durasi(saran.jam_mulai, durasi)
        if jam_selesai is None:
            continue

        calon = JadwalSlot(
            id=-1,
            hari=saran.hari,
            jam_mulai=saran.jam_mulai,
            jam_selesai=jam_selesai,
            ruangan_kode=target_ruang.kode,
            dosen_id=jadwal.dosen_id,
        )
        konflik = detect_schedule_conflict([*lain_list, calon])
        if any(-1 in k.affected for k in konflik):
            continue

        kunci = (saran.hari, saran.jam_mulai, target_ruang.kode)
        if kunci in terlihat:
            continue
        terlihat.add(kunci)
        valid.append(saran)

        if len(valid) >= 3:
            break

    return valid


class ReschedulerService:
    """Mengorkestrasi pembuatan saran AI tervalidasi dan penerapan satu pintu ke SchedulingService."""

    def __init__(
        self,
        db: Session,
        llm: LLMClient | None = None,
        scheduling_service: SchedulingService | None = None,
    ) -> None:
        self.db = db
        self.llm: LLMClient = llm if llm is not None else get_llm_client()
        self.scheduling = (
            scheduling_service
            if scheduling_service is not None
            else SchedulingService(db)
        )

    def _muat_jadwal(self, jadwal_id: int) -> Jadwal:
        jadwal = self.db.execute(
            select(Jadwal)
            .options(joinedload(Jadwal.kelas), joinedload(Jadwal.ruangan))
            .where(Jadwal.id == jadwal_id)
        ).scalar_one_or_none()
        if jadwal is None:
            raise NotFoundError(f"Jadwal {jadwal_id} tidak ditemukan")
        return jadwal

    def saran_alternatif(self, jadwal_id: int) -> tuple[Jadwal, list[Saran]]:
        """Menghitung slot bebas, meminta peringkat LLM, lalu menyaring lewat guardrail 4 lapis."""
        jadwal = self._muat_jadwal(jadwal_id)
        peserta = hitung_peserta(self.db, jadwal.kelas)
        semua_jadwal = self.db.scalars(select(Jadwal).order_by(Jadwal.id)).all()
        semua_ruang = self.db.scalars(select(Ruangan).order_by(Ruangan.kode)).all()

        slots = hitung_slot_tersedia(jadwal, peserta, semua_jadwal, semua_ruang)
        if not slots:
            return jadwal, []

        prompt = bangun_prompt(jadwal, jadwal.kelas, peserta, slots)
        raw = self.llm.complete(prompt)
        lain = [item for item in semua_jadwal if item.id != jadwal.id]
        ruang_map = {r.kode: r for r in semua_ruang}
        return jadwal, saring_saran(raw, jadwal, peserta, lain, ruang_map)

    def apply_saran(self, jadwal_id: int, saran: Saran) -> Jadwal:
        """Menerapkan saran terpilih melalui SchedulingService.update (prinsip satu pintu)."""
        jadwal = self._muat_jadwal(jadwal_id)
        durasi = hitung_durasi(jadwal)
        jam_selesai = tambah_durasi(saran.jam_mulai, durasi)
        if jam_selesai is None:
            raise ScheduleValidationError(
                "Durasi jadwal tidak muat dimulai pada jam_mulai tersebut di hari yang sama"
            )

        payload = JadwalIn(
            kelas_id=jadwal.kelas_id,
            hari=saran.hari,
            jam_mulai=saran.jam_mulai,
            jam_selesai=jam_selesai,
            ruangan_kode=saran.ruangan,
            dosen_id=jadwal.dosen_id,
        )
        return self.scheduling.update(jadwal_id, payload)

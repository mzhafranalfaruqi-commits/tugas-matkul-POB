"""Helper murni pengekspor jadwal kuliah ke format iCalendar RFC 5545 (.ics)."""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone

from app.services.conflict import JadwalLike

DEFAULT_SEMESTER_START = date(2025, 9, 1)  # Senin minggu pertama perkuliahan 20251
DEFAULT_SEMESTER_END = date(2025, 12, 20)
WIB = timezone(timedelta(hours=7))
_CRLF = "\r\n"

_VTIMEZONE_ASIA_JAKARTA: tuple[str, ...] = (
    "BEGIN:VTIMEZONE",
    "TZID:Asia/Jakarta",
    "BEGIN:STANDARD",
    "DTSTART:19700101T000000",
    "TZOFFSETFROM:+0700",
    "TZOFFSETTO:+0700",
    "TZNAME:WIB",
    "END:STANDARD",
    "END:VTIMEZONE",
)


def _tanggal_pertama(awal: date, hari: int) -> date:
    """Mencari tanggal pertemuan pertama pada atau setelah `awal` untuk hari 1..6."""
    # date.weekday(): Senin=0 .. Minggu=6; hari jadwal: Senin=1 .. Sabtu=6.
    selisih = (hari - 1 - awal.weekday()) % 7
    return awal + timedelta(days=selisih)


def _escape_ics_text(teks: str) -> str:
    """Melakukan escaping karakter khusus teks sesuai RFC 5545 Section 3.3.11."""
    return (
        teks.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _format_local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ke_vevent(
    jadwal: JadwalLike,
    judul: str,
    awal: date = DEFAULT_SEMESTER_START,
    akhir: date = DEFAULT_SEMESTER_END,
    sequence: int = 0,
    dtstamp: datetime | None = None,
) -> str:
    """Mengubah satu objek jadwal kuliah menjadi blok VEVENT berakhiran CRLF."""
    tgl_awal = _tanggal_pertama(awal, jadwal.hari)
    mulai_dt = datetime.combine(tgl_awal, jadwal.jam_mulai)
    selesai_dt = datetime.combine(tgl_awal, jadwal.jam_selesai)
    until_wib = datetime.combine(akhir, time(23, 59, 59), tzinfo=WIB)
    stamp = dtstamp if dtstamp is not None else datetime.now(timezone.utc)

    lines = [
        "BEGIN:VEVENT",
        f"UID:jadwal-{jadwal.id}@sevima-mini",
        f"SEQUENCE:{sequence}",
        f"DTSTAMP:{_format_utc(stamp)}",
        f"DTSTART;TZID=Asia/Jakarta:{_format_local(mulai_dt)}",
        f"DTEND;TZID=Asia/Jakarta:{_format_local(selesai_dt)}",
        f"RRULE:FREQ=WEEKLY;UNTIL={_format_utc(until_wib)}",
        f"SUMMARY:{_escape_ics_text(judul)}",
        f"LOCATION:{_escape_ics_text(jadwal.ruangan_kode)}",
        "END:VEVENT",
    ]
    return _CRLF.join(lines)


def export_jadwal_ics(
    items: Sequence[tuple[JadwalLike, str, int]],
    awal: date = DEFAULT_SEMESTER_START,
    akhir: date = DEFAULT_SEMESTER_END,
    dtstamp: datetime | None = None,
) -> str:
    """Membungkus nol atau lebih VEVENT ke dalam dokumen VCALENDAR RFC 5545."""
    stamp = dtstamp if dtstamp is not None else datetime.now(timezone.utc)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SEVIMA-Mini//Jadwal//ID",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Jadwal Kuliah SEVIMA-Mini",
        "X-WR-TIMEZONE:Asia/Jakarta",
        *_VTIMEZONE_ASIA_JAKARTA,
    ]
    for jadwal, judul, seq in items:
        lines.append(
            ke_vevent(
                jadwal,
                judul=judul,
                awal=awal,
                akhir=akhir,
                sequence=seq,
                dtstamp=stamp,
            )
        )
    lines.append("END:VCALENDAR")
    return _CRLF.join(lines) + _CRLF

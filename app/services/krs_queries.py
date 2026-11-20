"""Query SQL kompleks untuk pemeriksaan prasyarat mata kuliah Modul KRS."""

from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_BOBOT_LULUS = 2.0

PRASYARAT_BELUM_LULUS_SQL = text(
    """
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
    ORDER BY mk.kode_mk
    """
)


def prasyarat_belum_lulus(
    db: Session, nim: str, kode_mk: str, semester: str
) -> list[str]:
    """Mengembalikan daftar nama mata kuliah prasyarat yang belum lulus (nilai >= C)."""
    rows = db.execute(
        PRASYARAT_BELUM_LULUS_SQL,
        {
            "nim": nim,
            "kode_mk": kode_mk,
            "semester": semester,
            "min_bobot": MIN_BOBOT_LULUS,
        },
    ).all()
    return [row[1] for row in rows]

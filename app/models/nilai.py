"""Model ORM SQLAlchemy 2.0 untuk audit trail perubahan nilai (grade_history)."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.pmb import Base

CREATE_VIEW_RIWAYAT_NILAI_SQL = """
CREATE VIEW v_riwayat_nilai AS
SELECT
    gh.id AS id,
    gh.grade_id AS grade_id,
    k.nim AS nim,
    k.semester AS semester,
    d.kode_mk AS kode_mk,
    d.kelas_id AS kelas_id,
    gh.old_value AS old_value,
    gh.new_value AS new_value,
    gh.changed_by AS pengubah_id,
    dsn.nama AS pengubah,
    gh.changed_at AS changed_at,
    gh.reason AS reason
FROM grade_history gh
JOIN krs_detail d ON d.id = gh.grade_id
JOIN krs k ON k.id = d.krs_id
JOIN dosen dsn ON dsn.id = gh.changed_by
"""

DROP_VIEW_RIWAYAT_NILAI_SQL = "DROP VIEW IF EXISTS v_riwayat_nilai"


class GradeHistory(Base):
    """Jejak audit append-only setiap pengisian maupun pembaruan nilai mahasiswa."""

    __tablename__ = "grade_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    grade_id: Mapped[int] = mapped_column(
        ForeignKey("krs_detail.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_value: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("skala_nilai.huruf"), default=None
    )
    new_value: Mapped[str] = mapped_column(
        String(2), ForeignKey("skala_nilai.huruf"), nullable=False
    )
    changed_by: Mapped[int] = mapped_column(
        ForeignKey("dosen.id"), nullable=False, index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reason: Mapped[str | None] = mapped_column(String(500), default=None)

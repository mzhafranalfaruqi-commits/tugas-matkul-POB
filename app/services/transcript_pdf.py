"""Renderer HTML (Jinja2) dan generator PDF Transkrip Akademik (ReportLab)."""

from datetime import date
from io import BytesIO
from pathlib import Path
import re
from typing import Protocol
from xml.sax.saxutils import escape as xml_escape

from jinja2 import Environment, FileSystemLoader, select_autoescape
from reportlab.graphics.shapes import Circle, Drawing, Polygon, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.gpa_calculator import TranskripAkademik

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

_BULAN_INDONESIA = (
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

_NAVY = colors.HexColor("#102a43")
_GOLD = colors.HexColor("#b48a2c")
_SLATE_BG = colors.HexColor("#f1f5f9")
_ALT_ROW = colors.HexColor("#f8fafc")
_BORDER = colors.HexColor("#cbd5e1")
_MUTED = colors.HexColor("#475569")


def format_tanggal_indonesia(tanggal: date) -> str:
    """Memformat objek date menjadi format resmi Indonesia tanpa ketergantungan locale OS."""
    return f"{tanggal.day:02d} {_BULAN_INDONESIA[tanggal.month]} {tanggal.year}"


def sanitize_filename_segment(value: str) -> str:
    """Membersihkan NIM atau segmen nama file agar aman di header Content-Disposition."""
    bersih = re.sub(r"[^A-Za-z0-9_-]", "_", value.strip())
    return bersih or "mahasiswa"


def render_transcript_html(transkrip: TranskripAkademik) -> str:
    """Merender halaman preview HTML transkrip akademik menggunakan template Jinja2."""
    template = _JINJA_ENV.get_template("transkrip.html")
    return template.render(
        transkrip=transkrip,
        tanggal_cetak_id=format_tanggal_indonesia(transkrip.tanggal_cetak),
    )


class TranscriptPdfRenderer(Protocol):
    """Port untuk generator biner PDF transkrip (siap diganti adaptor lain)."""

    def render_pdf(self, transkrip: TranskripAkademik) -> bytes:
        """Menghasilkan payload bytes PDF dari model domain TranskripAkademik."""
        ...


def _esc(value: object) -> str:
    """Melakukan XML escaping sebelum memasukkan teks dinamis ke ReportLab Paragraph."""
    return xml_escape(str(value))


def _buat_logo_universitas() -> Drawing:
    """Membangun logo vektor universitas (perisai emas & inisial SM)."""
    logo = Drawing(54, 54)
    logo.add(Circle(27, 27, 25, fillColor=_NAVY, strokeColor=_GOLD, strokeWidth=2.2))
    logo.add(
        Polygon(
            [27, 46, 43, 38, 43, 24, 27, 9, 11, 24, 11, 38],
            fillColor=None,
            strokeColor=_GOLD,
            strokeWidth=1.5,
        )
    )
    logo.add(
        String(
            27,
            22,
            "SM",
            textAnchor="middle",
            fontName="Times-Bold",
            fontSize=14,
            fillColor=colors.white,
        )
    )
    return logo


def _gambar_bingkai_halaman(canvas: Canvas, doc: SimpleDocTemplate) -> None:
    """Menggambar garis bingkai resmi dan nomor halaman pada setiap lembar PDF."""
    canvas.saveState()
    lebar, tinggi = A4
    canvas.setStrokeColor(_NAVY)
    canvas.setLineWidth(1.2)
    canvas.rect(10 * mm, 10 * mm, lebar - 20 * mm, tinggi - 20 * mm)
    canvas.setStrokeColor(_GOLD)
    canvas.setLineWidth(0.5)
    canvas.rect(11.5 * mm, 11.5 * mm, lebar - 23 * mm, tinggi - 23 * mm)

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(_MUTED)
    canvas.drawString(
        15 * mm,
        13 * mm,
        "Dokumen Transkrip Akademik Resmi - Universitas SEVIMA-Mini",
    )
    canvas.drawRightString(lebar - 15 * mm, 13 * mm, f"Halaman {doc.page}")
    canvas.restoreState()


class ReportLabTranscriptRenderer:
    """Implementasi TranscriptPdfRenderer menggunakan ReportLab murni (cross-platform)."""

    def render_pdf(self, transkrip: TranskripAkademik) -> bytes:
        """Menghasilkan dokumen PDF transkrip akademik lengkap beserta logo dan TTD Dekan."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=19 * mm,
            title=f"Transkrip Akademik - {transkrip.biodata.nim}",
            author="Universitas SEVIMA-Mini",
        )

        styles = getSampleStyleSheet()
        s_univ = ParagraphStyle(
            "UnivName",
            parent=styles["Normal"],
            fontName="Times-Bold",
            fontSize=14,
            leading=17,
            alignment=TA_CENTER,
            textColor=_NAVY,
        )
        s_sub = ParagraphStyle(
            "UnivSub",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            alignment=TA_CENTER,
            textColor=_MUTED,
        )
        s_title = ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName="Times-Bold",
            fontSize=15,
            leading=19,
            alignment=TA_CENTER,
            textColor=_NAVY,
            spaceBefore=3,
        )
        s_normal = ParagraphStyle(
            "BodyNormal",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11.5,
            textColor=colors.black,
        )
        s_normal_right = ParagraphStyle(
            "BodyRight",
            parent=s_normal,
            alignment=TA_RIGHT,
        )
        s_normal_center = ParagraphStyle(
            "BodyCenter",
            parent=s_normal,
            alignment=TA_CENTER,
        )
        s_th = ParagraphStyle(
            "TableHead",
            parent=s_normal,
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=colors.white,
        )
        s_th_center = ParagraphStyle("TableHeadCenter", parent=s_th, alignment=TA_CENTER)
        s_th_right = ParagraphStyle("TableHeadRight", parent=s_th, alignment=TA_RIGHT)
        s_sem = ParagraphStyle(
            "SemHeading",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=13,
            textColor=_NAVY,
            spaceBefore=6,
            spaceAfter=4,
        )
        s_sig = ParagraphStyle(
            "SigStyle",
            parent=s_normal,
            alignment=TA_LEFT,
            fontSize=8.8,
            leading=12.5,
        )

        usable_width = A4[0] - doc.leftMargin - doc.rightMargin
        story: list[object] = []

        # 1. Header: Logo Universitas + Kop + Judul TRANSKRIP AKADEMIK
        header_center = [
            Paragraph("UNIVERSITAS SEVIMA-MINI", s_univ),
            Paragraph(
                "Jl. Akademika No. 1, Kampus Terpadu Bandung | Sistem Informasi Akademik",
                s_sub,
            ),
            Paragraph("<u>TRANSKRIP AKADEMIK</u>", s_title),
        ]
        header_table = Table(
            [[_buat_logo_universitas(), header_center]],
            colWidths=[22 * mm, usable_width - 22 * mm],
        )
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(header_table)
        story.append(HRFlowable(width="100%", thickness=1.5, color=_NAVY, spaceAfter=8))

        # 2. Biodata Mahasiswa
        bio = transkrip.biodata
        bio_rows = [
            [
                Paragraph("<b>NIM</b>", s_normal),
                Paragraph(f": <b>{_esc(bio.nim)}</b>", s_normal),
                Paragraph("<b>Program Studi</b>", s_normal),
                Paragraph(f": {_esc(bio.program_studi)}", s_normal),
            ],
            [
                Paragraph("<b>Nama</b>", s_normal),
                Paragraph(f": <b>{_esc(bio.nama)}</b>", s_normal),
                Paragraph("<b>Fakultas</b>", s_normal),
                Paragraph(f": {_esc(bio.fakultas)}", s_normal),
            ],
            [
                Paragraph("<b>Angkatan</b>", s_normal),
                Paragraph(f": {_esc(bio.angkatan)}", s_normal),
                Paragraph("", s_normal),
                Paragraph("", s_normal),
            ],
        ]
        bio_table = Table(
            bio_rows,
            colWidths=[23 * mm, 63 * mm, 27 * mm, usable_width - 113 * mm],
        )
        bio_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _ALT_ROW),
                    ("BOX", (0, 0), (-1, -1), 0.6, _BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(bio_table)
        story.append(Spacer(1, 7))

        # 3. Tabel Mata Kuliah per Semester
        if not transkrip.semesters:
            story.append(
                Paragraph(
                    "Belum ada mata kuliah yang memiliki nilai.",
                    s_normal_center,
                )
            )
            story.append(Spacer(1, 10))
        else:
            col_widths = [24 * mm, usable_width - 80 * mm, 16 * mm, 18 * mm, 22 * mm]
            for sem in transkrip.semesters:
                story.append(
                    Paragraph(
                        f"Semester {_esc(sem.semester)} - {_esc(sem.label_semester)}",
                        s_sem,
                    )
                )
                rows: list[list[Paragraph]] = [
                    [
                        Paragraph("Kode MK", s_th),
                        Paragraph("Nama MK", s_th),
                        Paragraph("SKS", s_th_center),
                        Paragraph("Nilai", s_th_center),
                        Paragraph("Mutu", s_th_right),
                    ]
                ]
                for item in sem.items:
                    ket = ""
                    if not item.lulus:
                        ket = " <i>(Tidak Lulus)</i>"
                    elif not item.dipakai_ipk:
                        ket = " <i>(Diulang)</i>"
                    rows.append(
                        [
                            Paragraph(f"<b>{_esc(item.kode_mk)}</b>", s_normal),
                            Paragraph(f"{_esc(item.nama_mk)}{ket}", s_normal),
                            Paragraph(str(item.sks), s_normal_center),
                            Paragraph(f"<b>{_esc(item.huruf)}</b>", s_normal_center),
                            Paragraph(str(item.mutu), s_normal_right),
                        ]
                    )
                rows.append(
                    [
                        Paragraph("", s_normal),
                        Paragraph(
                            f"<b>Rekap Semester {_esc(sem.semester)} (IPS: {_esc(sem.ips)})</b>",
                            s_normal,
                        ),
                        Paragraph(f"<b>{sem.total_sks}</b>", s_normal_center),
                        Paragraph("-", s_normal_center),
                        Paragraph(f"<b>{_esc(sem.total_mutu)}</b>", s_normal_right),
                    ]
                )

                sem_table = Table(rows, colWidths=col_widths, repeatRows=1)
                last_row = len(rows) - 1
                sem_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                            ("BACKGROUND", (0, last_row), (-1, last_row), _SLATE_BG),
                            ("ROWBACKGROUNDS", (0, 1), (-1, last_row - 1), [colors.white, _ALT_ROW]),
                            ("GRID", (0, 0), (-1, -1), 0.45, _BORDER),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ]
                    )
                )
                story.append(sem_table)
                story.append(Spacer(1, 5))

        # 4. Ringkasan IPK, Total SKS, Predikat, & Blok TTD Dekan (tidak terpotong halaman)
        tanggal_str = format_tanggal_indonesia(transkrip.tanggal_cetak)
        summary_rows = [
            [
                Paragraph("<b>Total SKS Lulus</b>", s_normal),
                Paragraph(f": <b>{transkrip.total_sks_lulus} SKS</b>", s_normal),
            ],
            [
                Paragraph("Total SKS Ditempuh", s_normal),
                Paragraph(f": {transkrip.total_sks_tempuh} SKS", s_normal),
            ],
            [
                Paragraph("Total Mutu", s_normal),
                Paragraph(f": {_esc(transkrip.total_mutu_lulus)}", s_normal),
            ],
            [
                Paragraph("<b>IPK</b>", s_normal),
                Paragraph(f": <b>{_esc(transkrip.ipk)}</b>", s_normal),
            ],
            [
                Paragraph("<b>Predikat Kelulusan</b>", s_normal),
                Paragraph(f": <b>{_esc(transkrip.predikat)}</b>", s_normal),
            ],
        ]
        summary_box = Table(summary_rows, colWidths=[38 * mm, 48 * mm])
        summary_box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _ALT_ROW),
                    ("BOX", (0, 0), (-1, -1), 0.9, _NAVY),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, _BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        ttd_blok = Paragraph(
            "<br/>".join(
                [
                    f"Bandung, {_esc(tanggal_str)}",
                    f"Dekan {_esc(bio.fakultas)},",
                    "",
                    "",
                    "<i>[TTD Dekan / Cap Resmi]</i>",
                    "",
                    "<b>Prof. Dr. Ir. Hendrawan Pratama, M.T.</b>",
                    "NIP. 196805121993031002",
                ]
            ),
            s_sig,
        )

        footer_grid = Table(
            [[summary_box, ttd_blok]],
            colWidths=[92 * mm, usable_width - 92 * mm],
        )
        footer_grid.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        story.append(
            KeepTogether(
                [
                    HRFlowable(width="100%", thickness=1.0, color=_NAVY, spaceBefore=6),
                    footer_grid,
                ]
            )
        )

        doc.build(
            story,
            onFirstPage=_gambar_bingkai_halaman,
            onLaterPages=_gambar_bingkai_halaman,
        )
        return buffer.getvalue()


def get_transcript_pdf_renderer() -> TranscriptPdfRenderer:
    """Provider DI FastAPI untuk renderer PDF Transkrip Akademik."""
    return ReportLabTranscriptRenderer()

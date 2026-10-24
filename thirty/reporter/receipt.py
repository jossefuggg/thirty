"""PDF receipt builder for the reporter Front_Door (Requirement 7).

``build_receipt(ref_number, summary, reporter_type, language) -> bytes`` renders
a one-page PDF receipt for a submitted report and returns it as raw PDF bytes.
It mirrors ``vigil.py``'s fpdf2 setup: the bundled ``DejaVuSans`` /
``DejaVuSans-Bold`` fonts from ``thirty/fonts`` (Latin-script, covering
English/Spanish/Portuguese/Haitian-Creole), falling back to the built-in
``Helvetica`` if a font file is missing. fpdf2 being absent degrades gracefully
to a tiny plain-bytes fallback rather than crashing the flow.

This function is pure-ish: it takes data in and returns bytes. It does NOT write
files (the route persists the bytes to ``VIGIL_DIR/reports/receipts/``) and it
makes NO network calls.

``summary`` shape
-----------------
``summary`` is an ordered sequence of ``(label, value)`` pairs, e.g.::

    [("What happened", "The mask stopped sealing overnight."),
     ("Device brand name", "AeroFlow A200 CPAP"),
     ("Lot or serial number", "UNKNOWN"),
     ("Date of the event", "2026-10-01")]

Each ``label`` is a plain-words field name and each ``value`` is the reporter's
answer. The system-wide ``UNKNOWN`` sentinel is rendered to the reader as the
plain words "not known" (never the raw sentinel). A plain ``dict`` is also
accepted and iterated in insertion order. The Front_Door (task 7.3) builds this
summary; for ``patient_family`` reporters it must contain no regulatory-citation
jargon (Requirement 7.5).
"""
import os
from datetime import date

from .. import config

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except Exception:  # fpdf2 optional — never crash the reporter flow
    FPDF = None

# The system-wide "value not known" sentinel (see thirty/sample_data.py, base.py).
UNKNOWN = "UNKNOWN"
# Plain-words rendering of UNKNOWN shown to the reporter (Requirement 7.2 / 5.2).
NOT_KNOWN = "not known"

# Bundled fonts live in thirty/fonts (relative to CODE_DIR); a system DejaVu
# install is accepted as a fallback, mirroring vigil.py's FONT_DIR resolution.
FONT_DIR = next(
    (d for d in (os.path.join(config.CODE_DIR, "thirty", "fonts"),
                 "/usr/share/fonts/truetype/dejavu")
     if os.path.exists(os.path.join(d, "DejaVuSans.ttf"))),
    os.path.join(config.CODE_DIR, "thirty", "fonts"),
)

# The exact line required for user-facility (nurse/clinician) receipts (R7.4).
FACILITY_LINE = "Copy for your facility's records (user facility reporting, 21 CFR 803.30)"


def _display(value):
    """Render a stored answer for the reader: UNKNOWN -> "not known"."""
    if value is None:
        return NOT_KNOWN
    text = str(value).strip()
    if text == "" or text == UNKNOWN:
        return NOT_KNOWN
    return text


def _pairs(summary):
    """Normalise the summary arg to an ordered list of (label, value) pairs."""
    if summary is None:
        return []
    if isinstance(summary, dict):
        return list(summary.items())
    return [(label, value) for label, value in summary]


def build_receipt(ref_number, summary, reporter_type, language="en"):
    """Build the PDF receipt for a submitted report and return it as bytes.

    Args:
        ref_number: the Reference_Number (``REP-xxxxxxxx``) to show prominently.
        summary: ordered ``(label, value)`` pairs (or a dict); see module docstring.
        reporter_type: ``nurse_clinician`` | ``patient_family`` | ``company_staff``.
        language: the reporter's language code (``en`` | ``es`` | ``pt`` | ``ht``);
            affects only which bundled Latin-script glyphs are exercised.

    Returns:
        bytes: the PDF document. Starts with the ``%PDF`` magic when fpdf2 is
        available; a minimal plain-bytes fallback is returned if fpdf2 is absent.
    """
    ref = str(ref_number or "").strip()
    pairs = _pairs(summary)
    submitted = date.today().isoformat()
    is_facility = reporter_type == "nurse_clinician"

    if FPDF is None:
        return _fallback_bytes(ref, pairs, submitted, is_facility)

    pdf = FPDF(format="Letter")
    # Register the bundled DejaVu fonts (Latin-script; covers en/es/pt/ht accents),
    # mirroring vigil.py's setup. They are used for any text a core font cannot
    # encode (e.g. accented Spanish/Portuguese/Haitian-Creole glyphs). The built-in
    # Helvetica is the fallback and is used for plain Latin-1 text so the content
    # stream stays byte-searchable.
    have_dejavu = os.path.exists(f"{FONT_DIR}/DejaVuSans.ttf")
    if have_dejavu:
        pdf.add_font("DejaVu", "", f"{FONT_DIR}/DejaVuSans.ttf")
        pdf.add_font("DejaVu", "B", f"{FONT_DIR}/DejaVuSans-Bold.ttf")
    # Leave the content stream uncompressed so the rendered Latin text (reference
    # number, facility line, summary) is accessible to downstream readers.
    pdf.set_compression(False)
    pdf.set_margins(16, 16, 16)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    def font_for(text, prefer_dejavu=False):
        """Pick Helvetica for plain Latin-1 text (keeps it text-accessible);
        fall back to the embedded DejaVu font for anything it cannot encode."""
        if prefer_dejavu and have_dejavu:
            return "DejaVu"
        try:
            str(text).encode("latin-1")
            return "Helvetica"
        except (UnicodeEncodeError, AttributeError):
            return "DejaVu" if have_dejavu else "Helvetica"

    def line(text, size, style="", height=6.0, color=0, multi=False):
        pdf.set_font(font_for(text), style, size)
        pdf.set_text_color(color)
        if multi:
            pdf.multi_cell(0, height, str(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.cell(0, height, str(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0)

    # Title.
    line("Report received", 16, "B", height=9)
    line("Thank you for reporting a device problem. This is your copy.", 10, color=90)
    pdf.ln(3)

    # Reference number, prominently.
    line("Reference number", 9, color=90, height=5)
    line(ref or NOT_KNOWN, 20, "B", height=10)
    pdf.ln(2)

    # Submission date.
    line(f"Submitted on {submitted}", 10)
    pdf.ln(4)

    # Plain-words summary of the submitted answers.
    line("What you told us", 12, "B", height=7)
    pdf.ln(1)
    for label, value in pairs:
        line(str(label), 10, "B", height=5.5, multi=True)
        line(_display(value), 10, height=5.5, color=40, multi=True)
        pdf.ln(1.5)

    # Facility-copy line for nurse/clinician reporters only (R7.4). Patient/family
    # receipts carry no regulatory-citation jargon (R7.5) — the summary pairs the
    # Front_Door supplies for patient/family are already free of citations.
    if is_facility:
        pdf.ln(3)
        line(FACILITY_LINE, 9, color=90, height=5, multi=True)

    out = pdf.output()
    return bytes(out)


def _fallback_bytes(ref, pairs, submitted, is_facility):
    """Minimal receipt when fpdf2 is unavailable — degrade, never crash.

    Produces a valid single-page PDF containing the reference number, summary,
    and (for nurse/clinician) the facility line, so downstream byte checks and
    the %PDF prefix still hold without the fpdf2 dependency.
    """
    lines = ["Report received", "", f"Reference number: {ref or NOT_KNOWN}",
             f"Submitted on {submitted}", "", "What you told us:"]
    for label, value in pairs:
        lines.append(f"- {label}: {_display(value)}")
    if is_facility:
        lines += ["", FACILITY_LINE]

    # Hand-assemble a tiny one-page PDF so the output is still a real PDF file.
    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    text_ops = ["BT", "/F1 11 Tf", "16 760 Td", "14 TL"]
    for line in lines:
        text_ops.append(f"({esc(line)}) Tj")
        text_ops.append("T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("latin-1", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(objs) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF").encode()
    return bytes(pdf)

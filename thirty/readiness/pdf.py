"""Device readiness PDF export (fpdf2), mirroring ``vigil.render_mdr_pdf``.

Graceful degradation: if ``fpdf2`` is not installed, :func:`available` returns
False and :func:`build_pdf` returns ``None`` so the route can omit the button
(Requirement 9.3). The PDF renders strictly from the engine result, the loaded
signals, and the rules' day-one checklist — nothing is invented, and the
citations/sources printed are exactly those shown on the page (Requirement 9.2).
"""
import datetime as dt
import io
import os

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from fpdf.fonts import FontFace
except Exception:  # fpdf2 absent -> degrade gracefully
    FPDF = None

# Bundled DejaVu fonts (same as vigil.py); system DejaVu as a fallback.
_FONT_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the thirty package
FONT_DIR = next(
    (d for d in (os.path.join(_FONT_BASE, "fonts"), "/usr/share/fonts/truetype/dejavu")
     if os.path.exists(os.path.join(d, "DejaVuSans.ttf"))),
    os.path.join(_FONT_BASE, "fonts"),
)


def available():
    """True when ``fpdf2`` is importable and a PDF can be built."""
    return FPDF is not None


def _cite_line(c):
    """One-line citation string: label (+ date) (+ url)."""
    parts = [c.get("label", c.get("key", ""))]
    if c.get("date"):
        parts.append(f"({c['date']})")
    if c.get("url"):
        parts.append(c["url"])
    return " ".join(parts)


def build_pdf(result, signals, checklist, *, product_code=None):
    """Build the readiness result as a PDF and return the bytes (or ``None``).

    Returns ``None`` when ``fpdf2`` is unavailable (caller hides the button).
    ``result`` is a :func:`thirty.readiness.engine.categorize` result,
    ``signals`` a :func:`thirty.readiness.openfda.load_signals` result, and
    ``checklist`` a :func:`thirty.readiness.engine.day_one_checklist` list.

    Sections: disclaimer (top); category result + drivers + paths; signals
    summary with the incomplete-data notice; the day-one checklist with
    citations and Thirty tags; a "Sources" block listing every citation and the
    openFDA query URLs/fetch dates used; disclaimer (bottom).
    """
    if FPDF is None:
        return None

    result = result or {}
    signals = signals or {}
    checklist = checklist or []
    disclaimer = result.get("disclaimer", "")

    pdf = FPDF(format="Letter")
    if os.path.exists(f"{FONT_DIR}/DejaVuSans.ttf"):
        pdf.add_font("DejaVu", "", f"{FONT_DIR}/DejaVuSans.ttf")
        pdf.add_font("DejaVu", "B", f"{FONT_DIR}/DejaVuSans-Bold.ttf")
        FONT = "DejaVu"
    else:
        FONT = "Helvetica"
    pdf.set_margins(14, 14, 14)
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()

    def h(text, size=12):
        pdf.set_font(FONT, "B", size)
        pdf.set_text_color(0)
        pdf.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

    def p(text, size=9, color=0):
        pdf.set_font(FONT, "", size)
        pdf.set_text_color(color)
        pdf.multi_cell(0, 4.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def disclaimer_box():
        pdf.set_font(FONT, "B", 8)
        pdf.set_text_color(150, 60, 40)
        pdf.multi_cell(0, 4.2, disclaimer, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0)
        pdf.ln(2)

    # Title + disclaimer (top).
    pdf.set_font(FONT, "B", 16)
    pdf.cell(0, 8, "Device readiness", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(FONT, "", 8)
    pdf.set_text_color(90)
    pdf.cell(0, 5, f"Generated {dt.date.today().isoformat()} - Thirty", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0)
    pdf.ln(2)
    disclaimer_box()

    # Category result.
    h(result.get("label", ""))
    p(result.get("headline", ""))
    if result.get("drivers"):
        pdf.ln(1)
        p("What drove this:", size=9)
        for d in result["drivers"]:
            p(f"  - {d}", size=9, color=60)
    if result.get("paths"):
        pdf.ln(1)
        for path in result["paths"]:
            p(f"  Path: {path.get('name', '')} - {path.get('when', '')}", size=9, color=60)
    pdf.ln(2)

    # Signals summary.
    rules_notice = _signals_notice()
    h(f"What goes wrong with devices like this{(' (' + product_code + ')') if product_code else ''}", size=12)
    p(rules_notice, size=8, color=90)
    pdf.ln(1)
    if signals.get("has_data"):
        _pairs(pdf, FONT, "Top device problems", signals.get("device_problems"))
        _pairs(pdf, FONT, "Top patient problems", signals.get("patient_problems"))
        yrs = signals.get("reports_per_year") or []
        if yrs:
            p("Reports per year: " + ", ".join(f"{y['year']}: {y['count']}" for y in yrs), size=9)
        recalls = signals.get("recalls") or []
        if recalls:
            p("Recent recalls:", size=9)
            for r in recalls[:5]:
                p(f"  - {r.get('date', '')}: {r.get('reason', '')}", size=8, color=60)
    else:
        p("No data available for this product code.", size=9, color=90)
    pdf.ln(2)

    # Day-one checklist.
    h("What starts on day one as a device manufacturer", size=12)
    for item in checklist:
        tag = f"  [{item['thirty_label']}]" if item.get("thirty_label") else ""
        p(f"- {item.get('text', '')}{tag}", size=9)
        for c in item.get("citations", []):
            p(f"    {_cite_line(c)}", size=7, color=90)
    pdf.ln(2)

    # Sources.
    h("Sources", size=11)
    seen = set()
    for c in result.get("citations", []):
        line = _cite_line(c)
        if line not in seen:
            seen.add(line)
            p(f"- {line}", size=7, color=90)
    for item in checklist:
        for c in item.get("citations", []):
            line = _cite_line(c)
            if line not in seen:
                seen.add(line)
                p(f"- {line}", size=7, color=90)
    fetched = signals.get("fetched") or {}
    if signals.get("has_data") or any(fetched.values()):
        p("- openFDA device adverse-event API https://api.fda.gov/device/event.json"
          + (f" (fetched {fetched.get('event')})" if fetched.get("event") else ""), size=7, color=90)
        p("- openFDA device recall API https://api.fda.gov/device/recall.json"
          + (f" (fetched {fetched.get('recall')})" if fetched.get("recall") else ""), size=7, color=90)
    pdf.ln(2)

    # Disclaimer (bottom).
    disclaimer_box()

    out = pdf.output()
    return bytes(out) if not isinstance(out, (bytes, bytearray)) else bytes(out)


def _signals_notice():
    """The exact incomplete-data notice from the rules (safe default if unreadable)."""
    try:
        from .engine import load_rules
        return load_rules().get("incomplete_data_notice", "")
    except Exception:
        return ("Patterns from public FDA reports for similar devices. Reports are incomplete and have "
                "no usage denominator, so counts are not failure rates. Use this to decide where to look "
                "first, not to predict your device's faults.")


def _pairs(pdf, FONT, title, items):
    """Render a '{title}: term (count), ...' line for a term/count list."""
    items = items or []
    if not items:
        return
    from fpdf.enums import XPos, YPos
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(0)
    line = title + ": " + ", ".join(f"{i.get('term', '')} ({i.get('count', 0)})" for i in items[:6])
    pdf.multi_cell(0, 4.6, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

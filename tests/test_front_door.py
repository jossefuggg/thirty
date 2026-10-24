"""Reporter Front_Door tests. QR generator: produces an inline SVG and rejects empty input."""
import os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty.reporter.qr import qr_svg, QRError  # noqa: E402


def test_qr_svg_renders_inline_svg_for_public_report_url():
    # ~60-char public demo URL (https://thirty-demo.onrender.com/report/<slug>).
    url = "https://thirty-demo.onrender.com/report/AF-northwind-medical"
    assert len(url) >= 60
    svg = qr_svg(url)
    # We do not decode the QR; we assert it is a non-trivial inline <svg> string.
    assert "<svg" in svg
    assert svg.rstrip().endswith("</svg>")
    assert len(svg) > 200


def test_qr_svg_empty_input_raises_qr_error():
    with pytest.raises(QRError):
        qr_svg("")


# --- PDF receipt builder (Requirement 7) ---------------------------------
from thirty.reporter.receipt import build_receipt, FACILITY_LINE  # noqa: E402

_SUMMARY = [
    ("What happened", "The mask stopped sealing overnight."),
    ("Device brand name", "AeroFlow A200 CPAP"),
    ("Lot or serial number", "UNKNOWN"),
    ("Date of the event", "2026-10-01"),
]


def test_build_receipt_returns_pdf_bytes():
    pdf = build_receipt("REP-12ab34cd", _SUMMARY, "nurse_clinician", "en")
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 0
    assert pdf[:4] == b"%PDF"


def test_nurse_clinician_receipt_includes_facility_reporting_line():
    # R7.4: the user-facility copy carries the exact 21 CFR 803.30 citation.
    assert "21 CFR 803.30" in FACILITY_LINE
    pdf = build_receipt("REP-12ab34cd", _SUMMARY, "nurse_clinician", "en")
    # The rendered Latin text sits in an uncompressed content stream; PDF string
    # escaping touches "(" / ")" but leaves the citation itself verbatim.
    assert b"21 CFR 803.30" in pdf


def test_patient_family_receipt_omits_regulatory_citations():
    # R7.5: patient/family receipts carry no regulatory citation jargon.
    pdf = build_receipt("REP-99zz88yy", _SUMMARY, "patient_family", "en")
    assert pdf[:4] == b"%PDF"
    assert b"21 CFR" not in pdf
    assert b"803.30" not in pdf

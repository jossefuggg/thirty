"""Deterministic parts of the pipeline (rules, deadlines, PDF draft); nothing here calls a model."""
import datetime as dt, importlib.util, os, subprocess, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def vigil(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("vigil_mod", os.path.join(ROOT, "vigil.py"))
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
    v.REPORTS = str(tmp_path_factory.mktemp("reports"))
    return v


def test_red_flags_are_whole_words(vigil):
    hits = dict(vigil.red_flag_hits("Every mother knows the ER is busy; the device exploded and the patient died."))
    assert "ER" in hits and "explod" in hits and "died" in hits
    assert "icu" not in hits


def test_priority_levels(vigil):
    score, level, _ = vigil.priority({"text": "The patient died after the device caught fire", "event_type": "Death", "outcomes": "Death"})
    assert level == "URGENT" and score >= 15
    _, level, _ = vigil.priority({"text": "The screen flickers sometimes", "event_type": "", "outcomes": ""})
    assert level == "NORMAL"


def test_deadlines(vigil):
    assert vigil.deadline_days({"text": "smoke came out of the unit"}, {"decision": "REPORTABLE"}) == 5
    assert vigil.deadline_days({"text": "foam dust"}, {"decision": "REPORTABLE", "remedial_action_needed": "true"}) == 5
    assert vigil.deadline_days({"text": "foam dust"}, {"decision": "REPORTABLE"}) == 30
    assert vigil.deadline_days({"text": "smoke"}, {"decision": "NOT_REPORTABLE"}) is None
    # 5 work days from a Friday lands on the next Friday; 30 calendar days is plain arithmetic
    assert vigil.add_deadline(dt.date(2026, 10, 2), 5) == dt.date(2026, 10, 9)
    assert vigil.add_deadline(dt.date(2026, 10, 2), 30) == dt.date(2026, 11, 1)


def test_failure_mode_and_family(vigil):
    assert vigil.failure_mode("", "black particles in the tubing") == "material degradation/particles"
    assert vigil.failure_mode("Overheating of Device", "") == "electrical/shock/fire"
    assert vigil.device_family("AeroFlow A200 CPAP") == "AEROFLOW"


@pytest.mark.skipif(not os.path.exists("/usr/bin/pdftotext"), reason="pdftotext not installed")
def test_pdf_draft_is_branded(vigil):
    if vigil.FPDF is None:
        pytest.skip("fpdf2 not installed")
    c = dict(id="NW-1", text="Device stopped delivering pressure.", device="AeroFlow A200 CPAP", manufacturer="Northwind Medical",
             event_date="", received="20261001")
    row = dict(decision="REPORTABLE", category="MALFUNCTION", confidence=80, priority="HIGH", deadline_days=30, due_date="2026-10-31", missing="")
    path = vigil.render_mdr_pdf(c, row, {"B5_event_description": c["text"], "B4_date_of_report": "2026-10-01", "G7_report_type": "30-day"})
    text = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True).stdout
    assert "THIRTY" in text and "Thirty decision" in text and "Vigil" not in text

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

# =========================================================================
# Route unit/integration tests (task 7.4).
#
# The report/*.html templates do not exist yet (task 9 creates them), so these
# tests MUST NOT depend on real template rendering. We monkeypatch
# ``thirty.reporter.front_door.render_template`` with a fake that records each
# (template_name, context) pair and returns a short string, then assert on the
# recorded template name + context values (this tests the route logic, which is
# what 7.4 covers). Submission goes through the REAL intake.submit map / validate
# / dedupe / index path, but the model/pipeline call and background worker are
# neutralised and storage is redirected to a tmp dir, mirroring the isolation in
# tests/test_front_door_properties.py (Property 3).
#
# Each test builds its own fresh Flask app (never imports the console app.py),
# points VIGIL_DIR + intake storage at a tmp dir, and restores every global it
# touches, so every test is hermetic.
# =========================================================================
import contextlib  # noqa: E402

import flask  # noqa: E402

import intake as _intake  # noqa: E402  (importing triggers `import vigil`, fine offline)
from thirty import config as _config  # noqa: E402
from thirty import agents as _agents  # noqa: E402
from thirty.reporter import front_door as _fd  # noqa: E402
from thirty.reporter import interview  # noqa: E402


class _RenderRecorder:
    """A fake render_template that records (template, context) and returns a stub.

    Installed onto ``front_door.render_template`` so routes render without the
    report/*.html templates existing. ``calls`` is the ordered list of
    ``(template_name, context_dict)`` the routes asked to render; ``last`` is a
    convenience for the final render.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, template_name, **context):
        self.calls.append((template_name, dict(context)))
        return f"[rendered {template_name}]"

    @property
    def last(self):
        return self.calls[-1] if self.calls else (None, None)

    def names(self):
        return [name for name, _ in self.calls]


@contextlib.contextmanager
def _front_door_env(tmp_path, agent_env=None):
    """A hermetic Front_Door test environment.

    Yields ``(client, recorder)`` where ``client`` is a Flask test client for a
    fresh app with only the reporter blueprint mounted, and ``recorder`` is the
    :class:`_RenderRecorder` capturing every route render.

    Isolation performed (all restored on exit):

    - ``VIGIL_DIR`` -> ``tmp_path`` so sessions/receipts land under the tmp dir;
    - ``front_door.render_template`` -> the recorder (no real templates needed);
    - ``intake.INTAKE/RAW/INDEX`` -> tmp paths; ``intake.vigil.process`` and
      ``intake.start_worker`` -> no-ops, so ``submit()`` maps/validates/dedupes/
      indexes without a background thread or a model call;
    - ``agent_env`` (e.g. ``"none"``) forces ``THIRTY_AGENT`` for the body and the
      cached agent registry is reset so ``get_agent()`` re-resolves to it; both
      the env var and the registry are restored on exit.
    """
    saved_dir = os.environ.get("VIGIL_DIR")
    saved_agent_env = os.environ.get("THIRTY_AGENT")
    saved = {
        "render": _fd.render_template,
        "INTAKE": _intake.INTAKE,
        "RAW": _intake.RAW,
        "INDEX": _intake.INDEX,
        "process": _intake.vigil.process,
        "start_worker": _intake.start_worker,
    }
    recorder = _RenderRecorder()
    data_dir = str(tmp_path)
    try:
        os.environ["VIGIL_DIR"] = data_dir
        _fd.render_template = recorder
        _intake.INTAKE = os.path.join(data_dir, "intake")
        _intake.RAW = os.path.join(_intake.INTAKE, "raw")
        _intake.INDEX = os.path.join(_intake.INTAKE, "index.csv")
        _intake.vigil.process = lambda *a, **k: None
        _intake.start_worker = lambda *a, **k: None
        if agent_env is not None:
            os.environ["THIRTY_AGENT"] = agent_env
            _agents.set_agent(None)  # drop any cached agent so get_agent() re-resolves

        app = flask.Flask(__name__)
        app.config["TESTING"] = True
        _fd.init_app(app)
        yield app.test_client(), recorder
    finally:
        if saved_dir is None:
            os.environ.pop("VIGIL_DIR", None)
        else:
            os.environ["VIGIL_DIR"] = saved_dir
        if saved_agent_env is None:
            os.environ.pop("THIRTY_AGENT", None)
        else:
            os.environ["THIRTY_AGENT"] = saved_agent_env
        _fd.render_template = saved["render"]
        _intake.INTAKE = saved["INTAKE"]
        _intake.RAW = saved["RAW"]
        _intake.INDEX = saved["INDEX"]
        _intake.vigil.process = saved["process"]
        _intake.start_worker = saved["start_worker"]
        if agent_env is not None:
            _agents.set_agent(None)  # reset so other tests re-resolve the configured agent


def _index_rows_for_ref(ref):
    """All rows in the current ``intake.INDEX`` whose vigil_id == ``ref``."""
    import csv as _csv
    if not os.path.exists(_intake.INDEX):
        return []
    with open(_intake.INDEX, encoding="utf-8") as f:
        return [r for r in _csv.DictReader(f) if r["vigil_id"] == ref]


def _walk_interview_to_review(client, recorder):
    """Drive GET /interview + POST /answer until redirected to /report/review.

    Gives a non-empty description for ``event_description`` and answers the
    patient_outcome choice; everything else is answered "I don't know" so an
    UNKNOWN shows up on the review screen. Returns when the interview redirects
    to the review route (or after a generous safety bound). Mirrors a real
    reporter walking the adaptive loop with the sample agent.
    """
    for _ in range(interview.QUESTION_CAP + 3):
        r = client.get("/report/interview")
        if r.status_code == 302 and "/report/review" in r.headers["Location"]:
            return
        assert r.status_code == 200
        _, ctx = recorder.last
        field = ctx.get("field")
        if field == "event_description":
            form = {"answer": "The mask stopped sealing overnight and the alarm failed."}
        elif field == "patient_outcome":
            form = {"answer": "injury"}
        else:
            form = {"idk": "1"}
        client.post("/report/answer", data=form)
    # Final nudge: if the cap/complete has been reached, the next GET redirects.
    r = client.get("/report/interview")
    assert r.status_code == 302 and "/report/review" in r.headers["Location"]


# --- landing: languages, reporter types, device pre-fill (R1.3, R1.4, R2.1) ---
def test_get_report_landing_offers_four_languages_and_three_reporter_types(tmp_path):
    with _front_door_env(tmp_path) as (client, recorder):
        r = client.get("/report")
        assert r.status_code == 200
        name, ctx = recorder.last
        assert name == _fd.TPL_LANDING
        # Exactly the 4 interview languages (Requirement 2.1).
        assert [code for code, _ in ctx["languages"]] == ["en", "es", "pt", "ht"]
        assert len(ctx["languages"]) == 4
        # Exactly the 3 reporter types (Requirement 3.1 context for 2.1/3.4).
        assert [code for code, _ in ctx["reporter_types"]] == [
            "nurse_clinician",
            "patient_family",
            "company_staff",
        ]
        assert len(ctx["reporter_types"]) == 3
        # A bare /report starts device-less.
        assert ctx["device"] is None


def test_get_report_known_slug_prefills_device(tmp_path):
    # Requirement 1.3: a slug matching a catalogue key pre-fills that device.
    with _front_door_env(tmp_path) as (client, recorder):
        r = client.get("/report/AF")
        assert r.status_code == 200
        name, ctx = recorder.last
        assert name == _fd.TPL_LANDING
        assert ctx["device"] is not None
        assert ctx["device"]["key"] == "AF"
        assert ctx["unknown_slug"] is False
        # The reporter can still change it: the full device picker is offered.
        assert any(d["key"] == "AF" for d in ctx["devices"])


def test_get_report_unknown_slug_prompts_device_selection(tmp_path):
    # Requirement 1.4: an unknown slug serves the landing page with no pre-fill
    # and prompts the reporter to pick a device.
    with _front_door_env(tmp_path) as (client, recorder):
        r = client.get("/report/BOGUS")
        assert r.status_code == 200
        name, ctx = recorder.last
        assert name == _fd.TPL_LANDING
        assert ctx["device"] is None
        assert ctx["unknown_slug"] is True


# --- start: reporter-type gate (R3.4) --------------------------------------
def test_post_start_without_reporter_type_rerenders_landing_with_error(tmp_path):
    # Requirement 3.4 / 2.2: reporter-type is required; the start is refused and
    # the landing page is re-rendered with the error, no interview begun.
    with _front_door_env(tmp_path) as (client, recorder):
        r = client.post("/report/start", data={"language": "en", "device": "AF"})
        assert r.status_code == 200  # re-render, not a redirect
        name, ctx = recorder.last
        assert name == _fd.TPL_LANDING
        assert ctx["error"] == "reporter_type_required"


def test_post_start_with_reporter_type_redirects_to_interview(tmp_path):
    with _front_door_env(tmp_path) as (client, recorder):
        r = client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        assert r.status_code == 302
        assert "/report/interview" in r.headers["Location"]


# --- happy-path walk to review (R5.2) --------------------------------------
def test_full_interview_walk_reaches_review_with_plain_not_known(tmp_path):
    # Requirement 5.2: an UNKNOWN answer shows as the plain "not known" label on
    # the review screen, never the raw sentinel.
    with _front_door_env(tmp_path) as (client, recorder):
        start = client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        assert start.status_code == 302

        _walk_interview_to_review(client, recorder)

        r = client.get("/report/review")
        assert r.status_code == 200
        name, ctx = recorder.last
        assert name == _fd.TPL_REVIEW
        assert ctx["end_reason"] in {"complete", "cap"}
        # At least one field was answered "I don't know"; it reads "not known".
        values = [row["value"] for row in ctx["summary"]]
        assert _fd.NOT_KNOWN_LABEL in values
        assert "not known" in values
        # The raw sentinel never leaks to the reporter.
        assert "UNKNOWN" not in values


# --- confirm happy path -> done + receipt (R6.4, R7.1, R7.2, R7.3) ---------
def test_confirm_happy_path_creates_one_complaint_and_servable_pdf(tmp_path):
    with _front_door_env(tmp_path) as (client, recorder):
        client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        _walk_interview_to_review(client, recorder)

        confirm = client.post("/report/confirm")
        # Requirement 6.4: a queued report redirects to /report/done/<ref>.
        assert confirm.status_code == 302
        location = confirm.headers["Location"]
        assert "/report/done/REP-" in location
        ref = location.rsplit("/report/done/", 1)[1].split("?", 1)[0]
        assert _fd._REF_RE.match(ref)

        # Requirement 6.7: exactly one reporter-source index row for this ref.
        rows = _index_rows_for_ref(ref)
        assert len(rows) == 1
        assert rows[0]["source"] == "reporter"

        # Requirements 7.1/7.2/7.3: the receipt is a servable PDF.
        pdf = client.get(f"/report/receipt/{ref}.pdf")
        assert pdf.status_code == 200
        assert pdf.mimetype == "application/pdf"
        assert pdf.data[:4] == b"%PDF"


# --- empty-description confirm is rejected (R2.7 / R6.8) --------------------
def test_confirm_with_empty_description_rerenders_review_and_creates_nothing(tmp_path):
    # Requirement 2.7: an empty free-text description is rejected; all answers
    # are retained and nothing is submitted.
    with _front_door_env(tmp_path) as (client, recorder):
        client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        # Walk the interview answering EVERYTHING "I don't know", so the
        # event_description stays UNKNOWN.
        for _ in range(interview.QUESTION_CAP + 3):
            r = client.get("/report/interview")
            if r.status_code == 302:
                break
            client.post("/report/answer", data={"idk": "1"})

        confirm = client.post("/report/confirm")
        assert confirm.status_code == 200  # re-render, not a redirect
        name, ctx = recorder.last
        assert name == _fd.TPL_REVIEW
        assert ctx.get("description_required") is True
        # Nothing was submitted: the empty description is rejected before intake,
        # so no index file (hence no complaint) was ever created.
        assert not os.path.exists(_intake.INDEX)


# --- duplicate submit (R6.5 / R6.8) ----------------------------------------
def test_confirm_twice_dedupes_to_one_complaint(tmp_path):
    with _front_door_env(tmp_path) as (client, recorder):
        client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        _walk_interview_to_review(client, recorder)

        first = client.post("/report/confirm")
        assert first.status_code == 302
        ref = first.headers["Location"].rsplit("/report/done/", 1)[1].split("?", 1)[0]
        assert len(_index_rows_for_ref(ref)) == 1

        second = client.post("/report/confirm")
        # Requirement 6.5: the duplicate shows the done page with a dup flag.
        assert second.status_code == 302
        location = second.headers["Location"]
        assert f"/report/done/{ref}" in location
        assert "dup=1" in location
        # Requirement 6.8: no second complaint row was created.
        assert len(_index_rows_for_ref(ref)) == 1

        # The done page surfaces the duplicate indication.
        done = client.get(location)
        assert done.status_code == 200
        name, ctx = recorder.last
        assert name == _fd.TPL_DONE
        assert ctx["duplicate"] is True
        assert ctx["reference_number"] == ref


# --- rejected submit (R6.6) ------------------------------------------------
def test_confirm_rejected_rerenders_review_with_error_and_creates_nothing(tmp_path):
    # Requirement 6.6: a rejected submission re-renders the review with a plain
    # error, retains all answers, and creates no complaint.
    with _front_door_env(tmp_path) as (client, recorder):
        client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        _walk_interview_to_review(client, recorder)

        saved_submit = _intake.submit
        try:
            _intake.submit = lambda *a, **k: (400, {"status": "rejected", "error": "bad payload"})
            confirm = client.post("/report/confirm")
        finally:
            _intake.submit = saved_submit

        assert confirm.status_code == 200  # re-render, not a redirect
        name, ctx = recorder.last
        assert name == _fd.TPL_REVIEW
        assert ctx.get("submit_error")
        # Nothing was indexed (our stub never touched the index).
        assert not os.path.exists(_intake.INDEX)


# --- NoAgent single-screen checklist (R8.7) --------------------------------
def test_start_with_no_agent_renders_checklist_instead_of_interview(tmp_path):
    # Requirement 8.7: with NoAgent there is no adaptive loop; start renders the
    # single-screen checklist template rather than redirecting to the interview.
    with _front_door_env(tmp_path, agent_env="none") as (client, recorder):
        r = client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        assert r.status_code == 200  # the checklist render, not a 302 redirect
        name, ctx = recorder.last
        assert name == _fd.TPL_CHECKLIST
        assert ctx["fields"] == interview.FIELD_ORDER


# =========================================================================
# Console wiring / integration test (task 10.1).
#
# Proves the reporter Front_Door is mounted on the REAL console app by
# init_runtime() (task 10) and that a confirmed sample-agent submission flows
# end-to-end through intake.submit as a reporter-source complaint.
#
# Approach (preferred path: the real console app via init_runtime()):
#   - import dashboard_v2/app.py fresh under its own module name with
#     THIRTY_SKIP_RUNTIME_INIT=1, so the import is side-effect free (the reporter
#     blueprint mounts in init_runtime(), not at import, so a skipped-init import
#     must NOT have it — we assert that too);
#   - point VIGIL_DIR + the console's paths at a tmp dir, force the sample agent
#     with zero latency;
#   - neutralise the pipeline (vigil.process), the background workers
#     (start_intake_worker, the intake worker, health_loop) and sample-data
#     seeding so nothing touches the network, spawns a thread, or seeds the repo;
#   - call app_module.init_runtime() explicitly (idempotent) to mount intake's
#     paths AND the reporter blueprint;
#   - assert the reporter.* rules are on the console url_map and GET /report is
#     200, then walk start -> interview -> confirm and assert the redirect to
#     /report/done/REP-... and exactly one source="reporter" row in the console's
#     intake index (VIGIL_DIR/intake/index.csv).
# Every env var / module global touched is restored on exit.
# =========================================================================
import importlib.util as _ilu  # noqa: E402


@contextlib.contextmanager
def _console_with_reporter(tmp_path):
    """Import the console app fresh, mount intake + reporter via init_runtime(),
    yield (app_module, client). Hermetic: tmp VIGIL_DIR, sample agent, no threads,
    no model, no seeding. Restores all env + module globals on exit."""
    data_dir = str(tmp_path)
    saved_env = {k: os.environ.get(k) for k in (
        "VIGIL_DIR", "THIRTY_AGENT", "THIRTY_SAMPLE_DELAY", "THIRTY_SKIP_RUNTIME_INIT",
        "VIGIL_CONSOLE_ACTIONS", "VIGIL_CONSOLE_SETTINGS", "VIGIL_CONSOLE_INTAKE",
    )}
    saved_intake = {
        "INTAKE": _intake.INTAKE, "RAW": _intake.RAW, "INDEX": _intake.INDEX,
        "process": _intake.vigil.process, "start_worker": _intake.start_worker,
    }
    saved_agent_registry = _agents.get_agent()
    prev_module = sys.modules.get("console_app_wiring")
    try:
        os.environ["VIGIL_DIR"] = data_dir
        os.environ["THIRTY_AGENT"] = "sample"
        os.environ["THIRTY_SAMPLE_DELAY"] = "0"
        os.environ["THIRTY_SKIP_RUNTIME_INIT"] = "1"  # import must be side-effect free
        os.environ["VIGIL_CONSOLE_ACTIONS"] = os.path.join(data_dir, "actions.csv")
        os.environ["VIGIL_CONSOLE_SETTINGS"] = os.path.join(data_dir, "settings.json")
        os.environ["VIGIL_CONSOLE_INTAKE"] = os.path.join(data_dir, "intake.json")
        _agents.set_agent(None)  # re-resolve to the sample agent under this env

        spec = _ilu.spec_from_file_location(
            "console_app_wiring", os.path.join(ROOT, "dashboard_v2", "app.py"))
        app_module = _ilu.module_from_spec(spec)
        sys.modules["console_app_wiring"] = app_module
        spec.loader.exec_module(app_module)
        app_module.app.config["TESTING"] = True
        # Complete first-run setup in the tmp data dir so the console's _first_run
        # gate serves pages instead of redirecting to /setup (mirrors conftest's
        # data_dir fixture). This is not a public demo, so the gate is active.
        app_module.tsetup.complete("explore")

        # Import was side-effect free: the reporter blueprint is NOT mounted yet.
        rules_before = {r.endpoint for r in app_module.app.url_map.iter_rules()}
        assert not any(e.startswith("reporter.") for e in rules_before)

        # Neutralise everything init_runtime() would spawn or seed, and the model.
        app_module.ensure_sample_data = lambda *a, **k: None
        app_module.health_loop = lambda *a, **k: None
        app_module.start_intake_worker = lambda *a, **k: None
        _intake.INTAKE = os.path.join(data_dir, "intake")
        _intake.RAW = os.path.join(_intake.INTAKE, "raw")
        _intake.INDEX = os.path.join(_intake.INTAKE, "index.csv")
        _intake.vigil.process = lambda *a, **k: None
        _intake.start_worker = lambda *a, **k: None

        app_module.init_runtime()  # mounts intake paths + the reporter blueprint

        yield app_module, app_module.app.test_client()
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _intake.INTAKE = saved_intake["INTAKE"]
        _intake.RAW = saved_intake["RAW"]
        _intake.INDEX = saved_intake["INDEX"]
        _intake.vigil.process = saved_intake["process"]
        _intake.start_worker = saved_intake["start_worker"]
        _agents.set_agent(saved_agent_registry)
        if prev_module is None:
            sys.modules.pop("console_app_wiring", None)
        else:
            sys.modules["console_app_wiring"] = prev_module


def test_console_mounts_reporter_and_submits_reporter_source_complaint(tmp_path):
    # Task 10.1 / Requirements 6.1, 6.7, 9.1. Proven on the REAL console app:
    # init_runtime() mounts the Front_Door, and a confirmed sample-agent report
    # lands as exactly one source="reporter" complaint through intake.submit.
    with _console_with_reporter(tmp_path) as (app_module, client):
        # 1. The reporter blueprint's routes are registered on the console app.
        endpoints = {r.endpoint for r in app_module.app.url_map.iter_rules()}
        for ep in ("reporter.landing", "reporter.interview", "reporter.confirm"):
            assert ep in endpoints, f"missing {ep}; have {sorted(endpoints)}"
        # And the /report entry point answers on the console.
        assert client.get("/report").status_code == 200

        # 2. Walk the real reporter flow with the sample agent, end to end.
        start = client.post(
            "/report/start",
            data={"language": "en", "reporter_type": "nurse_clinician", "device": "AF"},
        )
        assert start.status_code == 302

        # Answer every question with a real value, so event_description is a
        # non-empty description and confirm is accepted (the sample agent drives
        # the adaptive loop; the Front_Door owns the 8-question cap).
        for _ in range(interview.QUESTION_CAP + 3):
            r = client.get("/report/interview")
            if r.status_code == 302 and "/report/review" in r.headers["Location"]:
                break
            assert r.status_code == 200
            client.post("/report/answer", data={
                "answer": "The CPAP mask stopped sealing overnight and the alarm failed."})

        confirm = client.post("/report/confirm")
        assert confirm.status_code == 302
        location = confirm.headers["Location"]
        assert "/report/done/REP-" in location
        ref = location.rsplit("/report/done/", 1)[1].split("?", 1)[0]
        assert _fd._REF_RE.match(ref)

        # 3. Exactly one reporter-source row in the console's own intake index
        #    (VIGIL_DIR/intake/index.csv), submitted via intake.submit.
        console_index = os.path.join(str(tmp_path), "intake", "index.csv")
        assert os.path.exists(console_index)
        import csv as _csv
        with open(console_index, encoding="utf-8") as f:
            rows = [r for r in _csv.DictReader(f) if r["vigil_id"] == ref]
        assert len(rows) == 1
        assert rows[0]["source"] == "reporter"

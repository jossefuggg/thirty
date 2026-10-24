"""Flask blueprint and routes for the reporter Front_Door.

The public, no-login "Report a device problem" flow. This module owns the HTTP
surface: the landing page (with and without a pre-filled device), starting the
interview, and (in later tasks) the adaptive question loop, review, confirm and
PDF receipt. The pure interview-state logic lives in ``interview.py``; this
module only wires HTTP in and out of those reducers.

Mounting into the console app happens in ``init_app(app)`` (called next to
``intake.init_app(app)``). Defining it here is what lets ``thirty.reporter``'s
lazy ``init_app`` export resolve.

Session / state store
----------------------
There is no login. Each visitor gets an opaque ``session_id`` in a cookie (a
random url-safe token, no PII). The per-session interview state (the dict shape
built by :func:`interview.start_state`) is persisted to a small JSON file under
``data_dir()/reporter_sessions/<session_id>.json`` so the flow survives a worker
restart and is testable without a live cookie jar. The store is resilient: a
missing directory is created, and a missing or corrupt file yields a fresh
session rather than an error.

No-auth, offline, no model on GET
---------------------------------
Every route is unauthenticated (Requirement 1.5). ``GET`` renders are a static
template plus an in-memory catalogue lookup — no network and no model call
(Requirement 1.8); the agent is only invoked when an answer is submitted (task
7.2). Each ``GET`` render is wrapped so a rendering failure shows a plain
no-auth error page with a retry link to the same URL, never a login redirect
(Requirement 1.9).
"""
import json
import os
import re
import secrets

from flask import (
    Blueprint,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .. import config
from . import interview
from . import receipt

# The blueprint. Routes are absolute (/report...), so no url_prefix. Named
# "reporter"; the console mounts it via init_app(app) in task 10.
bp = Blueprint("reporter", __name__)

# The cookie that carries the opaque session id (no PII, no login).
SESSION_COOKIE = "thirty_report_sid"

# The four supported interview languages (Requirement 2.1), in display order.
# code -> English label; templates localise the labels themselves.
LANGUAGES = [
    ("en", "English"),
    ("es", "Espanol"),
    ("pt", "Portugues"),
    ("ht", "Kreyol Ayisyen"),
]
LANGUAGE_CODES = [code for code, _ in LANGUAGES]
DEFAULT_LANGUAGE = "en"

# The three reporter types (Requirement 3.1). code -> English label.
REPORTER_TYPES = [
    ("nurse_clinician", "Nurse or clinician"),
    ("patient_family", "Patient or family"),
    ("company_staff", "Company staff"),
]
REPORTER_TYPE_CODES = [code for code, _ in REPORTER_TYPES]

# The ceiling on a single free-text answer (Requirement 2.3). Longer answers are
# accepted and capped at this length rather than rejected, so a reporter never
# loses their report to an over-length description.
MAX_ANSWER_CHARS = 5000

# Template names (created in task 9). Referencing them here is intentional; a
# missing template is handled by the GET render guard, not a crash.
TPL_LANDING = "report/landing.html"
TPL_CHECKLIST = "report/checklist.html"
TPL_INTERVIEW = "report/interview.html"
TPL_REVIEW = "report/review.html"
TPL_DONE = "report/done.html"

# A Reference_Number is the intake vigil_id for a reporter complaint: REP-<8 hex>.
# Validate any ref against this before using it in a file path so a hostile value
# can never escape the receipts directory (no path traversal).
_REF_RE = re.compile(r"^REP-[A-Za-z0-9]+$")

# Plain, citation-free human labels for the Requirement-4 interview fields, in
# FIELD_ORDER. Used to build the review summary (Requirement 5.1); the copy is
# free of statute / clause / form-number references so it is safe for the
# patient/family plain-language mode (Requirements 1.7, 5.2).
FIELD_LABELS = {
    "device_brand_name": "Device brand name",
    "device_model": "Device model",
    "lot_or_serial": "Lot or serial number",
    "event_description": "What happened",
    "patient_outcome": "Patient outcome",
    "device_malfunctioned": "Did the device malfunction?",
    "event_date": "Date of the event",
    "date_noticed": "Date the problem was noticed",
    "follow_up_contact": "Follow-up contact",
}

# How an UNKNOWN value reads to the reporter on the review screen (Requirement
# 5.2): a plain-language "not known", never the raw sentinel string.
NOT_KNOWN_LABEL = "not known"


# ---------------------------------------------------------------- device catalogue
def _catalogue():
    """The sample device catalogue ``{key: (brand, common, product_code)}``.

    Imported lazily so the module stays import-light and offline. Returns an
    empty dict if sample data is unavailable rather than raising.
    """
    try:
        from thirty.sample_data import DEVICES
    except Exception:
        return {}
    return DEVICES


def catalogue_devices():
    """All catalogue devices as detail dicts, in catalogue order.

    Each item is ``{"key","brand","common","product_code"}``. Used by the
    landing template to offer the device picker (Requirement 1.3 lets the
    reporter change a pre-filled device to any other entry).
    """
    out = []
    for key, entry in _catalogue().items():
        try:
            brand, common, product_code = entry
        except (TypeError, ValueError):
            continue
        out.append({"key": key, "brand": brand, "common": common, "product_code": product_code})
    return out


def resolve_device(device_slug):
    """Resolve ``device_slug`` to a device detail dict, or ``None``.

    The match is case-insensitive against the eight catalogue keys (AF, PG, NS,
    TC, CL, VV, LM, SP) (Requirement 1.3). The raw key form (e.g. ``"AF"`` or
    ``"af"``) is accepted; a slug that carries extra url-safe punctuation is
    tolerated by comparing only the alphanumerics, so a future slug form still
    resolves to the right key. An unknown slug yields ``None`` so the landing
    route can prompt the reporter to pick a device (Requirement 1.4).
    """
    if not device_slug:
        return None
    wanted = re.sub(r"[^a-z0-9]", "", str(device_slug).lower())
    if not wanted:
        return None
    catalogue = _catalogue()
    for key, entry in catalogue.items():
        if re.sub(r"[^a-z0-9]", "", key.lower()) == wanted:
            try:
                brand, common, product_code = entry
            except (TypeError, ValueError):
                return None
            return {"key": key, "brand": brand, "common": common, "product_code": product_code}
    return None


# ---------------------------------------------------------------- plain-language mode
def plain_mode(reporter_type):
    """True when the reporter is a patient or family member.

    Patient/family screens and the PDF receipt use plain, citation-free copy
    (no statute / clause / form-number references) (Requirements 1.7, 7.5).
    Centralising the choice here keeps templates from re-deriving it.
    """
    return reporter_type == "patient_family"


# ---------------------------------------------------------------- session store
def _sessions_dir():
    """The directory holding per-session JSON state, created on demand."""
    path = os.path.join(config.data_dir(), "reporter_sessions")
    os.makedirs(path, exist_ok=True)
    return path


# A session id is an opaque url-safe token. Validate it before using it in a
# file path so a hostile cookie value can never escape the sessions directory.
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _is_valid_sid(session_id):
    return bool(session_id) and bool(_SID_RE.match(session_id))


def _session_path(session_id):
    return os.path.join(_sessions_dir(), f"{session_id}.json")


def new_session_id():
    """A fresh opaque session id (random url-safe token, no PII)."""
    return secrets.token_urlsafe(24)


def new_session(session_id=None, reporter_type=None, language=None, device_key=None):
    """Build a fresh interview-state dict carrying its ``session_id``.

    Uses :func:`interview.start_state` for the state shape; the ``session_id``
    is stored on the state so :func:`interview.submission_id` derives a stable
    ``external_id`` per confirmation (Property 3).
    """
    sid = session_id or new_session_id()
    state = interview.start_state(reporter_type, language, device_key)
    state["session_id"] = sid
    return state


def load_session(session_id):
    """Load the interview state for ``session_id``, or ``None``.

    Resilient: an invalid id, a missing file, or a corrupt/non-dict payload all
    yield ``None`` so the caller can start a fresh session instead of failing.
    """
    if not _is_valid_sid(session_id):
        return None
    path = _session_path(session_id)
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    state.setdefault("session_id", session_id)
    return state


def save_session(state):
    """Persist ``state`` to its per-session JSON file (atomic replace).

    Returns the ``session_id`` written. A state without a valid ``session_id``
    is given a fresh one first so the file path stays inside the sessions dir.
    """
    sid = state.get("session_id")
    if not _is_valid_sid(sid):
        sid = new_session_id()
        state["session_id"] = sid
    path = _session_path(sid)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)
    return sid


def _current_session():
    """The session for the request's cookie, or a fresh (unsaved) one.

    Reads the opaque session id from the cookie; if it is missing or its stored
    state is gone/corrupt, a brand-new session is returned (not yet persisted —
    callers persist and set the cookie when they have something to store).
    """
    sid = request.cookies.get(SESSION_COOKIE)
    state = load_session(sid) if sid else None
    if state is None:
        state = new_session()
    return state


def _with_session_cookie(response, session_id):
    """Attach the opaque session cookie to ``response`` (lax, http-only)."""
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=60 * 60 * 24,  # a day is plenty for one report
        httponly=True,
        samesite="Lax",
    )
    return response


# ---------------------------------------------------------------- render helpers
def _safe_render(template_name, retry_url, **context):
    """Render ``template_name``; on any failure show a no-auth error page.

    Requirement 1.9: if rendering the reporting page fails, show a plain error
    message with a retry link to the same URL — never a login redirect. The
    fallback is a tiny inline page so it works even when the error templates
    themselves are missing.
    """
    try:
        return render_template(template_name, **context)
    except Exception:
        return _render_error(retry_url)


def _render_error(retry_url):
    """A minimal, dependency-free no-auth error page (Requirement 1.9)."""
    try:
        return render_template("report/error.html", retry_url=retry_url), 503
    except Exception:
        pass
    safe_url = (retry_url or url_for("reporter.landing")).replace('"', "%22")
    html = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Report a device problem</title></head>"
        "<body style=\"font-size:16px;font-family:system-ui,sans-serif;margin:2rem\">"
        "<p>The reporting page could not be loaded. Please try again.</p>"
        f"<p><a href=\"{safe_url}\" style=\"display:inline-block;min-width:44px;"
        "min-height:44px;line-height:44px\">Try again</a></p>"
        "</body></html>"
    )
    return html, 503


def _landing_context(state, device, unknown_slug=False, error=None):
    """Shared context for the landing template.

    ``device`` is the resolved pre-filled device detail or ``None``;
    ``unknown_slug`` is True when a slug was given but matched no catalogue key
    (the template then prompts the reporter to pick a device, Requirement 1.4).
    """
    return {
        "languages": LANGUAGES,
        "default_language": state.get("language") or DEFAULT_LANGUAGE,
        "reporter_types": REPORTER_TYPES,
        "selected_reporter_type": state.get("reporter_type"),
        "devices": catalogue_devices(),
        "device": device,
        "unknown_slug": unknown_slug,
        "plain_mode": plain_mode(state.get("reporter_type")),
        "error": error,
    }


# ---------------------------------------------------------------- routes
@bp.get("/report")
def landing():
    """Landing page without a pre-filled device (Requirements 1.1, 1.4, 1.5)."""
    state = _current_session()
    # Clear any stale pre-filled device: a bare /report starts device-less.
    if state.get("device_key"):
        state = dict(state)
        state["device_key"] = None
    context = _landing_context(state, device=None)
    body = _safe_render(TPL_LANDING, retry_url=url_for("reporter.landing"), **context)
    sid = save_session(state)
    return _with_session_cookie(make_response(body), sid)


@bp.get("/report/<device_slug>")
def landing_device(device_slug):
    """Landing page, pre-filling the device when the slug matches a key.

    A slug that case-insensitively matches a catalogue key pre-fills that device
    and still lets the reporter change it (Requirements 1.2, 1.3). An unknown
    slug serves the landing page with no pre-fill and prompts the reporter to
    pick a device (Requirement 1.4).
    """
    state = _current_session()
    device = resolve_device(device_slug)
    state = dict(state)
    state["device_key"] = device["key"] if device else None
    context = _landing_context(state, device=device, unknown_slug=device is None)
    retry_url = url_for("reporter.landing_device", device_slug=device_slug)
    body = _safe_render(TPL_LANDING, retry_url=retry_url, **context)
    sid = save_session(state)
    return _with_session_cookie(make_response(body), sid)


@bp.post("/report/start")
def start():
    """Record language + reporter-type (+ device) and begin the interview.

    Rejects (re-renders the landing page with a prompt) when no reporter-type
    was chosen (Requirements 2.2, 3.2, 3.4). On a valid start, a fresh session
    is created carrying the selections. When the active agent is NoAgent
    (``get_agent().id == "none"``) there is no adaptive loop: the start routes
    to a single-screen checklist (Requirement 8.7). Otherwise it proceeds to the
    adaptive interview route (task 7.2 implements ``/report/interview``).
    """
    form = request.form
    reporter_type = (form.get("reporter_type") or "").strip()
    language = (form.get("language") or "").strip()
    device_slug = (form.get("device") or form.get("device_key") or "").strip()

    device = resolve_device(device_slug)
    device_key = device["key"] if device else None

    # Normalise language to a supported code; fall back to the default.
    if language not in LANGUAGE_CODES:
        language = DEFAULT_LANGUAGE

    # Requirement 3.4 / 2.2: reporter-type is required to start the interview.
    if reporter_type not in REPORTER_TYPE_CODES:
        state = new_session(language=language, device_key=device_key)
        context = _landing_context(
            state,
            device=device,
            unknown_slug=bool(device_slug) and device is None,
            error="reporter_type_required",
        )
        body = _safe_render(TPL_LANDING, retry_url=url_for("reporter.landing"), **context)
        sid = save_session(state)
        return _with_session_cookie(make_response(body), sid)

    # Fresh session for this report, carrying the selections.
    state = new_session(reporter_type=reporter_type, language=language, device_key=device_key)

    # Requirement 8.7: NoAgent means no adaptive loop — a single-screen checklist.
    if _agent_is_none():
        state["checklist"] = True
        sid = save_session(state)
        context = {
            "languages": LANGUAGES,
            "language": language,
            "reporter_type": reporter_type,
            "device": device,
            "devices": catalogue_devices(),
            "fields": interview.FIELD_ORDER,
            "plain_mode": plain_mode(reporter_type),
        }
        body = _safe_render(TPL_CHECKLIST, retry_url=url_for("reporter.landing"), **context)
        return _with_session_cookie(make_response(body), sid)

    # Adaptive path: persist and hand off to the interview route (task 7.2).
    state["checklist"] = False
    sid = save_session(state)
    response = make_response(redirect(url_for("reporter.landing")))
    # task 7.2 adds /report/interview; until then redirect back to landing so
    # the start still resolves. Replace the target once 7.2 lands.
    try:
        response = make_response(redirect(url_for("reporter.interview")))
    except Exception:
        response = make_response(redirect(url_for("reporter.landing")))
    return _with_session_cookie(response, sid)


# ---------------------------------------------------------------- interview routes
def _active_agent():
    """The active agent from the registry, or ``None`` on any failure.

    Resolved through ``get_agent()`` so the choice follows the configured agent.
    A failure to resolve the agent yields ``None``; the interview route then
    treats the next-question step as malformed and ends the interview gracefully
    rather than raising (Requirement 4.9).
    """
    try:
        from thirty.agents import get_agent
        return get_agent()
    except Exception:
        return None


@bp.get("/report/interview", endpoint="interview")
def interview_route():
    """Present the current single interview question (Requirements 4.1, 4.4, 4.6).

    Loads the request's session. If the interview has already ended, redirects
    to the review screen. Otherwise the Front_Door — not the agent — drives the
    loop and owns the 8-question cap (Requirement 4.5): when ``questions_asked``
    has reached :data:`interview.QUESTION_CAP` the interview is ended with reason
    ``"cap"`` and the reporter is sent to review.

    The next question is computed on the server via
    :func:`interview.safe_next_question` (which never raises). A ``complete``
    marker ends the interview (``"complete"``) and redirects to review; a
    malformed result ends it (``"malformed"``) and still redirects to review
    with answers preserved (Requirement 4.9).

    To avoid an extra model call on a plain refresh, a question already stored
    in ``state["current"]`` is re-displayed as-is; the agent is only consulted
    when there is no pending current question.
    """
    state = _current_session()

    # Already terminal → straight to the plain-words review.
    if state.get("ended"):
        return _redirect_with_session("reporter.review", state)

    # Front_Door-side cap: never ask past the 8th question (Requirement 4.5).
    if state.get("questions_asked", 0) >= interview.QUESTION_CAP:
        state = interview.end_interview(state, "cap")
        return _redirect_with_session("reporter.review", state)

    # Re-display a pending question without touching the agent (refresh-safe).
    question = state.get("current")
    if not interview._is_valid_question(question):
        agent = _active_agent()
        result = interview.safe_next_question(agent, interview.answers_view(state))
        if result == interview._COMPLETE:
            state = interview.end_interview(state, "complete")
            return _redirect_with_session("reporter.review", state)
        if result == interview._MALFORMED:
            state = interview.end_interview(state, "malformed")
            return _redirect_with_session("reporter.review", state)
        # A valid question: stash it as the current question and persist.
        state = dict(state)
        state["current"] = result
        question = result

    sid = save_session(state)
    context = _interview_context(state, question)
    body = _safe_render(TPL_INTERVIEW, retry_url=url_for("reporter.interview"), **context)
    return _with_session_cookie(make_response(body), sid)


@bp.post("/report/answer")
def answer():
    """Record the answer to the current question and advance (Requirements 4.2, 4.3, 4.7).

    Reads the submitted value for ``state["current"]["field"]``. An "I don't
    know" selection (form field ``idk`` truthy) records :data:`interview.UNKNOWN`
    (Requirement 4.7); otherwise the real value is recorded, accepted up to
    :data:`MAX_ANSWER_CHARS` characters in the reporter's language and capped at
    that length (Requirement 2.3). After recording, the current question is
    cleared, the 8-question cap is enforced (Requirement 4.5), and control
    returns to ``GET /report/interview`` which fetches the next question.
    """
    state = _current_session()

    # No pending question (stale POST / direct hit): bounce to the interview so
    # the loop re-synchronises rather than erroring.
    current = state.get("current")
    if not interview._is_valid_question(current):
        return _redirect_with_session("reporter.interview", state)

    field = current["field"]
    form = request.form
    idk = _is_truthy(form.get("idk"))

    if idk:
        state = interview.record_answer(state, field, interview.UNKNOWN, idk=True)
    else:
        raw = form.get("answer", "")
        value = raw[:MAX_ANSWER_CHARS]  # accept-and-cap, never reject on length
        state = interview.record_answer(state, field, value, idk=False)

    # Done with this question; the next GET will fetch the following one.
    state = dict(state)
    state["current"] = None

    # Cap enforced on the answer side too, so the next GET never has to ask
    # again once 8 answers are in (Requirement 4.5).
    if state.get("questions_asked", 0) >= interview.QUESTION_CAP:
        state = interview.end_interview(state, "cap")
        return _redirect_with_session("reporter.review", state)

    return _redirect_with_session("reporter.interview", state)


# ---------------------------------------------------------------- review routes
@bp.get("/report/review")
def review():
    """Plain-words review of the collected answers (Requirements 5.1, 5.2, 5.5).

    Renders a readable summary of every Requirement-4 field in ``FIELD_ORDER``
    with a human label; an UNKNOWN value is shown as the plain-language
    :data:`NOT_KNOWN_LABEL`, never the raw sentinel (Requirement 5.2). When the
    interview ended because the agent misbehaved (``end_reason == "malformed"``)
    a gentle note indicates it ended without completion, while still letting the
    reporter review and (later) submit (Requirement 4.9).
    """
    state = _current_session()
    context = _review_context(state)
    body = _safe_render(TPL_REVIEW, retry_url=url_for("reporter.review"), **context)
    sid = save_session(state)
    return _with_session_cookie(make_response(body), sid)


@bp.post("/report/review/edit")
def review_edit():
    """Revise a single collected answer, then return to review (Requirement 5.3).

    Accepts a ``field`` and either an ``idk`` flag (record :data:`interview.UNKNOWN`)
    or a new ``value`` (recorded, capped at :data:`MAX_ANSWER_CHARS`). An edit to
    a field already answered as UNKNOWN is honoured through
    :func:`interview.record_answer`'s own rules. An unknown/absent field is a
    no-op; either way the reporter is redirected back to the review screen.
    """
    state = _current_session()
    form = request.form
    field = (form.get("field") or "").strip()

    if field in interview.FIELD_ORDER:
        if _is_truthy(form.get("idk")):
            state = interview.record_answer(state, field, interview.UNKNOWN, idk=True)
        else:
            value = (form.get("value") or "")[:MAX_ANSWER_CHARS]
            state = interview.record_answer(state, field, value, idk=False)

    return _redirect_with_session("reporter.review", state)


# ---------------------------------------------------------------- confirm / done / receipt
def _english_text(description, language):
    """The English form of the reporter's description, per the translation rule.

    - English (``language == "en"``): the identical original text, with no
      translation call (Requirement 2.5).
    - Non-English: ask the ACTIVE agent to translate via
      :meth:`Agent.translate_to_english`. A non-empty string is used as-is; a
      ``None``/empty result (SampleAgent and NoAgent always; a model agent when
      it cannot translate) yields ``None`` so :func:`interview.to_intake_payload`
      stores :data:`interview.TRANSLATION_PENDING_MARKER` (Requirements 2.4, 2.6,
      2.8). A translation is never synthesised here.
    """
    if (language or DEFAULT_LANGUAGE) == "en":
        return description
    agent = _active_agent()
    if agent is None:
        return None
    try:
        translated = agent.translate_to_english(description, language)
    except Exception:
        return None
    if translated is not None and str(translated).strip():
        return str(translated)
    return None


def _receipts_dir():
    """The directory holding generated PDF receipts, created on demand."""
    path = os.path.join(config.data_dir(), "reports", "receipts")
    os.makedirs(path, exist_ok=True)
    return path


def _receipt_summary(state):
    """Ordered ``(label, value)`` pairs for the PDF receipt, built from the review.

    Reuses :func:`review_summary` so the receipt shows exactly what the reporter
    reviewed, with UNKNOWN already rendered as the plain-language "not known".
    """
    return [(row["label"], row["value"]) for row in review_summary(state)]


def _write_receipt(ref, state):
    """Build and persist the PDF receipt for ``ref``; return its file path.

    Writes to ``data_dir()/reports/receipts/<ref>.pdf`` (atomic replace). The
    nurse/clinician facility line vs. the citation-free patient/family summary
    is handled inside :func:`receipt.build_receipt` by ``reporter_type``.
    """
    pdf_bytes = receipt.build_receipt(
        ref,
        _receipt_summary(state),
        state.get("reporter_type"),
        state.get("language") or DEFAULT_LANGUAGE,
    )
    path = os.path.join(_receipts_dir(), f"{ref}.pdf")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(pdf_bytes)
    os.replace(tmp, path)
    return path


@bp.post("/report/confirm")
def confirm():
    """Finalize and submit the report into the existing intake pipeline.

    Requirements 5.4, 5.5, 2.4-2.8, 6.1-6.8, 7.1. The reporter's own free-text
    description (the ``event_description`` answer, in their language) is
    required: an empty/blank or UNKNOWN description re-renders the review screen
    with ``description_required`` set and submits nothing (Requirement 2.7).

    Otherwise the English form is computed per the translation rule
    (:func:`_english_text`), the payload is built by
    :func:`interview.to_intake_payload` (which fills missing fields and always
    sets ``source="reporter"`` + ``reporter_type``), and the report is submitted
    through ``intake.submit(..., kind="reporter", default_source="reporter")``.
    The three intake outcomes are handled per Requirement 6:

    - 202 queued  -> persist the PDF receipt, mark the session submitted, and
      redirect to ``/report/done/<ref>`` (Requirements 6.4, 6.7, 7.1).
    - 200 duplicate -> redirect to ``/report/done/<ref>?dup=1`` using the
      existing ``vigil_id``; no second complaint (Requirements 6.5, 6.8).
    - 400 rejected -> re-render the review with a plain-language error, retain
      all answers, require re-confirm; no complaint created (Requirements 6.6,
      6.8).
    """
    state = _current_session()

    description = interview._answer(state, "event_description")
    if not description or not str(description).strip() or description == interview.UNKNOWN:
        # Requirement 2.7: an empty free-text description is rejected; all prior
        # answers are retained and nothing is submitted.
        context = _review_context(state)
        context["description_required"] = True
        body = _safe_render(TPL_REVIEW, retry_url=url_for("reporter.review"), **context)
        sid = save_session(state)
        return _with_session_cookie(make_response(body), sid)

    language = state.get("language") or DEFAULT_LANGUAGE
    english_text = _english_text(description, language)

    payload = interview.to_intake_payload(state, free_text=description, english_text=english_text)

    import intake  # lazy: submission only ever goes through intake.submit
    status, res = intake.submit(payload, kind="reporter", default_source="reporter")

    if status == 202:
        ref = res.get("vigil_id")
        state = dict(state)
        state["submitted"] = True
        state["reference_number"] = ref
        try:
            _write_receipt(ref, state)
        except Exception:
            # A receipt failure must not lose a queued complaint; the receipt
            # route regenerates lazily if the file is missing.
            pass
        return _redirect_with_session("reporter.done", state, ref=ref)

    if status == 200:
        # Duplicate: show the existing reference, create no second complaint.
        ref = res.get("vigil_id")
        state = dict(state)
        state["submitted"] = True
        state["reference_number"] = ref
        return _redirect_with_session("reporter.done", state, ref=ref, dup=1)

    # 400 rejected (or any other status): re-render review, keep answers.
    context = _review_context(state)
    context["submit_error"] = (res or {}).get("error") or "The report could not be submitted. Please try again."
    body = _safe_render(TPL_REVIEW, retry_url=url_for("reporter.review"), **context)
    sid = save_session(state)
    return _with_session_cookie(make_response(body), sid)


@bp.get("/report/done/<ref>", endpoint="done")
def done(ref):
    """Show the Reference_Number and a link to the PDF receipt (Requirements 6.4, 6.5, 7.3).

    No auth. A ``dup`` query flag indicates the report was already received
    (Requirement 6.5). The reference is validated against the REP pattern before
    it is echoed into a receipt URL.
    """
    safe_ref = ref if _REF_RE.match(ref or "") else ""
    duplicate = _is_truthy(request.args.get("dup"))
    context = {
        "reference_number": safe_ref,
        "duplicate": duplicate,
        "receipt_url": url_for("reporter.receipt", ref=safe_ref) if safe_ref else None,
        "language": (_current_session().get("language") or DEFAULT_LANGUAGE),
        "reporter_type": _current_session().get("reporter_type"),
        "plain_mode": plain_mode(_current_session().get("reporter_type")),
    }
    return _safe_render(TPL_DONE, retry_url=url_for("reporter.done", ref=safe_ref or "REP-"), **context)


@bp.get("/report/receipt/<ref>.pdf", endpoint="receipt")
def receipt_pdf(ref):
    """Serve the PDF receipt for ``ref`` (Requirements 7.1, 7.2, 7.3).

    Validates ``ref`` against the REP pattern before using it in a path (no
    traversal). Serves the persisted file when present; otherwise regenerates it
    from the current session when that session matches the ref, persists it, and
    serves it. A ref with no file and no matching session is a 404.
    """
    if not _REF_RE.match(ref or ""):
        abort(404)

    receipts = _receipts_dir()
    filename = f"{ref}.pdf"
    path = os.path.join(receipts, filename)

    if not os.path.exists(path):
        # Regenerate from the current session only when it is this ref's report.
        state = _current_session()
        if state.get("reference_number") == ref:
            try:
                _write_receipt(ref, state)
            except Exception:
                abort(404)
        else:
            abort(404)

    if not os.path.exists(path):
        abort(404)

    return send_from_directory(
        receipts,
        filename,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
    )


# ---------------------------------------------------------------- interview/review context
def _is_truthy(value):
    """True for the common HTML-form truthy encodings of a checkbox/flag."""
    return str(value).strip().lower() in {"1", "true", "on", "yes", "idk"}


def _redirect_with_session(endpoint, state, **url_values):
    """Persist ``state``, redirect to ``endpoint``, and carry the session cookie.

    Centralises the save → redirect → set-cookie dance so every interview/review
    hop keeps the opaque session alive without a login. Extra ``url_values`` are
    passed through to :func:`url_for` (e.g. the ``ref`` path value and a ``dup``
    query flag for the done page).
    """
    sid = save_session(state)
    response = make_response(redirect(url_for(endpoint, **url_values)))
    return _with_session_cookie(response, sid)


def _interview_context(state, question):
    """Context for the single-question interview template.

    Exposes the current ``question`` (with its ``options`` for a ``choice`` type)
    and a flag telling the template to always render an "I don't know"
    affordance (Requirement 4.6), plus the reporter type / language and the
    plain-language mode for patient/family copy (Requirement 1.7).
    """
    q = question if isinstance(question, dict) else {}
    options = q.get("options") or []
    return {
        "question": q,
        "field": q.get("field"),
        "prompt": q.get("prompt"),
        "input_type": q.get("type") or "text",
        "options": options,
        "allow_idk": True,  # the Front_Door always offers "I don't know"
        "language": state.get("language") or DEFAULT_LANGUAGE,
        "reporter_type": state.get("reporter_type"),
        "plain_mode": plain_mode(state.get("reporter_type")),
        "questions_asked": state.get("questions_asked", 0),
        "question_cap": interview.QUESTION_CAP,
        "max_answer_chars": MAX_ANSWER_CHARS,
    }


def review_summary(state):
    """Build the ordered plain-words review summary for ``state``.

    Returns a list of ``{"field","label","value","is_unknown"}`` dicts, one per
    Requirement-4 field in ``interview.FIELD_ORDER``. A field that was answered
    UNKNOWN (or never reached) has ``is_unknown=True`` and a ``value`` of
    :data:`NOT_KNOWN_LABEL` so the template never shows the raw sentinel
    (Requirement 5.2). A ``list`` answer (none presently, but defensive) is
    joined for display.
    """
    answers = state.get("answers", {})
    rows = []
    for field in interview.FIELD_ORDER:
        raw = answers.get(field, interview.UNKNOWN)
        is_unknown = (raw == interview.UNKNOWN) or raw is None or raw == ""
        if is_unknown:
            display = NOT_KNOWN_LABEL
        elif isinstance(raw, (list, tuple)):
            display = ", ".join(str(x) for x in raw)
        else:
            display = str(raw)
        rows.append({
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "value": display,
            "is_unknown": is_unknown,
        })
    return rows


def _review_context(state):
    """Context for the review template.

    Carries the ordered summary, the "ended without completion" note for a
    malformed end (Requirement 4.9), the reporter type / language and the
    plain-language mode (Requirement 1.7). ``end_reason`` is exposed so the
    template can tailor copy per terminal reason if it wishes.
    """
    return {
        "summary": review_summary(state),
        "fields": interview.FIELD_ORDER,
        "field_labels": FIELD_LABELS,
        "not_known_label": NOT_KNOWN_LABEL,
        "ended": bool(state.get("ended")),
        "end_reason": state.get("end_reason"),
        "ended_without_completion": state.get("end_reason") == "malformed",
        "language": state.get("language") or DEFAULT_LANGUAGE,
        "reporter_type": state.get("reporter_type"),
        "plain_mode": plain_mode(state.get("reporter_type")),
        "max_answer_chars": MAX_ANSWER_CHARS,
    }


# ---------------------------------------------------------------- agent helper
def _agent_is_none():
    """True when the active agent is NoAgent (manual review, no adaptive loop).

    Resolved through the registry so the choice follows ``get_agent()``. Any
    failure resolving the agent is treated as "not NoAgent" so the adaptive path
    is attempted rather than silently forcing the checklist; the interview route
    (task 7.2) still guards the agent call.
    """
    try:
        from thirty.agents import get_agent
        return get_agent().id == "none"
    except Exception:
        return False


# ---------------------------------------------------------------- app wiring
def init_app(app):
    """Register the Front_Door blueprint on an existing Flask app (task 10).

    Called from the console's init block next to ``intake.init_app(app)``.
    Defining it here is required so ``thirty.reporter``'s lazy ``init_app``
    export resolves.
    """
    app.register_blueprint(bp)

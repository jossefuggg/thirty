"""Pure interview-state logic for the reporter Front_Door.

The Front_Door — not the agent — owns the adaptive interview loop and the
8-question cap. This module holds the *pure* reducer functions that take and
return a plain interview-state dict (see ``Answers_So_Far`` in the design's Data
Models). Keeping them Flask- and import-light lets the property tests drive the
interview without a web server or templates.

The state model (task 1.2):

- constants (:data:`QUESTION_CAP`, :data:`IDK`, :data:`UNKNOWN`,
  :data:`FIELD_ORDER`);
- :func:`start_state` — a fresh interview-state dict;
- :func:`record_answer` — append an answer (an "I don't know" maps to
  ``UNKNOWN`` and is never overwritten);
- :func:`should_continue` — whether the loop may ask another question;
- :func:`end_interview` — mark the interview terminal with a reason.

The field mapping and loop driver (task 1.3), built on top of the state model:

- :func:`to_draft_3500a` — map the interview state to a Draft Form 3500A dict,
  filling every missing required field with ``UNKNOWN`` (Requirement 4.10);
- :func:`to_intake_payload` — build the dict passed to ``intake.submit`` (it
  only composes a dict; it never imports or calls intake);
- :func:`safe_next_question` — wrap ``agent.next_question`` so it never raises
  and always yields a normalized marker;
- :func:`run_interview` — the pure loop driver reused by the property tests; it
  enforces the 8-question cap independently of the agent (Property 1).

Key invariants maintained by these reducers:

- ``state["questions_asked"] == len(state["asked"])`` at all times;
- ``state["questions_asked"] <= QUESTION_CAP`` at all times;
- an ``"I don't know"`` answer stores ``UNKNOWN`` in ``answers[field]`` and is
  never overwritten by a later guessed, blank, or defaulted value (Property 2).

The reducers are pure: they never mutate the input ``state`` in place; each
returns a new dict so callers can treat state as immutable.
"""

# The hard cap on interview questions (Requirement 4.5 / Property 1).
QUESTION_CAP = 8

# Internal marker for an "I don't know" answer. Not stored in the state; it is
# translated to UNKNOWN by record_answer. Kept distinct from any real answer so
# the Front_Door can pass idk=True explicitly rather than string-matching.
IDK = "__IDK__"

# The system-wide sentinel for a value the reporter does not know. Matches the
# literal string used throughout thirty.sample_data and the 3500A field shapes.
UNKNOWN = "UNKNOWN"

# The Requirement 4.8 data set, in the order the interview collects it. These
# are the internal interview-field keys; the field -> Draft_3500A -> intake
# payload mapping (task 1.3) lives alongside to_draft_3500a / to_intake_payload.
FIELD_ORDER = [
    "device_brand_name",   # device brand name           -> D1_brand_name / payload.device
    "device_model",        # device model                -> D4_model
    "lot_or_serial",       # lot number or serial number -> D4_lot / D4_serial
    "event_description",   # free-text what happened      -> B5_event_description / payload.text
    "patient_outcome",     # death | hospitalisation | injury | none -> B2_outcomes
    "device_malfunctioned",# yes | no | UNKNOWN          -> B1_event_type / H3 context
    "event_date",          # date of the event           -> B3_date_of_event / payload.event_date
    "date_noticed",        # date the problem was noticed -> stored
    "follow_up_contact",   # a follow-up contact          -> payload.reporter
]


def start_state(reporter_type, language, device_key):
    """Build a fresh interview-state dict.

    ``reporter_type`` is one of ``nurse_clinician`` / ``patient_family`` /
    ``company_staff``; ``language`` is one of ``en`` / ``es`` / ``pt`` / ``ht``;
    ``device_key`` is a catalogue key (e.g. ``"AF"``) or ``None`` when no device
    has been resolved yet. The device detail dict is filled in by the Front_Door
    from the catalogue; here we store only the key so this module stays
    dependency-free.
    """
    return {
        "reporter_type": reporter_type,
        "language": language,
        "device_key": device_key,
        "answers": {},            # {field: value or UNKNOWN}
        "asked": [],              # fields already presented, in order
        "questions_asked": 0,     # == len(asked); the cap counter
        "current": None,          # the current question object (set by the loop)
        "ended": False,
        "end_reason": None,       # None | "complete" | "cap" | "malformed"
        "free_text_original": "",  # the reporter's description in their language
    }


def record_answer(state, field, raw_value, idk=False):
    """Return a new state with ``field`` recorded.

    An "I don't know" answer (``idk=True``) stores :data:`UNKNOWN`. A real answer
    stores ``raw_value`` unchanged. A field already answered as :data:`UNKNOWN`
    (from an earlier "I don't know") is never overwritten — the UNKNOWN sticks
    (Property 2). ``field`` is added to ``asked`` and the cap counter advances
    only the first time the field is presented, so ``questions_asked ==
    len(asked)`` stays true and never exceeds :data:`QUESTION_CAP`.
    """
    answers = dict(state["answers"])
    asked = list(state["asked"])
    questions_asked = state["questions_asked"]

    already_asked = field in asked
    if not already_asked:
        asked.append(field)
        # Never let the counter run past the cap, even if a caller records more
        # answers than it should; the loop driver is the real gate.
        questions_asked = min(questions_asked + 1, QUESTION_CAP)

    # UNKNOWN, once set by an "I don't know", is never overwritten.
    if answers.get(field) == UNKNOWN:
        value = UNKNOWN
    else:
        value = UNKNOWN if idk else raw_value
    answers[field] = value

    new_state = dict(state)
    new_state["answers"] = answers
    new_state["asked"] = asked
    new_state["questions_asked"] = questions_asked
    return new_state


def should_continue(state):
    """Whether the interview may ask another question.

    True only while the interview is not ended and fewer than
    :data:`QUESTION_CAP` questions have been asked.
    """
    return (not state["ended"]) and state["questions_asked"] < QUESTION_CAP


def end_interview(state, reason):
    """Return a new state marked terminal with ``reason``.

    ``reason`` must be one of ``"complete"`` (the agent returned the completion
    sentinel), ``"cap"`` (the 8-question cap was reached), or ``"malformed"``
    (the agent returned neither a valid question nor the completion sentinel, or
    raised). All recorded answers are preserved unchanged.
    """
    if reason not in {"complete", "cap", "malformed"}:
        raise ValueError(f"invalid end reason: {reason!r}")
    new_state = dict(state)
    new_state["ended"] = True
    new_state["end_reason"] = reason
    new_state["current"] = None
    return new_state


# ---------------------------------------------------------------- device catalogue
# The device detail used by the mappings below. start_state stores only a
# catalogue key to stay dependency-free; here we resolve it lazily against the
# sample-data catalogue (offline, no network). DEVICES[key] = (brand, common,
# product_code); MAKER is the fixed manufacturer for the invented catalogue.
def _device_detail(device_key):
    """Resolve ``device_key`` to ``{"key","brand","common","product_code"}`` or ``None``.

    Imported lazily so this module stays import-light for the property tests. An
    unknown or missing key yields ``None``; the mappings then fall back to
    UNKNOWN / empty values rather than guessing a device.
    """
    if not device_key:
        return None
    from thirty.sample_data import DEVICES  # lazy: keep module import-light
    entry = DEVICES.get(device_key)
    if not entry:
        return None
    brand, common, product_code = entry
    return {"key": device_key, "brand": brand, "common": common, "product_code": product_code}


def _maker():
    from thirty.sample_data import MAKER  # lazy
    return MAKER


# ---------------------------------------------------------------- helpers
def _known(value):
    """True when ``value`` is a real answer (not blank, not UNKNOWN)."""
    return bool(value) and value != UNKNOWN


def _answer(state, field):
    """The recorded answer for ``field``; UNKNOWN when the field was not answered.

    A field the reporter never reached is treated the same as an explicit "I
    don't know": its 3500A value is UNKNOWN (Requirement 4.10).
    """
    return state["answers"].get(field, UNKNOWN)


def normalize_event_date(value):
    """Normalize a date answer to ``YYYYMMDD``; missing/UNKNOWN/unparseable -> ``""``.

    Accepts ``YYYYMMDD`` and ``YYYY-MM-DD`` (the two forms ``intake`` accepts).
    An UNKNOWN or blank date maps to an empty string, which ``intake`` accepts.
    """
    if not _known(value):
        return ""
    import re  # stdlib, cheap; kept local to the one caller family
    d = str(value).strip()
    if re.fullmatch(r"\d{8}", d):
        return d
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", d)
    return "".join(m.groups()) if m else ""


# ---------------------------------------------------------------- field -> Draft 3500A
def to_draft_3500a(state):
    """Build a Draft Form 3500A dict from the interview ``state``.

    Every required field absent from the interview is filled with :data:`UNKNOWN`
    (Requirement 4.10). An "I don't know" answer stays :data:`UNKNOWN` and is
    never overwritten with a guess, blank, or default (Property 2) — the stored
    answer already carries UNKNOWN (see :func:`record_answer`), so we copy it
    through verbatim.

    The field -> 3500A mapping follows the design's Data Models table:

    - ``device_brand_name``  -> ``D1_brand_name``
    - ``device_model``       -> ``D4_model``
    - ``lot_or_serial``      -> ``D4_lot`` / ``D4_serial``
    - ``event_description``  -> ``B5_event_description``
    - ``patient_outcome``    -> ``B2_outcomes`` + derived ``H1_type_of_reportable_event``
    - ``device_malfunctioned`` -> ``B1_event_type`` / ``H3_device_evaluated`` context
    - ``event_date``         -> ``B3_date_of_event``
    - ``date_noticed``       -> stored ``date_noticed``
    - ``follow_up_contact``  -> stored ``follow_up_contact``
    - fixed                  -> ``D2b_product_code`` / ``D3_manufacturer`` from the device

    Returns a plain dict in the ``draft_report`` field shape (see
    ``thirty/agents/base.py``). Pure: it does not mutate ``state``.
    """
    device = _device_detail(state.get("device_key"))

    brand = _answer(state, "device_brand_name")
    # Prefer the reporter's own brand answer; fall back to the resolved device
    # brand only when the reporter did not supply one. Never downgrade a known
    # answer to UNKNOWN.
    if not _known(brand) and device:
        brand = device["brand"]

    model = _answer(state, "device_model")
    lot_or_serial = _answer(state, "lot_or_serial")
    description = _answer(state, "event_description")
    outcome = _answer(state, "patient_outcome")
    malfunctioned = _answer(state, "device_malfunctioned")
    event_date = _answer(state, "event_date")
    date_noticed = _answer(state, "date_noticed")
    follow_up = _answer(state, "follow_up_contact")

    product_code = device["product_code"] if device else UNKNOWN
    common = device["common"] if device else UNKNOWN
    manufacturer = _maker()

    draft = {
        "A1_patient_identifier": UNKNOWN,
        "A2_age": UNKNOWN,
        "A3_sex": UNKNOWN,
        "A4_weight": UNKNOWN,
        "B1_event_type": _event_type(malfunctioned),
        "B2_outcomes": _outcomes(outcome),
        "B3_date_of_event": event_date,
        "B5_event_description": description,
        "D1_brand_name": brand,
        "D2_common_device_name": common,
        "D2b_product_code": product_code,
        "D3_manufacturer": manufacturer,
        "D4_model": model,
        "D4_lot": lot_or_serial,
        "D4_serial": lot_or_serial,
        "H1_type_of_reportable_event": _reportable_event_type(outcome),
        "H3_device_evaluated": _device_evaluated(malfunctioned),
        "H10_manufacturer_narrative": UNKNOWN,
        "date_noticed": date_noticed,
        "follow_up_contact": follow_up,
        "follow_up_questions": [],
    }
    return draft


def _outcomes(patient_outcome):
    """Map the patient-outcome answer to the ``B2_outcomes`` list shape.

    A real answer becomes a one-item list; UNKNOWN / blank / "none" become an
    empty list (no outcome asserted). "none" is a real answer meaning the
    reporter stated there was no patient harm.
    """
    if not _known(patient_outcome):
        return []
    value = str(patient_outcome).strip().lower()
    if value == "none":
        return []
    return [value]


def _reportable_event_type(patient_outcome):
    """Derive ``H1_type_of_reportable_event`` from the patient outcome.

    death -> DEATH; hospitalisation/injury -> SERIOUS_INJURY; anything else
    (none / unknown / blank) -> UNKNOWN. We never upgrade an unknown outcome to
    a reportable category (the agent/pipeline classifies; this is only the draft).
    """
    if not _known(patient_outcome):
        return UNKNOWN
    value = str(patient_outcome).strip().lower()
    if value == "death":
        return "DEATH"
    if value in ("hospitalisation", "hospitalization", "injury"):
        return "SERIOUS_INJURY"
    return UNKNOWN


def _event_type(device_malfunctioned):
    """Derive ``B1_event_type`` from the device-malfunctioned answer.

    yes -> PRODUCT_PROBLEM; no/none -> ADVERSE_EVENT; unknown/blank -> UNKNOWN.
    """
    if not _known(device_malfunctioned):
        return UNKNOWN
    value = str(device_malfunctioned).strip().lower()
    if value in ("yes", "true"):
        return "PRODUCT_PROBLEM"
    if value in ("no", "false"):
        return "ADVERSE_EVENT"
    return UNKNOWN


def _device_evaluated(device_malfunctioned):
    """Map the device-malfunctioned answer to ``H3_device_evaluated`` (YES/NO/UNKNOWN)."""
    if not _known(device_malfunctioned):
        return UNKNOWN
    value = str(device_malfunctioned).strip().lower()
    if value in ("yes", "true"):
        return "YES"
    if value in ("no", "false"):
        return "NO"
    return UNKNOWN


# ---------------------------------------------------------------- field -> intake payload
# The literal marker stored for the English text when no model-backed agent is
# available to translate (design: Bilingual text storage, R2.6/R8.10).
TRANSLATION_PENDING_MARKER = "translation pending (no model)"


def to_intake_payload(state, free_text, english_text):
    """Build the dict passed to ``intake.submit`` — it does NOT call intake.

    Maps the interview state to the recognised intake payload fields (see
    ``intake.to_complaint``) following the design's field -> intake table:

    - ``source``        -> literal ``"reporter"`` (R6.1);
    - ``text``          -> the composed bilingual text (R6.3; see below);
    - ``device``        -> the resolved device brand (or the reporter's brand
      answer, else empty);
    - ``manufacturer``  -> ``MAKER`` (the fixed invented catalogue maker);
    - ``event_date``    -> ``YYYYMMDD`` or empty when missing/UNKNOWN;
    - ``product_code``  -> the resolved device product code (empty if unknown);
    - ``reporter``      -> the follow-up contact answer (empty when UNKNOWN);
    - ``external_id``   -> a deterministic id derived from the confirmed session
      so re-submitting the same confirmation de-duplicates to one complaint
      (Property 3);
    - ``reporter_type`` -> passed through (R6.2); also carried inside ``text``.

    ``free_text`` is the reporter's own description in their language.
    ``english_text`` is the English form supplied by the caller: an
    active-agent translation, the identical text when the language is English,
    or ``None`` when no translation is available. When it is ``None`` the
    composed text uses :data:`TRANSLATION_PENDING_MARKER`; the Front_Door never
    stores a fabricated/guessed translation (R2.8).

    Pure: builds and returns a dict only (no intake import, no I/O).
    """
    device = _device_detail(state.get("device_key"))
    reporter_type = state.get("reporter_type") or ""
    language = state.get("language") or ""

    english = english_text if (english_text is not None and str(english_text).strip()) else TRANSLATION_PENDING_MARKER
    original = free_text if free_text is not None else ""

    # Composed bilingual text: English-or-marker, then the original description
    # in the reporter's language, then the reporter type (design: intake payload).
    text = (
        f"{english}\n\n"
        f"[Original ({language})]: {original}\n"
        f"[Reporter type: {reporter_type}]"
    )

    follow_up = _answer(state, "follow_up_contact")
    reporter = follow_up if _known(follow_up) else ""

    brand_answer = _answer(state, "device_brand_name")
    if _known(brand_answer):
        device_name = brand_answer
    elif device:
        device_name = device["brand"]
    else:
        device_name = ""

    return {
        "source": "reporter",
        "text": text,
        "device": device_name,
        "manufacturer": _maker(),
        "event_date": normalize_event_date(_answer(state, "event_date")),
        "product_code": device["product_code"] if device else "",
        "reporter": reporter,
        "external_id": submission_id(state),
        "reporter_type": reporter_type,
    }


def submission_id(state):
    """A deterministic external_id for a confirmed interview.

    Derived from the stable parts of the confirmed session (session id when
    present, else the reporter type / language / device / answers) so one
    confirmation always yields the same ``external_id`` — hence the same
    ``vigil_id`` — and a re-POST is de-duplicated into a single complaint
    (Property 3). Pure and offline.
    """
    session_id = state.get("session_id")
    if session_id:
        return str(session_id)
    import hashlib
    import json
    key = {
        "reporter_type": state.get("reporter_type"),
        "language": state.get("language"),
        "device_key": state.get("device_key"),
        "answers": state.get("answers", {}),
    }
    blob = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return "rep-" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- loop driver
# Normalized markers returned by safe_next_question so the loop driver never has
# to inspect agent internals or catch exceptions itself.
_COMPLETE = "complete"     # the interview data set is fully collected
_MALFORMED = "__malformed__"  # the agent raised or returned an invalid value


def _is_valid_question(q):
    """True when ``q`` is a well-formed question object (dict with field/prompt/type)."""
    return (
        isinstance(q, dict)
        and isinstance(q.get("field"), str) and q["field"]
        and isinstance(q.get("prompt"), str) and q["prompt"]
        and isinstance(q.get("type"), str) and q["type"]
    )


def safe_next_question(agent, answers_view):
    """Call ``agent.next_question(answers_view)`` without ever raising.

    Returns a normalized marker so the loop driver can dispatch on it:

    - :data:`_COMPLETE` (the string ``"complete"``) — the agent returned the
      completion sentinel ``base.COMPLETE``;
    - a validated question dict — the agent returned a well-formed question
      object (has non-empty ``field``, ``prompt`` and ``type``);
    - :data:`_MALFORMED` — the agent raised, returned ``None``, returned a
      value that is neither the sentinel nor a valid question, or an otherwise
      malformed shape (Requirement 4.9).

    This is what guarantees termination and tolerance of a misbehaving agent:
    any exception or junk value is reduced to :data:`_MALFORMED`, which the loop
    driver turns into a terminal "malformed" end with answers preserved.
    """
    from thirty.agents.base import COMPLETE  # lazy: avoid importing agents at module load
    try:
        result = agent.next_question(answers_view)
    except Exception:
        return _MALFORMED
    if result == COMPLETE:
        return _COMPLETE
    if _is_valid_question(result):
        return result
    return _MALFORMED


def answers_view(state):
    """The read-only ``Answers_So_Far`` view handed to ``agent.next_question``.

    Shapes the interview state into the collection documented in
    ``thirty/agents/base.py``: ``{reporter_type, language, device, answers,
    asked}``. The device is resolved to its detail dict (or ``None``). Pure.
    """
    return {
        "reporter_type": state.get("reporter_type"),
        "language": state.get("language"),
        "device": _device_detail(state.get("device_key")),
        "answers": dict(state.get("answers", {})),
        "asked": list(state.get("asked", [])),
    }


def run_interview(agent, state, answer_source):
    """Pure loop driver: run the adaptive interview to a terminal state.

    This is the loop the Front_Door route runs, factored out so the property
    tests can drive it without Flask. It owns the 8-question cap
    :data:`QUESTION_CAP` and enforces it **independently of the agent**, so
    termination holds (Property 1) even for an adversarial agent that never
    returns the completion sentinel or a malformed agent that returns junk /
    raises.

    ``agent`` must expose ``next_question(answers_view)`` (see
    ``thirty/agents/base.py``); it is only ever called through
    :func:`safe_next_question`, so it may misbehave.

    ``answer_source`` is the caller-supplied source of answers, one per asked
    question. Its contract: it is a **callable** taking the current question
    object and returning a ``(value, idk)`` pair — ``value`` is the reporter's
    answer (ignored when ``idk`` is True) and ``idk`` is a bool that is True for
    an "I don't know" answer (stored as :data:`UNKNOWN`). For convenience an
    **iterator/iterable** of ``(value, idk)`` pairs is also accepted; it is
    advanced once per asked question. When the source is exhausted (a callable
    raising ``StopIteration`` or an iterator running out) the current question
    is answered as "I don't know" so the loop still makes progress and
    terminates.

    Returns the terminal state (``ended=True``) with ``end_reason`` one of
    ``"complete"`` (agent signalled completion), ``"cap"`` (the 8-question cap
    was reached), or ``"malformed"`` (the agent misbehaved). Pure: the input
    ``state`` is not mutated; a new state is returned.
    """
    # Accept either a callable(question) -> (value, idk) or an iterator/iterable
    # of (value, idk) pairs. Normalize to a single next_answer(question) callable.
    if callable(answer_source):
        def next_answer(question):
            try:
                return answer_source(question)
            except StopIteration:
                return (UNKNOWN, True)
    else:
        it = iter(answer_source)

        def next_answer(question):
            try:
                return next(it)
            except StopIteration:
                return (UNKNOWN, True)

    # Count asks here, in the driver, rather than trusting the state's
    # questions_asked (which counts *distinct* fields). An adversarial agent
    # that returns the same field on every turn must still be capped, so the
    # cap is enforced against the number of questions the driver has presented.
    asks = 0

    # First question.
    q = safe_next_question(agent, answers_view(state))

    while True:
        if q == _COMPLETE:
            return end_interview(state, "complete")
        if q == _MALFORMED:
            return end_interview(state, "malformed")

        # q is a validated question object: record an answer for it.
        value, idk = next_answer(q)
        state = dict(state)
        state["current"] = q
        state = record_answer(state, q["field"], value, idk)
        asks += 1

        # Enforce the cap independently of the agent. This is the guarantee that
        # no agent — adversarial or malformed — can run the loop past 8 asks,
        # even one that keeps re-asking the same field.
        if asks >= QUESTION_CAP:
            return end_interview(state, "cap")

        q = safe_next_question(agent, answers_view(state))

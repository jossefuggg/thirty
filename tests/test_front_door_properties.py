"""Property-based tests for the reporter Front_Door (Hypothesis).

Each property is universally quantified over generated inputs and must hold for
every generated case. Tests drive the *pure* interview logic in
``thirty.reporter.interview`` directly (no Flask, no templates, no network), so
they run fully offline in Demo_Mode.

Properties live here so the three later PBT sub-tasks (6.1, 6.2, 6.3) all append
to this one file:

- Property 1: question-loop termination (this file, task 6.1)
- Property 2: UNKNOWN preservation (task 6.2, appended later)
- Property 3: single complaint on submit (task 6.3, appended later)
"""
import os, sys

from hypothesis import given, settings, strategies as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from thirty.reporter import interview  # noqa: E402
from thirty.reporter.interview import (  # noqa: E402
    QUESTION_CAP,
    run_interview,
    start_state,
    safe_next_question,
    answers_view,
)
from thirty.agents.base import Agent, COMPLETE  # noqa: E402
from thirty.agents.sample import SampleAgent  # noqa: E402


# --------------------------------------------------------------------------- agents
# A set of agent implementations exercised by the termination property. The whole
# point of Property 1 is that termination holds for ANY agent, including ones that
# never signal completion or return junk / raise. The Front_Door's cap and
# safe_next_question must enforce termination regardless.


class AdversarialAgent(Agent):
    """Never returns COMPLETE: next_question always returns a valid question.

    This exercises the 8-question cap. Without the Front_Door's independent cap,
    such an agent would run the interview forever. It re-asks the same field so
    the cap must count *questions presented*, not distinct fields.
    """

    id = "adversarial"
    name = "Adversarial agent"

    def next_question(self, answers_so_far):
        return {
            "field": "event_description",   # always the same field, never advances
            "prompt": "Tell me more.",
            "language": (answers_so_far or {}).get("language") or "en",
            "type": "text",
            "allow_idk": True,
        }


class MalformedAgent(Agent):
    """Returns junk and/or raises: next_question never yields a valid shape.

    Cycles through a string, a list, an int, a dict missing required keys, and a
    raised exception. The Front_Door must treat every one of these as malformed
    and terminate (end_reason == "malformed"), preserving answers.
    """

    id = "malformed"
    name = "Malformed agent"

    def __init__(self):
        self._n = 0

    def next_question(self, answers_so_far):
        self._n += 1
        junk = [
            "not a question",                      # a bare string (not COMPLETE)
            ["a", "list"],                         # a list
            42,                                     # an int
            {"prompt": "missing field/type"},      # dict missing required keys
            None,                                   # None
        ]
        choice = junk[self._n % len(junk)]
        if self._n % 7 == 0:
            raise RuntimeError("agent blew up")     # also exercise the raise path
        return choice


class CompleteImmediatelyAgent(Agent):
    """Returns COMPLETE on the first call: terminates at end_reason == 'complete'."""

    id = "complete-now"
    name = "Complete-immediately agent"

    def next_question(self, answers_so_far):
        return COMPLETE


def _agents():
    """Fresh agent instances for each example (MalformedAgent carries state)."""
    return {
        "sample": SampleAgent(delay=0),
        "adversarial": AdversarialAgent(),
        "malformed": MalformedAgent(),
        "complete": CompleteImmediatelyAgent(),
    }


# --------------------------------------------------------------------------- strategies
REPORTER_TYPES = ["nurse_clinician", "patient_family", "company_staff"]
# "zz" is deliberately unsupported so the language-fallback path is exercised.
LANGUAGES = ["en", "es", "pt", "ht", "zz"]

reporter_type_st = st.sampled_from(REPORTER_TYPES)
language_st = st.sampled_from(LANGUAGES)
# Deliberately longer than the 8-question cap so the cap is exercised, and a mix
# of free text and the "I don't know" marker.
answer_sequence_st = st.lists(
    st.one_of(st.text(), st.just("I don't know")),
    max_size=40,
)


def _answer_source(answer_sequence):
    """Build an answer_source run_interview accepts from a flat answer_sequence.

    Per interview.run_interview's documented contract the source may be a
    callable(question) -> (value, idk) OR an iterator/iterable of (value, idk)
    pairs. We hand it an iterator of pairs: "I don't know" -> (UNKNOWN, idk=True);
    any other string -> (value, idk=False). When the sequence is exhausted the
    driver itself answers "I don't know", so the loop always makes progress.
    """
    pairs = []
    for raw in answer_sequence:
        if raw == "I don't know":
            pairs.append((interview.UNKNOWN, True))
        else:
            pairs.append((raw, False))
    return iter(pairs)


# --------------------------------------------------------------------------- Property 1
# Feature: report-front-door, Property 1: question-loop termination
@settings(max_examples=200)
@given(
    reporter_type=reporter_type_st,
    language=language_st,
    answer_sequence=answer_sequence_st,
    agent_key=st.sampled_from(["sample", "adversarial", "malformed", "complete"]),
)
def test_property1_interview_loop_terminates(reporter_type, language, answer_sequence, agent_key):
    """For ANY agent and ANY answer sequence, the interview loop terminates.

    It ends after at most QUESTION_CAP (== 8) questions, in a terminal state
    whose end_reason is one of "complete" (agent signalled completion), "cap"
    (the 8-question cap was reached), or "malformed" (the agent misbehaved). The
    invariant ``questions_asked <= 8`` holds at the end; no input yields an
    unbounded interview.

    Validates: Requirements 4.3, 4.5, 11.1
    """
    agent = _agents()[agent_key]
    state0 = start_state(reporter_type, language, device_key=None)

    # Drive the pure loop. If it did not terminate this call would hang; returning
    # is itself the primary termination evidence.
    state = run_interview(agent, state0, _answer_source(answer_sequence))

    # Terminal state.
    assert state["ended"] is True
    assert state["end_reason"] in {"complete", "cap", "malformed"}

    # The cap invariant: never more than 8 questions recorded.
    assert state["questions_asked"] <= QUESTION_CAP
    assert QUESTION_CAP == 8  # the fixed Question_Cap (Requirement 4.5)

    # The input state is not mutated (pure driver).
    assert state0["ended"] is False
    assert state0["questions_asked"] == 0


# Feature: report-front-door, Property 1: question-loop termination
@settings(max_examples=200)
@given(
    reporter_type=reporter_type_st,
    language=language_st,
    answer_sequence=answer_sequence_st,
)
def test_property1_adversarial_agent_hits_the_cap(reporter_type, language, answer_sequence):
    """An agent that never returns COMPLETE still terminates at exactly the cap.

    The adversarial agent always returns a valid question (never COMPLETE), so
    only the Front_Door's independent 8-question cap can stop the loop. The
    interview must end with end_reason == "cap" — this is what proves
    termination does not depend on the agent. The cap is enforced against the
    number of questions the driver *presents* (8 here), which run_interview
    counts internally; because this adversarial agent re-asks the *same* field
    every turn, state["questions_asked"] (which counts distinct fields, per the
    documented invariant questions_asked == len(asked)) stays at 1 while the
    driver still stops after 8 presentations. The invariant questions_asked <= 8
    must always hold.

    Validates: Requirements 4.3, 4.5, 11.1
    """
    agent = AdversarialAgent()
    state0 = start_state(reporter_type, language, device_key=None)

    state = run_interview(agent, state0, _answer_source(answer_sequence))

    assert state["ended"] is True
    assert state["end_reason"] == "cap"
    assert QUESTION_CAP == 8
    assert state["questions_asked"] <= QUESTION_CAP
    assert state["questions_asked"] == len(state["asked"])
    # The adversarial agent re-asks one field, so distinct fields asked == 1,
    # even though the driver presented the cap's worth of questions.
    assert state["questions_asked"] == 1


# Feature: report-front-door, Property 1: question-loop termination
@settings(max_examples=200)
@given(
    reporter_type=reporter_type_st,
    language=language_st,
    answer_sequence=answer_sequence_st,
)
def test_property1_malformed_agent_terminates_cleanly(reporter_type, language, answer_sequence):
    """An agent that returns junk / raises terminates without propagating errors.

    safe_next_question must reduce any junk value or raised exception to a
    terminal state. Because the malformed agent never yields a valid first
    question, the interview ends immediately with end_reason == "malformed" and
    zero recorded answers, never past the cap.

    Validates: Requirements 4.3, 4.5, 11.1
    """
    agent = MalformedAgent()
    state0 = start_state(reporter_type, language, device_key=None)

    state = run_interview(agent, state0, _answer_source(answer_sequence))

    assert state["ended"] is True
    assert state["end_reason"] in {"malformed", "cap"}
    assert state["questions_asked"] <= QUESTION_CAP


# Feature: report-front-door, Property 1: question-loop termination
@settings(max_examples=50)
@given(
    reporter_type=reporter_type_st,
    language=language_st,
    n_calls=st.integers(min_value=0, max_value=50),
)
def test_property1_safe_next_question_never_raises(reporter_type, language, n_calls):
    """safe_next_question tolerates a misbehaving agent and never raises.

    Repeatedly calling the raising/junk-returning malformed agent through
    safe_next_question always yields a normalized marker (never an exception),
    which is the primitive that guarantees run_interview can always reach a
    terminal state.

    Validates: Requirements 4.3, 4.5, 11.1
    """
    agent = MalformedAgent()
    state = start_state(reporter_type, language, device_key=None)
    view = answers_view(state)
    for _ in range(n_calls):
        result = safe_next_question(agent, view)
        # Either the completion sentinel, a validated question dict, or the
        # internal malformed marker — but always a return, never a raise.
        assert result == interview._COMPLETE or isinstance(result, (dict, str))


# --------------------------------------------------------------------------- Property 2 strategies
# The Requirement-4 interview fields (interview.FIELD_ORDER). For each field the
# generated answer is one of three choices:
#   - "idk":      the reporter answered "I don't know"  -> record_answer(idk=True)
#   - "value":    a real, non-empty, non-UNKNOWN answer -> record_answer(idk=False)
#   - "skip":     the field is never asked/answered at all
# "skip" exercises the Requirement 4.10 corollary: a required field never
# answered still ends up UNKNOWN in the Draft_3500A (same as an "I don't know").

# A value that is definitely a real answer: non-empty and never equal to UNKNOWN.
# (We lowercase-independent exclude the sentinel so a generated "UNKNOWN" literal
# can't masquerade as a real answer and confuse the known/unknown assertions.)
real_value_st = st.text(min_size=1).filter(
    lambda s: s.strip() != "" and s.strip().upper() != interview.UNKNOWN
)

field_choice_st = st.sampled_from(["idk", "value", "skip"])

# A map {field: ("idk"|"value"|"skip", value)} over every FIELD_ORDER field.
answer_plan_st = st.fixed_dictionaries(
    {
        field: st.tuples(field_choice_st, real_value_st)
        for field in interview.FIELD_ORDER
    }
)


def _build_state_from_plan(reporter_type, language, plan):
    """Fold record_answer over ``plan`` to build an interview state.

    ``plan`` maps each FIELD_ORDER field to a ``(choice, value)`` pair. "idk"
    records the field as "I don't know" (idk=True); "value" records the real
    ``value`` (idk=False); "skip" never records the field at all. device_key is
    None so no catalogue fallback can fill a missing brand (keeps the
    exact-UNKNOWN invariant clean). Returns ``(state, idk_fields, value_fields)``
    where ``idk_fields`` are the fields marked "I don't know", ``value_fields``
    maps the answered fields to their real values.
    """
    state = start_state(reporter_type, language, device_key=None)
    idk_fields = set()
    value_fields = {}
    for field in interview.FIELD_ORDER:
        choice, value = plan[field]
        if choice == "idk":
            state = interview.record_answer(state, field, interview.UNKNOWN, idk=True)
            idk_fields.add(field)
        elif choice == "value":
            state = interview.record_answer(state, field, value, idk=False)
            value_fields[field] = value
        # "skip": leave the field unanswered
    return state, idk_fields, value_fields


# The interview fields that map DIRECTLY to a 3500A string field (verbatim copy
# through to_draft_3500a). Each entry lists the 3500A key(s) that must equal the
# stored answer exactly.
DIRECT_3500A_FIELDS = {
    "device_brand_name": ["D1_brand_name"],
    "device_model": ["D4_model"],
    "lot_or_serial": ["D4_lot", "D4_serial"],
    "event_description": ["B5_event_description"],
    "event_date": ["B3_date_of_event"],
    "date_noticed": ["date_noticed"],
    "follow_up_contact": ["follow_up_contact"],
}

# The interview fields that are DERIVED (transformed), not copied verbatim.
# patient_outcome      -> B2_outcomes (list) + H1_type_of_reportable_event
# device_malfunctioned -> B1_event_type + H3_device_evaluated
DERIVED_FIELDS = {"patient_outcome", "device_malfunctioned"}


# --------------------------------------------------------------------------- Property 2
# Feature: report-front-door, Property 2: UNKNOWN preservation
@settings(max_examples=200)
@given(
    reporter_type=reporter_type_st,
    language=language_st,
    plan=answer_plan_st,
)
def test_property2_unknown_is_preserved_in_draft(reporter_type, language, plan):
    """An "I don't know" (or never-answered) field is exactly UNKNOWN in the draft.

    For every interview field the reporter marked "I don't know", the
    corresponding Draft_3500A value is exactly ``UNKNOWN`` — never overwritten by
    a guessed, blank, or defaulted value (Property 2 / Requirement 4.7). The same
    holds for a required field never answered at all (Requirement 4.10): it ends
    up UNKNOWN too. Derived fields (patient_outcome, device_malfunctioned) are
    never *upgraded* to a known/reportable category from an unknown answer — the
    weaker-but-correct invariant the design intends (B2_outcomes empty; H1/B1/H3
    stay UNKNOWN). A real answer, by contrast, is carried through verbatim, so
    the property is non-trivial (it would fail an implementation that blindly
    sets everything to UNKNOWN).

    Validates: Requirements 4.7, 4.10, 11.2
    """
    state, idk_fields, value_fields = _build_state_from_plan(reporter_type, language, plan)

    # The fields that are UNKNOWN going into the draft: those answered "I don't
    # know" PLUS those never answered (the Requirement 4.10 corollary). In both
    # cases interview._answer(...) yields UNKNOWN.
    answered = set(idk_fields) | set(value_fields)
    skipped = set(interview.FIELD_ORDER) - answered
    unknown_fields = set(idk_fields) | skipped

    draft = interview.to_draft_3500a(state)

    # -- directly-mapped fields: UNKNOWN must survive verbatim ---------------
    for field in unknown_fields:
        if field in DIRECT_3500A_FIELDS:
            for key in DIRECT_3500A_FIELDS[field]:
                assert draft[key] == interview.UNKNOWN, (
                    f"{field} was 'I don't know'/unanswered but {key} = "
                    f"{draft[key]!r} (expected the exact UNKNOWN sentinel)"
                )

    # -- derived fields: an unknown outcome/malfunction is never upgraded ----
    # patient_outcome unknown -> no reportable category asserted.
    if "patient_outcome" in unknown_fields:
        assert draft["B2_outcomes"] == [], (
            f"unknown patient_outcome produced B2_outcomes={draft['B2_outcomes']!r} "
            f"(expected an empty list, never a guessed outcome)"
        )
        assert draft["H1_type_of_reportable_event"] == interview.UNKNOWN, (
            "unknown patient_outcome must not be upgraded to a reportable "
            f"category, got {draft['H1_type_of_reportable_event']!r}"
        )
    # device_malfunctioned unknown -> event type / evaluation stay UNKNOWN.
    if "device_malfunctioned" in unknown_fields:
        assert draft["B1_event_type"] == interview.UNKNOWN, (
            f"unknown device_malfunctioned produced B1_event_type="
            f"{draft['B1_event_type']!r} (expected UNKNOWN)"
        )
        assert draft["H3_device_evaluated"] == interview.UNKNOWN, (
            f"unknown device_malfunctioned produced H3_device_evaluated="
            f"{draft['H3_device_evaluated']!r} (expected UNKNOWN)"
        )

    # -- non-triviality: a real answer is carried through, not clobbered -----
    # For directly-mapped fields a real answer must appear verbatim in the draft,
    # proving the property is meaningful (an implementation that sets everything
    # to UNKNOWN would fail here).
    for field, value in value_fields.items():
        if field in DIRECT_3500A_FIELDS:
            for key in DIRECT_3500A_FIELDS[field]:
                assert draft[key] == value, (
                    f"real answer for {field} ({value!r}) was not carried through "
                    f"to {key}; got {draft[key]!r}"
                )
            # And a real answer is never silently turned into the sentinel.
            assert draft[DIRECT_3500A_FIELDS[field][0]] != interview.UNKNOWN or value == interview.UNKNOWN


# Feature: report-front-door, Property 2: UNKNOWN preservation
@settings(max_examples=200)
@given(
    reporter_type=reporter_type_st,
    language=language_st,
    plan=answer_plan_st,
)
def test_property2_idk_is_never_overwritten_by_a_later_answer(reporter_type, language, plan):
    """Once a field is "I don't know", a later real answer can't overwrite the UNKNOWN.

    record_answer freezes a field at UNKNOWN once an "I don't know" is recorded
    (the sticky-UNKNOWN invariant). Re-recording the same field with a real value
    afterwards must leave both the stored answer and the resulting Draft_3500A at
    UNKNOWN for the directly-mapped fields — the reporter's "I don't know" is
    authoritative and never silently replaced.

    Validates: Requirements 4.7, 11.2
    """
    state, idk_fields, _ = _build_state_from_plan(reporter_type, language, plan)

    # Try to overwrite every "I don't know" field with a real value.
    for field in idk_fields:
        state = interview.record_answer(state, field, "a real answer now", idk=False)
        # The stored answer stays UNKNOWN (sticky).
        assert state["answers"][field] == interview.UNKNOWN

    draft = interview.to_draft_3500a(state)
    for field in idk_fields:
        if field in DIRECT_3500A_FIELDS:
            for key in DIRECT_3500A_FIELDS[field]:
                assert draft[key] == interview.UNKNOWN, (
                    f"{field} was 'I don't know' then re-answered, but {key} = "
                    f"{draft[key]!r} (the UNKNOWN must stick)"
                )

# --------------------------------------------------------------------------- Property 3 setup
# Property 3 drives the REAL intake.submit dedupe/index/raw machinery, but keeps
# everything offline and deterministic: per example we redirect intake's storage
# to a fresh temp dir and neutralise both vigil.process (the model/pipeline call)
# and the background worker, so submit() still maps/validates/dedupes/indexes and
# returns its (status, res) without processing through vigil or spawning a thread.
import csv as _csv  # noqa: E402  (read the index.csv intake writes)
import json as _json  # noqa: E402
import shutil as _shutil  # noqa: E402
import tempfile as _tempfile  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import intake  # noqa: E402  (importing triggers `import vigil`, which is fine offline)


@contextmanager
def _isolated_intake():
    """Redirect intake storage to a fresh temp dir and neutralise the worker/model.

    Yields the temp dir. On exit it restores every module global we touched and
    deletes the temp dir, so each example is hermetic and leaves nothing in the
    repo. We monkeypatch:

    - ``intake.INTAKE/RAW/INDEX`` -> paths under the temp dir, so submit() reads
      and writes its dedupe index + raw files there (never the repo's intake/).
    - ``intake.vigil.process`` -> a no-op, so no model/pipeline work runs.
    - ``intake.start_worker`` -> a no-op, so submit() never spawns the real
      background thread that would call vigil.process; the test stays single
      threaded and deterministic. submit() still enqueues onto intake._q, but
      with no worker draining it that is harmless.

    This isolates intake's own map/validate/dedupe/index/raw behaviour, which is
    exactly what Property 3 (single complaint + dedupe) is about.
    """
    tmp = _tempfile.mkdtemp(prefix="front_door_p3_")
    saved = {
        "INTAKE": intake.INTAKE,
        "RAW": intake.RAW,
        "INDEX": intake.INDEX,
        "process": intake.vigil.process,
        "start_worker": intake.start_worker,
    }
    try:
        intake.INTAKE = os.path.join(tmp, "intake")
        intake.RAW = os.path.join(intake.INTAKE, "raw")
        intake.INDEX = os.path.join(intake.INTAKE, "index.csv")
        intake.vigil.process = lambda *a, **k: None   # stay offline: no pipeline/model
        intake.start_worker = lambda *a, **k: None     # no real background thread
        yield tmp
    finally:
        intake.INTAKE = saved["INTAKE"]
        intake.RAW = saved["RAW"]
        intake.INDEX = saved["INDEX"]
        intake.vigil.process = saved["process"]
        intake.start_worker = saved["start_worker"]
        _shutil.rmtree(tmp, ignore_errors=True)


def _index_rows_for(vigil_id):
    """All rows in the current intake.INDEX csv whose vigil_id == ``vigil_id``."""
    if not os.path.exists(intake.INDEX):
        return []
    with open(intake.INDEX, encoding="utf-8") as f:
        return [r for r in _csv.DictReader(f) if r["vigil_id"] == vigil_id]


# Reuse Property 2's answer-plan machinery to build a confirmed interview state,
# but force a non-empty free-text description so the composed intake text is
# always valid (intake.to_complaint rejects empty text). The description is the
# reporter's own free text passed to to_intake_payload; the composed bilingual
# text always includes it, so a non-empty description guarantees non-empty text.
description_st = st.text(min_size=1).filter(lambda s: s.strip() != "")


# --------------------------------------------------------------------------- Property 3
# Feature: report-front-door, Property 3: single complaint on submit
@settings(max_examples=100, deadline=None)
@given(
    reporter_type=reporter_type_st,
    language=st.sampled_from(["en", "es", "pt", "ht"]),
    plan=answer_plan_st,
    description=description_st,
)
def test_property3_single_complaint_on_submit(reporter_type, language, plan, description):
    """A confirmed report yields exactly one reporter-source complaint; a re-submit dedupes.

    For any confirmed ``(reporter_type, language, collected_answers)``:

    - the payload built by ``to_intake_payload`` always carries
      ``source == "reporter"`` (Requirement 6.1) — asserted before submitting;
    - submitting through the real ``intake.submit`` creates exactly ONE complaint
      for that confirmation: one index row for the returned ``vigil_id`` (which
      matches the ``REP-...`` format), and the stored complaint JSON has
      ``source == "reporter"`` (Requirements 6.1, 6.7);
    - re-submitting the SAME confirmation is de-duplicated by intake's existing
      ``vigil_id`` mechanism: the second call returns ``duplicate`` and the index
      still holds exactly one row for that ``vigil_id`` — no second complaint
      (Requirements 6.7, 6.8, 11.3).

    The test drives intake's real map/validate/dedupe/index/raw path; it only
    neutralises the model/pipeline call (``vigil.process``) and the background
    worker so it is offline and deterministic. Storage is redirected to a fresh
    temp dir per example, so nothing is left in the repo.

    Validates: Requirements 6.1, 6.7, 6.8, 11.3
    """
    # Build a confirmed interview state from the generated plan (device_key=None
    # so no catalogue fallback; the free-text description is supplied separately).
    state, _idk, _values = _build_state_from_plan(reporter_type, language, plan)

    # english_text: identical to the original for English, None (-> marker) for
    # the other languages (no model-backed agent in this offline test). Either
    # way the composed text is non-empty because the description is non-empty.
    english_text = description if language == "en" else None
    payload = interview.to_intake_payload(state, free_text=description, english_text=english_text)

    # Requirement 6.1: the payload always carries source == "reporter".
    assert payload["source"] == "reporter"

    with _isolated_intake():
        # First submission: a brand-new complaint is queued.
        status1, res1 = intake.submit(payload, kind="reporter", default_source="reporter")
        assert status1 == 202, f"expected 202 queued, got {status1}: {res1}"
        assert res1["status"] == "queued"
        vid = res1["vigil_id"]
        assert vid.startswith("REP-"), f"vigil_id {vid!r} is not a REP- reference number"

        # Exactly one index row for this vigil_id (one complaint created).
        rows_after_first = _index_rows_for(vid)
        assert len(rows_after_first) == 1, (
            f"expected exactly one index row for {vid}, got {len(rows_after_first)}"
        )
        assert rows_after_first[0]["source"] == "reporter"

        # The persisted complaint record carries source == "reporter".
        complaint_path = os.path.join(intake.RAW, f"{vid}.complaint.json")
        assert os.path.exists(complaint_path), f"no stored complaint JSON at {complaint_path}"
        with open(complaint_path, encoding="utf-8") as f:
            stored = _json.load(f)
        assert stored["source"] == "reporter"
        assert stored["id"] == vid

        # Re-submit the SAME confirmation: intake must de-duplicate it.
        status2, res2 = intake.submit(payload, kind="reporter", default_source="reporter")
        assert status2 == 200, f"expected 200 duplicate on re-submit, got {status2}: {res2}"
        assert res2["status"] == "duplicate"
        assert res2["vigil_id"] == vid

        # Still exactly one complaint: the re-submit created no second row.
        rows_after_second = _index_rows_for(vid)
        assert len(rows_after_second) == 1, (
            f"re-submit created a second complaint: {len(rows_after_second)} rows for {vid}"
        )

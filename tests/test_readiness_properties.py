"""Property-based tests for the device-readiness category engine (Hypothesis).

The answer space is the full cross-product of the six Step 1 questions, so these
properties are effectively exhaustive. Each test is tagged with the property it
validates. See .kiro/specs/device-readiness.
"""
import shutil
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from thirty.readiness import engine, openfda

CLAIMS = st.sets(st.sampled_from(engine.CLAIM_OPTIONS))
BOOLS = st.booleans()
WORST = st.sampled_from(engine.WORST_OUTCOMES)
USERS = st.sampled_from(engine.USERS)
PREDICATE = st.sampled_from(engine.PREDICATE)


def _answers(claims, invasive, disease, worst, users, predicate):
    return engine.normalize({
        "claims": list(claims), "invasive": invasive, "disease_claim": disease,
        "worst": worst, "users": users, "predicate": predicate,
    })


# Feature: device-readiness, Property 1: exactly one category.
@settings(max_examples=300)
@given(CLAIMS, BOOLS, BOOLS, WORST, USERS, PREDICATE)
def test_property_1_exactly_one_category(claims, invasive, disease, worst, users, predicate):
    res = engine.categorize(_answers(claims, invasive, disease, worst, users, predicate))
    assert res["category"] in engine.CATEGORIES


# Feature: device-readiness, Property 1 (totality on malformed raw input).
@settings(max_examples=200)
@given(st.dictionaries(st.text(), st.one_of(st.text(), st.integers(), st.booleans(), st.none())))
def test_property_1_totality_on_junk(raw):
    res = engine.categorize(engine.normalize(raw))
    assert res["category"] in engine.CATEGORIES
    assert res["disclaimer"]
    assert len(res["citations"]) >= 1


# Feature: device-readiness, Property 2: never general wellness on a device trigger.
@settings(max_examples=300)
@given(CLAIMS, BOOLS, BOOLS, WORST, USERS, PREDICATE)
def test_property_2_never_wellness_on_trigger(claims, invasive, disease, worst, users, predicate):
    trigger = bool(set(claims) & {"flag", "diagnose", "treat", "replace"}) or invasive or disease
    res = engine.categorize(_answers(claims, invasive, disease, worst, users, predicate))
    if trigger:
        assert res["category"] != "general_wellness"


# Feature: device-readiness, Property 2b: a body-measurement feature with worst
# harm serious injury or death is never Borderline or general wellness (general
# wellness and the borderline path cover only low-risk products).
@settings(max_examples=300)
@given(CLAIMS, BOOLS, BOOLS, st.sampled_from(("serious", "death")), USERS, PREDICATE)
def test_property_2b_high_risk_measurement_is_a_device(claims, invasive, disease, worst, users, predicate):
    claims = set(claims) | {"measure"}  # ensure a body-measurement claim is present
    res = engine.categorize(_answers(claims, invasive, disease, worst, users, predicate))
    assert res["category"] not in ("borderline", "general_wellness")
    assert res["category"] in ("class_i", "class_ii", "class_iii")


# Feature: device-readiness, Property 3: death is never Class I.
@settings(max_examples=300)
@given(CLAIMS, BOOLS, BOOLS, USERS, PREDICATE)
def test_property_3_death_never_class_i(claims, invasive, disease, users, predicate):
    res = engine.categorize(_answers(claims, invasive, disease, "death", users, predicate))
    assert res["category"] != "class_i"


# Feature: device-readiness, Property 4: every result carries the disclaimer and a citation.
@settings(max_examples=300)
@given(CLAIMS, BOOLS, BOOLS, WORST, USERS, PREDICATE)
def test_property_4_disclaimer_and_citation(claims, invasive, disease, worst, users, predicate):
    res = engine.categorize(_answers(claims, invasive, disease, worst, users, predicate))
    assert res["disclaimer"] == engine.DISCLAIMER
    assert len(res["citations"]) >= 1
    cat = engine.load_rules()["citations"]
    for c in res["citations"]:
        assert c["key"] in cat  # only catalogue citations, never invented


# Feature: device-readiness, Property 5: the checklist always includes 21 CFR 803.
@settings(max_examples=100)
@given(CLAIMS, BOOLS, BOOLS, WORST, USERS, PREDICATE)
def test_property_5_checklist_always_803(claims, invasive, disease, worst, users, predicate):
    # The checklist is category-independent, but assert it per generated result.
    engine.categorize(_answers(claims, invasive, disease, worst, users, predicate))
    checklist = engine.day_one_checklist()
    assert any(any(c["key"] == "reg_803" for c in item["citations"]) for item in checklist)


# Feature: device-readiness, Property 6: empty / missing cache is safe and visible.
@settings(max_examples=100)
@given(st.text(min_size=0, max_size=6))
def test_property_6_empty_cache_safe(code):
    # Point both cache dirs at an empty temp folder so nothing resolves. We swap
    # the module functions directly (not the monkeypatch fixture) because
    # Hypothesis re-runs the body many times and cannot take function-scoped
    # fixtures as generated arguments.
    empty = tempfile.mkdtemp(prefix="rd-empty-")
    orig_rt, orig_sh = openfda._runtime_cache_dir, openfda._shipped_cache_dir
    openfda._runtime_cache_dir = lambda: empty
    openfda._shipped_cache_dir = lambda: empty
    try:
        s = openfda.load_signals(code)
        assert s["has_data"] is False
        assert s["device_problems"] == [] and s["recalls"] == []
    finally:
        openfda._runtime_cache_dir = orig_rt
        openfda._shipped_cache_dir = orig_sh
        shutil.rmtree(empty, ignore_errors=True)


# Feature: device-readiness, Property 7: every where-to-look-first item shows count and source.
@settings(max_examples=200)
@given(CLAIMS, USERS)
def test_property_7_wlf_count_and_source(claims, users):
    # Synthetic signals with data so there is something to map.
    signals = {
        "code": "TEST", "has_data": True,
        "device_problems": [
            {"term": "Incorrect Measurement", "count": 100},
            {"term": "Wireless Communication Problem", "count": 80},
            {"term": "Break", "count": 5},
        ],
        "patient_problems": [], "reports_per_year": [], "recalls": [],
    }
    answers = engine.normalize({"claims": list(claims), "users": users})
    items = openfda.where_to_look_first(signals, answers)
    for it in items:
        assert isinstance(it["count"], int)
        assert it["source"]
        assert "label" in it and it["label"]

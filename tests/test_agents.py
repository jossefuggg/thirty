"""The agent interface: sample agent shapes, registry selection, local-model agent against a fake server."""
import json, os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty import config, sample_data  # noqa: E402
from thirty.agents import get_agent, make_agent, set_agent  # noqa: E402
from thirty.agents.base import NoAgent  # noqa: E402
from thirty.agents.sample import SampleAgent  # noqa: E402

KEYS = {"decision", "category", "reason", "remedial_action_needed", "missing_info", "confidence"}


def test_registry_follows_config(monkeypatch):
    monkeypatch.setenv("THIRTY_AGENT", "sample"); set_agent(None)
    assert get_agent().id == "sample" and config.demo_mode()
    monkeypatch.setenv("THIRTY_AGENT", "none")
    assert isinstance(get_agent(), NoAgent) and not config.demo_mode()
    monkeypatch.delenv("THIRTY_AGENT"); monkeypatch.delenv("VIGIL_LLM_BASE", raising=False); monkeypatch.delenv("VIGIL_LLM_MODEL", raising=False)
    assert config.agent_id() == "sample", "no model configured -> demo mode"
    monkeypatch.setenv("VIGIL_LLM_BASE", "http://localhost:8000/v1")
    assert config.agent_id() == "local"
    monkeypatch.setenv("THIRTY_AGENT", "sample"); set_agent(None)


def test_sample_agent_catalogue_and_fallback():
    a = SampleAgent(delay=0)
    for item in sample_data.CATALOGUE + sample_data.INCOMING:
        c = sample_data.complaint(item)
        res = a.classify(c)
        assert set(res) == KEYS and res["decision"] == item[2] and 0 <= res["confidence"] <= 100
        f = a.draft_report(c, {"decision": res["decision"], "category": res["category"], "deadline_days": 30, "missing": ""})
        assert f["D1_brand_name"] == c["device"] and isinstance(f["follow_up_questions"], list)
    assert a.classify({"id": "?", "text": "smoke came out of the unit and the patient was burned"})["remedial_action_needed"] is True
    assert a.classify({"id": "?", "text": "The strap is a bit loose but everything works fine and nobody was affected in any way."})["decision"] == "NOT_REPORTABLE"
    assert a.classify({"id": "?", "text": "it broke"})["decision"] == "NEEDS_INFO"
    qs, msg = a.follow_up_questions({"id": "NW-24001"}, [])
    assert len(qs) == 3 and msg


def test_sample_agent_delay_is_configurable(monkeypatch):
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0.01")
    import time
    t = time.perf_counter(); SampleAgent().classify({"id": "NW-24001"}); assert time.perf_counter() - t >= 0.01


def test_seed_is_relative_to_today_and_covers_every_state(tmp_path):
    import csv, datetime as dt
    ids = sample_data.seed(str(tmp_path), with_pdfs=False)
    rows = list(csv.DictReader(open(tmp_path / "decisions.csv")))
    assert len(ids) == len(rows) == 40
    today = dt.date.today()
    dues = [(dt.date.fromisoformat(r["due_date"]) - today).days for r in rows if r["due_date"]]
    assert min(dues) < 0 < max(dues) and 0 in dues, "overdue, due today and future deadlines"
    assert {r["decision"] for r in rows} == {"REPORTABLE", "NEEDS_INFO", "NOT_REPORTABLE"}
    assert sum(r["status"].startswith("APPROVED") for r in rows) >= 5 and sum(r["status"].startswith("INFO REQUESTED") for r in rows) >= 3
    assert sum(r["deadline_days"] == "5" for r in rows) >= 2 and {r["priority"] for r in rows} >= {"URGENT", "HIGH", "NORMAL"}
    assert sample_data.seed_date(str(tmp_path)) == today
    assert os.path.exists(tmp_path / "history.csv") and len(list(csv.DictReader(open(tmp_path / "actions.csv")))) >= 8
    text = " ".join(r["text"] + r["device"] for r in rows).lower()
    for real in ("philips", "dreamstation", "medtronic", "respironics"):
        assert real not in text


class _FakeLLM:
    """Minimal OpenAI-compatible server stand-in for requests.get/post."""
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def get(self, url, timeout=0, headers=None):
        self.calls.append(("GET", url)); return self

    def post(self, url, timeout=0, json=None, headers=None):
        self.calls.append(("POST", url, json)); return self

    def raise_for_status(self): pass

    def json(self):
        if self.calls[-1][0] == "GET":
            return {"data": [{"id": "local/test-model"}]}
        return {"choices": [{"message": {"content": self.answer}}]}


def test_local_model_agent_parses_model_json(monkeypatch):
    from thirty.agents import local_model as lm
    fake = _FakeLLM('<think>hmm</think>{"decision": "REPORTABLE", "category": "MALFUNCTION", "reason": "r", "remedial_action_needed": false, "missing_info": ["lot number"], "confidence": 77}')
    monkeypatch.setattr(lm.requests, "get", fake.get); monkeypatch.setattr(lm.requests, "post", fake.post)
    monkeypatch.setattr(lm, "LLM_MODEL", "")
    a = make_agent("local")
    res = a.classify({"text": "t", "device": "d", "event_date": "", "received": ""})
    assert res["decision"] == "REPORTABLE" and res["missing_info"] == ["lot number"]
    body = fake.calls[-1][2]
    assert body["temperature"] == 0 and body["model"] == "local/test-model" and "21 CFR 803" in body["messages"][0]["content"]
    fake.answer = "not json"
    assert a.classify({"text": "t", "device": "d", "event_date": "", "received": ""})["decision"] == "NEEDS_INFO"
    h = a.health()
    assert h["ok"] and h["name"] == "test-model"


def test_pipeline_uses_the_registry(tmp_path, monkeypatch):
    """vigil.process() runs end to end on the sample agent: no model, PDF drafted, deadline set."""
    import importlib.util
    monkeypatch.setenv("THIRTY_AGENT", "sample"); monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0"); set_agent(None)
    spec = importlib.util.spec_from_file_location("vigil_e2e", os.path.join(ROOT, "vigil.py"))
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
    v.LOG, v.REPORTS, v.OUTBOX, v.HISTORY, v.SANDBOX = str(tmp_path / "d.csv"), str(tmp_path / "r"), str(tmp_path / "o.txt"), str(tmp_path / "h.csv"), ""
    c = sample_data.incoming_complaints()[3]  # the warming-blanket fire
    row = v.process(c)
    assert row["decision"] == "REPORTABLE" and row["deadline_days"] == 5 and row["due_date"]
    assert os.path.exists(tmp_path / "r" / f"MDR_{c['id']}.pdf") or v.FPDF is None
    assert [r["id"] for r in v.read_log()] == [c["id"]]


# ---------------------------------------------------------------- reporter front door: next_question / translate_to_english
from thirty.agents.base import COMPLETE  # noqa: E402
from thirty.agents.local_model import LocalModelAgent  # noqa: E402
from thirty.agents.claude_model import ClaudeAgent  # noqa: E402

_LANGS = ("en", "es", "pt", "ht")


def _all_agents():
    """One instance of every agent (no network touched by construction)."""
    return [SampleAgent(delay=0), NoAgent(), make_agent("local"), LocalModelAgent(), ClaudeAgent()]


def _answers_view(language, asked):
    """The read-only Answers_So_Far view next_question reads (interview.answers_view shape)."""
    return {"reporter_type": "patient_family", "language": language, "device": None, "answers": {}, "asked": list(asked)}


def _is_question(q):
    """A well-formed next_question object: non-empty field/prompt/type and the allow_idk affordance."""
    return (isinstance(q, dict) and isinstance(q.get("field"), str) and q["field"]
            and isinstance(q.get("prompt"), str) and q["prompt"]
            and isinstance(q.get("type"), str) and q["type"] and q.get("allow_idk") is True)


def test_every_agent_exposes_the_front_door_methods():
    """Requirement 8.1/8.2/8.5/8.6: next_question and translate_to_english are callable on every agent."""
    for a in _all_agents():
        assert callable(getattr(a, "next_question", None)), f"{a.id} missing next_question"
        assert callable(getattr(a, "translate_to_english", None)), f"{a.id} missing translate_to_english"


def test_sample_agent_scripts_every_language_to_completion(monkeypatch):
    """Requirement 8.2/8.8/8.9: scripted loop yields one valid question per field in each language, then COMPLETE."""
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0")
    a = SampleAgent()
    prompts_by_lang = {}
    for lang in _LANGS:
        asked, fields = [], []
        for _ in range(len(a._NQ_ORDER)):
            q = a.next_question(_answers_view(lang, asked))
            assert _is_question(q), f"{lang}: expected a question, got {q!r}"
            assert q["language"] == lang, f"{lang}: prompt language echoed as {q['language']!r}"
            assert q["prompt"].strip(), f"{lang}: empty prompt for {q['field']}"
            assert q["field"] not in asked, f"{lang}: repeated field {q['field']}"
            fields.append(q["field"]); asked.append(q["field"])
        assert fields == a._NQ_ORDER, f"{lang}: field order {fields} != {a._NQ_ORDER}"
        # After the whole field set has been asked, the base COMPLETE sentinel.
        assert a.next_question(_answers_view(lang, asked)) == COMPLETE, f"{lang}: expected COMPLETE after full set"
        # The first question (no fields asked yet) is the brand-name prompt; keep it to compare across languages.
        prompts_by_lang[lang] = a.next_question(_answers_view(lang, []))["prompt"]
    # Real localization, not a stub: the brand-name prompt differs across at least two languages.
    brand_prompts = set(prompts_by_lang.values())
    assert len(brand_prompts) >= 2, "brand-name prompt is identical in every language (stub, not localized)"


def test_sample_agent_choice_fields_carry_localized_options(monkeypatch):
    """Requirement 8.2: choice fields expose localized option labels in the requested language."""
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0")
    a = SampleAgent()
    # patient_outcome is the first choice field; drive up to it and read its options in two languages.
    up_to = a._NQ_ORDER[:a._NQ_ORDER.index("patient_outcome")]
    en = a.next_question(_answers_view("en", up_to)); es = a.next_question(_answers_view("es", up_to))
    assert en["field"] == es["field"] == "patient_outcome" and en["type"] == es["type"] == "choice"
    en_labels = [o["label"] for o in en["options"]]; es_labels = [o["label"] for o in es["options"]]
    assert en_labels and es_labels and en_labels != es_labels, "choice labels are not localized"


def test_sample_agent_unknown_language_falls_back_to_english(monkeypatch):
    """Requirement 8.3: an unsupported language still yields a valid question, in the default (en) strings."""
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0")
    a = SampleAgent()
    q = a.next_question(_answers_view("zz", []))
    assert _is_question(q) and q["language"] == "en"
    assert q["prompt"] == a.next_question(_answers_view("en", []))["prompt"]


def test_sample_agent_next_question_returns_one_question_or_complete(monkeypatch):
    """Requirement 8.8/8.9: every step returns exactly one question dict OR the COMPLETE sentinel — never list/None."""
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0")
    a = SampleAgent()
    asked = []
    for _ in range(len(a._NQ_ORDER) + 3):  # run past the end to hit COMPLETE and keep returning it
        q = a.next_question(_answers_view("en", asked))
        assert q is not None and not isinstance(q, (list, tuple))
        assert q == COMPLETE or _is_question(q), f"unexpected return {q!r}"
        if q == COMPLETE:
            break
        asked.append(q["field"])
    assert a.next_question(_answers_view("en", a._NQ_ORDER)) == COMPLETE


def test_sample_and_no_agent_defer_translation():
    """Requirement 8.10: SampleAgent and NoAgent never translate — translate_to_english returns None."""
    for a in (SampleAgent(delay=0), NoAgent()):
        assert a.translate_to_english("hola, el aparato falló", "es") is None
        assert a.translate_to_english("texte en français", "fr") is None


def test_no_agent_next_question_is_complete_immediately():
    """Requirement 8.7: NoAgent has no adaptive loop — next_question returns COMPLETE on the first call."""
    assert NoAgent().next_question(_answers_view("en", [])) == COMPLETE


def test_sample_agent_next_question_makes_zero_network_calls(monkeypatch):
    """Requirement 8.4: the sample agent drives the interview fully offline — any socket use would raise."""
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0")
    import socket

    def _no_network(*args, **kwargs):
        raise AssertionError("SampleAgent.next_question attempted a network call")

    monkeypatch.setattr(socket, "socket", _no_network)
    # Belt and braces: if sample.py ever imported requests, a call would blow up too.
    from thirty.agents import sample as sample_mod
    if hasattr(sample_mod, "requests"):
        monkeypatch.setattr(sample_mod.requests, "get", _no_network, raising=False)
        monkeypatch.setattr(sample_mod.requests, "post", _no_network, raising=False)

    a = SampleAgent()
    asked = []
    for _ in range(len(a._NQ_ORDER)):
        q = a.next_question(_answers_view("en", asked))
        assert _is_question(q)
        asked.append(q["field"])
    assert a.next_question(_answers_view("en", asked)) == COMPLETE

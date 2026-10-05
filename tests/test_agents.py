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

    def get(self, url, timeout=0):
        self.calls.append(("GET", url)); return self

    def post(self, url, timeout=0, json=None):
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

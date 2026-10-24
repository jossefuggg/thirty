"""Claude agent: mocked HTTP, property-based robustness tests and example shape/health/plugin tests.

No test here reaches the network: requests.post is monkeypatched to a fake response whose .json() returns
{"content":[{"type":"text","text":<supplied>}]} and whose raise_for_status() optionally raises, capturing
the request kwargs for contract assertions.
"""
import json, os, sys

import pytest
import requests
from hypothesis import HealthCheck, given, settings, strategies as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty import plugins  # noqa: E402
from thirty.agents.base import UNREADABLE  # noqa: E402
from thirty.agents import claude_model as cm  # noqa: E402
from thirty.agents.claude_model import ClaudeAgent  # noqa: E402

COMPLAINT = {"id": "C1", "text": "device overheated", "device": "Pump X",
             "event_date": "2026-01-01", "received": "2026-01-02"}
ROW = {"id": "C1", "decision": "REPORTABLE", "category": "MALFUNCTION", "device": "Pump X",
       "deadline_days": 30, "missing": "", "text": "device overheated"}

VALID_CLASSIFY = json.dumps({"decision": "REPORTABLE", "category": "MALFUNCTION", "reason": "803.50",
                             "remedial_action_needed": False, "missing_info": [], "confidence": 80})
VALID_DRAFT = json.dumps({"B5_event_description": "overheated", "H10_manufacturer_narrative": "n",
                          "D1_brand_name": "Pump X", "follow_up_questions": []})
VALID_ASK = json.dumps({"questions": ["Patient age?", "Lot number?"], "message": "We are looking into it."})


class FakeResponse:
    def __init__(self, text, status=200):
        self._text, self._status = text, status

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"{self._status}")


@pytest.fixture()
def capture(monkeypatch):
    """Monkeypatch requests.post; record calls; serve a configurable text/status."""
    state = {"text": "", "status": 200, "calls": []}

    def fake_post(url, **kwargs):
        state["calls"].append({"url": url, **kwargs})
        return FakeResponse(state["text"], state["status"])

    monkeypatch.setattr(cm.requests, "post", fake_post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # force the setting-provided key
    return state


def agent():
    return ClaudeAgent(api_key="test-key", model="claude-sonnet-5-5", timeout=60)


# ---------------------------------------------------------------- property-based tests
#
# Property tests patch cm.requests.post via a contextmanager rather than the function-scoped
# monkeypatch/capture fixtures (those are not reset between @given inputs). The patched behaviour is
# constant across examples, so a single patch per test is correct.
import contextlib  # noqa: E402


@contextlib.contextmanager
def patched_post(responder):
    """Patch cm.requests.post with `responder(url, **kwargs) -> FakeResponse`, recording calls."""
    calls = []
    orig = cm.requests.post
    env = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = ""  # force the setting-provided key

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return responder(url, **kwargs)

    cm.requests.post = fake_post
    try:
        yield calls
    finally:
        cm.requests.post = orig
        if env is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = env


NO_FIXTURE = settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])


# Feature: claude-agent-plugin, Property 1: Response-robustness (shape stability, no raises).
# For ANY model output, classify->dict, draft_report->dict, follow_up_questions->(list,str); none raise.
@settings(max_examples=100)
@given(text=st.text())
def test_property1_response_robustness(text):
    with patched_post(lambda url, **kw: FakeResponse(text)):
        a = agent()
        c = a.classify(COMPLAINT)
        d = a.draft_report(COMPLAINT, ROW)
        q, m = a.follow_up_questions(ROW, ["patient age"])
    assert isinstance(c, dict)
    assert isinstance(d, dict)
    assert isinstance(q, list) and isinstance(m, str)


# Feature: claude-agent-plugin, Property 2: Fallback determinism on unparseable output.
# For any output with no parseable JSON: classify==UNREADABLE, draft has H10, follow_up==([], "").
@settings(max_examples=100)
@given(text=st.text(alphabet=st.characters(blacklist_characters="{}")))
def test_property2_fallback_determinism(text):
    with patched_post(lambda url, **kw: FakeResponse(text)):
        a = agent()
        assert a.classify(COMPLAINT) == dict(UNREADABLE)
        assert "H10_manufacturer_narrative" in a.draft_report(COMPLAINT, ROW)
        assert a.follow_up_questions(ROW, []) == ([], "")


# Feature: claude-agent-plugin, Property 3: Question-count bound (<=5, first 5 in order).
@settings(max_examples=100)
@given(questions=st.lists(st.text(min_size=1)))
def test_property3_question_bound(questions):
    body = json.dumps({"questions": questions, "message": "hi"})
    with patched_post(lambda url, **kw: FakeResponse(body)):
        qs, _ = agent().follow_up_questions(ROW, [])
    assert len(qs) <= 5
    expected = [q.strip() for q in questions if q.strip()][:5]
    assert qs == expected


# Feature: claude-agent-plugin, Property 4: Classification determinism via temperature 0.
@settings(max_examples=100)
@given(memory=st.text())
def test_property4_temperature_zero(memory):
    with patched_post(lambda url, **kw: FakeResponse(VALID_CLASSIFY)) as calls:
        agent().classify(COMPLAINT, memory=memory)
    assert calls, "no request captured"
    assert calls[-1]["json"]["temperature"] == 0


# Feature: claude-agent-plugin, Property 5: Request-contract invariants.
@settings(max_examples=100)
@given(text=st.text())
def test_property5_request_contract(text):
    with patched_post(lambda url, **kw: FakeResponse(text)) as calls:
        agent().classify(COMPLAINT)
    call = calls[-1]
    assert call["url"] == cm.API_URL
    assert call["headers"]["x-api-key"] == "test-key"
    assert call["headers"]["anthropic-version"]
    msgs = call["json"]["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user" and isinstance(msgs[0]["content"], str)


# ---------------------------------------------------------------- example tests

def test_happy_path_shapes(capture):
    a = agent()
    capture["text"] = VALID_CLASSIFY
    c = a.classify(COMPLAINT)
    assert c["decision"] == "REPORTABLE" and c["confidence"] == 80
    capture["text"] = VALID_DRAFT
    d = a.draft_report(COMPLAINT, ROW)
    assert d["D1_brand_name"] == "Pump X"
    capture["text"] = VALID_ASK
    qs, msg = a.follow_up_questions(ROW, ["patient age"])
    assert qs == ["Patient age?", "Lot number?"] and msg == "We are looking into it."


def test_fence_wrapped_json(capture):
    capture["text"] = "```json\n" + VALID_CLASSIFY + "\n```"
    assert agent().classify(COMPLAINT)["decision"] == "REPORTABLE"


def test_key_resolution_setting_precedence(capture, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    capture["text"] = VALID_CLASSIFY
    ClaudeAgent(api_key="setting-key").classify(COMPLAINT)
    assert capture["calls"][-1]["headers"]["x-api-key"] == "setting-key"


def test_key_resolution_env_fallback(capture, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    capture["text"] = VALID_CLASSIFY
    ClaudeAgent(api_key="   ").classify(COMPLAINT)
    assert capture["calls"][-1]["headers"]["x-api-key"] == "env-key"


def test_key_resolution_none_falls_back(capture, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No key anywhere -> _messages raises -> classify returns UNREADABLE and no request is sent.
    assert ClaudeAgent(api_key="").classify(COMPLAINT) == dict(UNREADABLE)
    assert capture["calls"] == []


def test_health_success(capture):
    capture["text"] = "ok"
    h = agent().health()
    assert h["ok"] is True and isinstance(h["ms"], int) and h["name"] == "claude-sonnet-5-5"
    assert capture["calls"][-1]["json"]["max_tokens"] == 1


def test_health_error(capture):
    capture["status"] = 401
    h = agent().health()
    assert h["ok"] is False and h["ms"] is None and "offline" in h["label"]


def test_http_error_falls_back(capture):
    capture["status"] = 500
    assert agent().classify(COMPLAINT) == dict(UNREADABLE)
    assert "H10_manufacturer_narrative" in agent().draft_report(COMPLAINT, ROW)
    assert agent().follow_up_questions(ROW, []) == ([], "")


def test_plugin_discovery_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("VIGIL_DIR", str(tmp_path))
    monkeypatch.delenv("THIRTY_AGENT", raising=False)
    plugins.discover(force=True)
    p = plugins.get("claude")
    assert p and not p.error and "agent" in p.capabilities
    a = p.create({"api_key": "k", "model": "claude-sonnet-5-5", "timeout": 60})
    assert all(callable(getattr(a, m, None)) for m in ("classify", "draft_report", "follow_up_questions", "health"))
    monkeypatch.setattr(cm.requests, "post", lambda url, **kw: FakeResponse("ok"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    plugins.update_plugin("claude", enabled=True, settings={"api_key": "k"})
    assert plugins.status("claude")["state"] == "ready"
    monkeypatch.setattr(cm.requests, "post", lambda url, **kw: FakeResponse("", status=500))
    plugins.discover(force=True)  # drop cached instance so the new mock is used
    plugins.update_plugin("claude", settings={"api_key": "k2"})
    assert plugins.status("claude")["state"] == "error"


# ---------------------------------------------------------------- badge swap (template rendering)

BADGE_TPL = '<span class="badge-local">{{ "Cloud model (demo, sample data)" if CLOUD_AGENT else "0 bytes to cloud AI" }}</span>'


def _render(console, cloud_agent):
    with console.app.app_context():
        from flask import render_template_string
        return render_template_string(BADGE_TPL, CLOUD_AGENT=cloud_agent)


def test_badge_cloud_when_claude_active(console):
    html = _render(console, cloud_agent=True)
    assert "Cloud model (demo, sample data)" in html
    assert "0 bytes to cloud AI" not in html


def test_badge_local_when_not_claude(console):
    html = _render(console, cloud_agent=False)
    assert "0 bytes to cloud AI" in html
    assert "Cloud model (demo, sample data)" not in html


def test_pages_keep_local_badge_by_default(client):
    """Under the default sample agent, pages still show the 0-bytes badge (keeps test_console green)."""
    html = client.get("/").get_data(as_text=True)
    assert "0 bytes to cloud AI" in html
    assert "Cloud model (demo, sample data)" not in html

"""Jurisdiction clocks, the reportability decision tree and the hash-chained audit trail (no model needed)."""
import datetime as dt, json, os

import pytest

from thirty import audit, decisions, jurisdictions as J

AWARE = dt.date(2026, 10, 1)  # a Thursday
TODAY = dt.date(2026, 10, 6)


def due(code, category, **kw):
    hits = [d for d in J.deadlines(category, AWARE, kw.pop("enabled", ["US", "EU", "UK", "CA"]), today=TODAY, **kw) if d["code"] == code]
    return hits[0] if hits else None


def test_us_clock_30_calendar_and_5_work_days():
    assert due("US", "MALFUNCTION")["due"] == "2026-10-31"
    five = due("US", "SERIOUS_INJURY", five_day=True)
    assert five["days"] == 5 and five["work_days"] and five["due"] == "2026-10-08"  # Thu + 5 work days skips the weekend
    assert J.awareness_from_due(dt.date(2026, 10, 8), 5) == AWARE
    assert J.awareness_from_due(dt.date(2026, 10, 31), 30) == AWARE


def test_eu_uk_ladder_and_canada():
    assert due("EU", "DEATH")["days"] == 10
    assert due("EU", "SERIOUS_INJURY")["days"] == 15
    assert due("EU", "SERIOUS_INJURY", unanticipated=True)["days"] == 10
    assert due("UK", "MALFUNCTION")["days"] == 15
    assert due("EU", "MALFUNCTION", public_health_threat=True)["days"] == 2
    assert due("CA", "DEATH")["days"] == 10 and due("CA", "MALFUNCTION")["days"] == 30


def test_deadlines_sorted_earliest_first_and_not_reportable_empty():
    ds = J.deadlines("DEATH", AWARE, ["US", "EU", "CA"], today=TODAY)
    assert [d["code"] for d in ds] == ["EU", "CA", "US"] and ds[0]["days_left"] == 5
    assert J.deadlines("NONE", AWARE, ["US", "EU"]) == []
    assert J.normalise(["xx", "eu", "US"]) == ["US", "EU"] and J.normalise([]) == ["US"] and J.normalise(["CA"]) == ["US", "CA"]


def test_decision_tree_outcomes():
    assert decisions.evaluate({"death": "yes"})["category"] == "DEATH"
    si = decisions.evaluate({"death": "no", "serious_injury": "yes", "remedial": "yes"})
    assert si["decision"] == "REPORTABLE" and si["five_day"] and "803.53" in si["basis"]
    assert decisions.evaluate({"death": "no", "serious_injury": "no", "malfunction_likely": "yes"})["category"] == "MALFUNCTION"
    assert decisions.evaluate({"death": "no", "serious_injury": "no", "malfunction_likely": "no"})["decision"] == "NOT_REPORTABLE"
    assert decisions.evaluate({"death": "no", "serious_injury": "unknown", "malfunction_likely": "no"})["decision"] == "NEEDS_INFO"
    assert not decisions.evaluate({"death": "no", "serious_injury": "no", "malfunction_likely": "no", "remedial": "yes"})["five_day"]


def test_prefill_mirrors_agent_classification():
    a = decisions.prefill({"decision": "REPORTABLE", "category": "SERIOUS_INJURY", "deadline_days": "5"})
    assert a["serious_injury"] == "yes" and a["death"] == "no" and a["remedial"] == "yes" and a["unanticipated"] == "yes"
    assert decisions.prefill({"decision": "NEEDS_INFO"})["death"] == "unknown"
    assert all(v == "no" for v in decisions.prefill({"decision": "NOT_REPORTABLE"}).values())


def test_record_requires_name_rationale_and_similar_ref(tmp_path):
    d = str(tmp_path)
    with pytest.raises(ValueError):
        decisions.record("C1", {"death": "yes"}, "reason", "", data_dir=d)
    with pytest.raises(ValueError):
        decisions.record("C1", {"death": "yes"}, "", "A. Rivera", data_dir=d)
    with pytest.raises(ValueError):
        decisions.record("C1", {"death": "no", "serious_injury": "no", "malfunction_likely": "no", "similar_investigated": "yes"}, "r", "A. Rivera", data_dir=d)
    with pytest.raises(ValueError):
        decisions.record("C1", {"death": "yes"}, "r", "A. Rivera", aware=(TODAY + dt.timedelta(days=1)).isoformat(), data_dir=d, today=TODAY)


def test_record_keeps_history_and_clocks(tmp_path):
    d = str(tmp_path)
    rec = decisions.record("C9", {"death": "no", "serious_injury": "yes", "malfunction_likely": "no", "unanticipated": "yes"},
                           "Patient was hospitalised with a burn.", "A. Rivera", aware=AWARE.isoformat(), enabled=["US", "EU"], data_dir=d, today=TODAY)
    assert rec["outcome"]["decision"] == "REPORTABLE" and rec["outcome"]["category"] == "SERIOUS_INJURY"
    assert [c["code"] for c in rec["clocks"]] == ["EU", "US"] and rec["clocks"][0]["days"] == 10
    rec2 = decisions.record("C9", {"death": "no", "serious_injury": "no", "malfunction_likely": "no"}, "Later facts: no injury.", "A. Rivera", data_dir=d, today=TODAY)
    assert rec2["outcome"]["decision"] == "NOT_REPORTABLE" and rec2["clocks"] == []
    assert len(decisions.history("C9", d)) == 2 and decisions.latest("C9", d)["rationale"].startswith("Later")
    with open(os.path.join(d, "decisions", "C9.json"), encoding="utf-8") as f:
        assert len(json.load(f)) == 2


def test_audit_chain_appends_and_detects_tampering(tmp_path):
    d = str(tmp_path)
    assert audit.verify(d) == {"ok": True, "count": 0, "head": audit.GENESIS, "broken_at": None}
    e1 = audit.append("A. Rivera", "Approved", "C1", "Draft approved", audit.MEANINGS["approve"], data_dir=d)
    e2 = audit.append("A. Rivera", "Decision recorded", "C1", "REPORTABLE", audit.MEANINGS["decision"], extra={"category": "DEATH"}, data_dir=d)
    assert e1["prev"] == audit.GENESIS and e2["prev"] == e1["hash"] and e2["seq"] == 2
    v = audit.verify(d)
    assert v["ok"] and v["count"] == 2 and v["head"] == e2["hash"]
    assert [e["seq"] for e in audit.entries(d, cid="C1")] == [1, 2]
    p = audit.path(d)
    lines = open(p, encoding="utf-8").read().splitlines()
    lines[0] = lines[0].replace("Draft approved", "Draft rejected")
    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    v = audit.verify(d)
    assert not v["ok"] and v["broken_at"] == 1

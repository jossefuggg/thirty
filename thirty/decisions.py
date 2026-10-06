"""Reportability decision tree with a recorded justification (21 CFR 803.18 / ISO 13485 8.2.2 / 820.35).

The tree is deterministic. The agent's classification pre-fills the answers; a named reviewer confirms or
changes them, writes the rationale, and records the decision. Every record (including "not reportable")
is kept with the answers, the rationale, the reviewer, the time, the awareness date and the clocks it
produced, in <data>/decisions/<id>.json (a list, newest last) and as a hash-chained audit entry.
"""
import datetime as dt, json, os

from . import config, jurisdictions as J

DIR = "decisions"
YES, NO, UNKNOWN = "yes", "no", "unknown"

# (key, question, help, jurisdictions it matters for)
QUESTIONS = [
    ("death", "Did the event cause or contribute to a death?",
     "21 CFR 803.3 · 803.50(a)(1). A death that may have been caused or contributed to by the device.", "US EU UK CA"),
    ("serious_injury", "Did it cause or contribute to a serious injury?",
     "Life-threatening, permanent impairment or damage, or medical/surgical intervention needed to preclude either (803.3). EU/UK: serious deterioration in health.", "US EU UK CA"),
    ("malfunction_likely", "If it recurred, would the malfunction be likely to cause or contribute to a death or serious injury?",
     "803.50(a)(2). Includes the device failing to perform as intended when that failure could reasonably be expected to cause harm.", "US EU UK CA"),
    ("remedial", "Is remedial action needed to prevent an unreasonable risk of substantial harm to public health?",
     "803.53: a 5-work-day report. Also when the FDA has requested a 5-day report in writing.", "US"),
    ("public_health_threat", "Is this a serious public health threat?",
     "MDR Art. 87(4) / GB regs: imminent risk of death, serious deterioration or serious illness that requires prompt remedial action. 2-day clock.", "EU UK"),
    ("unanticipated", "Was the serious deterioration unanticipated?",
     "MDR Art. 87(5): death or unanticipated serious deterioration gets the 10-day clock; anticipated serious incidents get 15 days.", "EU UK"),
    ("similar_investigated", "Has a similar complaint already been investigated?",
     "820.35(a) / ISO 13485 8.2.2: when a similar complaint has already been investigated, record the reference instead of repeating the investigation.", "US"),
]
KEYS = [q[0] for q in QUESTIONS]

# 21 CFR 820.35(a) complaint record fields that the intake does not always carry
RECORD_FIELDS = [
    ("udi", "UDI / lot / serial", "Device identifiers beyond the brand name (820.35(a)(3))."),
    ("complainant", "Complainant name and contact", "Name, address, phone number of the complainant (820.35(a)(4))."),
    ("similar_ref", "Similar complaint reference", "ID of the complaint already investigated, when 'similar complaint investigated' is yes."),
    ("correction", "Correction / corrective action", "Any correction or corrective action taken (820.35(a)(6))."),
    ("reply", "Reply to the complainant", "What was sent back to the complainant, and when (820.35(a)(7))."),
]


def path(cid, data_dir=None):
    return os.path.join(data_dir or config.data_dir(), DIR, f"{cid}.json")


def evaluate(answers):
    """Deterministic outcome from the answers. Returns decision, category, five_day, flags, basis."""
    a = {k: (answers.get(k) or UNKNOWN) for k in KEYS}
    if a["death"] == YES:
        decision, category, basis = "REPORTABLE", "DEATH", "Death: 21 CFR 803.50(a)(1)"
    elif a["serious_injury"] == YES:
        decision, category, basis = "REPORTABLE", "SERIOUS_INJURY", "Serious injury: 21 CFR 803.50(a)(1)"
    elif a["malfunction_likely"] == YES:
        decision, category, basis = "REPORTABLE", "MALFUNCTION", "Malfunction likely to cause death or serious injury if it recurred: 21 CFR 803.50(a)(2)"
    elif UNKNOWN in (a["death"], a["serious_injury"], a["malfunction_likely"]):
        decision, category, basis = "NEEDS_INFO", "NONE", "Facts needed before the reportability questions can be answered"
    else:
        decision, category, basis = "NOT_REPORTABLE", "NONE", "No death, serious injury or malfunction likely to cause either: no MDR required (21 CFR 803)"
    five_day = decision == "REPORTABLE" and a["remedial"] == YES
    if five_day:
        basis += " · 5-day report (803.53)"
    return {"decision": decision, "category": category, "five_day": five_day, "basis": basis,
            "public_health_threat": a["public_health_threat"] == YES, "unanticipated": a["unanticipated"] == YES,
            "similar_investigated": a["similar_investigated"] == YES, "answers": a}


def prefill(row):
    """Answers implied by the agent's classification (the reviewer sees them pre-selected and can change them)."""
    dec, cat = (row.get("decision") or "").upper(), (row.get("category") or "").upper()
    a = {k: NO for k in KEYS}
    if dec == "REPORTABLE":
        a["death"] = YES if cat == "DEATH" else NO
        a["serious_injury"] = YES if cat == "SERIOUS_INJURY" else NO
        a["malfunction_likely"] = YES if cat == "MALFUNCTION" else NO
        a["remedial"] = YES if str(row.get("deadline_days")) == "5" else NO
        a["unanticipated"] = YES if cat in ("DEATH", "SERIOUS_INJURY") else NO
    elif dec == "NEEDS_INFO":
        a["death"] = a["serious_injury"] = a["malfunction_likely"] = UNKNOWN
    return a


def awareness_of(row, today=None):
    """Awareness date for a logged row: the recorded one, else inverted from the US due date, else the processing day."""
    rec = latest(row.get("id"))
    if rec and rec.get("aware"):
        return dt.date.fromisoformat(rec["aware"])
    try:
        days = int(row.get("deadline_days") or 0)
        if row.get("due_date") and days in (5, 30):
            return J.awareness_from_due(dt.date.fromisoformat(row["due_date"]), days)
    except (TypeError, ValueError):
        pass
    t = (row.get("time") or "")[:10]
    try:
        return dt.date.fromisoformat(t)
    except ValueError:
        return today or dt.date.today()


def clocks(row, enabled=None, today=None):
    """Per-jurisdiction deadlines for a row, using the latest decision record when there is one."""
    rec = latest(row.get("id"))
    if rec:
        ev, aware = rec["outcome"], dt.date.fromisoformat(rec["aware"])
    else:
        ev = {"category": (row.get("category") or "").upper(), "five_day": str(row.get("deadline_days")) == "5",
              "public_health_threat": False, "unanticipated": (row.get("category") or "").upper() in ("DEATH", "SERIOUS_INJURY"),
              "decision": row.get("decision")}
        aware = awareness_of(row, today)
    if ev.get("decision") != "REPORTABLE":
        return []
    return J.deadlines(ev["category"], aware, enabled, ev.get("five_day"), ev.get("public_health_threat"), ev.get("unanticipated"), today)


def history(cid, data_dir=None):
    try:
        with open(path(cid, data_dir), encoding="utf-8") as f:
            recs = json.load(f)
        return recs if isinstance(recs, list) else []
    except (OSError, ValueError):
        return []


def latest(cid, data_dir=None):
    h = history(cid, data_dir)
    return h[-1] if h else None


def record(cid, answers, rationale, by, aware=None, fields=None, enabled=None, data_dir=None, today=None):
    """Evaluate, store and return the record. Raises ValueError on bad input."""
    by = " ".join((by or "").split())[:60]
    if not by:
        raise ValueError("Enter your name first.")
    rationale = (rationale or "").strip()
    if not rationale:
        raise ValueError("Write the rationale: every decision, including not reportable, needs one on file.")
    today = today or dt.date.today()
    aware_d = dt.date.fromisoformat(aware) if aware else today
    if aware_d > today:
        raise ValueError("The awareness date cannot be in the future.")
    ev = evaluate({k: str(v).lower() for k, v in (answers or {}).items()})
    if ev["similar_investigated"] and not (fields or {}).get("similar_ref", "").strip():
        raise ValueError("Give the reference of the similar complaint that was investigated.")
    due = J.deadlines(ev["category"], aware_d, enabled, ev["five_day"], ev["public_health_threat"], ev["unanticipated"], today) \
        if ev["decision"] == "REPORTABLE" else []
    rec = {"time": dt.datetime.now().isoformat(timespec="seconds"), "id": cid, "by": by, "aware": aware_d.isoformat(),
           "answers": ev["answers"], "rationale": rationale[:4000],
           "fields": {k: str((fields or {}).get(k) or "").strip()[:500] for k, _, _ in RECORD_FIELDS},
           "outcome": {k: ev[k] for k in ("decision", "category", "five_day", "basis", "public_health_threat", "unanticipated", "similar_investigated")},
           "clocks": due, "version": 1}
    p = path(cid, data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    recs = history(cid, data_dir) + [rec]
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(recs, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)
    return rec


def label(decision):
    return {"REPORTABLE": "Reportable", "NOT_REPORTABLE": "Not reportable", "NEEDS_INFO": "Needs info"}.get(decision, decision or "")

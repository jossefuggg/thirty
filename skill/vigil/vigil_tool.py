#!/usr/bin/env python3
"""Vigil skill helper (runs inside the OpenShell sandbox). Reads decisions.csv, appends approvals.csv / info_requests.csv."""
import argparse, csv, datetime as dt, json, os, re, sys, urllib.request
from collections import Counter

DIR = os.environ.get("VIGIL_DIR", "/sandbox/vigil")
DECISIONS = os.path.join(DIR, "decisions.csv")
APPROVALS = os.path.join(DIR, "approvals.csv")
INFO_REQUESTS = os.path.join(DIR, "info_requests.csv")
# Local model through the OpenShell managed inference route (direct host:8000 is denied by sandbox policy).
LLM_BASE = os.environ.get("VIGIL_LLM_BASE", "https://inference.local/v1")

ASK = """You are a medical device complaint investigator at the manufacturer. A customer complaint needs
more information before the FDA report (21 CFR 803) can be completed.

Complaint #{id} ({decision}, {category}) about device: {device}
Complaint text: {text}
Information Vigil flagged as missing: {missing}

Write 3 to 5 specific questions to send the customer, most important first. Plain language a patient or
family member understands, no jargon, no legal terms, one question each, about THIS complaint's details.
Questions must be specific to the symptoms and device in this complaint. For breathing/respiratory symptoms
(cough, headache, chest pain, difficulty breathing) always ask about: when symptoms started relative to device
use, any black particles/debris/foam in tubing or mask, medical treatment received, device model/serial,
whether the patient is still using it. Never ask about unrelated injuries.
Then write a short, polite, ready-to-send message to the customer (2-3 sentences) explaining that we are
looking into their report and need a few details; do not admit fault and do not promise outcomes.
Answer ONLY with JSON: {{"questions": ["..."], "message": "..."}}"""

# Questions for the code-level gaps vigil.py logs (missing_fields); model gaps are phrased generically.
QUESTIONS = {
    "device model": "What is the exact device model and serial number?",
    "event date": "On what date did the event happen?",
    "patient outcome": "What happened to the patient: any injury, treatment, hospital visit or lasting harm?",
    "detailed description": "Can you describe what happened in detail, step by step?",
}


def load():
    if not os.path.exists(DECISIONS):
        sys.exit("No Vigil data yet (decisions.csv not synced to the sandbox).")
    rows = list(csv.DictReader(open(DECISIONS, encoding="utf-8")))
    latest = {}
    for r in rows:  # a complaint may be logged more than once; keep the newest entry
        latest[r["id"]] = r
    approved, requested = _by_id(APPROVALS), _by_id(INFO_REQUESTS)
    for r in latest.values():
        if r["id"] in approved:
            r["status"] = f"APPROVED by {approved[r['id']]}"
        elif r["id"] in requested and not r["status"].startswith("APPROVED"):
            r["status"] = f"INFO REQUESTED by {requested[r['id']]}"
    return latest


def _by_id(path):
    if not os.path.exists(path):
        return {}
    return {a["id"]: a["by"] for a in csv.DictReader(open(path, encoding="utf-8"))}


def _append(path, cid, by):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "id", "by"])
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), cid, by])


def _clean_id(raw):
    cid = raw.strip().lstrip("#")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
        sys.exit(f"Invalid complaint ID: {raw}")
    return cid


def _question(item):
    item = item.strip().rstrip(".")
    if item.lower() in QUESTIONS:
        return QUESTIONS[item.lower()]
    if item.endswith("?"):
        return item
    m = re.match(r"(?i)(?:confirmation of |confirm )?(whether|if)\b(.*)", item)
    if m:
        return f"Can you confirm {m.group(1).lower()}{m.group(2)}?"
    return f"Can you provide the {item[0].lower() + item[1:]}?"


def is_open(r):
    return r["due_date"] and not r["status"].startswith("APPROVED")


def cmd_due(a):
    today = dt.date.today()
    end = today + dt.timedelta(days=a.days)
    rows = sorted((r for r in load().values() if is_open(r) and r["due_date"] <= end.isoformat()),
                  key=lambda r: r["due_date"])
    if not rows:
        print(f"Nothing due in the next {a.days} days.")
        return
    print(f"Due by {end.isoformat()} ({len(rows)} open):")
    for r in rows:
        d = (dt.date.fromisoformat(r["due_date"]) - today).days
        when = f"OVERDUE {-d}d" if d < 0 else "today" if d == 0 else f"in {d}d"
        print(f"#{r['id']} {r['decision']} ({r['category']}) due {r['due_date']} [{when}] - {r['device'][:30]}")


def cmd_status(_):
    rows = list(load().values())
    by_dec = Counter(r["decision"] for r in rows)
    approved = sum(r["status"].startswith("APPROVED") for r in rows)
    open_ = sorted((r for r in rows if is_open(r)), key=lambda r: r["due_date"])
    print(f"Vigil: {len(rows)} complaints processed. " + ", ".join(f"{k} {v}" for k, v in by_dec.most_common()))
    print(f"Approved: {approved}. Awaiting review: {len(open_)}.")
    if open_:
        n = open_[0]
        print(f"Next deadline: #{n['id']} {n['decision']} due {n['due_date']} ({n['device'][:30]})")


def cmd_approve(a):
    cid = _clean_id(a.id)
    rows = load()
    r = rows.get(cid)
    if not r:
        sys.exit(f"Unknown complaint #{cid}. Nothing approved.")
    if r["status"].startswith("APPROVED"):
        print(f"#{cid} is already {r['status']}.")
        return
    _append(APPROVALS, cid, a.by or "someone")
    print(f"✅ #{cid} approved by {a.by or 'someone'}. Logged. ({r['decision']}, {r['device'][:30]}, due {r['due_date'] or 'n/a'})")


def _llm(prompt, max_tokens=700):
    def get(url, body=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=90))
    model = get(f"{LLM_BASE}/models")["data"][0]["id"]
    out = get(f"{LLM_BASE}/chat/completions", {
        "model": model, "temperature": 0.2, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False}})
    text = out["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S)


def _questions_for(r, items):
    """3-5 customer questions + ready-to-send message from the local model; rule-based fallback if it fails."""
    try:
        raw = _llm(ASK.format(id=r["id"], decision=r["decision"], category=r["category"], device=r["device"],
                              text=r.get("text") or "", missing="; ".join(items) or "none listed"))
        j = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        qs = [str(q).strip() for q in j.get("questions") or [] if str(q).strip()][:5]
        if len(qs) >= 3 and j.get("message"):
            return qs, str(j["message"]).strip()
    except Exception as e:
        print(f"(local model unavailable: {type(e).__name__}; using standard questions)", file=sys.stderr)
    qs = list(dict.fromkeys(_question(m) for m in items))[:5] or [QUESTIONS["detailed description"]]
    msg = ("Thank you for reporting this issue with your device. We are looking into it and need a few more "
           "details to complete our review. Could you please answer the questions below?")
    return qs, msg


def _nice(d):
    try:
        d = dt.date.fromisoformat(d); return f"{d.day} {d:%b %Y}"
    except Exception:
        return d


def cmd_need_info(a):
    cid = _clean_id(a.id)
    r = load().get(cid)
    if not r:
        sys.exit(f"Unknown complaint #{cid}. Nothing changed.")
    if r["status"].startswith("APPROVED"):
        print(f"#{cid} is already {r['status']}. Nothing changed.")
        return
    by = a.by or "someone"
    _append(INFO_REQUESTS, cid, by)  # record first: the request stands even if the model is slow or down
    items = [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()]
    qs, msg = _questions_for(r, items)
    print(f"🟠 #{cid} INFO REQUESTED by {by}")
    print("Questions for the customer:")
    for i, q in enumerate(qs, 1):
        print(f"{i}. {q}")
    print(f"✉️ Ready-to-send message: {msg}")
    print(f"⏰ Clock still running: due {_nice(r['due_date'])}" if r["due_date"] else "⏰ No reporting deadline (not reportable).")


p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
d = sub.add_parser("due"); d.add_argument("--days", type=int, default=7)
sub.add_parser("status")
ap = sub.add_parser("approve"); ap.add_argument("id"); ap.add_argument("--by", default="")
ni = sub.add_parser("need-info"); ni.add_argument("id"); ni.add_argument("--by", default="")
a = p.parse_args()
{"due": cmd_due, "status": cmd_status, "approve": cmd_approve, "need-info": cmd_need_info}[a.cmd](a)

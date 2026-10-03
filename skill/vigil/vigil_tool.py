#!/usr/bin/env python3
"""Vigil skill helper (runs inside the OpenShell sandbox). Reads decisions.csv, appends approvals.csv / info_requests.csv."""
import argparse, csv, datetime as dt, fcntl, json, os, re, sys, time, urllib.error, urllib.request
from collections import Counter

DIR = os.environ.get("VIGIL_DIR", "/sandbox/vigil")
DECISIONS = os.path.join(DIR, "decisions.csv")
APPROVALS = os.path.join(DIR, "approvals.csv")
INFO_REQUESTS = os.path.join(DIR, "info_requests.csv")
NAMES = os.path.join(DIR, "names.json")  # {"names": {session: first name}, "pending": {session: {...}}}
# OpenClaw's session log: real Telegram messages carry __openclaw.senderName (the model does not see it).
SESSIONS = os.environ.get("VIGIL_SESSIONS", "/sandbox/.openclaw/agents/main/sessions")
NOT_NAMES = {"hello", "hi", "hey", "yes", "no", "ok", "okay", "thanks", "thank", "you", "sure", "please", "vigil",
             "bot", "help", "what", "who", "why", "how", "cancel", "stop", "status", "due", "approve", "need", "info"}
GENERIC_NAMES = {"", "someone", "user", "webchat", "unknown", "sender", "anonymous", "me", "none", "null"}
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


def reply(msg):
    """End with a message for the chat. Exit 0: these are answers, not tool failures (a non-zero exit makes
    OpenClaw post '⚠️ Exec failed' in the group)."""
    print(msg)
    sys.exit(0)


def _read_decisions(tries=4, wait=0.5):
    """decisions.csv is replaced by the host's sync upload; retry if it is caught missing or mid-write."""
    for i in range(tries):
        try:
            with open(DECISIONS, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if all(r.get("id") for r in rows):
                return rows
        except (OSError, csv.Error, UnicodeDecodeError):
            pass
        time.sleep(wait)
    if not os.path.exists(DECISIONS):
        reply("No complaints logged yet.")
    reply("Vigil data is being updated right now. Please send the command again in a few seconds.")


def load():
    rows = _read_decisions()
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
    with open(path, "a", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # two button taps at once must not interleave rows
        w = csv.writer(f)
        if f.tell() == 0: w.writerow(["time", "id", "by"])
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), cid, by])


# ---------------------------------------------------------------- who is acting (sender name)
def _first(name):
    return (name or "").strip().split()[0] if (name or "").strip() else ""


def _session_store():
    try:
        with open(os.path.join(SESSIONS, "sessions.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _current_message(cid=None, window=900):
    """(session id, sender first name) for the newest chat message in the last `window` s that mentions `cid`
    (any message when cid is None). The name is "" if OpenClaw recorded no sender (e.g. a CLI test)."""
    best = None
    for s in _session_store().values():
        path = s.get("sessionFile") or ""
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-300:]
        except Exception:
            continue
        for line in reversed(lines):
            try:
                m = json.loads(line).get("message") or {}
            except Exception:
                continue
            if m.get("role") != "user":
                continue
            ts = (m.get("timestamp") or 0) / 1000
            if time.time() - ts > window:
                break
            text = m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
            if cid and cid not in (text or ""):
                continue
            meta = m.get("__openclaw") or {}
            name = _first(meta.get("senderName") or meta.get("senderUsername"))
            if best is None or ts > best[0]:
                best = (ts, s.get("sessionId") or path, name)
            break
    if best:
        return best[1], best[2]
    newest = max(_session_store().values(), key=lambda s: s.get("updatedAt") or 0, default={})
    return newest.get("sessionId") or "default", ""


def _names():
    try:
        with open(NAMES, encoding="utf-8") as f:
            d = json.load(f)
        return {"names": d.get("names") or {}, "pending": d.get("pending") or {}}
    except Exception:
        return {"names": {}, "pending": {}}


def _save_names(d):
    tmp = NAMES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, NAMES)


def actor(by, cid, action):
    """First name to log: Telegram sender metadata, else a real --by, else the name given earlier in this
    session. If none, ask once ('Who should I log this under?') and keep the action pending until answered."""
    session, meta_name = _current_message(cid)
    d = _names()
    name = meta_name or ("" if _first(by).lower() in GENERIC_NAMES else _first(by)) or d["names"].get(session, "")
    if name:
        if d["names"].get(session) != name:
            d["names"][session] = name
            _save_names(d)
        return name
    d["pending"][session] = {"action": action, "id": cid, "time": time.time()}
    _save_names(d)
    reply("Who should I log this under? Reply with your first name.")


def _who(status):
    return status.split(" by ", 1)[1].strip() if " by " in (status or "") else "someone"


def _clean_id(raw):
    cid = raw.strip().lstrip("#")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
        reply(f"Invalid complaint ID: {raw}")
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
        reply(f"Unknown complaint #{cid}. Nothing approved.")
    if r["status"].startswith("APPROVED"):
        reply(f"#{cid} is already approved by {_who(r['status'])} — no change.")
    by = actor(a.by, cid, "approve")  # an INFO REQUESTED complaint can still be approved once the answers are in
    _append(APPROVALS, cid, by)
    print(f"✅ #{cid} approved by {by}. Logged. ({r['decision']}, {r['device'][:30]}, due {r['due_date'] or 'n/a'})")


def _llm(prompt, max_tokens=700):
    """Bounded so need-info always answers inside the exec window (yieldMs 180 s): <= ~100 s here, then the
    rule-based questions. One retry on a quick connection error (inference route warming up)."""
    def get(url, body=None, timeout=15):
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
        for attempt in (1, 2):
            try:
                return json.load(urllib.request.urlopen(req, timeout=timeout))
            except urllib.error.URLError as e:
                if attempt == 2 or "timed out" in str(e.reason):
                    raise
                time.sleep(2)
    model = get(f"{LLM_BASE}/models")["data"][0]["id"]
    out = get(f"{LLM_BASE}/chat/completions", timeout=75, body={
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
        reply(f"Unknown complaint #{cid}. Nothing changed.")
    if r["status"].startswith("APPROVED"):
        reply(f"#{cid} is already approved by {_who(r['status'])} — no change.")
    if r["status"].startswith("INFO REQUESTED"):
        reply(f"#{cid} already has info requested by {_who(r['status'])} — no change.")
    by = actor(a.by, cid, "need-info")
    _append(INFO_REQUESTS, cid, by)  # record first: the request stands even if the model is slow or down
    items = [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()]
    qs, msg = _questions_for(r, items)
    print(f"🟠 #{cid} INFO REQUESTED by {by}")
    print("Questions for the customer:")
    for i, q in enumerate(qs, 1):
        print(f"{i}. {q}")
    print(f"✉️ Ready-to-send message: {msg}")
    print(f"⏰ Clock still running: due {_nice(r['due_date'])}" if r["due_date"] else "⏰ No reporting deadline (not reportable).")


def cmd_msg(a):
    """The chat message as-is ('@VigilMDR_bot need info #123 please'): mention, slashes and extra words are
    ignored; the intent and ID are parsed here, so the model only has to pass the text through."""
    text = " ".join(a.words)
    t = re.sub(r"@\w+", " ", text)                     # bot mention(s)
    t = re.sub(r"[^\w#\s-]", " ", t).lower()           # quotes, slashes, punctuation
    m = re.search(r"\bneed[\s_-]*info\b\s*#?\s*([A-Za-z0-9_-]+)", t)
    if m:
        return cmd_need_info(argparse.Namespace(id=m.group(1), by=a.by))
    m = re.search(r"\bapprove\b\s*#?\s*([A-Za-z0-9_-]+)", t)
    if m:
        return cmd_approve(argparse.Namespace(id=m.group(1), by=a.by))
    if re.search(r"\b(need[\s_-]*info|approve)\b", t):
        reply("Which complaint? Send it with the ID, e.g. 'approve 12638552' or 'need info 12638552'.")
    if re.search(r"\b(due|deadlines?|overdue)\b", t):
        days = 1 if re.search(r"\btoday\b", t) else 30 if re.search(r"\bmonth\b", t) else 7
        return cmd_due(argparse.Namespace(days=days))
    if re.search(r"\b(status|how many|summary)\b", t):
        return cmd_status(None)
    session, _ = _current_message()
    d = _names()
    pend = d["pending"].get(session)
    words = re.sub(r"^(?:(?:it|this|that) (?:is|s)|its|i am|i m|im|my name is|name is|log (?:it|this) under|under|as)\s+",
                   "", t.strip()).split()
    if (pend and time.time() - pend.get("time", 0) < 900 and 1 <= len(words) <= 2
            and all(w.isalpha() and w not in NOT_NAMES for w in words)):
        name = words[0].capitalize()
        d["names"][session] = name
        d["pending"].pop(session, None)
        _save_names(d)
        cmd = cmd_approve if pend["action"] == "approve" else cmd_need_info
        return cmd(argparse.Namespace(id=pend["id"], by=name))
    print("Vigil commands: status · due · approve <id> · need info <id>")


p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
d = sub.add_parser("due"); d.add_argument("--days", type=int, default=7)
sub.add_parser("status")
ap = sub.add_parser("approve"); ap.add_argument("id"); ap.add_argument("--by", default="")
ni = sub.add_parser("need-info"); ni.add_argument("id"); ni.add_argument("--by", default="")
ms = sub.add_parser("msg"); ms.add_argument("words", nargs="+"); ms.add_argument("--by", default="")
a = p.parse_args()
{"due": cmd_due, "status": cmd_status, "approve": cmd_approve, "need-info": cmd_need_info, "msg": cmd_msg}[a.cmd](a)

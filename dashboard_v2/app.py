"""Vigil Console v2 - live, demo-ready command center for the Vigil complaint agent.

Reads ../decisions.csv (written by vigil.py), serves the draft 3500A PDFs from ../reports, drives demo
replays/resets of vigil.py in a subprocess, and shows live system health. vigil.py is never edited.
Everything is local: no CDNs, no external fonts.

Run in the background:  ~/hackathon/vigil/dashboard_v2/start_console.sh   ->  http://localhost:5001
"""
import csv, datetime as dt, fcntl, io, os, re, shutil, signal, subprocess, sys, tempfile, threading, time
from collections import defaultdict

import requests
from flask import Flask, abort, jsonify, render_template, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
VIGIL_DIR = os.environ.get("VIGIL_DIR", os.path.dirname(HERE))  # override only for testing on a scratch copy
LOG = os.path.join(VIGIL_DIR, "decisions.csv")
LOCK = LOG + ".lock"  # the same lock file vigil.py's log_lock() uses
REPORTS = os.path.join(VIGIL_DIR, "reports")
OUTBOX = os.path.join(VIGIL_DIR, "outbox.txt")
DEMO_CSV = os.path.join(VIGIL_DIR, "demo_set.csv")
CHART = os.path.join(VIGIL_DIR, "philips_chart.png")
ACTIONS = os.environ.get("VIGIL_CONSOLE_ACTIONS", os.path.join(HERE, "actions.csv"))  # who/when for console actions
VENV_BIN = os.path.expanduser(os.environ.get("VIGIL_VENV_BIN", "~/hackathon/venv/bin"))
LLM_BASE = os.environ.get("VIGIL_LLM_BASE", "http://localhost:8000/v1")
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text"]

app = Flask(__name__)
import logging; logging.getLogger("werkzeug").setLevel(logging.WARNING)  # polling would flood console.log

# ---------------------------------------------------------------- decisions.csv
_cache = {"rows": [], "mtime": None}

def read_rows():
    """Rows of decisions.csv. vigil.py holds the lock for up to a minute (sandbox upload inside log()), so we
    never block on it: take a shared lock if it is free, otherwise read anyway and fall back to the last good
    copy if the file looks mid-rewrite (fewer rows than before)."""
    if not os.path.exists(LOG):
        _cache.update(rows=[], mtime=None)
        return []
    lockf = open(LOCK, "a")
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_SH | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            locked = False
        try:
            with open(LOG, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            return _cache["rows"]
        if not locked and len(rows) < len(_cache["rows"]):
            return _cache["rows"]
        _cache["rows"] = rows
        return rows
    finally:
        lockf.close()  # releases the flock


def set_status(cid, status, guard):
    """Read-modify-write under vigil.py's exclusive lock. guard(old_status) -> bool decides if a row changes.
    The new file is written next to the old one and swapped in atomically, so unlocked readers never see it torn."""
    with open(LOCK, "a") as lockf:
        deadline = time.time() + 90  # vigil.py may hold the lock through a sandbox upload (<= 60 s)
        while True:
            try:
                fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.time() > deadline:
                    raise TimeoutError("decisions.csv is busy, try again")
                time.sleep(0.2)
        with open(LOG, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields, rows = reader.fieldnames or FIELDS, list(reader)
        hit = [r for r in rows if r["id"] == cid]
        if not hit:
            return None
        changed = [r for r in hit if guard(r.get("status") or "")]
        for r in changed:
            r["status"] = status
        if changed:
            fd, tmp = tempfile.mkstemp(dir=VIGIL_DIR, prefix=".decisions.", suffix=".tmp")
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader(); w.writerows(rows)
            shutil.copymode(LOG, tmp)
            os.replace(tmp, LOG)
    if changed:
        threading.Thread(target=push_to_sandbox, daemon=True).start()
    return bool(changed)


def latest_by_id(rows):
    out = {}
    for r in rows:
        out[r["id"]] = r  # a re-processed complaint replaces its earlier row
    return out

# ---------------------------------------------------------------- vigil.py bridge (read-only use, imported lazily)
_vigil, _vigil_lock = None, threading.Lock()

def vigil():
    global _vigil
    with _vigil_lock:
        if _vigil is None:
            sys.path.insert(0, VIGIL_DIR)
            import vigil as v
            _vigil = v
        return _vigil


def push_to_sandbox():
    """Keep the OpenClaw sandbox copy in sync after a console approval, like vigil.write_log does."""
    try:
        v = vigil()
        v.LOG = LOG
        v.push_log()
    except Exception as e:
        print("sandbox push skipped:", e, flush=True)

# ---------------------------------------------------------------- demo controls (vigil.py in a subprocess)
DEMO_COMMANDS = {
    # sg docker: nemoclaw (sandbox push / clear) needs the docker group. python3 resolves to the venv (fpdf2 etc.).
    "replay": 'sg docker -c "python3 vigil.py replay --csv demo_set.csv --delay 8"',
    "reset": 'sg docker -c "python3 vigil.py reset"',
}
PROCESSED_LINE = re.compile(r"^\S+ (URGENT|HIGH|NORMAL) (REPORTABLE|NEEDS_INFO|NOT_REPORTABLE|None)\b")  # cmd_replay's per-complaint line


class DemoRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc, self.kind, self.cmd = None, None, None
        self.lines, self.seq = [], 0
        self.started = self.ended = None
        self.rc, self.stopped, self.processed = None, False, 0

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _emit(self, text, tag=""):
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, tag, text))
            del self.lines[:-4000]

    def start(self, kind):
        with self.lock:
            if self.running:
                return f"A {self.kind} is already running. Stop it first."
            self.lines, self.kind, self.cmd = [], kind, DEMO_COMMANDS[kind]
            self.started, self.ended, self.rc, self.stopped, self.processed = time.time(), None, None, False, 0
        env = {**os.environ, "PATH": f"{VENV_BIN}:{os.environ.get('PATH', '')}", "PYTHONUNBUFFERED": "1"}
        self._emit(f"$ {self.cmd}", "cmd")
        self.proc = subprocess.Popen(self.cmd, shell=True, cwd=VIGIL_DIR, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                     start_new_session=True)  # own process group, so Stop kills sg -> sh -> python
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        return None

    def _pump(self, proc):
        for line in proc.stdout:
            line = line.rstrip("\n")
            if PROCESSED_LINE.match(line):
                self.processed += 1
            self._emit(line, "warn" if re.search(r"WARNING|failed|FAILED|Traceback|Error", line) else "")
        rc = proc.wait()
        self.rc, self.ended = rc, time.time()
        if self.stopped:
            self._emit("■ stopped from the console", "warn")
        else:
            self._emit(f"■ {self.kind} finished (exit code {rc})", "ok" if rc == 0 else "warn")

    def stop(self):
        if not self.running:
            return "Nothing is running."
        self.stopped = True
        pgid = self.proc.pid  # start_new_session: the group id is the shell's pid
        for sig, wait in ((signal.SIGTERM, 4), (signal.SIGKILL, 2)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return None
            end = time.time() + wait
            while time.time() < end:  # wait for every process in the group (sg -> sh -> python), not just the shell
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    return None
                time.sleep(0.1)
        return None

    def public(self, since=0):
        with self.lock:
            lines = [l for l in self.lines if l[0] > since]
        return {"running": self.running, "kind": self.kind, "cmd": self.cmd, "started": self.started, "ended": self.ended,
                "rc": self.rc, "stopped": self.stopped, "processed": self.processed, "total": demo_total(),
                "lines": lines, "next": self.seq}


DEMO = DemoRunner()


def demo_total():
    """Complaints a replay of demo_set.csv will process (rows with a description, like vigil.load_csv)."""
    try:
        with open(DEMO_CSV, newline="", encoding="utf-8") as f:
            return sum(1 for r in csv.DictReader(f) if (r.get("event_description") or r.get("manufacturer_narrative") or "").strip())
    except Exception:
        return 0

# ---------------------------------------------------------------- system health (refreshed in the background)
HEALTH = {"model": {"ok": False, "label": "checking…"}, "telegram": {"ok": False, "label": "checking…"},
          "sync": {"ok": False, "label": "checking…"}, "checked": None}

def _check_model():
    try:
        name = requests.get(f"{LLM_BASE}/models", timeout=3).json()["data"][0]["id"]
        t0 = time.perf_counter()
        r = requests.post(f"{LLM_BASE}/chat/completions", timeout=15, json={
            "model": name, "max_tokens": 1, "temperature": 0, "messages": [{"role": "user", "content": "ping"}],
            "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": True, "name": name.split("/")[-1], "ms": round(ms), "label": f"{name.split('/')[-1]} · {ms:.0f} ms"}
    except Exception as e:
        return {"ok": False, "label": f"offline ({type(e).__name__})"}


def _check_telegram():
    try:
        t0 = time.perf_counter()
        requests.get("https://api.telegram.org", timeout=4, allow_redirects=False)
        return {"ok": True, "label": f"reachable · {(time.perf_counter() - t0) * 1000:.0f} ms"}
    except Exception:
        return {"ok": False, "label": "unreachable (alerts queue in outbox)"}


def _check_sync():
    r = subprocess.run(["pgrep", "-f", r"vigil\.py sync"], capture_output=True, text=True)
    pids = r.stdout.split()
    return {"ok": bool(pids), "label": "running" if pids else "not running"}


def health_loop():
    while True:
        HEALTH.update(model=_check_model(), telegram=_check_telegram(), sync=_check_sync(),
                      checked=dt.datetime.now().strftime("%H:%M:%S"))
        time.sleep(10)

# ---------------------------------------------------------------- pages / API
STEP_ICONS = {
    "done": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    "info": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M12 7v6M12 17h.01"/></svg>',
    "todo": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><circle cx="12" cy="12" r="3"/></svg>'}


@app.context_processor
def _globals():
    return {"health": HEALTH, "ICON": STEP_ICONS}


@app.route("/")
def home():
    return render_template("home.html", page="home")


def status_kind(s):
    s = s or ""
    return "appr" if s.startswith("APPROVED") else "info" if s.startswith("INFO REQUESTED") else "pend"


def days_left(r):
    try:
        return (dt.date.fromisoformat(r["due_date"]) - dt.date.today()).days
    except Exception:
        return None


def is_open(r):
    """Still owes the FDA a report: has a deadline, is reportable/unsure, and is not approved yet."""
    return bool(r.get("due_date")) and r.get("decision") != "NOT_REPORTABLE" and status_kind(r.get("status")) != "appr"


def brief(r):
    return {k: r.get(k, "") for k in ("time", "id", "device", "priority", "score", "decision", "category", "reason",
                                       "due_date", "deadline_days", "confidence", "status")} | {
        "status_kind": status_kind(r.get("status")), "days_left": days_left(r)}


@app.route("/api/state")
def api_state():
    rows = list(latest_by_id(read_rows()).values())
    open_rows = [r for r in rows if is_open(r)]
    kpi = {
        "processed": len(rows),
        "reportable": sum(r["decision"] == "REPORTABLE" for r in rows),
        "needs_info": sum(r["decision"] == "NEEDS_INFO" for r in rows),
        "due7": sum(0 <= (days_left(r) or 0) <= 7 for r in open_rows),
        "overdue": sum((days_left(r) or 0) < 0 for r in open_rows),
        "approved": sum(status_kind(r.get("status")) == "appr" for r in rows),
    }
    feed = sorted(rows, key=lambda r: r.get("time") or "", reverse=True)[:40]
    clock = sorted(open_rows, key=lambda r: (r["due_date"], -int(r.get("score") or 0)))
    return jsonify(kpi=kpi, feed=[brief(r) for r in feed], clock=[brief(r) for r in clock])


# ---------------------------------------------------------------- complaint detail
_source_cache = {"mtime": None, "rows": {}}

def source_complaint(cid):
    """The original MAUDE row from demo_set.csv (full text, event type, outcomes), if this complaint came from it."""
    try:
        m = os.path.getmtime(DEMO_CSV)
        if m != _source_cache["mtime"]:
            with open(DEMO_CSV, newline="", encoding="utf-8") as f:
                _source_cache.update(mtime=m, rows={r["mdr_report_key"]: r for r in csv.DictReader(f)})
        return _source_cache["rows"].get(cid)
    except Exception:
        return None


def score_breakdown(r):
    """Re-derive vigil.priority(): red-flag keywords + event type/outcome + 2 x distress = score."""
    src = source_complaint(r["id"]) or {}
    text = (src.get("event_description") or src.get("manufacturer_narrative") or r.get("text") or "").lower()
    try:
        v = vigil()
        flags, weights = v.RED_FLAGS, v.EVENT_WEIGHT
    except Exception:
        flags, weights = {}, {}
    kws = sorted(((k.strip(), w) for k, w in flags.items() if k in text), key=lambda x: -x[1])
    kw = sum(w for _, w in kws)
    distress = int(r.get("distress") or 0) * 2
    total = int(r.get("score") or 0)
    event_type, outcomes = src.get("event_type") or "", src.get("patient_outcomes") or ""
    if src:
        event = weights.get(event_type, 0) + (10 if "death" in outcomes.lower() else 4 if outcomes else 0)
    else:
        event = max(0, total - kw - distress)  # source row unknown: whatever the keywords and distress don't explain
    parts = [("Red-flag keywords", kw, "var(--navy)"), ("Event type & outcome", event, "var(--orange)"),
             ("Distress (×2)", distress, "var(--teal)")]
    return {"total": total, "keywords": kws, "parts": parts, "event_type": event_type, "outcomes": outcomes,
            "level": r.get("priority")}


_fq_cache = {}

def follow_up_questions(cid):
    """Section 10 of the drafted 3500A PDF (the model's follow-up questions). [] if no PDF / no pdftotext."""
    path = os.path.join(REPORTS, f"MDR_{cid}.pdf")
    if not os.path.exists(path):
        return []
    key = (path, os.path.getmtime(path))
    if key not in _fq_cache:
        try:
            txt = subprocess.run(["pdftotext", "-raw", path, "-"], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            txt = ""
        qs, on = [], False
        for line in txt.splitlines():
            line = line.strip()
            if re.match(r"\d+\.\s*Follow-up questions", line):
                on = True; continue
            if not on: continue
            if not line or line.startswith(("Fields marked UNKNOWN", "VIGIL |", "Generated locally")): break
            m = re.match(r"([1-9])\.\s+(.*)", line)
            if m: qs.append(m.group(2))
            elif qs: qs[-1] += " " + line  # wrapped question
        _fq_cache[key] = qs
    return _fq_cache[key]


def last_action(cid, since):
    """Latest console action (approve / info) for this complaint at or after its processing time."""
    if not os.path.exists(ACTIONS):
        return None
    with open(ACTIONS, newline="", encoding="utf-8") as f:
        hits = [a for a in csv.DictReader(f) if a["id"] == cid and a["time"] >= (since or "")]
    return hits[-1] if hits else None


def record_action(cid, kind, by):
    new = not os.path.exists(ACTIONS)
    with open(ACTIONS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "id", "kind", "by"])
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), cid, kind, by])


def alert_state(cid):
    """'queued' if the Telegram alert for this complaint is parked in outbox.txt (Telegram unreachable)."""
    try:
        with open(OUTBOX, encoding="utf-8") as f:
            return "queued" if f"#{cid}" in f.read() else "sent"
    except FileNotFoundError:
        return "sent"


def fmt_time(iso):
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M:%S")
    except Exception:
        return iso or ""


def detail(r):
    cid, t = r["id"], r.get("time") or ""
    kind = status_kind(r.get("status"))
    act = last_action(cid, t)
    reportable = r.get("decision") in ("REPORTABLE", "NEEDS_INFO")
    rec = r.get("received") or ""
    rec = f"{rec[:4]}-{rec[4:6]}-{rec[6:8]}" if re.fullmatch(r"\d{8}", rec) else rec
    if kind == "appr":
        final = ("done", "Approved", r["status"])
    elif kind == "info":
        final = ("info", "Info requested", r["status"])
    elif reportable:
        final = ("todo", "Awaiting review", "Approve the draft or request more information")
    else:
        final = ("done", "Logged for audit", "Not reportable: reason kept in the audit trail")
    when = fmt_time(act["time"]) if act and kind != "pend" else ""
    alert = alert_state(cid)
    timeline = [
        ("done", "Received", f"Vigil intake {fmt_time(t)}" + (f" · original FDA receipt {rec}" if rec else ""), ""),
        ("done", "Scored", f"{r.get('priority')} priority · score {r.get('score')} · distress {r.get('distress')}", ""),
        ("done", "AI classified", f"{(r.get('decision') or '').replace('_', ' ')} · {r.get('category')} · "
                                  f"{r.get('confidence')}% confidence · local model", ""),
        ("done" if alert == "sent" else "info", "Alert sent" if alert == "sent" else "Alert queued",
         "Telegram alert" + (" + draft Form 3500A" if reportable else "") if alert == "sent"
         else "Telegram unreachable · parked in outbox.txt", ""),
        (final[0], final[1], final[2], when),
    ]
    missing = [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()]
    questions = follow_up_questions(cid)
    if not questions and missing and reportable:
        questions = [f"Can you provide the {re.sub(r'\s*\(.*?\)', '', m).strip().rstrip('.').lower()}?" for m in missing[:5]]
    return {**r, "status_kind": kind, "days_left": days_left(r), "reportable": reportable, "timeline": timeline,
            "missing_list": missing, "questions": questions, "breakdown": score_breakdown(r),
            "pdf": os.path.exists(os.path.join(REPORTS, f"MDR_{cid}.pdf")), "processed": fmt_time(t), "received_iso": rec,
            "full_text": ((source_complaint(cid) or {}).get("event_description") or r.get("text") or "")}


@app.route("/complaint/<cid>")
def complaint(cid):
    r = latest_by_id(read_rows()).get(cid)
    if not r:
        return render_template("missing.html", page="", cid=cid), 404
    return render_template("complaint.html", page="", r=detail(r))


@app.route("/api/complaint/<cid>")
def api_complaint(cid):
    r = latest_by_id(read_rows()).get(cid)
    if not r:
        abort(404)
    d = detail(r)
    return jsonify({k: d[k] for k in ("status", "status_kind", "pdf", "questions")} | {"timeline": d["timeline"]})


@app.post("/api/complaint/<cid>/action")
def api_action(cid):
    data = request.get_json(silent=True) or request.form
    kind, name = data.get("kind"), " ".join((data.get("name") or "").split())[:60]
    if kind not in ("approve", "info"):
        return jsonify(error="unknown action"), 400
    if not name:
        return jsonify(error="Enter your name first."), 400
    if kind == "approve":
        status, guard = f"APPROVED by {name}", lambda s: not s.startswith("APPROVED")
    else:  # same rule as vigil.py / the OpenClaw skill: a request for info never overrides an approval
        status, guard = f"INFO REQUESTED by {name}", lambda s: not s.startswith("APPROVED")
    try:
        changed = set_status(cid, status, guard)
    except TimeoutError as e:
        return jsonify(error=str(e)), 503
    if changed is None:
        return jsonify(error="Complaint not found."), 404
    if not changed:
        return jsonify(error="Already approved; nothing changed."), 409
    record_action(cid, kind, name)
    return jsonify(ok=True, status=status)


@app.route("/demo")
def demo():
    return render_template("demo.html", page="demo", commands=DEMO_COMMANDS)


@app.route("/api/demo")
def api_demo():
    return jsonify(DEMO.public(int(request.args.get("since") or 0)))


@app.post("/api/demo/<action>")
def api_demo_action(action):
    if action in DEMO_COMMANDS:
        err = DEMO.start(action)
    elif action == "stop":
        err = DEMO.stop()
    else:
        abort(404)
    return (jsonify(error=err), 409) if err else jsonify(ok=True)


@app.route("/api/health")
def api_health():
    d = DEMO.public(since=10**12)
    return jsonify({**HEALTH, "demo": {k: d[k] for k in ("running", "kind", "processed", "total")}})


@app.route("/reports/<cid>.pdf")
def pdf(cid):
    return send_from_directory(REPORTS, f"MDR_{cid}.pdf", max_age=0)


@app.route("/chart.png")
def chart():
    return send_from_directory(VIGIL_DIR, "philips_chart.png", max_age=0)


def _shutdown(*_):
    if DEMO.running:
        DEMO.stop()  # the replay runs in its own process group; do not leave it orphaned
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _shutdown)
    threading.Thread(target=health_loop, daemon=True).start()
    print(f"Vigil Console v2 on http://localhost:5001  (data: {VIGIL_DIR})", flush=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("VIGIL_CONSOLE_PORT", 5001)), debug=False, threaded=True)

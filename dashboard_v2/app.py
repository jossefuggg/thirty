"""Vigil Console v2 - live, demo-ready command center for the Vigil complaint agent.

Reads ../decisions.csv (written by vigil.py), serves the draft 3500A PDFs from ../reports, drives demo
replays/resets of vigil.py in a subprocess, and shows live system health. vigil.py is never edited.
Everything is local: no CDNs, no external fonts.

Run in the background:  ~/hackathon/vigil/dashboard_v2/start_console.sh   ->  http://localhost:5001
"""
import copy, csv, datetime as dt, fcntl, io, json, os, re, secrets, shutil, signal, subprocess, sys, tempfile, threading, time, uuid
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
HISTORY = os.path.join(VIGIL_DIR, "history.csv")  # past FDA MAUDE reports (vigil.py import-history)
ACTIONS = os.environ.get("VIGIL_CONSOLE_ACTIONS", os.path.join(HERE, "actions.csv"))  # who/when for console actions
VENV_BIN = os.path.expanduser(os.environ.get("VIGIL_VENV_BIN", "~/hackathon/venv/bin"))
LLM_BASE = os.environ.get("VIGIL_LLM_BASE", "http://localhost:8000/v1")
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text",
          "product_code", "memory", "failure_mode", "source"]  # same order as vigil.FIELDS; older files stop earlier

VERSION = "1.0.0"
WORKSPACE = {"org": "Acme Medical", "unit": "Quality", "env": "ON-PREM · GB10 · PRODUCTION"}

app = Flask(__name__)
import logging; logging.getLogger("werkzeug").setLevel(logging.WARNING)  # polling would flood console.log

# ---------------------------------------------------------------- decisions.csv
_cache = {"rows": [], "mtime": None}

def parse_log(f):
    """(fieldnames, rows) for any decisions.csv format: old (no product_code/memory), new, or an old header with
    newer rows appended (their extra values land under DictReader's None key and are mapped onto the FIELDS
    that follow the header). Missing values become "", so templates never see None."""
    reader = csv.DictReader(f)
    fields, rows = list(reader.fieldnames or FIELDS), []
    for r in reader:
        extra = r.pop(None, None) or []
        if extra and fields == FIELDS[:len(fields)]:
            for k, v in zip(FIELDS[len(fields):], extra):
                r[k] = v
        rows.append({k: ("" if v is None else v) for k, v in r.items()})
    if any(k not in fields for r in rows for k in r):  # upgraded rows: write back with the full current header
        fields = fields + [k for k in FIELDS if k not in fields]
    return fields, rows

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
                rows = parse_log(f)[1]
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
            fields, rows = parse_log(f)
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

# ---------------------------------------------------------------- settings.json (console configuration)
SETTINGS = os.environ.get("VIGIL_CONSOLE_SETTINGS", os.path.join(HERE, "settings.json"))
INTAKE = os.environ.get("VIGIL_CONSOLE_INTAKE", os.path.join(HERE, "intake.json"))
VIGIL_FIELDS = [("id", "Complaint ID"), ("text", "Complaint text"), ("device", "Device / brand"), ("received", "Date received"),
                ("event_date", "Event date"), ("event_type", "Event type"), ("outcomes", "Patient outcome"),
                ("manufacturer", "Manufacturer"), ("product_code", "Product code"), ("product_problems", "Product problems"),
                ("reporter", "Reporter")]
DEFAULT_MAPPING = [  # source field -> Vigil field; FDA MAUDE export columns and common helpdesk names
    ("mdr_report_key", "id"), ("event_description", "text"), ("brand_name", "device"), ("date_received", "received"),
    ("date_of_event", "event_date"), ("event_type", "event_type"), ("patient_outcomes", "outcomes"),
    ("manufacturer", "manufacturer"), ("product_code", "product_code"), ("product_problems", "product_problems"),
    ("description", "text"), ("subject", "device"), ("case_number", "id"), ("contact_name", "reporter")]
CONNECTORS = [  # key, name, kind, fields of the config form
    ("salesforce", "Salesforce Service Cloud", "Case management", ["Instance URL", "Client ID", "Client secret", "Case queue"]),
    ("zendesk", "Zendesk", "Helpdesk", ["Subdomain", "Agent email", "API token", "View ID"]),
    ("servicenow", "ServiceNow", "ITSM / CSM", ["Instance URL", "Username", "Password", "Table"]),
    ("sap_qm", "SAP QM", "Quality notifications", ["Host", "Client", "User", "Password", "Notification type"]),
    ("trackwise", "MasterControl / TrackWise", "QMS / CAPA", ["Base URL", "API user", "API key", "Complaint form"]),
    ("slack", "Slack", "Alert routing", ["Bot token", "Channel"]),
    ("teams", "Microsoft Teams", "Alert routing", ["Incoming webhook URL", "Channel name"]),
]
_settings_lock = threading.Lock()


def load_settings():
    with _settings_lock:
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        changed = False
        if not st.get("api_key"):
            st["api_key"], changed = "vgl_" + secrets.token_hex(16), True
        if "mapping" not in st:
            st["mapping"], changed = [{"source": a, "target": b} for a, b in DEFAULT_MAPPING], True
        st.setdefault("imap", {}); st.setdefault("connectors", {})
        if changed:
            _save_settings_unlocked(st)
        return st


def _save_settings_unlocked(st):
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    os.chmod(tmp, 0o600)  # holds the API key and connector credentials
    os.replace(tmp, SETTINGS)


def save_settings(update):
    st = load_settings()
    with _settings_lock:
        st.update(update)
        _save_settings_unlocked(st)
    return st

# ---------------------------------------------------------------- intake queue (REST / CSV / e-mail -> vigil.process)
_intake_lock = threading.Lock()
_intake_wake = threading.Event()
_intake_cache = {"mtime": None, "items": []}


def intake_items():
    try:
        m = os.path.getmtime(INTAKE)
    except OSError:
        return []
    if _intake_cache["mtime"] != m:
        try:
            with open(INTAKE, encoding="utf-8") as f:
                _intake_cache.update(mtime=m, items=json.load(f))
        except (OSError, ValueError):
            pass
    return _intake_cache["items"]


def _write_intake(items):
    tmp = INTAKE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    os.replace(tmp, INTAKE)
    _intake_cache.update(mtime=os.path.getmtime(INTAKE), items=items)


def _update_item(iid, **kw):
    with _intake_lock:
        items = copy.deepcopy(intake_items())
        for it in items:
            if it["iid"] == iid:
                it.update(kw)
        _write_intake(items)


def source_of(cid):
    """Where a complaint came from: the intake item that produced it, else the MAUDE demo replay."""
    for it in reversed(intake_items()):
        if it.get("cid") == cid and it.get("status") in ("processed", "processing", "queued"):
            return it["source"]
    return "replay"


SOURCES = {"rest": ("REST API", "zap"), "csv": ("File upload", "upload"), "email": ("Email", "mail"),
           "replay": ("MAUDE replay", "play"), "test": ("API test", "zap")}


def _yyyymmdd(v):
    v = str(v or "").strip()
    if re.fullmatch(r"\d{8}", v):
        return v
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(v[:19], fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    return ""


def normalize(raw, mapping):
    """Raw record (any field names) -> the complaint dict vigil.process() expects, via the field mapping.
    Fields already named like Vigil fields pass through unchanged."""
    norm = lambda k: re.sub(r"[\s\-/]+", "_", str(k).strip().lower())  # 'Case Number' == 'case_number'
    m = {norm(x["source"]): x["target"] for x in mapping if x.get("source") and x.get("target")}
    c = {}
    for k, v in raw.items():
        key = str(k).strip()
        target = key if key in dict(VIGIL_FIELDS) else m.get(norm(key))
        if target and v not in (None, "") and not c.get(target):
            c[target] = str(v).strip()
    c["received"] = _yyyymmdd(c.get("received")) or dt.date.today().strftime("%Y%m%d")
    c["event_date"] = _yyyymmdd(c.get("event_date"))
    for k in ("device", "event_type", "outcomes", "manufacturer", "product_code", "product_problems", "reporter"):
        c.setdefault(k, "")
    c.update(generic_name="", manufacturer_narrative="")
    return c


def enqueue(records, source, reporter=""):
    """Queue raw records. Returns [{iid, id, status, error?}]. Duplicates (id already logged or queued) are kept as
    'duplicate' items that point at the existing complaint; records without text are rejected."""
    mapping = load_settings()["mapping"]
    logged = {r["id"] for r in read_rows()}
    out = []
    with _intake_lock:
        items = copy.deepcopy(intake_items())
        active = {it["cid"] for it in items if it["status"] in ("queued", "processing", "processed")}
        for raw in records:
            c = normalize(raw, mapping)
            now = dt.datetime.now()
            if not c.get("text"):
                out.append({"id": c.get("id", ""), "status": "rejected", "error": "missing complaint text"}); continue
            if not c.get("id"):
                c["id"] = f"{source[:3].upper()}-{now:%y%m%d%H%M%S}-{secrets.token_hex(2).upper()}"
            c["id"] = re.sub(r"[^A-Za-z0-9_.-]", "-", c["id"])[:40]
            status = "duplicate" if (c["id"] in logged or c["id"] in active) else "queued"
            it = {"iid": uuid.uuid4().hex[:10], "source": source, "reporter": c.get("reporter") or reporter or "",
                  "received": now.isoformat(timespec="seconds"), "status": status, "cid": c["id"],
                  "device": c.get("device", ""), "excerpt": c["text"][:200], "complaint": c}
            items.append(it); active.add(c["id"])
            out.append({"iid": it["iid"], "id": c["id"], "status": status})
        _write_intake(items[-2000:])
    if any(o["status"] == "queued" for o in out):
        start_intake_worker(); _intake_wake.set()
    return out


_process_lock = threading.Lock()
_worker = {"thread": None, "current": None}


def _intake_loop():
    while True:
        nxt = next((it for it in intake_items() if it["status"] == "queued"), None)
        if not nxt:
            _intake_wake.wait(5); _intake_wake.clear(); continue
        _update_item(nxt["iid"], status="processing", started=dt.datetime.now().isoformat(timespec="seconds"))
        _worker["current"] = nxt["iid"]
        try:
            with _process_lock:  # one complaint at a time through the local model
                row = vigil().process(dict(nxt["complaint"]))
            _update_item(nxt["iid"], status="processed", decision=row.get("decision"),
                         finished=dt.datetime.now().isoformat(timespec="seconds"))
        except Exception as e:
            print("intake processing failed:", nxt["iid"], type(e).__name__, e, flush=True)
            _update_item(nxt["iid"], status="error", error=f"{type(e).__name__}: {e}"[:300])
        _worker["current"] = None


def start_intake_worker(recover=False):
    if recover:  # items that were mid-classification when the console stopped go back to the queue
        with _intake_lock:
            items = copy.deepcopy(intake_items())
            if any(it["status"] == "processing" for it in items):
                for it in items:
                    if it["status"] == "processing":
                        it["status"] = "queued"
                _write_intake(items)
    if not (_worker["thread"] and _worker["thread"].is_alive()):
        _worker["thread"] = threading.Thread(target=_intake_loop, daemon=True)
        _worker["thread"].start()


def read_upload(f):
    """Rows from an uploaded CSV / Excel file as dicts (header row = field names)."""
    name = (f.filename or "").lower()
    data = f.read()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        import pandas as pd
        df = pd.read_excel(io.BytesIO(data), dtype=str).fillna("")
        return df.to_dict("records")
    text = data.decode("utf-8-sig", errors="replace")
    csv.field_size_limit(sys.maxsize)
    return list(csv.DictReader(io.StringIO(text)))

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


_tg_fails = {"n": 0, "last_ok": None}

def _check_telegram():
    """Reachability of api.telegram.org, debounced: one slow or failed probe must not flip the badge.
    Reported offline only after 3 consecutive failures."""
    now = dt.datetime.now().strftime("%H:%M:%S")
    try:
        t0 = time.perf_counter()
        requests.get("https://api.telegram.org", timeout=4, allow_redirects=False)
        _tg_fails.update(n=0, last_ok=now)
        return {"ok": True, "label": f"reachable · {(time.perf_counter() - t0) * 1000:.0f} ms", "checked": now, "fails": 0}
    except Exception:
        _tg_fails["n"] += 1
        prev = HEALTH.get("telegram") or {}
        if _tg_fails["n"] < 3 and prev.get("ok"):
            return {**prev, "checked": now, "fails": _tg_fails["n"]}  # keep showing Online
        return {"ok": False, "label": "unreachable (alerts queue in outbox)", "checked": now, "fails": _tg_fails["n"],
                "last_ok": _tg_fails["last_ok"]}


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
def _svg(body, fill="none"):
    return (f'<svg class="i" viewBox="0 0 24 24" fill="{fill}" stroke="currentColor" stroke-width="1.75" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')

# Simple line icons (inline SVG, no icon font / CDN). Shared by Jinja (icon()) and JS (window.ICONS).
ICONS = {k: _svg(v) for k, v in {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l5.5-3.5z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "brain": '<path d="M9.5 4A2.5 2.5 0 0 0 7 6.5v.2A3 3 0 0 0 4.5 10a3 3 0 0 0 .7 1.9A3 3 0 0 0 6 17a2.5 2.5 0 0 0 3.5 2.3A2.5 2.5 0 0 0 12 18V6.5A2.5 2.5 0 0 0 9.5 4z"/><path d="M14.5 4A2.5 2.5 0 0 1 17 6.5v.2a3 3 0 0 1 2.5 3.3 3 3 0 0 1-.7 1.9A3 3 0 0 1 18 17a2.5 2.5 0 0 1-3.5 2.3A2.5 2.5 0 0 1 12 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01"/>',
    "alert": '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "cpu": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
    "sync": '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "arrow-left": '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    "chevron": '<path d="M9 6l6 6-6 6"/>',
    "scale": '<path d="M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "zap": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
    "upload": '<path d="M12 20V9M7 14l5-5 5 5M5 4h14"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M15 8l2 2"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
}.items()}
STEP_ICONS = {"done": ICONS["check"], "info": ICONS["help"], "todo": _svg('<circle cx="12" cy="12" r="3"/>')}

NAV = [("home", "/", "Command Center", "grid"), ("intake", "/intake", "Intake inbox", "download"), ("complaints", "/complaints", "Complaints", "inbox"),
       ("clock", "/clock", "Compliance Clock", "clock"), ("trends", "/trends", "Trends", "trend"),
       ("audit", "/audit", "Audit Log", "file"), ("integrations", "/integrations", "Integrations", "plug"), ("demo", "/demo", "Demo Control", "play")]


@app.context_processor
def _globals():
    from markupsafe import Markup
    return {"health": HEALTH, "ICON": STEP_ICONS, "ICONS": ICONS, "NAV": NAV, "VERSION": VERSION, "WS": WORKSPACE, "SOURCES": SOURCES,
            "icon": lambda name: Markup(ICONS.get(name, ""))}


@app.route("/")
def home():
    return render_template("home.html", page="home", title="Command Center")


PLACEHOLDERS = {"complaints": "Complaints", "clock": "Compliance Clock", "audit": "Audit Log"}

@app.route("/<any(complaints, clock, audit):name>")
def placeholder(name):
    return render_template("placeholder.html", page=name, title=PLACEHOLDERS[name])


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


def memory_text(r):
    """Long-term memory line without vigil.py's "🧠 Memory:" prefix (the UI adds the icon). "" for old rows."""
    return re.sub(r"^\s*(?:🧠\s*)?(?:memory\s*:\s*)?", "", r.get("memory") or "", flags=re.I).strip()


PRIORITY_RANK = {"URGENT": 0, "HIGH": 1, "NORMAL": 2}
MAKER_WORDS = {"PHILIPS", "RESPIRONICS", "PHILIPS-RESPIRONICS"}
# Device problems for pattern alerts (vigil.PROBLEM_WORDS minus patient outcomes/symptoms), grouped to one label.
ISSUES = {"foam": "foam", "particle": "particles", "black dust": "particles", "debris": "particles", "shock": "shock",
          "shutdown": "shutdown", "shut off": "shutdown", "shuts down": "shutdown", "shut down": "shutdown",
          "stopped working": "shutdown", "melt": "fire / smoke", "fire": "fire / smoke",
          "smoke": "fire / smoke", "burn": "fire / smoke", "overheat": "overheating", "alarm": "alarm",
          "pressure": "pressure", "water": "water / leak", "leak": "water / leak", "noise": "noise"}


def device_family(device):
    """Same grouping as vigil.py (memory, spike alerts): 'PHILIPS CPAP SYSTEM ONE REMSTAR' -> 'SYSTEM ONE'."""
    try:
        return vigil().device_family(device)
    except Exception:  # vigil.py not importable: first non-maker word
        words = [w for w in re.split(r"[\s,/]+", (device or "").upper()) if w and w not in MAKER_WORDS]
        return words[0] if words else "UNKNOWN"


def issues_of(r):
    src = source_complaint(r["id"]) or {}  # full narrative when the complaint came from demo_set.csv (log text is cut at 500)
    t = " ".join([r.get("text") or "", src.get("event_description") or "", src.get("manufacturer_narrative") or ""]).lower()
    t = re.sub(r"(continuous |bi-?level )?positive airway pressure", " ", t)  # the device's name, not a pressure problem
    return sorted({label for k, label in ISSUES.items() if k in t})


def memory_parts(r):
    """'412 prior complaints on DREAMSTATION (top issue: material degradation/particles, last: 2 Nov 2021)'
    (or the older '... on X in 90 days (top issue: foam)') -> {count, key, days, issue, last}; None if absent."""
    m = re.search(r"(\d+)\s+prior complaints?\s+on\s+(.+?)(?:\s+in\s+(\d+)\s+days)?\s*"
                  r"(?:\(top issue:\s*([^,)]+)(?:,\s*last:\s*([^)]+))?\))?\s*$", memory_text(r), re.I)
    return {"count": int(m.group(1)), "key": m.group(2), "days": int(m.group(3) or 0), "issue": m.group(4) or "",
            "last": m.group(5) or ""} if m else None


def sentence_case(t):
    """MAUDE narratives are ALL CAPS; soften them for excerpts (the full record keeps the original)."""
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t.lower())
        t = re.sub(r"\b(cpap|bipap|fda|mdr|er|icu|cfr|res|avaps\d*|udi|pt)\b", lambda m: m.group(1).upper(), t, flags=re.I)
    return t


def ptime(r):
    try:
        return dt.datetime.fromisoformat(r.get("time") or "")
    except Exception:
        return None


def brief(r):
    text = r.get("text") or ""
    try:
        conf = max(0, min(100, int(float(r.get("confidence") or 0))))
    except ValueError:
        conf = 0
    return {k: r.get(k, "") for k in ("time", "id", "device", "priority", "score", "decision", "category", "reason",
                                       "due_date", "deadline_days", "status", "product_code")} | {
        "confidence": conf, "status_kind": status_kind(r.get("status")), "days_left": days_left(r),
        "memory": memory_text(r), "mem": memory_parts(r), "excerpt": sentence_case(text[:260]),
        "family": device_family(r.get("device")), "open": is_open(r), "source": source_of(r["id"])}


def approvals_at():
    """complaint id -> time of the latest console approval (for the Approved sparkline)."""
    out = {}
    if os.path.exists(ACTIONS):
        with open(ACTIONS, newline="", encoding="utf-8") as f:
            for a in csv.DictReader(f):
                if a.get("kind") == "approve":
                    out[a["id"]] = a["time"]
    return out


def kpis(rows):
    now, today = dt.datetime.now(), dt.date.today()
    appr_t = approvals_at()
    preds = {
        "processed": lambda r: (ptime(r) or now).date() == today,
        "reportable": lambda r: r.get("decision") == "REPORTABLE",
        "needs_info": lambda r: r.get("decision") == "NEEDS_INFO",
        "due7": lambda r: is_open(r) and 0 <= (days_left(r) if days_left(r) is not None else 99) <= 7,
        "overdue": lambda r: is_open(r) and (days_left(r) if days_left(r) is not None else 0) < 0,
        "approved": lambda r: status_kind(r.get("status")) == "appr",
    }
    def when(k, r):
        if k == "approved" and r["id"] in appr_t:
            try: return dt.datetime.fromisoformat(appr_t[r["id"]])
            except ValueError: pass
        return ptime(r) or now
    out = {}
    edges = [now - dt.timedelta(minutes=30 - 2 * i) for i in range(16)]  # 15 two-minute buckets, cumulative
    for k, pred in preds.items():
        hits = [when(k, r) for r in rows if pred(r)]
        out[k] = {"value": len(hits),
                  "delta5": sum(t >= now - dt.timedelta(minutes=5) for t in hits),
                  "spark": [sum(t <= e for t in hits) for e in edges]}
    return out


# ---------------------------------------------------------------- history.csv (FDA MAUDE long-term memory)
_hist = {"mtime": None, "rows": []}

def history_rows():
    """[(date, family, failure_mode, event_type, id)] from history.csv, cached until the file changes.
    Text is not kept: 24k narratives are not needed for counting."""
    try:
        m = os.path.getmtime(HISTORY)
    except OSError:
        _hist.update(mtime=None, rows=[])
        return []
    if _hist["mtime"] != m:
        csv.field_size_limit(sys.maxsize)
        out = []
        with open(HISTORY, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    d = dt.date.fromisoformat((r.get("date_received") or "")[:10])
                except ValueError:
                    continue
                out.append((d, r.get("device_family") or "UNKNOWN", r.get("failure_mode") or "other",
                            r.get("event_type") or "", r.get("id") or ""))
        _hist.update(mtime=m, rows=out)
    return _hist["rows"]


def live_family(r):
    """Same grouping as history.csv: vigil.device_family() when available (falls back to the console's)."""
    fn = getattr(vigil(), "device_family", None)
    try:
        return fn(r.get("device")) if fn else device_family(r.get("device"))
    except Exception:
        return device_family(r.get("device"))


def live_mode(r):
    """failure_mode column when vigil.py wrote one, else vigil.failure_mode() on the complaint text."""
    if r.get("failure_mode"):
        return r["failure_mode"]
    src = source_complaint(r["id"]) or {}
    fn = getattr(vigil(), "failure_mode", None)
    if not fn:  # older vigil.py: map the console's keyword issues onto vigil's failure-mode vocabulary
        fallback = {"fire / smoke": "electrical/shock/fire", "shock": "electrical/shock/fire", "foam": "material degradation/particles",
                    "particles": "material degradation/particles", "alarm": "alarm failure", "shutdown": "power/shutdown",
                    "overheating": "electrical/shock/fire", "pressure": "pressure/airflow", "water / leak": "contamination"}
        found = [fallback[i] for i in issues_of(r) if i in fallback]
        order = ["electrical/shock/fire", "material degradation/particles", "alarm failure", "power/shutdown", "pressure/airflow", "contamination"]
        return min(found, key=order.index) if found else "other"
    try:
        return fn(src.get("product_problems") or "", src.get("event_description") or r.get("text") or "")
    except Exception:
        return "other"


def pattern_alerts(rows, days=90, min_live=2, threshold=3):
    """Same device family + same failure mode, FDA history + live complaints. Fires when the mode recurs live
    (>= min_live in the last `days`) and history + live >= threshold. 'other' is not a pattern."""
    since = dt.datetime.now() - dt.timedelta(days=days)
    live = defaultdict(list)
    for r in rows:
        if (ptime(r) or dt.datetime.now()) >= since:
            mode = live_mode(r)
            if mode != "other":
                live[(live_family(r), mode)].append(r)
    hist = defaultdict(int)
    for d, fam, mode, _, _ in history_rows():
        if (fam, mode) in live:
            hist[(fam, mode)] += 1
    today = dt.date.today()
    alerts = []
    for (fam, mode), hits in live.items():
        n_hist = hist[(fam, mode)]
        if len(hits) >= min_live and len(hits) + n_hist >= threshold:
            hits = sorted(hits, key=lambda r: r.get("time") or "", reverse=True)
            all_today = all((ptime(r) or dt.datetime.now()).date() == today for r in hits)
            alerts.append({"family": fam, "issue": mode, "count": len(hits) + n_hist, "historical": n_hist,
                           "live": len(hits), "live_label": "today" if all_today else f"in {days} days",
                           "days": days, "reportable": sum(r.get("decision") == "REPORTABLE" for r in hits),
                           "ids": [r["id"] for r in hits], "latest": hits[0].get("time")})
    return sorted(alerts, key=lambda a: (-a["live"], -a["historical"], a["family"]))


def pipeline(rows):
    reviewable = [r for r in rows if r.get("decision") in ("REPORTABLE", "NEEDS_INFO")]
    decided = [r for r in reviewable if status_kind(r.get("status")) != "pend"]
    return {"intake": len(rows), "urgent": sum(r.get("priority") == "URGENT" for r in rows),
            "scored": sum(bool(str(r.get("score") or "").strip()) for r in rows),
            "checked": sum(bool(r.get("decision")) for r in rows),
            "reportable": sum(r.get("decision") == "REPORTABLE" for r in rows),
            "needs_info": sum(r.get("decision") == "NEEDS_INFO" for r in rows),
            "not_reportable": sum(r.get("decision") == "NOT_REPORTABLE" for r in rows),
            "decided": len(decided), "reviewable": len(reviewable),
            "approved": sum(status_kind(r.get("status")) == "appr" for r in rows),
            "info": sum(status_kind(r.get("status")) == "info" for r in rows)}


def all_rows():
    return list(latest_by_id(read_rows()).values())


@app.route("/api/state")
def api_state():
    rows = all_rows()
    feed = sorted(rows, key=lambda r: r.get("time") or "", reverse=True)[:40]
    queue = sorted((r for r in rows if r.get("decision") in ("REPORTABLE", "NEEDS_INFO")
                    and status_kind(r.get("status")) == "pend"),
                   key=lambda r: (PRIORITY_RANK.get(r.get("priority"), 3), r.get("due_date") or "9999", -int(r.get("score") or 0)))
    clock = sorted((r for r in rows if is_open(r)), key=lambda r: (r["due_date"], -int(r.get("score") or 0)))
    return jsonify(kpi=kpis(rows), feed=[brief(r) for r in feed], queue=[brief(r) for r in queue],
                   alerts=pattern_alerts(rows), pipeline=pipeline(rows), clock=[brief(r) for r in clock],
                   demo={k: v for k, v in DEMO.public(since=10**12).items() if k in ("running", "kind", "processed", "total")})


RECALL = ("2021-06", "Philips recall · 14 Jun 2021")


@app.route("/trends")
def trends():
    return render_template("trends.html", page="trends", title="Trends", chart=os.path.exists(CHART))


@app.route("/api/trends")
def api_trends():
    """Monthly complaints per device family, failure modes ranked, events per quarter: history.csv + decisions.csv."""
    hist = history_rows()
    live = [(ptime(r) or dt.datetime.now(), r) for r in all_rows()]
    fam_tot = defaultdict(lambda: [0, 0])
    for _, fam, _, _, _ in hist:
        fam_tot[fam][0] += 1
    for _, r in live:
        fam_tot[live_family(r)][1] += 1
    families = sorted(fam_tot.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
    fam = request.args.get("family") or ("DREAMSTATION" if "DREAMSTATION" in fam_tot else (families[0][0] if families else ""))
    pick = (lambda f: True) if fam == "ALL" else (lambda f: f == fam)

    months, modes, quarters = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: defaultdict(int))
    def ev(e):
        e = (e or "").upper()
        return "Death" if "DEATH" in e else "Injury" if "INJUR" in e else "Malfunction" if "MALFUNCTION" in e else ""
    for d, f, mode, e, _ in hist:
        if pick(f):
            months[d.strftime("%Y-%m")][0] += 1; modes[mode][0] += 1
            if ev(e): quarters[f"{d.year}-Q{(d.month - 1) // 3 + 1}"][ev(e)] += 1
    for t, r in live:
        if pick(live_family(r)):
            months[t.strftime("%Y-%m")][1] += 1; modes[live_mode(r)][1] += 1
            e = ev(r.get("category") or "") or ("Malfunction" if r.get("category") == "MALFUNCTION" else "")
            if r.get("category") == "SERIOUS_INJURY": e = "Injury"
            if e: quarters[f"{t.year}-Q{(t.month - 1) // 3 + 1}"][e] += 1

    def month_range(keys):
        if not keys: return []
        y, m = map(int, min(keys).split("-")); y2, m2 = map(int, max(keys).split("-")); out = []
        while (y, m) <= (y2, m2):
            out.append(f"{y}-{m:02d}"); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    mkeys = month_range(list(months))
    qkeys = sorted(quarters)
    if qkeys:
        (y, q), (y2, q2) = [tuple(map(int, k.split("-Q"))) for k in (qkeys[0], qkeys[-1])]; qkeys = []
        while (y, q) <= (y2, q2):
            qkeys.append(f"{y}-Q{q}"); y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return jsonify(
        family=fam, has_history=bool(hist), history_rows=len(hist), live_rows=len(live),
        families=[{"family": f, "history": h, "live": l} for f, (h, l) in families[:12]],
        months=[{"m": k, "history": months[k][0], "live": months[k][1]} for k in mkeys],
        modes=sorted(({"mode": k, "history": v[0], "live": v[1]} for k, v in modes.items()), key=lambda x: -(x["history"] + x["live"])),
        quarters=[{"q": k, "Death": quarters[k]["Death"], "Injury": quarters[k]["Injury"], "Malfunction": quarters[k]["Malfunction"]} for k in qkeys],
        recall={"month": RECALL[0], "label": RECALL[1]})


@app.route("/api/notifications")
def api_notifications():
    """Bell feed: newest classifications, pattern alerts and overdue reports (the client tracks what was seen)."""
    rows = all_rows()
    ev = []
    for r in sorted(rows, key=lambda r: r.get("time") or "", reverse=True)[:12]:
        ev.append({"t": r.get("time") or "", "kind": "classified", "id": r["id"],
                   "title": f"#{r['id']} classified {(r.get('decision') or '').replace('_', ' ')}",
                   "sub": f"{r.get('device') or 'Unknown device'} · {r.get('priority')}"})
    for a in pattern_alerts(rows):
        ev.append({"t": a.get("latest") or "", "kind": "pattern", "id": a["ids"][0],
                   "title": f"Pattern: {a['family']} · {a['issue']}", "sub": f"{a['historical']:,} historical + {a['live']} {a['live_label']}"})
    for r in rows:
        if is_open(r) and (days_left(r) or 0) < 0:
            ev.append({"t": r.get("time") or "", "kind": "overdue", "id": r["id"], "title": f"#{r['id']} is overdue",
                       "sub": f"Due {r.get('due_date')} · {r.get('deadline_days')}-day report"})
    ev.sort(key=lambda e: e["t"], reverse=True)
    return jsonify(events=ev[:15])


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify(results=[])
    rows = sorted(all_rows(), key=lambda r: r.get("time") or "", reverse=True)
    hits = [r for r in rows if q in (r.get("id") or "").lower() or q in (r.get("device") or "").lower()
            or q in (r.get("text") or "").lower() or q in (r.get("reason") or "").lower()]
    return jsonify(results=[brief(r) for r in hits[:8]], total=len(hits))


@app.route("/api/summary/<cid>")
def api_summary(cid):
    """Compact record for the detail drawer."""
    r = latest_by_id(read_rows()).get(cid)
    if not r:
        abort(404)
    return jsonify(brief(r) | {"text": r.get("text") or "", "missing": [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()],
                               "pdf": os.path.exists(os.path.join(REPORTS, f"MDR_{cid}.pdf")), "processed": fmt_time(r.get("time"))})


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
    raw = src.get("event_description") or src.get("manufacturer_narrative") or r.get("text") or ""
    matcher = getattr(vigil(), "red_flag_hits", None) if flags else None  # same whole-word matcher as vigil.priority()
    hits = matcher(raw) if matcher else [(k, w) for k, w in flags.items() if k in raw.lower()]  # older vigil.py
    kws = sorted(hits, key=lambda x: -x[1])
    kw = sum(w for _, w in kws)
    distress = int(r.get("distress") or 0) * 2
    total = int(r.get("score") or 0)
    event_type, outcomes = src.get("event_type") or "", src.get("patient_outcomes") or ""
    if src:
        event = weights.get(event_type, 0)
        outcome = 10 if "death" in outcomes.lower() else 4 if outcomes else 0
        parts = [("Red-flag keywords", kw, "#0B1F3A"), ("Event type", event, "#EA580C"),
                 ("Patient outcome", outcome, "#DC2626"), ("Distress ×2", distress, "#0EA5A4")]
    else:  # source row unknown: whatever keywords and distress don't explain is event type + outcome
        parts = [("Red-flag keywords", kw, "#0B1F3A"), ("Event type & outcome", max(0, total - kw - distress), "#EA580C"),
                 ("Distress ×2", distress, "#0EA5A4")]
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


LEGAL = {"DEATH": "21 CFR 803.50(a)(1)", "SERIOUS_INJURY": "21 CFR 803.50(a)(1)", "MALFUNCTION": "21 CFR 803.50(a)(2)"}


def legal_basis(r):
    if r.get("decision") == "NOT_REPORTABLE":
        return "21 CFR 803 · no MDR required"
    base = LEGAL.get((r.get("category") or "").upper(), "21 CFR 803.50(a)")
    if str(r.get("deadline_days")) == "5":
        base += " · 803.53 (5-day)"
    return base + (" · facts pending" if r.get("decision") == "NEEDS_INFO" else "")


def short_time(iso):
    """'14:52:05' today, '3 Oct, 14:52' otherwise."""
    try:
        t = dt.datetime.fromisoformat(iso)
    except Exception:
        return ""
    return t.strftime("%H:%M:%S") if t.date() == dt.date.today() else t.strftime("%-d %b, %H:%M")


def device_history(r, rows, days=90):
    """Console-side memory: earlier complaints on the same device family within `days` of this one."""
    fam, t = device_family(r.get("device")), ptime(r)
    prior = [x for x in rows if x["id"] != r["id"] and device_family(x.get("device")) == fam
             and (t is None or ((ptime(x) or t) <= t and (t - (ptime(x) or t)).days <= days))]
    prior.sort(key=lambda x: x.get("time") or "", reverse=True)
    counts = defaultdict(int)
    for x in prior:
        for i in issues_of(x):
            counts[i] += 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])
    return {"family": fam, "count": len(prior), "days": days, "top": top[:3],
            "recent": [brief(x) for x in prior[:8]], "model_line": memory_text(r)}


def detail(r, rows=None):
    rows = rows if rows is not None else all_rows()
    cid, t = r["id"], r.get("time") or ""
    kind = status_kind(r.get("status"))
    act = last_action(cid, t)
    reportable = r.get("decision") in ("REPORTABLE", "NEEDS_INFO")
    pdf_path = os.path.join(REPORTS, f"MDR_{cid}.pdf")
    has_pdf = os.path.exists(pdf_path)
    pdf_t = dt.datetime.fromtimestamp(os.path.getmtime(pdf_path)).isoformat(timespec="seconds") if has_pdf else ""
    rec = r.get("received") or ""
    rec_d = dt.date(int(rec[:4]), int(rec[4:6]), int(rec[6:8])) if re.fullmatch(r"\d{8}", rec) else None
    b = score_breakdown(r)
    alert = alert_state(cid)
    act_t = act["time"] if act and kind != "pend" else ""

    # timeline: (state, title, detail, time) with state done | current | future | skip | warn
    steps = [
        ["done", "Received", "Original FDA receipt " + rec_d.strftime("%-d %b %Y") if rec_d else "Complaint taken in", t],
        ["done", "Priority scored", f"{r.get('priority')} · score {r.get('score')} · distress {r.get('distress')}/5", t],
        ["done", "AI classified", f"{(r.get('decision') or '').replace('_', ' ')} · {r.get('category')} · {r.get('confidence')}% confidence", t],
        ["done" if alert == "sent" else "warn", "Telegram alert sent" if alert == "sent" else "Telegram alert queued",
         "Card with Approve / Request info buttons" if alert == "sent" else "Telegram unreachable · parked in outbox.txt", t],
    ]
    if reportable:
        steps.append(["done", "Form 3500A drafted", f"MDR_{cid}.pdf", pdf_t] if has_pdf
                     else ["current", "Form 3500A drafting", "Local model is filling the form", ""])
    else:
        steps.append(["skip", "Form 3500A", "Not required: complaint is not reportable", ""])
    if kind == "appr":
        steps.append(["done", "Approved", r["status"].replace("APPROVED by ", "by "), act_t])
    elif kind == "info":
        steps.append(["current", "Info requested", r["status"].replace("INFO REQUESTED by ", "by ") + " · awaiting reporter", act_t])
    elif reportable:
        steps.append(["current" if has_pdf else "future", "Human decision", "Approve the draft or request info", ""])
    else:
        steps.append(["done", "Logged for audit", "Reason kept in the audit trail", t])
    for st in steps:
        st[3] = short_time(st[3]) if st[3] else ""

    missing = [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()]
    questions = follow_up_questions(cid)
    if not questions and missing and reportable:
        questions = [f"Can you provide the {re.sub(r'\s*\(.*?\)', '', m).strip().rstrip('.').lower()}?" for m in missing[:5]]
    src = source_complaint(cid) or {}
    try:
        conf = max(0, min(100, int(float(r.get("confidence") or 0))))
    except ValueError:
        conf = 0
    return {**r, "status_kind": kind, "days_left": days_left(r), "reportable": reportable, "open": is_open(r),
            "timeline": steps, "missing_list": missing, "questions": questions, "breakdown": b, "conf": conf,
            "legal": legal_basis(r), "pdf": has_pdf, "processed": fmt_time(t), "received_d": rec_d,
            "act": act if kind != "pend" else None, "act_time": fmt_time(act_t) if act_t else "",
            "history": device_history(r, rows), "family": device_family(r.get("device")), "source": source_of(cid),
            "full_text": src.get("event_description") or r.get("text") or "",
            "narrative": src.get("manufacturer_narrative") or "", "src": src,
            "due_label": dt.date.fromisoformat(r["due_date"]).strftime("%-d %b %Y") if r.get("due_date") else ""}


@app.route("/complaint/<cid>")
def complaint(cid):
    rows = all_rows()
    r = next((x for x in rows if x["id"] == cid), None)
    if not r:
        return render_template("missing.html", page="", cid=cid, title="Complaint not found"), 404
    return render_template("complaint.html", page="complaints", r=detail(r, rows), title=f"Complaint #{cid}")


@app.route("/api/complaint/<cid>")
def api_complaint(cid):
    """Live parts of the detail page, rendered server-side (one template for first paint and updates)."""
    rows = all_rows()
    r = next((x for x in rows if x["id"] == cid), None)
    if not r:
        abort(404)
    d = detail(r, rows)
    frag = {k: render_template(f"_detail_{k}.html", r=d) for k in ("review", "timeline", "pdf", "status_pill", "cd")}
    frag["hstatus"] = frag.pop("status_pill")
    return jsonify(frag | {"status": d.get("status"), "status_kind": d["status_kind"], "pdf": d["pdf"]})


@app.post("/api/complaint/<cid>/action")
def api_action(cid):
    data = request.get_json(silent=True) or request.form
    kind, name = data.get("kind"), " ".join((data.get("name") or "").split())[:60]
    if kind not in ("approve", "info", "undo"):
        return jsonify(error="unknown action"), 400
    if not name:
        return jsonify(error="Enter your name first."), 400
    if kind == "undo":  # back to the review queue (only from an approval or info request)
        status, guard = "PENDING_REVIEW", lambda s: s.startswith(("APPROVED", "INFO REQUESTED"))
    elif kind == "approve":
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
        return jsonify(error="Nothing to undo." if kind == "undo" else "Already approved; nothing changed."), 409
    record_action(cid, kind, name)
    return jsonify(ok=True, status=status)


@app.route("/demo")
def demo():
    return render_template("demo.html", page="demo", commands=DEMO_COMMANDS, title="Demo Control")


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


# ---------------------------------------------------------------- integrations + intake inbox
SAMPLE_COMPLAINT = {"text": "Customer reports the DreamStation Auto CPAP stopped delivering pressure overnight and black particles were found "
                            "in the humidifier chamber. The patient woke up short of breath and visited urgent care the next morning.",
                    "device": "DREAMSTATION AUTO CPAP", "event_type": "Injury", "reporter": "Integration test"}


def api_key_ok():
    key = request.headers.get("X-API-Key") or (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    return bool(key) and secrets.compare_digest(key, load_settings()["api_key"])


@app.post("/api/complaints")
def api_complaints_in():
    """Intake endpoint: JSON object or list {id?, text, device, event_date, received, event_type, outcomes, ...}."""
    if not api_key_ok():
        return jsonify(error="invalid or missing API key (X-API-Key header)"), 401
    body = request.get_json(silent=True)
    records = body if isinstance(body, list) else [body] if isinstance(body, dict) else None
    if not records or not all(isinstance(x, dict) for x in records):
        return jsonify(error="expected a JSON object or a list of objects"), 400
    res = enqueue(records[:500], "rest")
    return jsonify(accepted=sum(r["status"] == "queued" for r in res), items=res), 202


@app.post("/api/integrations/rest/test")
def api_rest_test():
    return jsonify(items=enqueue([dict(SAMPLE_COMPLAINT, id=f"TEST-{dt.datetime.now():%m%d%H%M%S}")], "test", "Integration test"))


@app.post("/api/intake/upload")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="choose a .csv or .xlsx file"), 400
    try:
        rows = read_upload(f)
    except Exception as e:
        return jsonify(error=f"could not read {f.filename}: {type(e).__name__}"), 400
    if not rows:
        return jsonify(error="the file has no data rows"), 400
    res = enqueue(rows[:1000], "csv", request.form.get("reporter") or "")
    return jsonify(file=f.filename, rows=len(rows), queued=sum(r["status"] == "queued" for r in res),
                   duplicates=sum(r["status"] == "duplicate" for r in res), rejected=sum(r["status"] == "rejected" for r in res))


@app.route("/api/intake")
def api_intake():
    items = intake_items()
    return jsonify(items=[{k: v for k, v in it.items() if k != "complaint"} for it in reversed(items[-500:])],
                   counts={s: sum(it["status"] == s for it in items) for s in ("queued", "processing", "processed", "duplicate", "error")},
                   working=_worker["current"])


@app.route("/intake")
def intake_page():
    return render_template("intake.html", page="intake", title="Intake inbox", SOURCES=SOURCES)


def integration_status():
    st, items = load_settings(), intake_items()
    def last(src):
        its = [i for i in items if i["source"] in src]
        return {"count": len(its), "last": its[-1]["received"] if its else ""}
    imap = st.get("imap") or {}
    return {"rest": last(("rest", "test")), "csv": last(("csv",)), "email": last(("email",)),
            "imap_connected": bool(imap.get("host") and imap.get("user")), "imap": {k: v for k, v in imap.items() if k != "password"},
            "imap_has_password": bool(imap.get("password")),
            "connectors": {k: bool(st["connectors"].get(k)) for k, *_ in CONNECTORS}}


@app.route("/integrations")
def integrations_page():
    st = load_settings()
    return render_template("integrations.html", page="integrations", title="Integrations", st=st, status=integration_status(),
                           CONNECTORS=CONNECTORS, VIGIL_FIELDS=VIGIL_FIELDS, endpoint=request.host_url.rstrip("/") + "/api/complaints",
                           sample=json.dumps(dict(SAMPLE_COMPLAINT, id="CASE-10042", event_date="2026-09-28"), indent=2))


@app.route("/api/integrations/status")
def api_integrations_status():
    return jsonify(integration_status())


@app.post("/api/settings/imap")
def api_settings_imap():
    d = request.get_json(silent=True) or {}
    cur = load_settings().get("imap") or {}
    imap = {k: str(d.get(k) or "").strip() for k in ("host", "port", "user", "folder", "ssl")}
    imap["password"] = str(d.get("password") or "") or cur.get("password", "")  # blank keeps the stored password
    if d.get("disconnect"):
        imap = {}
    save_settings({"imap": imap})
    return jsonify(ok=True, connected=bool(imap.get("host") and imap.get("user")))


@app.post("/api/settings/connector/<key>")
def api_settings_connector(key):
    if key not in {k for k, *_ in CONNECTORS}:
        abort(404)
    d = request.get_json(silent=True) or {}
    conns = load_settings()["connectors"]
    conns[key] = {} if d.get("clear") else {k: str(v) for k, v in (d.get("config") or {}).items() if str(v).strip()}
    save_settings({"connectors": conns})
    return jsonify(ok=True, configured=bool(conns[key]))


@app.post("/api/settings/mapping")
def api_settings_mapping():
    rows = (request.get_json(silent=True) or {}).get("mapping") or []
    valid = dict(VIGIL_FIELDS)
    mapping = [{"source": str(r.get("source", "")).strip(), "target": r.get("target")} for r in rows
               if str(r.get("source", "")).strip() and r.get("target") in valid]
    save_settings({"mapping": mapping})
    return jsonify(ok=True, mapping=mapping)


@app.post("/api/settings/api-key/rotate")
def api_rotate_key():
    st = save_settings({"api_key": "vgl_" + secrets.token_hex(16)})
    return jsonify(api_key=st["api_key"])


@app.route("/api/health")
def api_health():
    d = DEMO.public(since=10**12)
    try:
        changed = os.path.getmtime(LOG)
    except OSError:
        changed = None
    return jsonify({**HEALTH, "log_changed": changed, "now": time.time(),
                    "demo": {k: d[k] for k in ("running", "kind", "processed", "total")}})


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
    start_intake_worker(recover=True)  # resume anything left queued or interrupted
    print(f"Vigil Console v2 on http://localhost:5001  (data: {VIGIL_DIR})", flush=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("VIGIL_CONSOLE_PORT", 5001)), debug=False, threaded=True)

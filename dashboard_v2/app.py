"""Thirty console - live command center for the Thirty complaint agent (formerly "Vigil Console v2").

Reads ../decisions.csv (written by vigil.py), serves the draft 3500A PDFs from ../reports, drives demo
replays/resets of vigil.py in a subprocess, and shows live system health. vigil.py is never edited.
Everything is local: no CDNs, no external fonts.

Run:  python3 dashboard_v2/app.py  ->  http://localhost:5001   (the desktop app spawns this itself)
"""
import copy, csv, datetime as dt, io, json, os, re, secrets, shutil, signal, subprocess, sys, tempfile, threading, time, uuid
from collections import defaultdict

import requests
from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, send_from_directory

if getattr(sys, "frozen", False):  # PyInstaller build (desktop app): everything is unpacked under _MEIPASS
    CODE_DIR = sys._MEIPASS
    HERE = os.path.join(CODE_DIR, "dashboard_v2")
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    CODE_DIR = os.path.dirname(HERE)  # the repository / installed app: vigil.py, the thirty package, demo_set.csv
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)
from thirty import audit as taudit, config as tconfig, decisions as tdecisions, jurisdictions as tjur, licensing, plugins, sample_data, setup as tsetup  # noqa: E402
from thirty import readiness as treadiness  # noqa: E402  (Device readiness: pure engine + openFDA cache + PDF)
from thirty.agents import get_agent  # noqa: E402
from thirty.filelock import lock as _flock, unlock as _funlock, LockBusy  # noqa: E402

VIGIL_DIR = tconfig.data_dir()  # the data folder (VIGIL_DIR env; defaults to the repository root)
demo_mode = tconfig.demo_mode  # the sample agent is active (no model configured); can change at runtime
PUBLIC_DEMO = tconfig.public_demo()  # deployed as a locked public demo: every settings surface is read-only
PUBLIC_URL = tconfig.public_url()  # base URL for QR codes / shareable links (phone), e.g. https://…onrender.com
PUBLIC_DEMO_BANNER = "Public demo: invented sample data, sample agent, nothing is sent to the FDA"


def public_base():
    """Base URL for links shown to a phone: THIRTY_PUBLIC_URL when set, else this request's host."""
    if PUBLIC_URL:
        return PUBLIC_URL
    try:
        return request.host_url.rstrip("/")
    except RuntimeError:  # no request context (startup)
        return ""


def _locked():
    """JSON 403 used by every write route while the public demo is live."""
    return jsonify(error="Locked in the public demo"), 403


def sample_data_mode():
    """Sample agent AND the user chose to explore with sample data (not their own site)."""
    return demo_mode() and tsetup.wants_sample_data()
LOG = os.path.join(VIGIL_DIR, "decisions.csv")
LOCK = LOG + ".lock"  # the same lock file vigil.py's log_lock() uses
REPORTS = os.path.join(VIGIL_DIR, "reports")
OUTBOX = os.path.join(VIGIL_DIR, "outbox.txt")
DEMO_CSV = os.path.join(CODE_DIR, "demo_set.csv")
HISTORY = os.path.join(VIGIL_DIR, "history.csv")  # past FDA MAUDE reports (vigil.py import-history)
ACTIONS = os.environ.get("VIGIL_CONSOLE_ACTIONS", os.path.join(VIGIL_DIR, "actions.csv"))  # who/when for console actions
VENV_BIN = os.path.expanduser(os.environ.get("VIGIL_VENV_BIN", "~/hackathon/venv/bin"))
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text",
          "product_code", "memory", "failure_mode", "source"]  # same order as vigil.FIELDS; older files stop earlier

VERSION = "1.1.0"
try:
    from thirty import __version__ as VERSION  # single source of truth: thirty/__init__.py
except Exception:
    pass
def workspace():
    """Top-bar identity: the site chosen at first-run setup, or the sample company."""
    ws = tsetup.workspace()
    return {"org": ws["org"], "unit": ws["unit"], "mode": ws["mode"], "jurisdictions": ws.get("jurisdictions") or ["US"], "env": "ON-PREM · PRODUCTION", "env_short": "ON-PREM"}

app = Flask(__name__, template_folder=os.path.join(HERE, "templates"), static_folder=os.path.join(HERE, "static"))
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
    lockf = open(LOCK, "a+")
    try:
        try:
            _flock(lockf, exclusive=False, blocking=False)
            locked = True
        except LockBusy:
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
        if locked:
            _funlock(lockf)
        lockf.close()


def set_status(cid, status, guard):
    """Read-modify-write under vigil.py's exclusive lock. guard(old_status) -> bool decides if a row changes."""
    def mutate(r):
        if guard(r.get("status") or ""):
            r["status"] = status
            return True
        return False
    return update_rows(cid, mutate)


def update_rows(cid, mutate):
    """Apply mutate(row) -> changed? to every row of a complaint under vigil.py's exclusive lock.
    The new file is written next to the old one and swapped in atomically, so unlocked readers never see it torn.
    Returns None (unknown id), False (nothing changed) or True."""
    with open(LOCK, "a+") as lockf:
        deadline = time.time() + 90  # vigil.py may hold the lock through a sandbox upload (<= 60 s)
        while True:
            try:
                _flock(lockf, exclusive=True, blocking=False); break
            except LockBusy:
                if time.time() > deadline:
                    raise TimeoutError("decisions.csv is busy, try again")
                time.sleep(0.2)
        with open(LOG, newline="", encoding="utf-8") as f:
            fields, rows = parse_log(f)
        hit = [r for r in rows if r["id"] == cid]
        if not hit:
            _funlock(lockf)
            return None
        changed = [r for r in hit if mutate(r)]
        if changed:
            fd, tmp = tempfile.mkstemp(dir=VIGIL_DIR, prefix=".decisions.", suffix=".tmp")
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader(); w.writerows(rows)
            shutil.copymode(LOG, tmp)
            os.replace(tmp, LOG)
        _funlock(lockf)
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
            import vigil as v  # from CODE_DIR
            v.LOG, v.REPORTS, v.OUTBOX, v.HISTORY = LOG, REPORTS, OUTBOX, HISTORY
            if tconfig.agent_id() != "local":
                v.SANDBOX = ""  # the OpenClaw sandbox only exists next to the hackathon's local model
            _vigil = v
        return _vigil


def push_to_sandbox():
    """Keep the OpenClaw sandbox copy in sync after a console approval, like vigil.write_log does."""
    try:
        v = vigil()
        v.push_log()
    except Exception as e:
        print("sandbox push skipped:", e, flush=True)

# ---------------------------------------------------------------- demo controls (vigil.py in a subprocess)
DEMO_COMMANDS = {
    # sg docker: nemoclaw (sandbox push / clear) needs the docker group. python3 resolves to the venv (fpdf2 etc.).
    "replay": 'sg docker -c "python3 vigil.py replay --csv demo_set.csv --delay 8"',
    "reset": 'sg docker -c "python3 vigil.py reset"',
}
DEMO_DELAY = float(os.environ.get("THIRTY_DEMO_DELAY", "2.5"))  # seconds between replayed complaints in demo mode
PROCESSED_LINE = re.compile(r"^\S+ (URGENT|HIGH|NORMAL) (REPORTABLE|NEEDS_INFO|NOT_REPORTABLE|None)\b")  # cmd_replay's per-complaint line


def in_process():
    """Run demo actions inside the console (no subprocess, no sandbox) unless the hackathon local model is active."""
    return tconfig.agent_id() != "local"


def demo_commands():
    if not in_process():
        return DEMO_COMMANDS
    return {"replay": f"{get_agent().name} · {len(sample_data.INCOMING)} incoming complaints through the pipeline",
            "reset": "reset sample data · 40 complaints, history and drafts rewritten for today" if sample_data_mode() else "clear decisions.csv, drafted PDFs and the intake queue"}


class DemoRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc, self.kind, self.cmd = None, None, None
        self.thread, self._stop = None, threading.Event()
        self.lines, self.seq = [], 0
        self.started = self.ended = None
        self.rc, self.stopped, self.processed = None, False, 0

    @property
    def running(self):
        if self.thread is not None and self.thread.is_alive():
            return True
        return self.proc is not None and self.proc.poll() is None

    def _emit(self, text, tag=""):
        if not tag and PROCESSED_LINE.match(text):  # one per processed complaint, subprocess or in-process
            self.processed += 1
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, tag, text))
            del self.lines[:-4000]

    def start(self, kind):
        with self.lock:
            if self.running:
                return f"A {self.kind} is already running. Stop it first."
            self.lines, self.kind, self.cmd = [], kind, demo_commands()[kind]
            self.started, self.ended, self.rc, self.stopped, self.processed = time.time(), None, None, False, 0
        self._emit(f"$ {self.cmd}", "cmd")
        if in_process():
            self._stop.clear(); self.proc = None
            self.thread = threading.Thread(target=self._run_inprocess, args=(kind,), daemon=True)
            self.thread.start()
            return None
        env = {**os.environ, "PATH": f"{VENV_BIN}:{os.environ.get('PATH', '')}", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(self.cmd, shell=True, cwd=VIGIL_DIR, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                     start_new_session=True)  # own process group, so Stop kills sg -> sh -> python
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        return None

    def _pump(self, proc):
        for line in proc.stdout:
            line = line.rstrip("\n")
            self._emit(line, "warn" if re.search(r"WARNING|failed|FAILED|Traceback|Error", line) else "")
        rc = proc.wait()
        self.rc, self.ended = rc, time.time()
        if self.stopped:
            self._emit("■ stopped from the console", "warn")
        else:
            self._emit(f"■ {self.kind} finished (exit code {rc})", "ok" if rc == 0 else "warn")

    def _run_inprocess(self, kind):
        """Demo mode: replay the sample incoming complaints through vigil.process() with the sample agent, or
        reseed the sample data. Same output lines as the subprocess path, so the Demo page needs no changes."""
        rc = 0
        try:
            if kind == "reset" and sample_data_mode():
                self._emit("Rewriting sample data for today…")
                ids = sample_data.seed(VIGIL_DIR)
                _cache.update(rows=[], mtime=None)
                self._emit(f"{len(ids)} complaints, {len(sample_data.history_rows())} history rows, drafted PDFs written to {VIGIL_DIR}")
            elif kind == "reset":
                for name in ("decisions.csv", "outbox.txt", "intake.json", ".push_pending"):
                    try: os.remove(os.path.join(VIGIL_DIR, name)); self._emit(f"removed {name}")
                    except OSError: pass
                shutil.rmtree(REPORTS, ignore_errors=True); self._emit("removed reports/")
                _cache.update(rows=[], mtime=None)
            else:
                items = sample_data.incoming_complaints()
                self._emit(f"Replay started: {len(items)} complaints · agent: {get_agent().name}")
                for n, c in enumerate(items, 1):
                    if self._stop.is_set():
                        break
                    self._emit(f"→ #{c['id']} {c['device']}")
                    with _process_lock:
                        row = vigil().process(dict(c))
                    self._emit(f"{row['id']} {row['priority']} {row['decision']} {row['due_date']}")
                    if n < len(items):
                        self._stop.wait(DEMO_DELAY)
                if not self._stop.is_set():
                    self._emit("Replay finished.")
        except Exception as e:
            rc = 1
            self._emit(f"Error: {type(e).__name__}: {e}", "warn")
        self.rc, self.ended = rc, time.time()
        if self.stopped:
            self._emit("■ stopped from the console", "warn")
        else:
            self._emit(f"■ {kind} finished (exit code {rc})", "ok" if rc == 0 else "warn")

    def stop(self):
        if not self.running:
            return "Nothing is running."
        self.stopped = True
        if self.proc is None:  # in-process demo run
            self._stop.set()
            return None
        pgid = self.proc.pid  # start_new_session: the group id is the shell's pid
        if not hasattr(os, "killpg"):  # Windows: no process groups
            self.proc.terminate(); return None
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
    """Complaints a replay will process: the sample incoming set in demo mode, else demo_set.csv rows with text."""
    if in_process():
        return len(sample_data.INCOMING)
    try:
        with open(DEMO_CSV, newline="", encoding="utf-8") as f:
            return sum(1 for r in csv.DictReader(f) if (r.get("event_description") or r.get("manufacturer_narrative") or "").strip())
    except Exception:
        return 0

# ---------------------------------------------------------------- settings.json (console configuration)
SETTINGS = os.environ.get("VIGIL_CONSOLE_SETTINGS", os.path.join(VIGIL_DIR, "settings.json"))
INTAKE = os.environ.get("VIGIL_CONSOLE_INTAKE", os.path.join(VIGIL_DIR, "intake.json"))
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


_intake_mod = {"m": None, "tried": False}

def intake_mod():
    """intake.py (REST webhook /api/v1/complaints, CSV, IMAP) - used as-is, never edited."""
    if not _intake_mod["tried"]:
        _intake_mod["tried"] = True
        try:
            import intake as m  # from CODE_DIR; its files go to the data folder
            m.SETTINGS = os.path.join(VIGIL_DIR, "intake-settings.json")
            m.INTAKE = os.path.join(VIGIL_DIR, "intake"); m.RAW = os.path.join(m.INTAKE, "raw"); m.INDEX = os.path.join(m.INTAKE, "index.csv")
            _intake_mod["m"] = m
        except Exception as e:
            print("intake.py not available:", type(e).__name__, e, flush=True)
    return _intake_mod["m"]


def v1_items():
    """Items received through intake.py (its index.csv + raw complaint JSON), in the inbox item shape."""
    m = intake_mod()
    if not m:
        return []
    out = []
    try:
        for r in m._index_rows():
            c = {}
            try:
                with open(os.path.join(m.RAW, f"{r['vigil_id']}.complaint.json"), encoding="utf-8") as f:
                    c = json.load(f)
            except (OSError, ValueError):
                pass
            out.append({"iid": r["vigil_id"], "source": r.get("source") or "api", "reporter": c.get("reporter", ""), "received": r.get("time", ""),
                        "status": {"done": "processed", "failed": "error"}.get(r.get("status"), r.get("status") or "queued"),
                        "cid": r["vigil_id"], "device": c.get("device", ""), "excerpt": (c.get("text") or "")[:200], "error": r.get("error", "")})
    except Exception as e:
        print("intake index unreadable:", e, flush=True)
    return out


def source_of(cid):
    """Where a complaint came from: the intake item that produced it, else the MAUDE demo replay."""
    for it in reversed(intake_items()):
        if it.get("cid") == cid and it.get("status") in ("processed", "processing", "queued"):
            return it["source"]
    for it in v1_items():
        if it["cid"] == cid:
            return it["source"]
    return "replay"


SOURCES = {"rest": ("REST API", "zap"), "csv": ("File upload", "upload"), "email": ("Email", "mail"),
           "replay": ("Replay", "play"), "test": ("API test", "zap"), "api": ("API", "zap"),
           "history": ("FDA history", "file"), "reporter": ("Reporter", "user")}


# ---------------------------------------------------------------- reporter front-door helpers (report-front-door spec, R9)
# Required Draft_3500A fields for the Completeness_Score (the Requirement-4 data set, mapped to the keys the
# drafted 3500A JSON actually stores — see thirty/reporter/interview.to_draft_3500a). "lot_or_serial" is stored
# under both D4_lot and D4_serial, so it counts as a single required field satisfied by either key.
REQUIRED_3500A = [
    ("D1_brand_name",),          # device brand name
    ("D4_model",),               # device model
    ("D4_lot", "D4_serial"),     # lot number or serial number
    ("B5_event_description",),   # free-text description of what happened
    ("B2_outcomes",),            # patient outcome (list field)
    ("H3_device_evaluated",),    # device malfunctioned mapping
    ("B3_date_of_event",),       # date of the event
    ("date_noticed",),           # date the problem was noticed
    ("follow_up_contact",),      # follow-up contact
]


def is_reporter(row):
    """True only when a complaint came through the public report front door (source == "reporter").
    An absent or empty source column is treated as non-reporter (R9.1, R9.2, R9.7)."""
    return (row.get("source") or "") == "reporter"


def _draft_3500a_fields(cid):
    """The drafted Form 3500A fields persisted next to the PDF at REPORTS/MDR_<cid>.json (written by
    vigil.make_mdr()). Returns {} when the side JSON is missing or unreadable so the score degrades to 0."""
    side = os.path.join(REPORTS, f"MDR_{cid}.json")
    try:
        with open(side, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _known_3500a_value(value):
    """A drafted field counts as known when it is present, non-empty, and not the UNKNOWN sentinel.
    List fields (e.g. B2_outcomes) count as known only when the list has at least one known entry."""
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(_known_3500a_value(v) for v in value)
    text = str(value).strip()
    return bool(text) and text.upper() != "UNKNOWN"


def completeness_score(row):
    """Integer 0-100: the proportion of required Draft_3500A fields holding a known (non-UNKNOWN) value,
    rounded to the nearest integer (R9.3). All known -> 100 (R9.4); all UNKNOWN/empty -> 0 (R9.5). The
    drafted fields come from the per-complaint 3500A draft the pipeline already produces."""
    fields = _draft_3500a_fields(row.get("id", ""))
    known = sum(1 for keys in REQUIRED_3500A
                if any(_known_3500a_value(fields.get(k)) for k in keys))
    return round(100 * known / len(REQUIRED_3500A))


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
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    return list(csv.DictReader(io.StringIO(text)))

# ---------------------------------------------------------------- system health (refreshed in the background)
HEALTH = {"model": {"ok": False, "label": "checking…"}, "telegram": {"ok": False, "label": "checking…"},
          "sync": {"ok": False, "label": "checking…"}, "checked": None,
          "agent": {"id": tconfig.agent_id(), "name": get_agent().name}, "demo_mode": demo_mode()}

def _check_model():
    """The active agent's own health check (local model: ping the server; sample agent: always ready)."""
    try:
        a = get_agent()
        h = a.health()
        return {"ok": bool(h.get("ok")), "name": h.get("name") or a.name, "ms": h.get("ms"), "label": h.get("label") or ""}
    except Exception as e:
        return {"ok": False, "label": f"error ({type(e).__name__})"}


_tg_fails = {"n": 0, "last_ok": None}

def _check_telegram():
    """Reachability of api.telegram.org, debounced: one slow or failed probe must not flip the badge.
    Reported offline only after 3 consecutive failures."""
    now = dt.datetime.now().strftime("%H:%M:%S")
    if tconfig.agent_id() != "local":
        return {"ok": False, "label": "not configured", "checked": now, "fails": 0, "off": True}
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
    if tconfig.agent_id() != "local" or os.name != "posix":
        return {"ok": False, "label": "not configured", "off": True}
    try:
        r = subprocess.run(["pgrep", "-f", r"vigil\.py sync"], capture_output=True, text=True)
        pids = r.stdout.split()
    except Exception:
        pids = []
    return {"ok": bool(pids), "label": "running" if pids else "not running"}


def health_loop():
    last_model = 0
    while True:
        try:
            if time.time() - last_model >= (60 if tconfig.agent_id() == "local" else 10):
                HEALTH["model"] = _check_model(); last_model = time.time()
            HEALTH.update(telegram=_check_telegram(), sync=_check_sync(), checked=dt.datetime.now().strftime("%H:%M:%S"),
                          agent={"id": tconfig.agent_id(), "name": get_agent().name}, demo_mode=demo_mode())
        except Exception as e:  # never let the health thread die
            print("health check failed:", type(e).__name__, e, flush=True)
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
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
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
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
}.items()}
STEP_ICONS = {"done": ICONS["check"], "info": ICONS["help"], "todo": _svg('<circle cx="12" cy="12" r="3"/>')}

# Sidebar, grouped: Work (day-to-day), Records (read-only history), Settings (configure the console).
NAV_GROUPS = [
    ("Work", [("home", "/", "Command Center", "grid"), ("complaints", "/complaints", "Complaints", "inbox"),
              ("clock", "/clock", "Compliance Clock", "clock")]),
    ("Records", [("trends", "/trends", "Trends", "trend"), ("audit", "/audit", "Audit Log", "file")]),
    ("Settings", [("intake", "/intake", "Intake inbox", "download"), ("integrations", "/integrations", "Integrations", "plug"),
                  ("plugins", "/settings/plugins", "Plugins", "cpu"), ("demo", "/demo", "Demo Control", "play"),
                  ("licence", "/settings/licence", "Licence & updates", "key")]),
]
# Flat list kept for any code that still iterates every nav entry.
NAV = [item for _group, items in NAV_GROUPS for item in items]


@app.context_processor
def _globals():
    from markupsafe import Markup
    return {"health": HEALTH, "ICON": STEP_ICONS, "ICONS": ICONS, "NAV": NAV, "NAV_GROUPS": NAV_GROUPS, "VERSION": VERSION, "WS": workspace(), "SOURCES": SOURCES,
            "DEMO_MODE": demo_mode(), "SAMPLE_DATA": sample_data_mode(), "PUBLIC_DEMO": PUBLIC_DEMO, "PUBLIC_DEMO_BANNER": PUBLIC_DEMO_BANNER, "PUBLIC_BASE": public_base(), "AGENT": {"id": tconfig.agent_id(), "name": get_agent().name}, "LICENCE": licensing.check().status(),
            "fmt_day": fmt_day, "LOCAL_AGENT": tconfig.agent_id() == "local", "CLOUD_AGENT": tconfig.agent_id() == "claude", "DATA_DIR": VIGIL_DIR, "TODAY": dt.date.today().isoformat(), "JURISDICTIONS": tjur.JURISDICTIONS,
            "is_reporter": is_reporter, "completeness_score": completeness_score,
            "icon": lambda name: Markup(ICONS.get(name, ""))}


SETUP_FREE = ("/setup", "/api/setup", "/api/plugins", "/api/health", "/static/", "/readiness", "/api/readiness",
              "/report", "/start")  # the public, no-login reporter Front_Door (and its /report/* sub-paths) must be reachable before first-run setup


# Write endpoints that configure the console or drive the demo. All refuse in the public demo so a
# judge on a shared deployment cannot change the agent, edit integrations, touch the licence or reset.
LOCKED_ENDPOINTS = {
    "api_setup", "api_settings_imap", "api_settings_connector", "api_settings_mapping", "api_rotate_key",
    "api_licence_install", "api_licence_remove", "api_desktop", "api_workspace",
    "api_plugins_active", "api_plugins_update", "api_plugins_test", "api_demo_action",
    "api_readiness_refresh",  # Device readiness: no live openFDA refresh in the locked public demo
}


@app.before_request
def _public_demo_lock():
    """In the public demo every settings/plugins/licence/integrations write and the demo controls are read-only."""
    if PUBLIC_DEMO and request.endpoint in LOCKED_ENDPOINTS:
        return _locked()


@app.before_request
def _first_run():
    """Until first-run setup is complete, every page goes to /setup (API calls answer 409).
    The public demo skips setup entirely (completed on start), so this never redirects there."""
    if PUBLIC_DEMO:
        return
    if tsetup.required() and not request.path.startswith(SETUP_FREE):
        if request.path.startswith("/api/"):
            return jsonify(error="setup required", setup="/setup"), 409
        return redirect("/setup")


@app.route("/setup")
def setup_page():
    if not tsetup.required() and request.args.get("again") != "1":
        return redirect("/")
    return render_template("setup.html", data_dir=VIGIL_DIR, version=VERSION)


@app.post("/api/setup")
def api_setup():
    d = request.get_json(silent=True) or {}
    mode, agent = d.get("mode") or "explore", d.get("agent") or "sample"
    try:
        if agent == "local":
            plugins.update_plugin("local", enabled=True, settings=d.get("local") or {})
        if not plugins.forced_by_env():
            plugins.set_active(agent)
    except plugins.PluginError as e:
        return jsonify(error=str(e)), 400
    st = tsetup.complete(mode, d.get("org"), d.get("unit"), agent)
    if mode == "explore" and not os.path.exists(LOG):
        sample_data.seed(VIGIL_DIR); _cache.update(rows=[], mtime=None)
    HEALTH.update(model=_check_model(), agent={"id": tconfig.agent_id(), "name": get_agent().name}, demo_mode=demo_mode())
    return jsonify(ok=True, setup=st, agent=get_agent().name)


START_COOKIE = "thirty_start_seen"
REPO_URL = "https://github.com/jossefuggg/thirty"
SUBMISSION_URL = "https://github.com/jossefuggg/thirty/blob/hackachusetts/docs/hackachusetts/SUBMISSION.md"


def _needs_start(public_demo, cookies):
    """A public-demo visitor who has not seen the start page yet is sent there first."""
    return bool(public_demo) and cookies.get(START_COOKIE) != "1"


@app.route("/start")
def start_page():
    resp = make_response(render_template("start.html", page="start", title="Start",
                                         repo_url=REPO_URL, submission_url=SUBMISSION_URL))
    resp.set_cookie(START_COOKIE, "1", path="/", samesite="Lax", httponly=True)
    return resp


@app.route("/")
def home():
    if _needs_start(PUBLIC_DEMO, request.cookies):
        return redirect("/start")
    return render_template("home.html", page="home", title="Command Center")


def owner_of(r):
    m = re.match(r"(?:APPROVED|INFO REQUESTED) by (.+)", r.get("status") or "")
    return m.group(1) if m else ""


def list_row(r):
    d = days_left(r)
    rec = r.get("received") or ""
    return {"id": r["id"], "received": f"{rec[:4]}-{rec[4:6]}-{rec[6:8]}" if re.fullmatch(r"\d{8}", rec) else rec,
            "family": live_family(r), "device": r.get("device") or "", "decision": r.get("decision") or "", "category": r.get("category") or "",
            "priority": r.get("priority") or "", "mode": live_mode(r), "due": r.get("due_date") or "", "days_left": d if is_open(r) else None,
            "status": r.get("status") or "", "status_kind": "log" if r.get("status") == "LOGGED" else status_kind(r.get("status")),
            "owner": owner_of(r), "source": source_of(r["id"]), "live": True, "time": r.get("time") or ""}


@app.route("/complaints")
def complaints_page():
    return render_template("complaints.html", page="complaints", title="Complaints")


@app.route("/api/complaints/list")
def api_complaints_list():
    a = request.args
    rows = [list_row(r) for r in all_rows()]
    if a.get("history") == "1":
        live_ids = {r["id"] for r in rows}
        rows += [{"id": i, "received": d.isoformat(), "family": f, "device": f, "decision": "", "category": (e or "").upper(), "priority": "",
                  "mode": m, "due": "", "days_left": None, "status": "FDA history", "status_kind": "hist", "owner": "", "source": "history",
                  "live": False, "time": d.isoformat()} for d, f, m, e, i in history_rows() if i not in live_ids]
    facets = {"decision": defaultdict(int), "status_kind": defaultdict(int), "priority": defaultdict(int), "family": defaultdict(int)}
    for r in rows:
        for k in facets:
            if r[k]: facets[k][r[k]] += 1
    q = (a.get("q") or "").strip().lower()
    for k in ("decision", "status_kind", "priority", "family"):
        if a.get(k):
            rows = [r for r in rows if r[k] == a[k]]
    if q:
        rows = [r for r in rows if q in " ".join((r["id"], r["device"], r["family"], r["mode"], r["category"], r["owner"], r["status"])).lower()]
    key = a.get("sort") or "time"
    PR = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "": 3}
    keyf = (lambda r: PR.get(r["priority"], 3)) if key == "priority" else (lambda r: (r["due"] or "9999")) if key == "due" else (lambda r: str(r.get(key) or ""))
    rows.sort(key=keyf, reverse=(a.get("dir") or "desc") == "desc")
    per, page = 50, max(1, int(a.get("page") or 1))
    total = len(rows)
    return jsonify(rows=rows[(page - 1) * per: page * per], total=total, page=page, pages=max(1, -(-total // per)),
                   facets={k: dict(sorted(v.items(), key=lambda kv: -kv[1])[:12]) for k, v in facets.items()}, has_history=bool(history_rows()))


@app.route("/clock")
def clock_page():
    return render_template("clock.html", page="clock", title="Compliance Clock")


def audit_events():
    """Event log derived from decisions.csv (what Vigil did), the PDFs on disk and actions.csv (what reviewers did)."""
    ev = []
    for r in all_rows():
        t, cid = r.get("time") or "", r["id"]
        dec = (r.get("decision") or "").replace("_", " ")
        ev.append({"t": t, "actor": "Thirty agent", "action": "Classified", "id": cid, "decision": r.get("decision") or "",
                   "detail": f"{dec} · {r.get('category')} · {r.get('confidence')}% · {r.get('reason') or ''}"})
        ev.append({"t": t, "actor": "Thirty agent", "action": "Alert sent", "id": cid, "decision": "",
                   "detail": f"Telegram alert · {r.get('priority')} priority" + (" · queued in outbox" if alert_state(cid) != "sent" else "")})
        pdf = os.path.join(REPORTS, f"MDR_{cid}.pdf")
        if os.path.exists(pdf):
            ev.append({"t": dt.datetime.fromtimestamp(os.path.getmtime(pdf)).isoformat(timespec="seconds"), "actor": "Thirty agent",
                       "action": "PDF drafted", "id": cid, "decision": "", "detail": f"Form 3500A draft MDR_{cid}.pdf · due {r.get('due_date') or 'n/a'}"})
        if owner_of(r) and not last_action(cid, t):  # decided in Telegram: no console timestamp
            ev.append({"t": t, "actor": owner_of(r), "action": "Approved" if status_kind(r.get("status")) == "appr" else "Info requested",
                       "id": cid, "decision": "", "detail": "Recorded via Telegram (time of decision not captured)"})
    if os.path.exists(ACTIONS):
        with open(ACTIONS, newline="", encoding="utf-8") as f:
            for a in csv.DictReader(f):
                ev.append({"t": a["time"], "actor": a["by"], "action": {"approve": "Approved", "info": "Info requested", "undo": "Undo"}.get(a["kind"], a["kind"]),
                           "id": a["id"], "decision": "", "detail": {"approve": "Draft Form 3500A approved for submission", "info": "More information requested from the reporter",
                                                                    "undo": "Decision reverted to pending review"}.get(a["kind"], "")})
    for e in taudit.entries():
        if e.get("action") not in ("Approved", "Info requested", "Undo"):  # those come from actions.csv above
            ev.append({"t": e["time"], "actor": e["actor"], "action": e["action"], "id": e.get("id") or "", "decision": (e.get("data") or {}).get("outcome", {}).get("decision", ""),
                       "detail": e.get("detail") or "", "signed": True})
    ev.sort(key=lambda e: e["t"], reverse=True)
    return ev


@app.route("/audit")
def audit_page():
    return render_template("audit.html", page="audit", title="Audit Log")


@app.route("/api/audit")
def api_audit():
    return jsonify(events=audit_events()[:2000])


@app.route("/audit.csv")
def audit_csv():
    out = io.StringIO()
    w = csv.writer(out); w.writerow(["time", "actor", "action", "complaint", "detail"])
    for e in audit_events():
        w.writerow([e["t"], e["actor"], e["action"], e["id"], e["detail"]])
    return app.response_class(out.getvalue(), mimetype="text/csv",
                              headers={"Content-Disposition": f"attachment; filename=thirty_audit_{dt.date.today():%Y%m%d}.csv"})


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
        "family": device_family(r.get("device")), "open": is_open(r), "source": source_of(r["id"]),
        "clocks": [{"code": c["code"], "due": c["due"], "days_left": c["days_left"], "days": c["days"]} for c in tdecisions.clocks(r, _jur_cache()) if c["code"] != "US"] if is_open(r) else []}


_jur = {"t": 0.0, "v": ["US"]}
def _jur_cache():
    if time.time() - _jur["t"] > 5:
        _jur.update(t=time.time(), v=tsetup.jurisdictions())
    return _jur["v"]


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
    # one line of context under each number (the sparkline only shows while something is happening)
    open_rows = [r for r in rows if is_open(r)]
    lefts = sorted(days_left(r) for r in open_rows if days_left(r) is not None)
    week = sum(1 for r in rows if status_kind(r.get("status")) == "appr" and r["id"] in appr_t and appr_t[r["id"]][:10] >= (today - dt.timedelta(days=7)).isoformat())
    out["processed"]["caption"] = "since midnight"
    out["reportable"]["caption"] = f"of {len(rows)} complaints"
    out["needs_info"]["caption"] = "waiting on the reporter"
    soon = [d for d in lefts if 0 <= d <= 7]
    out["due7"]["caption"] = ("next one today" if soon and soon[0] == 0 else f"next in {soon[0]} day{'s' if soon[0] != 1 else ''}") if soon else "nothing due this week"
    out["overdue"]["caption"] = f"oldest {-lefts[0]} day{'s' if lefts[0] != -1 else ''} over" if lefts and lefts[0] < 0 else "none overdue"
    out["approved"]["caption"] = f"{week} in the last 7 days"
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
        csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
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


_hx = {"mtime": 0, "data": None}

def history_context():
    """Compact FDA-history summary for the Command Center (cached per history.csv version)."""
    hist = history_rows()
    if not hist:
        return {"rows": 0}
    if _hx["mtime"] != _hist["mtime"]:
        fam, months = defaultdict(int), defaultdict(int)
        for d, f, m, _, _ in hist:
            fam[f] += 1; months[d.strftime("%Y-%m")] += 1
        top_family = max(fam, key=fam.get)
        modes = defaultdict(int)
        for _, f, m, _, _ in hist:  # failure modes of the family with the most history
            if f == top_family and m != "other": modes[m] += 1
        if not modes:
            for _, _, m, _, _ in hist:
                if m != "other": modes[m] += 1
        keys = sorted(months)[-36:]
        _hx.update(mtime=_hist["mtime"], data={"rows": len(hist), "dream": fam.get(top_family, 0),
                   "top_family": top_family, "top_mode": max(modes, key=modes.get).split("/")[0] if modes else "n/a",
                   "spark": [months[k] for k in keys]})
    return _hx["data"]


@app.route("/api/state")
def api_state():
    rows = all_rows()
    feed = sorted(rows, key=lambda r: r.get("time") or "", reverse=True)[:40]
    queue = sorted((r for r in rows if r.get("decision") in ("REPORTABLE", "NEEDS_INFO")
                    and status_kind(r.get("status")) == "pend"),
                   key=lambda r: (PRIORITY_RANK.get(r.get("priority"), 3), r.get("due_date") or "9999", -int(r.get("score") or 0)))
    clock = sorted((r for r in rows if is_open(r)), key=lambda r: (r["due_date"], -int(r.get("score") or 0)))
    return jsonify(history=history_context(), kpi=kpis(rows), feed=[brief(r) for r in feed], queue=[brief(r) for r in queue],
                   alerts=pattern_alerts(rows), pipeline=pipeline(rows), clock=[brief(r) for r in clock],
                   demo={**{k: v for k, v in DEMO.public(since=10**12).items() if k in ("running", "kind", "processed", "total")}, "demo_mode": demo_mode()})


RECALL = ("2021-06", "Philips recall · 14 Jun 2021")


@app.route("/trends")
def trends():
    return render_template("trends.html", page="trends", title="Trends")


# ---------------------------------------------------------------- Device readiness (/readiness)
# Decision support for wellness/wearable companies: likely category (deterministic,
# rule-based - no AI decides it), public openFDA patterns for similar devices, and
# the day-one device-manufacturer obligations. See thirty/readiness + the spec.
# No-auth, works in the public demo; the engine runs server-side only.
@app.route("/readiness")
def readiness_page():
    rules = treadiness.load_rules()
    return render_template(
        "readiness.html", page="readiness", title="Device readiness",
        product_codes=rules.get("product_codes", []),
        example_preset=rules.get("example_preset", {}),
        checklist=treadiness.day_one_checklist(),
        disclaimer=rules.get("disclaimer", ""),
        incomplete_notice=rules.get("incomplete_data_notice", ""),
        thirty_tags=rules.get("thirty_tags", {}),
        pdf_available=treadiness.available(),
    )


@app.post("/api/readiness/category")
def api_readiness_category():
    """Deterministic category from the Step 1 answers. No AI, no model."""
    answers = treadiness.normalize(request.get_json(silent=True) or {})
    result = treadiness.categorize(answers)
    return jsonify(result=result, checklist=treadiness.day_one_checklist())


@app.route("/api/readiness/signals")
def api_readiness_signals():
    """Cached openFDA patterns for a product code + the where-to-look-first mapping."""
    code = (request.args.get("code") or "").strip().upper()
    answers = treadiness.normalize({
        "claims": request.args.getlist("claim"),
        "users": request.args.get("users"),
    })
    signals = treadiness.load_signals(code)
    return jsonify(signals=signals,
                   where_to_look_first=treadiness.where_to_look_first(signals, answers),
                   notice=treadiness.load_rules().get("incomplete_data_notice", ""))


@app.post("/api/readiness/refresh")
def api_readiness_refresh():
    """Refresh one product code's openFDA cache from the live API (online only).

    Locked in the public demo via LOCKED_ENDPOINTS. On any failure the existing
    cache is kept unchanged and a plain-language message is returned.
    """
    code = ((request.get_json(silent=True) or {}).get("code") or "").strip().upper()
    if not code:
        return jsonify(error="no product code"), 400
    try:
        signals = treadiness.fetch_and_cache(code)
    except treadiness.RefreshError as e:
        return jsonify(ok=False, error=f"Refresh did not complete: {e}",
                       signals=treadiness.load_signals(code)), 200
    return jsonify(ok=True, signals=signals)


@app.post("/api/readiness/pdf")
def api_readiness_pdf():
    """Build the readiness result as a PDF (same disclaimer, citations and sources)."""
    if not treadiness.available():
        abort(404)
    body = request.get_json(silent=True) or {}
    answers = treadiness.normalize(body.get("answers") or {})
    code = (body.get("code") or "").strip().upper()
    result = treadiness.categorize(answers)
    signals = treadiness.load_signals(code) if code else treadiness.load_signals("")
    pdf_bytes = treadiness.build_pdf(result, signals, treadiness.day_one_checklist(), product_code=code or None)
    if not pdf_bytes:
        abort(404)
    from flask import Response
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="device-readiness.pdf"'})


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
        side = os.path.join(REPORTS, f"MDR_{cid}.json")
        if os.path.exists(side):  # written next to the PDF by vigil.make_mdr()
            try:
                with open(side, encoding="utf-8") as f:
                    qs = [str(q).strip() for q in (json.load(f).get("follow_up_questions") or []) if str(q).strip()][:5]
                _fq_cache[key] = qs
                return qs
            except (OSError, ValueError):
                pass
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


def record_action(cid, kind, by, meaning=""):
    new = not os.path.exists(ACTIONS)
    with open(ACTIONS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "id", "kind", "by"])
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), cid, kind, by])
    try:  # the signed, hash-chained copy (21 CFR 11 style); never blocks the decision itself
        taudit.append(by, {"approve": "Approved", "info": "Info requested", "undo": "Undo"}.get(kind, kind), cid,
                      ACTION_DETAIL.get(kind, ""), meaning or taudit.MEANINGS.get(kind, ""))
    except Exception as e:
        print("audit chain append failed:", e, flush=True)


ACTION_DETAIL = {"approve": "Draft Form 3500A approved for submission", "info": "More information requested from the reporter",
                 "undo": "Decision reverted to pending review"}


def alert_state(cid):
    """'queued' if the Telegram alert for this complaint is parked in outbox.txt (Telegram unreachable)."""
    try:
        with open(OUTBOX, encoding="utf-8") as f:
            return "queued" if f"#{cid}" in f.read() else "sent"
    except FileNotFoundError:
        return "sent"


def fmt_day(d):
    """'6 Oct 2026' on every OS (strftime %-d is POSIX-only)."""
    return f"{d.day} {d:%b %Y}" if d else ""


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
    return t.strftime("%H:%M:%S") if t.date() == dt.date.today() else f"{t.day} {t:%b, %H:%M}"


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
        ["done", "Received", "Original FDA receipt " + fmt_day(rec_d) if rec_d else "Complaint taken in", t],
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
    drec = tdecisions.latest(cid)
    if drec:
        steps.insert(4, ["done", "Decision recorded", f"{tdecisions.label(drec['outcome']['decision'])} · by {drec['by']}", drec["time"]])
    for st in steps:
        st[3] = short_time(st[3]) if st[3] else ""

    missing = [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()]
    questions = follow_up_questions(cid)
    if not questions and missing and reportable:
        _PAREN = re.compile(r"\s*\(.*?\)")  # Python 3.11: no backslashes inside an f-string expression
        questions = [f"Can you provide the {_PAREN.sub('', m).strip().rstrip('.').lower()}?" for m in missing[:5]]
    src = source_complaint(cid) or {}
    try:
        conf = max(0, min(100, int(float(r.get("confidence") or 0))))
    except ValueError:
        conf = 0
    rec = tdecisions.latest(cid)
    enabled = tsetup.jurisdictions()
    clocks = tdecisions.clocks(r, enabled) if is_open(r) or rec else []
    return {**r, "status_kind": kind, "days_left": days_left(r), "reportable": reportable, "open": is_open(r),
            "timeline": steps, "missing_list": missing, "questions": questions, "breakdown": b, "conf": conf,
            "tree": tdecisions.QUESTIONS, "answers": (rec or {}).get("answers") or tdecisions.prefill(r), "record": rec,
            "record_fields": tdecisions.RECORD_FIELDS, "aware": tdecisions.awareness_of(r).isoformat(), "clocks": clocks,
            "jurisdictions": enabled, "jur_names": tjur.JURISDICTIONS, "records_n": len(tdecisions.history(cid)),
            "legal": legal_basis(r), "pdf": has_pdf, "processed": fmt_time(t), "received_d": rec_d,
            "act": act if kind != "pend" else None, "act_time": fmt_time(act_t) if act_t else "",
            "history": device_history(r, rows), "family": device_family(r.get("device")), "source": source_of(cid),
            "full_text": src.get("event_description") or r.get("text") or "",
            "narrative": src.get("manufacturer_narrative") or "", "src": src,
            "due_label": fmt_day(dt.date.fromisoformat(r["due_date"])) if r.get("due_date") else ""}


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
    frag = {k: render_template(f"_detail_{k}.html", r=d) for k in ("review", "timeline", "pdf", "status_pill", "cd", "decision")}
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
    if licensing.blocks_decisions():
        return jsonify(error="The licence has expired. Install a renewed key under Licence & updates to approve or request info."), 403
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
    record_action(cid, kind, name, " ".join((data.get("meaning") or "").split())[:300])
    return jsonify(ok=True, status=status)


# ---------------------------------------------------------------- reportability decision record (803.18 / 820.35)
@app.post("/api/complaint/<cid>/decision")
def api_decision(cid):
    d = request.get_json(silent=True) or {}
    name = " ".join((d.get("name") or "").split())[:60]
    if licensing.blocks_decisions():
        return jsonify(error="The licence has expired. Install a renewed key under Licence & updates to record decisions."), 403
    rows = all_rows()
    if not any(r["id"] == cid for r in rows):
        return jsonify(error="Complaint not found."), 404
    try:
        rec = tdecisions.record(cid, d.get("answers") or {}, d.get("rationale"), name, aware=d.get("aware") or None,
                                fields=d.get("fields") or {}, enabled=tsetup.jurisdictions())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    out = rec["outcome"]
    us = next((c for c in rec["clocks"] if c["code"] == "US"), None)

    def mutate(r):
        r["decision"], r["category"] = out["decision"], out["category"]
        r["deadline_days"] = str(us["days"]) if us else ""
        r["due_date"] = us["due"] if us else ""
        r["reason"] = rec["rationale"][:500]
        st = r.get("status") or ""
        if out["decision"] == "NOT_REPORTABLE" and not st.startswith("APPROVED"):
            r["status"] = "LOGGED"
        elif out["decision"] != "NOT_REPORTABLE" and st in ("LOGGED", ""):
            r["status"] = "PENDING_REVIEW"
        return True
    try:
        update_rows(cid, mutate)
    except TimeoutError as e:
        return jsonify(error=str(e)), 503
    _cache.update(rows=[], mtime=None)
    taudit.append(name, "Decision recorded", cid, f"{out['decision'].replace('_', ' ')} · {out['basis']} · awareness {rec['aware']} · {rec['rationale'][:200]}",
                  taudit.MEANINGS["decision"], extra={"outcome": out, "clocks": [(c["code"], c["due"]) for c in rec["clocks"]], "aware": rec["aware"]})
    return jsonify(ok=True, record=rec)


@app.route("/api/complaint/<cid>/decisions")
def api_decisions(cid):
    return jsonify(records=tdecisions.history(cid), questions=[{"key": k, "q": q, "help": h, "for": f.split()} for k, q, h, f in tdecisions.QUESTIONS])


@app.route("/complaint/<cid>/pack.zip")
def submission_pack(cid):
    """Everything a human needs to file: the drafted 3500A (PDF + fields), the decision record and the signed audit entries."""
    import zipfile
    rows = all_rows()
    r = next((x for x in rows if x["id"] == cid), None)
    if not r:
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ext in ("pdf", "json"):
            fp = os.path.join(REPORTS, f"MDR_{cid}.{ext}")
            if os.path.exists(fp):
                z.write(fp, f"MDR_{cid}.{ext}")
        z.writestr("complaint.json", json.dumps({k: r.get(k, "") for k in r}, indent=1, ensure_ascii=False))
        z.writestr("decision-record.json", json.dumps(tdecisions.history(cid), indent=1, ensure_ascii=False))
        z.writestr("clocks.json", json.dumps(tdecisions.clocks(r, tsetup.jurisdictions()), indent=1))
        chain = taudit.entries(cid=cid)
        z.writestr("audit-entries.jsonl", "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in chain))
        v = taudit.verify()
        z.writestr("README.txt", f"Thirty submission pack for complaint #{cid}\nGenerated {dt.datetime.now():%Y-%m-%d %H:%M}\n\n"
                   "MDR_<id>.pdf / .json   drafted Form 3500A and its fields (UNKNOWN fields must be completed before filing)\n"
                   "decision-record.json   reportability decision tree answers, rationale, reviewer, awareness date (21 CFR 803.18)\n"
                   "clocks.json            reporting deadlines per jurisdiction\n"
                   "audit-entries.jsonl    hash-chained audit entries for this complaint "
                   f"(chain {'verified' if v['ok'] else 'BROKEN at entry ' + str(v['broken_at'])}, head {v['head'][:16]}…)\n\n"
                   "Thirty drafts; a human files. Submit through the regulator's own channel (FDA ESG / eSubmitter, competent authority, MORE portal).\n")
    buf.seek(0)
    return app.response_class(buf.getvalue(), mimetype="application/zip",
                              headers={"Content-Disposition": f"attachment; filename=thirty_{cid}_pack.zip"})


@app.route("/api/audit/verify")
def api_audit_verify():
    return jsonify(taudit.verify())


@app.route("/audit.jsonl")
def audit_jsonl():
    try:
        with open(taudit.path(), encoding="utf-8") as f:
            body = f.read()
    except FileNotFoundError:
        body = ""
    return app.response_class(body, mimetype="application/x-ndjson",
                              headers={"Content-Disposition": f"attachment; filename=thirty_audit_chain_{dt.date.today():%Y%m%d}.jsonl"})


@app.route("/demo")
def demo():
    return render_template("demo.html", page="demo", commands=demo_commands(), title="Demo Control", in_process=in_process(),
                           seeded=sample_data.seed_date(VIGIL_DIR) if sample_data_mode() else None, data_dir=VIGIL_DIR)


def ensure_sample_data():
    """Demo mode: seed on first run, and reseed once a day so the deadlines stay relative to today."""
    if demo_mode() and tsetup.wants_sample_data() and (not os.path.exists(LOG) or sample_data.seed_date(VIGIL_DIR) != dt.date.today()):
        print(f"Demo mode: writing sample data to {VIGIL_DIR}", flush=True)
        sample_data.seed(VIGIL_DIR)
        _cache.update(rows=[], mtime=None)


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
SAMPLE_COMPLAINT = {"text": "Customer reports the AeroFlow A200 CPAP stopped delivering pressure overnight and black particles were found "
                            "in the humidifier chamber. The patient woke up short of breath and visited urgent care the next morning.",
                    "device": "AeroFlow A200 CPAP", "event_type": "Injury", "reporter": "Integration test"}


def api_key_ok():
    key = request.headers.get("X-API-Key") or (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    m = intake_mod()
    keys = [load_settings()["api_key"]] + ([m.settings()["api_key"]] if m else [])  # console key or intake.py key
    return bool(key) and any(secrets.compare_digest(key, k) for k in keys)


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
    items = sorted(list(intake_items()) + v1_items(), key=lambda it: it.get("received") or "")
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
    status = integration_status()
    if PUBLIC_DEMO:  # never hand a secret to the template, and render the page read-only
        st = {"api_key": "", "mapping": st.get("mapping") or [], "imap": {}, "connectors": {k: {} for k, *_ in CONNECTORS}}
        status = {**status, "imap": {}, "imap_has_password": False}
    return render_template("integrations.html", page="integrations", title="Integrations", st=st, status=status,
                           CONNECTORS=CONNECTORS, VIGIL_FIELDS=VIGIL_FIELDS, endpoint=public_base() + "/api/complaints",
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


# ---------------------------------------------------------------- licence, updates, workspace (settings)
DESKTOP_FILE = os.path.join(VIGIL_DIR, "desktop.json")  # read by the Electron shell: {"auto_update": bool}


def desktop_settings():
    try:
        with open(DESKTOP_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("auto_update", True)
    d["in_desktop"] = bool(os.environ.get("THIRTY_DESKTOP"))
    d["app_version"] = os.environ.get("THIRTY_APP_VERSION") or ""
    return d


@app.route("/settings/licence")
def licence_page():
    return render_template("licence.html", page="licence", title="Licence & updates", data_dir=VIGIL_DIR,
                           app_version=os.environ.get("THIRTY_APP_VERSION") or "")


@app.route("/api/licence")
def api_licence():
    return jsonify(licence=licensing.check().status(), desktop=desktop_settings())


@app.post("/api/licence")
def api_licence_install():
    key = (request.get_json(silent=True) or {}).get("key") or ""
    try:
        st = licensing.check().install(key)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if st["state"] == "invalid":
        licensing.check().remove()
        return jsonify(error=st["reason"] or st["label"]), 400
    return jsonify(ok=True, licence=st)


@app.post("/api/licence/remove")
def api_licence_remove():
    licensing.check().remove()
    return jsonify(ok=True, licence=licensing.check().status())


@app.post("/api/desktop")
def api_desktop():
    d = request.get_json(silent=True) or {}
    cur = {k: v for k, v in desktop_settings().items() if k in ("auto_update",)}
    if "auto_update" in d:
        cur["auto_update"] = bool(d["auto_update"])
    tmp = DESKTOP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
    os.replace(tmp, DESKTOP_FILE)
    return jsonify(ok=True, **cur)


@app.post("/api/workspace")
def api_workspace():
    d = request.get_json(silent=True) or {}
    org, unit = (d.get("org") or "").strip()[:80], (d.get("unit") or "").strip()[:80]
    if not org:
        return jsonify(error="Enter a company or site name."), 400
    jur = tjur.normalise(d.get("jurisdictions")) if isinstance(d.get("jurisdictions"), list) else None
    st = tsetup.update(org=org, unit=unit or "Quality", jurisdictions=jur)
    taudit.append("Console", "Workspace changed", "", f"{st['org']} · {st['unit']} · clocks {', '.join(tsetup.jurisdictions())}")
    _cache.update(rows=[], mtime=None)
    return jsonify(ok=True, org=st["org"], unit=st["unit"], jurisdictions=tsetup.jurisdictions())


# ---------------------------------------------------------------- plugins (settings)
@app.route("/settings/plugins")
def plugins_page():
    return render_template("plugins.html", page="plugins", title="Plugins", data_dir=VIGIL_DIR)


@app.route("/api/plugins")
def api_plugins():
    return jsonify(plugins.overview(probe=request.args.get("probe", "1") != "0"))


@app.post("/api/plugins/active")
def api_plugins_active():
    pid = (request.get_json(silent=True) or {}).get("id") or "none"
    try:
        plugins.set_active(pid)
    except plugins.PluginError as e:
        return jsonify(error=str(e)), 400
    HEALTH.update(model=_check_model(), agent={"id": tconfig.agent_id(), "name": get_agent().name}, demo_mode=demo_mode())
    if demo_mode():
        ensure_sample_data()
    return jsonify(ok=True, active_agent=plugins.active_agent_id(), agent=get_agent().name, demo_mode=demo_mode())


@app.post("/api/plugins/<pid>")
def api_plugins_update(pid):
    d = request.get_json(silent=True) or {}
    try:
        st = plugins.update_plugin(pid, enabled=d.get("enabled"), settings=d.get("settings"))
    except plugins.PluginError as e:
        return jsonify(error=str(e)), 400
    HEALTH.update(model=_check_model(), agent={"id": tconfig.agent_id(), "name": get_agent().name}, demo_mode=demo_mode())
    return jsonify(ok=True, enabled=st["enabled"], status=plugins.status(pid, probe=False), active_agent=plugins.active_agent_id())


@app.post("/api/plugins/<pid>/test")
def api_plugins_test(pid):
    return jsonify(status=plugins.status(pid, probe=True))


@app.route("/api/health")
def api_health():
    d = DEMO.public(since=10**12)
    try:
        changed = os.path.getmtime(LOG)
    except OSError:
        changed = None
    return jsonify({**HEALTH, "licence": licensing.check().status()["state"], "log_changed": changed, "now": time.time(),
                    "demo": {k: d[k] for k in ("running", "kind", "processed", "total")}})


@app.route("/reports/<cid>.pdf")
def pdf(cid):
    return send_from_directory(REPORTS, f"MDR_{cid}.pdf", max_age=0)




def _shutdown(*_):
    if DEMO.running:
        DEMO.stop()  # the replay runs in its own process group; do not leave it orphaned
    sys.exit(0)


_init_once = threading.Lock()
_initialised = False


def init_runtime():
    """Seed data, point vigil.py at the data folder, start the health + intake threads and mount intake.py.
    Safe to call from __main__ (dev) or at import time (gunicorn in the public demo); runs its work once."""
    global _initialised
    with _init_once:
        if _initialised:
            return
        _initialised = True
    if PUBLIC_DEMO:
        # The public demo has no first-run flow: complete setup in explore mode and seed invented data on start.
        if tsetup.required():
            tsetup.complete("explore", org=tsetup.SAMPLE_ORG, unit=tsetup.SAMPLE_UNIT, agent="sample")
    ensure_sample_data()
    vigil()  # point vigil.py at the data folder before any worker (console or intake.py) can process a complaint
    threading.Thread(target=health_loop, daemon=True).start()
    start_intake_worker(recover=True)  # resume anything left queued or interrupted
    if intake_mod():
        try:
            intake_mod().init_app(app)  # mounts POST /api/v1/complaints (+ /csv, status) and intake.py's worker
        except Exception as e:
            print("intake.py endpoints not mounted:", type(e).__name__, e, flush=True)
    try:
        from thirty import reporter  # lazy: keep the reporter package off the import-time path
        reporter.init_app(app)  # mounts the public /report Front_Door blueprint after intake's paths are set
    except Exception as e:
        print("reporter Front_Door not mounted:", type(e).__name__, e, flush=True)


# Under gunicorn (the public demo) app.py is imported, not run as __main__: initialise at import time so the
# background threads, sample data and intake endpoints are ready before the first request. In dev, __main__ runs it.
if os.environ.get("THIRTY_SKIP_RUNTIME_INIT") != "1":
    init_runtime()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _shutdown)
    init_runtime()  # no-op if already initialised at import
    port = int(os.environ.get("VIGIL_CONSOLE_PORT", 5001))
    print(f"Thirty console on http://localhost:{port}  (data: {VIGIL_DIR} · agent: {get_agent().name}{' · demo mode' if demo_mode() else ''})", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

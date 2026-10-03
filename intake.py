#!/usr/bin/env python3
"""
Vigil intake - complaints from real channels into vigil.process(), 100% local.

  REST webhook   POST /api/v1/complaints        (header X-API-Key, JSON)        source = payload 'source' or 'api'
  CSV upload     POST /api/v1/complaints/csv    (multipart 'file') or enqueue_csv()   source = 'csv'
  Email          IMAP poller every 60 s (optional, settings.json "email")            source = 'email'

Every complaint is mapped (settings.json "field_map"), validated, de-duplicated by external_id + source,
saved raw under intake/raw/, then processed ONE AT A TIME by a background worker so the local model is
never flooded. The queue survives restarts (intake/index.csv).

Usage:
  python3 intake.py serve                 # webhook on 127.0.0.1:5050 (+ email poller if enabled)
  python3 intake.py csv complaints.csv    # queue a CSV file and process it now
  python3 intake.py key                   # print the API key

The console can mount the same endpoints:  import intake; intake.init_app(app)
"""
import csv, datetime as dt, email, email.policy, fcntl, hashlib, hmac, imaplib, io, json, os, queue, re, secrets
import sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    from flask import Blueprint, Flask, jsonify, request
except ImportError:  # flask lives in ~/hackathon/venv, like fpdf2 for vigil.py
    _venv_py = os.path.join(os.path.dirname(HERE), "venv", "bin", "python")
    if __name__ == "__main__" and os.path.exists(_venv_py) and os.path.realpath(sys.executable) != _venv_py:
        os.execv(_venv_py, [_venv_py, *sys.argv])
    raise

sys.path.insert(0, HERE)
import vigil  # noqa: E402  (process(), log, Telegram, PDFs - unchanged)

SETTINGS = os.path.join(HERE, "settings.json")
INTAKE = os.path.join(HERE, "intake")
RAW = os.path.join(INTAKE, "raw")
INDEX = os.path.join(INTAKE, "index.csv")  # external_id, source -> vigil_id, status (dedupe + restart-safe queue)
INDEX_FIELDS = ["time", "vigil_id", "source", "external_id", "status", "error"]
MAX_TEXT = 20000

DEFAULT_SETTINGS = {
    "api_key": "",
    "host": "127.0.0.1",  # local only; set 0.0.0.0 to accept complaints from other machines on the network
    "port": 5050,
    # incoming field name -> Vigil field (text, device, event_date, reporter, external_id, source, manufacturer,
    # product_code). Applied to API and CSV payloads; names already in Vigil format pass through.
    "field_map": {
        "api": {"complaint": "text", "description": "text", "product": "device", "date_of_event": "event_date",
                "id": "external_id", "ticket_id": "external_id", "customer": "reporter"},
        "csv": {"mdr_report_key": "external_id", "event_description": "text", "brand_name": "device",
                "date_of_event": "event_date", "manufacturer": "manufacturer", "product_code": "product_code",
                "reporter_name": "reporter"},
    },
    "email": {"enabled": False, "host": "imap.gmail.com", "user": "", "app_password": "", "folder": "INBOX",
              "interval_seconds": 60},
}


def settings():
    """settings.json, created on first use with a fresh API key (file mode 0600: it holds secrets)."""
    s = json.load(open(SETTINGS)) if os.path.exists(SETTINGS) else {}
    changed = not os.path.exists(SETTINGS)
    for k, v in DEFAULT_SETTINGS.items():
        if k not in s:
            s[k], changed = v, True
    if not s.get("api_key"):
        s["api_key"], changed = secrets.token_urlsafe(32), True
    if changed:
        fd = os.open(SETTINGS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(s, f, indent=2)
    return s


# ---------------------------------------------------------------- normalize + validate
def apply_map(payload, kind):
    fmap = settings()["field_map"].get(kind, {})
    out = {}
    for k, v in payload.items():
        key = fmap.get(k, k)
        if key not in out or not out[key]:  # first non-empty value wins (e.g. two columns mapped to text)
            out[key] = v
    return out


def _yyyymmdd(d):
    d = str(d or "").strip()
    if re.fullmatch(r"\d{8}", d):
        return d
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", d)
    return "".join(m.groups()) if m else ""


def vigil_id(source, external_id):
    """Stable, Telegram/skill-safe id: same external_id + source always maps to the same complaint."""
    return f"{source[:3].upper()}-" + hashlib.sha1(f"{source}|{external_id}".encode()).hexdigest()[:8]


def to_complaint(p, default_source):
    """Mapped payload -> (vigil complaint dict, None) or (None, error message)."""
    text = " ".join(str(p.get("text") or "").split())
    if not text:
        return None, "text is required"
    if len(text) > MAX_TEXT:
        return None, f"text longer than {MAX_TEXT} characters"
    source = re.sub(r"[^a-z0-9_-]", "", str(p.get("source") or default_source).lower())[:20] or default_source
    ext = str(p.get("external_id") or "").strip()[:200] or hashlib.sha1(text.encode()).hexdigest()[:16]
    reporter = str(p.get("reporter") or "").strip()[:200]
    c = dict(id=vigil_id(source, ext), text=text, device=str(p.get("device") or "").strip()[:200],
             manufacturer=str(p.get("manufacturer") or "").strip()[:200], event_date=_yyyymmdd(p.get("event_date")),
             received=dt.date.today().strftime("%Y%m%d"), event_type="", outcomes="", generic_name="",
             product_code=str(p.get("product_code") or "").strip()[:10], product_problems="",
             manufacturer_narrative="", source=source, external_id=ext, reporter=reporter)
    return c, None


# ---------------------------------------------------------------- index (dedupe) + worker queue
_q = queue.Queue()
_index_lock = threading.Lock()
_worker = None


def _index_rows():
    return list(csv.DictReader(open(INDEX, encoding="utf-8"))) if os.path.exists(INDEX) else []


def _index_update(vid, **kw):
    """Insert or update one index row (thread lock + flock: the console and `intake.py serve` may both run)."""
    os.makedirs(INTAKE, exist_ok=True)
    with _index_lock, open(INDEX + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rows = _index_rows()
        hit = next((r for r in rows if r["vigil_id"] == vid), None)
        if hit is None:
            hit = {k: "" for k in INDEX_FIELDS}
            rows.append(hit)
        hit.update(kw, vigil_id=vid)
        tmp = INDEX + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=INDEX_FIELDS, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
        os.replace(tmp, INDEX)


def submit(payload, kind="api", default_source="api", raw=None, raw_ext="json"):
    """Map, validate, de-duplicate, save raw, queue. Returns (http_status, response dict)."""
    c, err = to_complaint(apply_map(payload, kind), default_source)
    if err:
        return 400, {"status": "rejected", "error": err}
    existing = next((r for r in _index_rows() if r["vigil_id"] == c["id"]), None)
    if existing:
        return 200, {"status": "duplicate", "vigil_id": c["id"], "state": existing["status"]}
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, f"{c['id']}.{raw_ext}")
    with open(path, "wb" if isinstance(raw, bytes) else "w") as f:  # raw evidence, as received
        f.write(raw if raw is not None else json.dumps({"payload": payload, "complaint": c}, indent=2))
    json.dump(c, open(os.path.join(RAW, f"{c['id']}.complaint.json"), "w"), indent=2)
    _index_update(c["id"], time=dt.datetime.now().isoformat(timespec="seconds"), source=c["source"],
                  external_id=c["external_id"], status="queued", error="")
    start_worker()
    _q.put(c)
    return 202, {"status": "queued", "vigil_id": c["id"]}


def _work():
    while True:
        c = _q.get()
        try:
            _index_update(c["id"], status="processing")
            if c.get("reporter"):  # keep who reported it in the narrative the model and reviewers see
                c = {**c, "text": f"{c['text']} (Reported by: {c['reporter']})"}
            vigil.process(c)
            _index_update(c["id"], status="done")
        except Exception as e:  # never kill the worker: mark failed, keep the raw payload for a retry
            print(f"intake: #{c['id']} failed: {type(e).__name__}: {e}", flush=True)
            _index_update(c["id"], status="failed", error=f"{type(e).__name__}: {e}"[:300])
        finally:
            _q.task_done()


def start_worker():
    """One worker thread per process; re-queues complaints that were queued/processing when we last stopped."""
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_work, daemon=True, name="vigil-intake")
    _worker.start()
    for r in _index_rows():
        cpath = os.path.join(RAW, f"{r['vigil_id']}.complaint.json")
        if r["status"] in ("queued", "processing") and os.path.exists(cpath):
            _q.put(json.load(open(cpath)))


# ---------------------------------------------------------------- CSV upload (console + CLI)
def enqueue_csv(f, source="csv"):
    """Queue every row of a CSV (path, bytes or text file object). Returns per-row results."""
    if isinstance(f, (bytes, bytearray)):
        f = io.StringIO(f.decode("utf-8-sig"))
    elif isinstance(f, str):
        f = open(f, encoding="utf-8-sig", newline="")
    csv.field_size_limit(sys.maxsize)
    out = []
    for i, row in enumerate(csv.DictReader(f), 1):
        status, res = submit({k: v for k, v in row.items() if k}, kind="csv", default_source=source)
        out.append({"row": i, **res})
    return out


# ---------------------------------------------------------------- email (IMAP, optional)
def _body(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    text = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def poll_email_once():
    cfg = settings()["email"]
    m = imaplib.IMAP4_SSL(cfg["host"])
    try:
        m.login(cfg["user"], cfg["app_password"])
        m.select(cfg.get("folder") or "INBOX")
        _, ids = m.search(None, "UNSEEN")
        for num in ids[0].split():
            _, data = m.fetch(num, "(RFC822)")  # fetching marks the message \Seen
            raw = data[0][1]
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            payload = {"external_id": msg.get("Message-ID") or hashlib.sha1(raw).hexdigest(),
                       "text": f"{msg.get('Subject', '')}. {_body(msg)}".strip(". "),
                       "reporter": msg.get("From", ""), "source": "email"}
            status, res = submit(payload, kind="email", default_source="email", raw=raw, raw_ext="eml")
            print(f"intake email: {res}", flush=True)
    finally:
        try: m.logout()
        except Exception: pass


def start_email_poller():
    cfg = settings()["email"]
    if not (cfg.get("enabled") and cfg.get("user") and cfg.get("app_password")):
        return False

    def loop():
        while True:
            try:
                poll_email_once()
            except Exception as e:
                print(f"intake email poll failed: {type(e).__name__}: {e}", flush=True)
            time.sleep(int(cfg.get("interval_seconds") or 60))
    threading.Thread(target=loop, daemon=True, name="vigil-email").start()
    return True


# ---------------------------------------------------------------- HTTP (blueprint + standalone app)
bp = Blueprint("vigil_intake", __name__)


def _authorized():
    key = request.headers.get("X-API-Key", "")
    return bool(key) and hmac.compare_digest(key, settings()["api_key"])


@bp.post("/api/v1/complaints")
def api_complaint():
    if not _authorized():
        return jsonify(status="unauthorized", error="missing or wrong X-API-Key"), 401
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(status="rejected", error="body must be a JSON object"), 400
    code, res = submit(payload, kind="api", default_source="api")
    return jsonify(res), code


@bp.post("/api/v1/complaints/csv")
def api_csv():
    if not _authorized():
        return jsonify(status="unauthorized", error="missing or wrong X-API-Key"), 401
    f = request.files.get("file")
    if not f:
        return jsonify(status="rejected", error="multipart field 'file' is required"), 400
    return jsonify(results=enqueue_csv(f.read())), 202


@bp.get("/api/v1/complaints/<vid>")
def api_status(vid):
    if not _authorized():
        return jsonify(status="unauthorized"), 401
    r = next((r for r in _index_rows() if r["vigil_id"] == vid), None)
    return (jsonify(r), 200) if r else (jsonify(status="unknown"), 404)


def init_app(app):
    """Mount the intake endpoints on an existing Flask app (e.g. the console) and start the worker."""
    app.register_blueprint(bp)
    start_worker()
    start_email_poller()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    s = settings()
    if cmd == "key":
        print(s["api_key"])
    elif cmd == "csv":
        for r in enqueue_csv(sys.argv[2]):
            print(r)
        _q.join()
    elif cmd == "serve":
        app = Flask(__name__)
        app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
        init_app(app)
        print(f"Vigil intake on http://{s['host']}:{s['port']}  (email poller: "
              f"{'on' if s['email'].get('enabled') else 'off'}; key: python3 intake.py key)", flush=True)
        app.run(host=s["host"], port=int(s["port"]), threaded=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()

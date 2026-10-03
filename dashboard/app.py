"""Vigil Console - local web dashboard for the Vigil complaint agent.

Reads ../decisions.csv (written by vigil.py), serves the draft MDR PDFs from ../reports,
and runs new complaints through vigil.process(). Everything is local: no CDNs, no external fonts.

Run:  ~/hackathon/venv/bin/python ~/hackathon/vigil/dashboard/app.py   ->  http://localhost:5000
"""
import csv, datetime as dt, fcntl, io, os, sys, threading, time, traceback, uuid

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

HERE = os.path.dirname(os.path.abspath(__file__))
VIGIL_DIR = os.path.dirname(HERE)
LOG = os.environ.get("VIGIL_LOG", os.path.join(VIGIL_DIR, "decisions.csv"))
REPORTS = os.environ.get("VIGIL_REPORTS", os.path.join(VIGIL_DIR, "reports"))
CHART = os.path.join(VIGIL_DIR, "philips_chart.png")
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text"]
DECISIONS = ["REPORTABLE", "NEEDS_INFO", "NOT_REPORTABLE"]

app = Flask(__name__)

# ---------------------------------------------------------------- decisions.csv access
def read_rows():
    if not os.path.exists(LOG):
        return []
    with open(LOG, newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return list(csv.DictReader(f))
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def approve(cid, name):
    """Set status to 'APPROVED by <name>' for complaint <cid>. Holds an exclusive flock on decisions.csv
    and does the read-modify-write in one tight step; retries if the file grew underneath us
    (vigil.py appends without taking the lock)."""
    for _ in range(5):
        with open(LOG, "r+", newline="", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                before = f.read()
                reader = csv.DictReader(io.StringIO(before))
                fields = reader.fieldnames or FIELDS
                rows = list(reader)
                hit = [r for r in rows if r["id"] == cid]
                if not hit:
                    return False
                for r in hit:
                    r["status"] = f"APPROVED by {name}"
                out = io.StringIO()
                w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
                w.writeheader(); w.writerows(rows)
                if os.fstat(f.fileno()).st_size != len(before.encode("utf-8")):
                    continue  # an append landed while we were parsing - start over
                f.seek(0); f.write(out.getvalue()); f.truncate(); f.flush(); os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        threading.Thread(target=_push_to_sandbox, daemon=True).start()
        return True
    raise RuntimeError("decisions.csv kept changing; try again")

# ---------------------------------------------------------------- vigil.py bridge (imported lazily, never edited)
_vigil = None
_vigil_lock = threading.Lock()

def vigil():
    global _vigil
    with _vigil_lock:
        if _vigil is None:
            sys.path.insert(0, VIGIL_DIR)
            import vigil as v
            v.LOG, v.REPORTS = LOG, REPORTS  # same files the dashboard reads (env-overridable for testing)
            if os.environ.get("VIGIL_OUTBOX"):
                v.OUTBOX = os.environ["VIGIL_OUTBOX"]
            _vigil = v
        return _vigil


def _push_to_sandbox():
    try:
        vigil().push_log()  # keep the OpenClaw sandbox copy in sync, like vigil.write_log does
    except Exception as e:
        print("sandbox push skipped:", e)


JOBS = {}                      # job id -> dict(status, id, device, error, started, finished)
_process_lock = threading.Lock()  # one complaint at a time through the local model

def run_job(jid, c):
    with _process_lock:
        JOBS[jid].update(status="running", started=time.time())
        try:
            row = vigil().process(c)
            JOBS[jid].update(status="done", decision=row.get("decision"))
        except Exception as e:
            traceback.print_exc()
            JOBS[jid].update(status="error", error=f"{type(e).__name__}: {e}")
        JOBS[jid]["finished"] = time.time()

# ---------------------------------------------------------------- view helpers
def today():
    return dt.date.today()


def days_left(r):
    try:
        return (dt.date.fromisoformat(r["due_date"]) - today()).days
    except Exception:
        return None


def is_approved(r):
    return (r.get("status") or "").startswith("APPROVED")


def urgency(d):
    """red = overdue or due within 7 days, orange = 8-14 days, green = more than 14 days."""
    if d is None: return ""
    return "red" if d <= 7 else "orange" if d <= 14 else "green"


def latest_by_id(rows):
    seen = {}
    for r in rows:
        seen[r["id"]] = r  # later rows win
    return seen


def has_pdf(cid):
    return os.path.exists(os.path.join(REPORTS, f"MDR_{cid}.pdf"))


def decorate(r):
    r = dict(r)
    r["days_left"] = days_left(r)
    r["urgency"] = urgency(r["days_left"])
    r["approved"] = is_approved(r)
    r["pdf"] = has_pdf(r["id"])
    r["missing_list"] = [m.strip() for m in (r.get("missing") or "").split(";") if m.strip()]
    return r


def overview_data():
    rows = [decorate(r) for r in read_rows()]
    open_rows = [r for r in rows if not r["approved"] and r["days_left"] is not None]
    kpi = dict(
        processed=len(rows),
        reportable=sum(r["decision"] == "REPORTABLE" for r in rows),
        needs_info=sum(r["decision"] == "NEEDS_INFO" for r in rows),
        due7=sum(0 <= r["days_left"] <= 7 for r in open_rows),
        overdue=sum(r["days_left"] < 0 for r in open_rows),
        approved=sum(r["approved"] for r in rows),
    )
    deadlines = sorted((r for r in rows if r["due_date"]), key=lambda r: (r["due_date"], r["approved"]))
    return rows, kpi, deadlines


@app.context_processor
def globals_():
    return dict(now=dt.datetime.now().strftime("%d %b %Y, %H:%M:%S"), today=today().isoformat())

# ---------------------------------------------------------------- pages
@app.route("/")
def overview():
    rows, kpi, deadlines = overview_data()
    tpl = "_overview_live.html" if request.args.get("partial") else "overview.html"
    return render_template(tpl, page="overview", kpi=kpi, deadlines=deadlines, chart=os.path.exists(CHART))


@app.route("/complaint/<cid>")
def complaint(cid):
    r = latest_by_id(read_rows()).get(cid)
    if not r:
        abort(404)
    return render_template("complaint.html", page="audit", r=decorate(r), msg=request.args.get("msg"))


@app.post("/complaint/<cid>/approve")
def complaint_approve(cid):
    name = " ".join((request.form.get("name") or "").split())[:60]
    if not name:
        return redirect(url_for("complaint", cid=cid, msg="Enter your name to approve."))
    if not approve(cid, name):
        abort(404)
    return redirect(url_for("complaint", cid=cid, msg=f"Approved by {name}."))


@app.route("/audit")
def audit():
    sel = request.args.get("decision", "")
    rows = [decorate(r) for r in read_rows()]
    counts = {d: sum(r["decision"] == d for r in rows) for d in DECISIONS}
    if sel:
        rows = [r for r in rows if r["decision"] == sel]
    rows.reverse()  # newest first
    return render_template("audit.html", page="audit", rows=rows, sel=sel, counts=counts, decisions=DECISIONS)


@app.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "POST":
        text = (request.form.get("text") or "").strip()
        device = (request.form.get("device") or "").strip()
        if not text:
            return render_template("new.html", page="new", jobs=recent_jobs(), error="Paste the complaint text.",
                                   text=text, device=device)
        now = dt.datetime.now()
        cid = "WEB" + now.strftime("%Y%m%d%H%M%S")
        c = dict(id=cid, text=text, device=device, manufacturer="", event_date="", received=now.strftime("%Y%m%d"),
                 event_type="", outcomes="", generic_name="", product_code="")
        jid = uuid.uuid4().hex[:8]
        JOBS[jid] = dict(status="queued", id=cid, device=device, created=time.time())
        threading.Thread(target=run_job, args=(jid, c), daemon=True).start()
        return redirect(url_for("new", submitted=cid))
    return render_template("new.html", page="new", jobs=recent_jobs(), submitted=request.args.get("submitted"))


def recent_jobs():
    return sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)[:10]


@app.route("/api/jobs")
def api_jobs():
    return jsonify(recent_jobs())


@app.route("/reports/<cid>.pdf")
def pdf(cid):
    return send_from_directory(REPORTS, f"MDR_{cid}.pdf")


@app.route("/chart.png")
def chart():
    return send_from_directory(VIGIL_DIR, "philips_chart.png", max_age=0)


if __name__ == "__main__":
    print(f"Vigil Console on http://localhost:5000  (log: {LOG})")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

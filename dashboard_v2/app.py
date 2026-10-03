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
@app.context_processor
def _globals():
    return {"health": HEALTH}


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


@app.route("/api/health")
def api_health():
    return jsonify({**HEALTH, "demo": DEMO.public() if "DEMO" in globals() else None})


@app.route("/reports/<cid>.pdf")
def pdf(cid):
    return send_from_directory(REPORTS, f"MDR_{cid}.pdf", max_age=0)


@app.route("/chart.png")
def chart():
    return send_from_directory(VIGIL_DIR, "philips_chart.png", max_age=0)


if __name__ == "__main__":
    threading.Thread(target=health_loop, daemon=True).start()
    print(f"Vigil Console v2 on http://localhost:5001  (data: {VIGIL_DIR})", flush=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("VIGIL_CONSOLE_PORT", 5001)), debug=False, threaded=True)

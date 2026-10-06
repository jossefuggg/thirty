"""Tamper-evident audit trail: <data>/audit.jsonl, one JSON object per line, hash-chained.

Each entry carries the SHA-256 of the previous entry's hash plus its own canonical content, so editing or
removing any line breaks every later hash. verify() walks the chain. This is the 21 CFR 11.10(e) style
record for what reviewers did (approve, request info, undo, record a reportability decision) and what the
console changed (setup, plugins, workspace). It complements decisions.csv, which is the pipeline's own log.

An e-signature here is the reviewer's typed name plus the meaning of the signature (11.50) and the time.
"""
import datetime as dt, hashlib, json, os

from . import config, filelock

FILE = "audit.jsonl"
GENESIS = "0" * 64

MEANINGS = {
    "approve": "I approve this Form 3500A draft for submission to the regulator.",
    "info": "I am requesting more information before a reporting decision.",
    "undo": "I am reverting the previous decision to pending review.",
    "decision": "I have reviewed the facts and record this reportability decision and its rationale.",
}


def path(data_dir=None):
    return os.path.join(data_dir or config.data_dir(), FILE)


def _canonical(entry):
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(prev, entry):
    return hashlib.sha256((prev + _canonical(entry)).encode("utf-8")).hexdigest()


def _read(p):
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out


def append(actor, action, cid="", detail="", meaning="", extra=None, data_dir=None):
    """Append one signed entry and return it (with seq, prev, hash)."""
    p = path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with filelock.locked(p + ".lock"):
        rows = _read(p)
        prev = rows[-1]["hash"] if rows else GENESIS
        entry = {"seq": len(rows) + 1, "time": dt.datetime.now().isoformat(timespec="seconds"), "actor": actor, "action": action,
                 "id": cid or "", "detail": detail or "", "meaning": meaning or "", "prev": prev}
        if extra:
            entry["data"] = extra
        entry["hash"] = _digest(prev, {k: v for k, v in entry.items() if k != "hash"})
        with open(p, "a", encoding="utf-8") as f:
            f.write(_canonical(entry) + "\n")
    return entry


def entries(data_dir=None, cid=None):
    rows = _read(path(data_dir))
    return [r for r in rows if r.get("id") == cid] if cid else rows


def verify(data_dir=None):
    """Walk the chain. {'ok', 'count', 'head', 'broken_at': seq of the first bad entry or None}."""
    rows = _read(path(data_dir))
    prev = GENESIS
    for i, r in enumerate(rows, 1):
        body = {k: v for k, v in r.items() if k != "hash"}
        if r.get("seq") != i or r.get("prev") != prev or _digest(prev, body) != r.get("hash"):
            return {"ok": False, "count": len(rows), "head": rows[-1].get("hash", "") if rows else GENESIS, "broken_at": i}
        prev = r["hash"]
    return {"ok": True, "count": len(rows), "head": prev, "broken_at": None}

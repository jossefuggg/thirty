"""First-run setup state: <data>/setup.json.

{"completed": "2026-10-05T10:00:00", "mode": "explore" | "site", "org": "...", "unit": "...", "agent": "sample" | "local" | "none"}

Until the file exists the console shows the setup flow (/setup). Everything chosen there can be changed
later: the agent on the Plugins screen, the workspace on the Licence & updates screen, the mode by
running setup again (/setup?again=1).
"""
import datetime as dt, json, os

from . import config

FILE = "setup.json"
SAMPLE_ORG, SAMPLE_UNIT = "Northwind Medical", "Quality"


def path():
    return os.path.join(config.data_dir(), FILE)


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict) and st.get("completed"):
            return st
    except (OSError, ValueError):
        pass
    return None


def required():
    return load() is None


def complete(mode, org="", unit="", agent="sample"):
    mode = "explore" if mode != "site" else "site"
    st = {"completed": dt.datetime.now().isoformat(timespec="seconds"), "mode": mode,
          "org": (org or "").strip()[:80] or (SAMPLE_ORG if mode == "explore" else "My site"),
          "unit": (unit or "").strip()[:80] or (SAMPLE_UNIT if mode == "explore" else "Quality"),
          "agent": agent if agent in ("sample", "local", "none") else "sample"}
    save(st)
    return st


def save(st):
    os.makedirs(config.data_dir(), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, path())


def update(**fields):
    st = load() or {}
    st.update({k: v for k, v in fields.items() if v is not None})
    st.setdefault("completed", dt.datetime.now().isoformat(timespec="seconds"))
    save(st)
    return st


def workspace():
    """What the top bar shows: the site chosen at setup, or the sample company."""
    st = load() or {}
    return {"org": st.get("org") or SAMPLE_ORG, "unit": st.get("unit") or SAMPLE_UNIT, "mode": st.get("mode") or "explore"}


def wants_sample_data():
    """Seed sample data only once the user has chosen to explore; before setup nothing is written."""
    st = load()
    return st is not None and st.get("mode") == "explore"

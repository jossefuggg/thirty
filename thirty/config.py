"""Where Thirty keeps its data and which agent is active.

Code lives in the repository (or the installed app); data lives in one folder:
  VIGIL_DIR   -> explicit data folder (tests, screenshots, the desktop app)
  otherwise   -> the repository root, as in the hackathon layout

Agent selection: thirty.plugins decides (plugins.json in the data folder; THIRTY_AGENT=sample|local|none
forces it; default "local" when a model is configured via VIGIL_LLM_BASE, else "sample" = demo mode).
"""
import os

import sys

CODE_DIR = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    return os.path.abspath(os.environ.get("VIGIL_DIR") or CODE_DIR)


def model_configured():
    return bool(os.environ.get("VIGIL_LLM_BASE") or os.environ.get("VIGIL_LLM_MODEL"))


def agent_id():
    """Which agent plugin runs the pipeline ("none" = manual review). See thirty.plugins.active_agent_id()."""
    from . import plugins
    return plugins.active_agent_id()


def demo_mode():
    """True when the console runs on sample data with the sample agent (no model configured)."""
    return agent_id() == "sample"


def public_demo():
    """True when the console is deployed as a locked public demo (THIRTY_PUBLIC_DEMO=1).

    In public demo the agent is forced to "sample", every settings surface is read-only, no secret
    fields are rendered, first-run setup is skipped and sample data is seeded on start.
    """
    return (os.environ.get("THIRTY_PUBLIC_DEMO") or "").strip().lower() in ("1", "true", "on", "yes")


def public_url():
    """Public base URL for QR codes and shareable links (THIRTY_PUBLIC_URL), without a trailing slash."""
    return (os.environ.get("THIRTY_PUBLIC_URL") or "").strip().rstrip("/")

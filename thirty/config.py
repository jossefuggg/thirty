"""Where Thirty keeps its data and which agent is active.

Code lives in the repository (or the installed app); data lives in one folder:
  VIGIL_DIR   -> explicit data folder (tests, screenshots, the desktop app)
  otherwise   -> the repository root, as in the hackathon layout

Agent selection (Phase 2; Phase 3 moves this into settings):
  THIRTY_AGENT = sample | local | none
  default: "local" when a model is configured (VIGIL_LLM_BASE set), else "sample" (demo mode).
"""
import os

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    return os.path.abspath(os.environ.get("VIGIL_DIR") or CODE_DIR)


def model_configured():
    return bool(os.environ.get("VIGIL_LLM_BASE") or os.environ.get("VIGIL_LLM_MODEL"))


def agent_id():
    """Which built-in agent runs the pipeline."""
    a = (os.environ.get("THIRTY_AGENT") or "").strip().lower()
    if a in ("sample", "local", "none"):
        return a
    return "local" if model_configured() else "sample"


def demo_mode():
    """True when the console runs on sample data with the sample agent (no model configured)."""
    return agent_id() == "sample"

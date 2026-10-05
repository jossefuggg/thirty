"""Where Thirty keeps its data and which agent is active.

Code lives in the repository (or the installed app); data lives in one folder:
  VIGIL_DIR   -> explicit data folder (tests, screenshots, the desktop app)
  otherwise   -> the repository root, as in the hackathon layout

Agent selection: thirty.plugins decides (plugins.json in the data folder; THIRTY_AGENT=sample|local|none
forces it; default "local" when a model is configured via VIGIL_LLM_BASE, else "sample" = demo mode).
"""
import os

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

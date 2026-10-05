"""Agent registry: the active agent for the pipeline and the console.

    from thirty.agents import get_agent
    get_agent().classify(complaint, memory)

The choice comes from thirty.config.agent_id() (env THIRTY_AGENT, else "local" when a model is configured,
else "sample"). set_agent() overrides it for the running process (tests, the desktop app).
"""
import threading

from .. import config
from .base import Agent, NoAgent

_lock = threading.Lock()
_active = {"id": None, "agent": None}


def make_agent(agent_id):
    if agent_id == "local":
        from .local_model import LocalModelAgent
        return LocalModelAgent()
    if agent_id == "sample":
        from .sample import SampleAgent
        return SampleAgent()
    return NoAgent()


def get_agent():
    wanted = config.agent_id()
    with _lock:
        if _active["agent"] is None or _active["id"] != wanted:
            _active.update(id=wanted, agent=make_agent(wanted))
        return _active["agent"]


def set_agent(agent):
    """Pin an Agent instance for this process (or None to go back to the configured one)."""
    with _lock:
        _active.update(id=getattr(agent, "id", None), agent=agent)


__all__ = ["Agent", "NoAgent", "get_agent", "set_agent", "make_agent"]

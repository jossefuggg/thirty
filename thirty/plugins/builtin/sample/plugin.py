"""Built-in plugin: the sample agent (demo mode)."""
from thirty.agents.sample import SampleAgent


def create(settings):
    return SampleAgent(delay=float(settings.get("delay") or 0))

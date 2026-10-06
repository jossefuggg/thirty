"""Built-in plugin: the local model agent (the hackathon pipeline's prompts and HTTP calls)."""
from thirty.agents.local_model import LocalModelAgent


def create(settings):
    return LocalModelAgent(base_url=settings.get("base_url") or "", model=settings.get("model") or "",
                           api_key=settings.get("api_key") or "", timeout=float(settings.get("timeout") or 180))

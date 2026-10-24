"""Built-in plugin: the Claude agent (Anthropic Messages API)."""
from thirty.agents.claude_model import ClaudeAgent


def create(settings):
    return ClaudeAgent(api_key=settings.get("api_key") or "", model=settings.get("model") or "",
                       timeout=float(settings.get("timeout") or 60))

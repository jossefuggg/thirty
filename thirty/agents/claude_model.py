"""Claude agent: the local model's prompts and JSON parsing, sent to Anthropic's cloud model.

Calls the Anthropic Messages API directly over HTTP (POST https://api.anthropic.com/v1/messages) with
`requests` and no SDK. Reuses local_model's CLASSIFY, MDR_FIELDS and ASK prompts and its _json parser so
decisions stay comparable with the local model agent. Unlike every other agent this one sends complaint
text to a cloud model, so the console swaps its "0 bytes to cloud AI" badge while it is active. Demo
feature: invented sample data only.
"""
import os, re, time

import requests

from .base import Agent, UNREADABLE, COMPLETE
from . import local_model as lm

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"


def resolve_key(api_key):
    """The setting value if it has a non-whitespace char, else env ANTHROPIC_API_KEY, else ""."""
    if api_key and api_key.strip():
        return api_key.strip()
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _extract_json(text):
    """Strip Markdown code fences, then reuse local_model._json (first {...} span)."""
    cleaned = re.sub(r"```[a-zA-Z]*\n?|```", "", text or "")
    return lm._json(cleaned)


class ClaudeAgent(Agent):
    id = "claude"
    name = "Claude agent"

    def __init__(self, api_key="", model="", timeout=60):
        self.api_key = api_key or ""
        self.model = model or DEFAULT_MODEL
        self.timeout = float(timeout or 60)

    def _messages(self, prompt, max_tokens, temperature=0.1):
        """One Anthropic Messages API call. Raises on no key, HTTP error or network error."""
        key = resolve_key(self.api_key)
        if not key:
            raise RuntimeError("No Anthropic API key: set the api_key setting or ANTHROPIC_API_KEY.")
        r = requests.post(API_URL, timeout=self.timeout, headers={
            "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
        }, json={"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                 "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        content = r.json().get("content") or []
        return (content[0].get("text") if content else "") or ""

    def classify(self, complaint, memory=""):
        try:
            prompt = lm.CLASSIFY.format(memory=memory or "No prior complaints on this device family.", **complaint)
            return _extract_json(self._messages(prompt, 400, temperature=0))  # deterministic decision/deadline
        except Exception:
            return dict(UNREADABLE)

    def draft_report(self, complaint, row):
        try:
            prompt = lm.MDR_FIELDS.format(decision=row["decision"], category=row["category"],
                                          deadline=lm.deadline_text(row.get("deadline_days")),
                                          missing=row["missing"] or "none listed",
                                          **{"generic_name": "", "product_code": "", "manufacturer": "",
                                             "manufacturer_narrative": "none", **complaint})
            return _extract_json(self._messages(prompt, 1500))
        except Exception:
            return {"H10_manufacturer_narrative": "Model output unreadable - complete all fields manually."}

    def follow_up_questions(self, row, missing):
        try:
            prompt = lm.ASK.format(id=row["id"], decision=row["decision"], category=row["category"],
                                   device=row["device"], text=row.get("text") or "",
                                   missing="; ".join(missing) or "none listed")
            j = _extract_json(self._messages(prompt, 700, temperature=0.2))
            qs = [str(q).strip() for q in j.get("questions") or [] if str(q).strip()][:5]
            return qs, str(j.get("message") or "").strip()
        except Exception:
            return [], ""

    def next_question(self, answers_so_far):
        """One adaptive interview question, or COMPLETE. Any failure -> COMPLETE (safe termination)."""
        language = (answers_so_far or {}).get("language") or "en"
        try:
            prompt = lm.NEXT_Q.format(
                reporter_type=(answers_so_far or {}).get("reporter_type") or "",
                language=language,
                device=(answers_so_far or {}).get("device") or "UNKNOWN",
                answers=(answers_so_far or {}).get("answers") or {},
                asked=(answers_so_far or {}).get("asked") or [],
            )
            return lm.interpret_next_question(_extract_json(self._messages(prompt, 400, temperature=0.2)), language)
        except Exception:
            return COMPLETE

    def translate_to_english(self, text, source_language):
        """English translation of text, or None. Never fabricates: None on any failure/CANNOT_TRANSLATE."""
        if not text or not str(text).strip():
            return None
        if source_language == "en":
            return text
        try:
            prompt = lm.TRANSLATE.format(source_language=source_language, text=text)
            out = (self._messages(prompt, 1000) or "").strip()
            if not out or out == "CANNOT_TRANSLATE":
                return None
            return out
        except Exception:
            return None

    def health(self):
        try:
            t0 = time.perf_counter()
            self._messages("ping", 1, temperature=0)
            ms = round((time.perf_counter() - t0) * 1000)
            return {"ok": True, "name": self.model, "ms": ms, "label": f"{self.model} · {ms} ms"}
        except Exception as e:
            return {"ok": False, "name": self.name, "ms": None, "label": f"offline ({type(e).__name__})"}

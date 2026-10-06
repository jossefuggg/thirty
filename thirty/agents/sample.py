"""Sample agent: pre-written results for the sample complaints, a small rule-based fallback for anything
else (e.g. a complaint typed into the intake form while in demo mode), and a short fake delay so the
console's loading states are visible. Returns exactly the shapes the local model agent returns."""
import os, re, time

from .base import Agent
from .. import sample_data

_SERIOUS = re.compile(r"\b(death|died|fatal|hospital\w*|emergency|ER\b|ambulance|burn\w*|unconscious|cyanotic|resuscitat\w*|injur\w*)", re.I)
_FIVE = re.compile(r"\b(fire|smoke|smoking|explo\w*|electric(?:al)? shock|shocked)\b", re.I)
_MALF = re.compile(r"\b(stopped|shut ?down|failed|fail\w*|alarm|over-?infus\w*|particle\w*|foam|dust|wrong|incorrect|froze|frozen|leak\w*)\b", re.I)


class SampleAgent(Agent):
    id = "sample"
    name = "Sample agent"

    def __init__(self, delay=None):
        env = os.environ.get("THIRTY_SAMPLE_DELAY")
        self.delay = float(env) if env not in (None, "") else (1.2 if delay is None else delay)

    def _wait(self, factor=1.0):
        if self.delay:
            time.sleep(self.delay * factor)

    def classify(self, complaint, memory=""):
        self._wait()
        res = sample_data.result_for(complaint.get("id"))
        if res:
            return dict(res)
        text = complaint.get("text") or ""
        words = len(text.split())
        if _FIVE.search(text):
            return {"decision": "REPORTABLE", "category": "SERIOUS_INJURY" if _SERIOUS.search(text) else "MALFUNCTION",
                    "reason": "Fire, smoke or electrical shock is a malfunction with an unreasonable risk of substantial harm; 5-day report under 21 CFR 803.53.",
                    "remedial_action_needed": True, "missing_info": ["device serial number"], "confidence": 82}
        if _SERIOUS.search(text):
            return {"decision": "REPORTABLE", "category": "SERIOUS_INJURY",
                    "reason": "The complaint reasonably suggests the device may have caused or contributed to a serious injury, 21 CFR 803.50(a)(1).",
                    "remedial_action_needed": False, "missing_info": ["patient age", "medical treatment"], "confidence": 78}
        if _MALF.search(text) and words >= 12:
            return {"decision": "REPORTABLE", "category": "MALFUNCTION",
                    "reason": "The malfunction described would be likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
                    "remedial_action_needed": False, "missing_info": ["device serial number", "event date"], "confidence": 68}
        if words < 12 or _MALF.search(text):
            return {"decision": "NEEDS_INFO", "category": "MALFUNCTION" if _MALF.search(text) else "NONE",
                    "reason": "The complaint does not state the outcome or enough detail to decide reportability under 21 CFR 803.50.",
                    "remedial_action_needed": False, "missing_info": ["patient outcome", "detailed description"], "confidence": 50}
        return {"decision": "NOT_REPORTABLE", "category": "NONE",
                "reason": "No death, serious injury or malfunction likely to cause one is described; not reportable under 21 CFR 803.50.",
                "remedial_action_needed": False, "missing_info": [], "confidence": 80}

    def draft_report(self, complaint, row):
        self._wait(1.5)
        return sample_data.fields_for(complaint.get("id"), complaint, row)

    def follow_up_questions(self, row, missing):
        self._wait(0.5)
        qs = sample_data.questions_for(row.get("id")) or [f"Can you provide the {m.strip().lower()}?" for m in missing[:5]]
        msg = ("Thank you for reporting this issue with your device. We are looking into it and need a few more "
               "details to complete our review. Could you please answer the questions below?")
        return qs[:5], msg

    def health(self):
        return {"ok": True, "name": self.name, "ms": 0, "label": "sample data · no model"}

"""Example agent plugin. See docs/PLUGINS.md.

Thirty calls create(settings) once and then the four methods below. Return plain dicts in the documented
shapes; raise if something is wrong and the status shows "error"."""
from thirty.agents.base import Agent


class KeywordAgent(Agent):
    id = "keyword-agent"
    name = "Keyword agent (example)"

    def __init__(self, words, strict):
        self.words = [w.strip().lower() for w in words.split(",") if w.strip()]
        self.strict = strict

    def classify(self, complaint, memory=""):
        text = (complaint.get("text") or "").lower()
        hits = [w for w in self.words if w in text]
        if hits:
            return {"decision": "REPORTABLE", "category": "SERIOUS_INJURY" if any(w in hits for w in ("death", "injury", "hospital")) else "MALFUNCTION",
                    "reason": f"Contains {', '.join(hits)}: may have caused or contributed to death or serious injury, 21 CFR 803.50(a).",
                    "remedial_action_needed": any(w in hits for w in ("fire", "smoke")), "missing_info": [], "confidence": 60}
        if self.strict and len(text.split()) < 12:
            return {"decision": "NEEDS_INFO", "category": "NONE", "reason": "Too short to decide; ask the reporter for details.",
                    "remedial_action_needed": False, "missing_info": ["detailed description"], "confidence": 40}
        return {"decision": "NOT_REPORTABLE", "category": "NONE", "reason": "None of the reportable words appear; not reportable under 21 CFR 803.50.",
                "remedial_action_needed": False, "missing_info": [], "confidence": 55}

    def draft_report(self, complaint, row):
        return {"B5_event_description": complaint.get("text", ""), "D1_brand_name": complaint.get("device", ""),
                "H1_type_of_reportable_event": row.get("category") if row.get("category") != "NONE" else "MALFUNCTION",
                "H10_manufacturer_narrative": "Drafted by the keyword agent example; complete every field manually.",
                "follow_up_questions": ["What is the device serial number?", "What happened to the patient?"]}

    def follow_up_questions(self, row, missing):
        return [f"Can you provide the {m.lower()}?" for m in missing[:5]], "We are looking into your report and need a few details."

    def health(self):
        return {"ok": bool(self.words), "label": f"{len(self.words)} words" if self.words else "no words configured", "name": self.name, "ms": 0}


def create(settings):
    return KeywordAgent(settings.get("words", ""), bool(settings.get("strict", True)))

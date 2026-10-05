"""The agent interface: everything the pipeline and console ask an AI agent to do.

Three calls, all synchronous, all returning plain dicts/lists in the shapes below. An implementation
may be a local model, the sample agent, or (Phase 3) any plugin.

classify(complaint, memory) -> {
    "decision": "REPORTABLE" | "NOT_REPORTABLE" | "NEEDS_INFO",
    "category": "DEATH" | "SERIOUS_INJURY" | "MALFUNCTION" | "NONE",
    "reason": "one sentence citing the rule",
    "remedial_action_needed": bool,          # True -> 5-work-day report
    "missing_info": ["2-4 word items"],
    "confidence": 0-100,
}

draft_report(complaint, row) -> Form 3500A fields, e.g. {
    "A1_patient_identifier": "", "A2_age": "", "A3_sex": "", "A4_weight": "",
    "B1_event_type": "ADVERSE_EVENT|PRODUCT_PROBLEM|BOTH", "B2_outcomes": [...], "B3_date_of_event": "",
    "B5_event_description": "", "D1_brand_name": "", "D2_common_device_name": "", "D2b_product_code": "",
    "D3_manufacturer": "", "D4_model": "", "D4_lot": "", "D4_serial": "",
    "H1_type_of_reportable_event": "DEATH|SERIOUS_INJURY|MALFUNCTION", "H3_device_evaluated": "YES|NO|UNKNOWN",
    "H10_manufacturer_narrative": "", "follow_up_questions": ["..."],
}
(vigil.mdr_fields() then adds the fields Thirty sets itself: report date, report type, G4.)

follow_up_questions(row, missing) -> (["3-5 questions for the reporter"], "ready-to-send message")

health() -> {"ok": bool, "label": "short status", "name": "model or agent name", "ms": latency or None}
"""


class Agent:
    id = "base"
    name = "Agent"

    def classify(self, complaint, memory=""):
        raise NotImplementedError

    def draft_report(self, complaint, row):
        raise NotImplementedError

    def follow_up_questions(self, row, missing):
        raise NotImplementedError

    def health(self):
        return {"ok": False, "label": "not implemented", "name": self.name, "ms": None}


class NoAgent(Agent):
    """Manual review only: every complaint is NEEDS_INFO for a human, nothing is drafted."""
    id = "none"
    name = "No agent (manual review)"

    def classify(self, complaint, memory=""):
        return {"decision": "NEEDS_INFO", "category": "NONE", "reason": "No agent is active: a reviewer must assess this complaint under 21 CFR 803.",
                "remedial_action_needed": False, "missing_info": [], "confidence": 0}

    def draft_report(self, complaint, row):
        return {"H10_manufacturer_narrative": "No agent is active. Complete all fields manually.", "follow_up_questions": []}

    def follow_up_questions(self, row, missing):
        return [], ""

    def health(self):
        return {"ok": True, "label": "manual review only", "name": self.name, "ms": None}


UNREADABLE = {"decision": "NEEDS_INFO", "category": "NONE", "reason": "model output unreadable - human review",
              "deadline_days": 30, "missing_info": [], "confidence": 0}

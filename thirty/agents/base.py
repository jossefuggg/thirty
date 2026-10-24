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

The reporter front door adds two more calls (used only by the adaptive "Report a device problem" flow):

next_question(answers_so_far) -> question object | COMPLETE
    answers_so_far is the Answers_So_Far collection:
        {reporter_type, language, device, answers: {field: value}, asked: [field, ...]}
    Returns exactly one of:
      - the sentinel string COMPLETE ("complete"), meaning the Requirement-4 data set has been
        fully requested and no further question is needed, or
      - a question object (dict), e.g. {
            "field": "d1_brand_name",   # target field key
            "prompt": "...",            # the question text in answers_so_far["language"]
            "language": "es",           # the language the prompt is in
            "type": "text" | "choice",  # input kind
            "options": [{"value": "...", "label": "..."}, ...],  # for type == "choice"
            "allow_idk": True,          # the front door always offers an "I don't know" option
        }
    The front door owns the loop and enforces an 8-question cap independently of the agent.

translate_to_english(text, source_language) -> str | None
    Model-backed agents return an English translation of text. They MUST return None (never a
    fabricated translation) when they cannot translate. Callers short-circuit when
    source_language == "en"; agents that do not translate (SampleAgent, NoAgent) return None and
    the front door stores the Translation_Pending_Marker instead.
"""

# Sentinel returned by next_question when the interview data set is fully collected.
COMPLETE = "complete"


class Agent:
    id = "base"
    name = "Agent"

    def classify(self, complaint, memory=""):
        raise NotImplementedError

    def draft_report(self, complaint, row):
        raise NotImplementedError

    def follow_up_questions(self, row, missing):
        raise NotImplementedError

    def next_question(self, answers_so_far):
        raise NotImplementedError

    def translate_to_english(self, text, source_language):
        # Safe default: defer translation. The front door stores the Translation_Pending_Marker.
        return None

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

    def next_question(self, answers_so_far):
        # No adaptive loop: the front door renders a single fixed checklist instead.
        return COMPLETE

    def translate_to_english(self, text, source_language):
        return None

    def health(self):
        return {"ok": True, "label": "manual review only", "name": self.name, "ms": None}


UNREADABLE = {"decision": "NEEDS_INFO", "category": "NONE", "reason": "model output unreadable - human review",
              "deadline_days": 30, "missing_info": [], "confidence": 0}

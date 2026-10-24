"""Sample agent: pre-written results for the sample complaints, a small rule-based fallback for anything
else (e.g. a complaint typed into the intake form while in demo mode), and a short fake delay so the
console's loading states are visible. Returns exactly the shapes the local model agent returns."""
import os, re, time

from .base import Agent, COMPLETE
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

    # ------------------------------------------------------------------ reporter front door
    # The scripted Requirement-4 field set, in the order the interview collects it. Kept in
    # lockstep with interview.FIELD_ORDER; hard-coded here so the agent stays import-light and
    # makes zero outbound calls (Requirement 8.4). next_question walks this list and returns the
    # first field not yet in answers_so_far["asked"]; once every field has been asked it returns
    # the base COMPLETE sentinel (Requirements 8.8, 8.9).
    _NQ_ORDER = [
        "device_brand_name",
        "device_model",
        "lot_or_serial",
        "event_description",
        "patient_outcome",
        "device_malfunctioned",
        "event_date",
        "date_noticed",
        "follow_up_contact",
    ]

    # The two choice fields and their option values. Labels come from _NQ_STRINGS below.
    _NQ_CHOICE = {
        "patient_outcome": ["death", "hospitalisation", "injury", "none"],
        "device_malfunctioned": ["yes", "no"],
    }

    # Scripted prompts and choice-option labels for all four supported languages (Requirement 8.2).
    # Keyed [language][field] for prompts and [language]["options"][value] for option labels.
    # An unsupported language falls back to "en" (Requirement 8.3). All sample wording is generic
    # and carries no invented company/device/person names, so it stays fictional and reusable.
    _NQ_STRINGS = {
        "en": {
            "device_brand_name": "What is the brand name printed on the device?",
            "device_model": "What is the device model?",
            "lot_or_serial": "What is the lot number or serial number on the device?",
            "event_description": "In your own words, what happened?",
            "patient_outcome": "What happened to the patient?",
            "device_malfunctioned": "Did the device malfunction or stop working as expected?",
            "event_date": "On what date did the event happen?",
            "date_noticed": "On what date did you first notice the problem?",
            "follow_up_contact": "What is a phone number or email we can use to follow up?",
            "options": {
                "death": "Death",
                "hospitalisation": "Hospitalisation",
                "injury": "Injury",
                "none": "No harm to the patient",
                "yes": "Yes",
                "no": "No",
            },
        },
        "es": {
            "device_brand_name": "¿Cuál es la marca impresa en el dispositivo?",
            "device_model": "¿Cuál es el modelo del dispositivo?",
            "lot_or_serial": "¿Cuál es el número de lote o de serie del dispositivo?",
            "event_description": "Con sus propias palabras, ¿qué ocurrió?",
            "patient_outcome": "¿Qué le ocurrió al paciente?",
            "device_malfunctioned": "¿El dispositivo falló o dejó de funcionar como se esperaba?",
            "event_date": "¿En qué fecha ocurrió el evento?",
            "date_noticed": "¿En qué fecha notó el problema por primera vez?",
            "follow_up_contact": "¿Qué teléfono o correo podemos usar para dar seguimiento?",
            "options": {
                "death": "Muerte",
                "hospitalisation": "Hospitalización",
                "injury": "Lesión",
                "none": "Sin daño al paciente",
                "yes": "Sí",
                "no": "No",
            },
        },
        "pt": {
            "device_brand_name": "Qual é a marca impressa no dispositivo?",
            "device_model": "Qual é o modelo do dispositivo?",
            "lot_or_serial": "Qual é o número de lote ou de série do dispositivo?",
            "event_description": "Com suas próprias palavras, o que aconteceu?",
            "patient_outcome": "O que aconteceu com o paciente?",
            "device_malfunctioned": "O dispositivo falhou ou parou de funcionar como esperado?",
            "event_date": "Em que data o evento aconteceu?",
            "date_noticed": "Em que data você notou o problema pela primeira vez?",
            "follow_up_contact": "Qual telefone ou e-mail podemos usar para dar retorno?",
            "options": {
                "death": "Morte",
                "hospitalisation": "Hospitalização",
                "injury": "Lesão",
                "none": "Sem dano ao paciente",
                "yes": "Sim",
                "no": "Não",
            },
        },
        "ht": {
            "device_brand_name": "Ki mak ki ekri sou aparèy la?",
            "device_model": "Ki modèl aparèy la?",
            "lot_or_serial": "Ki nimewo lo oswa nimewo seri ki sou aparèy la?",
            "event_description": "Nan pwòp mo pa ou, kisa ki te pase?",
            "patient_outcome": "Kisa ki te rive pasyan an?",
            "device_malfunctioned": "Èske aparèy la te an pàn oswa li te sispann mache jan sa te dwe fèt?",
            "event_date": "Ki dat evènman an te pase?",
            "date_noticed": "Ki dat ou te premye remake pwoblèm nan?",
            "follow_up_contact": "Ki nimewo telefòn oswa imèl nou ka itilize pou kontakte ou?",
            "options": {
                "death": "Lanmò",
                "hospitalisation": "Entènman lopital",
                "injury": "Blesi",
                "none": "Pa gen domaj pou pasyan an",
                "yes": "Wi",
                "no": "Non",
            },
        },
    }

    def next_question(self, answers_so_far):
        """Scripted, offline next question for the reporter Front_Door.

        Walks the Requirement-4 field set in order and returns a question object for the first
        field not yet in ``answers_so_far["asked"]``; once every field has been asked, returns the
        base ``COMPLETE`` sentinel (Requirements 8.8, 8.9). The prompt and option labels are taken
        from the four-language string table in the reporter's language, falling back to English for
        any unsupported language code (Requirements 8.2, 8.3). Fully offline: zero network calls
        (Requirement 8.4); honours the shared fake delay via ``_wait()`` so the console's loading
        states stay visible, consistent with the other SampleAgent methods.
        """
        self._wait(0.5)

        language = (answers_so_far or {}).get("language")
        strings = self._NQ_STRINGS.get(language)
        if strings is None:
            language = "en"
            strings = self._NQ_STRINGS["en"]

        asked = set((answers_so_far or {}).get("asked") or [])
        for field in self._NQ_ORDER:
            if field in asked:
                continue
            question = {
                "field": field,
                "prompt": strings[field],
                "language": language,
                "allow_idk": True,
            }
            choices = self._NQ_CHOICE.get(field)
            if choices:
                question["type"] = "choice"
                question["options"] = [
                    {"value": value, "label": strings["options"][value]} for value in choices
                ]
            else:
                question["type"] = "text"
            return question

        # Every scripted field has been requested.
        return COMPLETE

    def translate_to_english(self, text, source_language):
        # The sample agent does not translate; the Front_Door stores the
        # Translation_Pending_Marker instead (Requirement 8.10).
        return None

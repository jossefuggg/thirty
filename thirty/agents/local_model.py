"""Local model agent: the hackathon pipeline's prompts and HTTP calls, moved here unchanged.

Talks to any OpenAI-compatible server (vLLM on the hackathon box): VIGIL_LLM_BASE (default
http://localhost:8000/v1), VIGIL_LLM_MODEL (auto-detected from /models when empty). Nothing leaves the
machine unless that URL points elsewhere.
"""
import json, os, re, time

import requests

from .base import Agent, UNREADABLE, COMPLETE

LLM_BASE = os.environ.get("VIGIL_LLM_BASE", "http://localhost:8000/v1")  # local vLLM (OpenAI-compatible)
LLM_MODEL = os.environ.get("VIGIL_LLM_MODEL", "")  # auto-detected if empty

CLASSIFY = """You are Vigil, a medical device complaint analyst for a manufacturer's quality team.
Apply FDA 21 CFR 803 (Medical Device Reporting).
This is a MANUFACTURER report: cite 21 CFR 803.50 (manufacturer reporting) — never 803.30 (user facilities).
A complaint is REPORTABLE if the information reasonably suggests the device:
- may have caused or contributed to a DEATH, or
- may have caused or contributed to a SERIOUS INJURY (life-threatening, permanent impairment, or needing medical/surgical intervention to prevent permanent damage), or
- MALFUNCTIONED and the malfunction would be likely to cause death or serious injury if it recurred.
Deadlines (Vigil computes them from your answer): 30 calendar days from awareness by default; 5 work days only
when remedial action is needed to prevent an unreasonable risk of substantial harm to the public.
Set "remedial_action_needed" to true ONLY if the complaint shows such a risk that needs action now (e.g. a defect
likely to recur in other units and seriously harm patients); otherwise false.
When unsure, lean toward REPORTABLE or NEEDS_INFO and say what is missing. Never discard a complaint.
Each "missing_info" item must be 2-4 words (e.g. "patient age", "lot number", "autopsy findings").
The examples only show the length: list the gaps that are actually missing from THIS complaint, and do not
list anything the complaint already states.

Complaint: {text}
Device: {device}   Event date: {event_date}   Received: {received}

Prior history for this device (long-term memory):
{memory}
Use history only to judge patterns and priority; base the decision on this complaint's facts.

Answer ONLY with JSON:
{{"decision": "REPORTABLE|NOT_REPORTABLE|NEEDS_INFO", "category": "DEATH|SERIOUS_INJURY|MALFUNCTION|NONE",
 "reason": "one sentence citing the rule", "remedial_action_needed": true or false, "missing_info": [], "confidence": 0-100}}"""

MDR_FIELDS = """You are Vigil. Fill the FDA MedWatch Form 3500A (mandatory reporting) fields for this medical device complaint.
STRICT RULE: never invent facts. Use only what the complaint states. Write "UNKNOWN" for anything not stated.
Only use company and device names that appear in the complaint data below. Never add or guess any other manufacturer, brand or model.
Deadline rule (21 CFR 803): 5 work days only when urgent remedial action is needed to prevent substantial harm to the public; otherwise 30 calendar days. Use the deadline given below; do not recalculate it.
Dates as YYYY-MM-DD.

Complaint: {text}
Device: {device}   Common name: {generic_name}   Product code: {product_code}
Manufacturer: {manufacturer}   Event date: {event_date}   Date received: {received}
Manufacturer narrative: {manufacturer_narrative}
Vigil decision: {decision} ({category})   Deadline: {deadline}   Missing information: {missing}

Extract D4 model, lot and serial numbers from the complaint AND the manufacturer narrative when present
(e.g. "MODEL #CAX500T12" -> D4_model "CAX500T12"). FDA redaction codes such as (B)(4) or (B)(6) mean the value
was redacted: write "REDACTED" for that field, never guess it.

Answer ONLY with JSON, all values strings except where a list is shown:
{{"A1_patient_identifier": "", "A2_age": "", "A3_sex": "", "A4_weight": "",
 "B1_event_type": "ADVERSE_EVENT|PRODUCT_PROBLEM|BOTH",
 "B2_outcomes": ["any of: Death, Life-threatening, Hospitalization (initial or prolonged), Disability or permanent damage, Congenital anomaly/birth defect, Required intervention to prevent permanent impairment/damage, Other serious (important medical event)"],
 "B3_date_of_event": "", "B5_event_description": "factual summary of the complaint",
 "D1_brand_name": "", "D2_common_device_name": "", "D2b_product_code": "", "D3_manufacturer": "",
 "D4_model": "", "D4_lot": "", "D4_serial": "",
 "G4_date_received_by_manufacturer": "",
 "H1_type_of_reportable_event": "DEATH|SERIOUS_INJURY|MALFUNCTION",
 "H3_device_evaluated": "YES|NO|UNKNOWN",
 "H10_manufacturer_narrative": "factual narrative, no speculation",
 "follow_up_questions": ["at most 5 specific questions, most important first, to close the gaps, e.g. patient age, serial number, treatment given, device available for return"]}}"""

ASK = """You are a medical device complaint investigator at the manufacturer. A customer complaint needs
more information before the FDA report (21 CFR 803) can be completed.

Complaint #{id} ({decision}, {category}) about device: {device}
Complaint text: {text}
Information flagged as missing: {missing}

Write 3 to 5 specific questions to send the customer, most important first. Plain language a patient or
family member understands, no jargon, no legal terms, one question each, about THIS complaint's details.
Then write a short, polite, ready-to-send message to the customer (2-3 sentences) explaining that we are
looking into their report and need a few details; do not admit fault and do not promise outcomes.
Answer ONLY with JSON: {{"questions": ["..."], "message": "..."}}"""


NEXT_Q = """You are Vigil, helping a person report a medical device problem for an FDA Form 3500A (21 CFR 803).
You ask ONE short question at a time, in plain language suited to the reporter, in their own language.
STRICT RULE: never invent facts. Ask only for information the reporter can provide; do not guess answers.

Reporter type: {reporter_type}
Reporter language (write the question in THIS language): {language}
Device: {device}
Answers collected so far (field: value): {answers}
Fields already asked (do not ask these again): {asked}

The full data set to collect (Requirement 4) is exactly these fields:
- device_brand_name: the brand name printed on the device
- device_model: the device model
- lot_or_serial: the lot number or serial number
- event_description: a free-text description of what happened
- patient_outcome: exactly one of death, hospitalisation, injury, or none
- device_malfunctioned: one of yes, no, or UNKNOWN
- event_date: the date the event happened
- date_noticed: the date the problem was noticed
- follow_up_contact: a contact for follow-up

Pick the single most useful field that is NOT already in the answers or the asked list and ask for it.
Write the "prompt" text in the reporter's language and in plain words appropriate to the reporter type.

Answer ONLY with JSON, exactly one of these two shapes:
- a single question object:
  {{"field": "<one of the field keys above>", "prompt": "<the question in {language}>",
   "language": "{language}", "type": "text" or "choice",
   "options": [{{"value": "<value>", "label": "<label in {language}>"}}],
   "allow_idk": true}}
  (omit "options" for type "text")
- OR, when the whole data set above has already been requested:
  {{"complete": true}}"""

TRANSLATE = """Translate the following text from {source_language} to English.
Return ONLY the translation text, nothing else. Do not add notes, quotes, or explanations.
If you cannot translate it, return exactly the token CANNOT_TRANSLATE.

Text:
{text}"""


def deadline_text(days):
    return "5 work days (urgent remedial action needed)" if str(days) == "5" else "30 calendar days"


def _headers(api_key):
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def model_name(base_url=None, model=None, api_key=""):
    """The model id to use: the configured one, else the first the server lists (cached on the module default)."""
    global LLM_MODEL
    if model:
        return model
    if base_url and base_url.rstrip("/") != LLM_BASE.rstrip("/"):
        r = requests.get(f"{base_url.rstrip('/')}/models", timeout=10, headers=_headers(api_key))
        return r.json()["data"][0]["id"]
    if not LLM_MODEL:
        r = requests.get(f"{LLM_BASE}/models", timeout=10, headers=_headers(api_key))
        LLM_MODEL = r.json()["data"][0]["id"]
    return LLM_MODEL


def llm(prompt, max_tokens=600, temperature=0.1, base_url=None, model=None, api_key="", timeout=180):
    base = (base_url or LLM_BASE).rstrip("/")
    r = requests.post(f"{base}/chat/completions", timeout=timeout, headers=_headers(api_key), json={
        "model": model_name(base, model, api_key), "temperature": temperature, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
    })
    r.raise_for_status()
    out = r.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def _json(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    return json.loads(m.group(0))


def interpret_next_question(obj, language):
    """Turn a parsed next_question JSON object into a question dict or COMPLETE.

    Shared by LocalModelAgent and ClaudeAgent so both agents treat model output
    identically. Returns the sentinel COMPLETE when the object signals completion
    or is not a usable question; otherwise a normalized question dict (allow_idk
    forced True, language defaulted to the reporter's language). Never raises.
    """
    if not isinstance(obj, dict):
        return COMPLETE
    if obj.get("complete") is True:
        return COMPLETE
    field = obj.get("field")
    prompt = obj.get("prompt")
    qtype = obj.get("type") or "text"
    if not (isinstance(field, str) and field and isinstance(prompt, str) and prompt and isinstance(qtype, str) and qtype):
        return COMPLETE
    question = {
        "field": field,
        "prompt": prompt,
        "language": obj.get("language") or language or "en",
        "type": qtype,
        "allow_idk": True,
    }
    if qtype == "choice" and isinstance(obj.get("options"), list):
        question["options"] = obj["options"]
    return question


class LocalModelAgent(Agent):
    id = "local"
    name = "Local model agent"

    def __init__(self, base_url=None, model=None, api_key="", timeout=180):
        self.base_url = (base_url or LLM_BASE).rstrip("/")
        self.model, self.api_key, self.timeout = model or LLM_MODEL, api_key, timeout

    def _llm(self, prompt, max_tokens, temperature=0.1):
        return llm(prompt, max_tokens, temperature, base_url=self.base_url, model=self.model, api_key=self.api_key, timeout=self.timeout)

    def classify(self, complaint, memory=""):
        raw = self._llm(CLASSIFY.format(memory=memory or "No prior complaints on this device family.", **complaint), 400,
                        temperature=0)  # same complaint -> same decision and deadline on every run
        try:
            return _json(raw)
        except Exception:
            return dict(UNREADABLE)

    def draft_report(self, complaint, row):
        raw = self._llm(MDR_FIELDS.format(decision=row["decision"], category=row["category"],
                                          deadline=deadline_text(row.get("deadline_days")), missing=row["missing"] or "none listed",
                                          **{"generic_name": "", "product_code": "", "manufacturer": "",
                                             "manufacturer_narrative": "none", **complaint}), 1500)
        try:
            return _json(raw)
        except Exception:
            return {"H10_manufacturer_narrative": "Model output unreadable - complete all fields manually."}

    def follow_up_questions(self, row, missing):
        raw = self._llm(ASK.format(id=row["id"], decision=row["decision"], category=row["category"], device=row["device"],
                                   text=row.get("text") or "", missing="; ".join(missing) or "none listed"), 700, temperature=0.2)
        j = _json(raw)
        qs = [str(q).strip() for q in j.get("questions") or [] if str(q).strip()][:5]
        return qs, str(j.get("message") or "").strip()

    def next_question(self, answers_so_far):
        """One adaptive interview question, or COMPLETE. Any failure -> COMPLETE (safe termination)."""
        language = (answers_so_far or {}).get("language") or "en"
        try:
            raw = self._llm(NEXT_Q.format(
                reporter_type=(answers_so_far or {}).get("reporter_type") or "",
                language=language,
                device=(answers_so_far or {}).get("device") or "UNKNOWN",
                answers=(answers_so_far or {}).get("answers") or {},
                asked=(answers_so_far or {}).get("asked") or [],
            ), 400, temperature=0.2)
            return interpret_next_question(_json(raw), language)
        except Exception:
            return COMPLETE

    def translate_to_english(self, text, source_language):
        """English translation of text, or None. Never fabricates: None on any failure/CANNOT_TRANSLATE."""
        if not text or not str(text).strip():
            return None
        if source_language == "en":
            return text
        try:
            out = (self._llm(TRANSLATE.format(source_language=source_language, text=text), 1000) or "").strip()
            if not out or out == "CANNOT_TRANSLATE":
                return None
            return out
        except Exception:
            return None

    def health(self):
        try:
            name = self.model or requests.get(f"{self.base_url}/models", timeout=3, headers=_headers(self.api_key)).json()["data"][0]["id"]
            t0 = time.perf_counter()
            r = requests.post(f"{self.base_url}/chat/completions", timeout=15, headers=_headers(self.api_key), json={
                "model": name, "max_tokens": 1, "temperature": 0, "messages": [{"role": "user", "content": "ping"}],
                "chat_template_kwargs": {"enable_thinking": False}})
            r.raise_for_status()
            ms = round((time.perf_counter() - t0) * 1000)
            return {"ok": True, "name": name.split("/")[-1], "ms": ms, "label": f"{name.split('/')[-1]} · {ms} ms"}
        except Exception as e:
            return {"ok": False, "name": self.name, "ms": None, "label": f"offline ({type(e).__name__})"}

#!/usr/bin/env python3
"""
Vigil - medical device complaint agent (100% local).

Layer 1 (code):   priority score, completeness, duplicates, distress, spike detection
Layer 2 (AI):     every complaint -> reportable / not / needs info (21 CFR 803), deadline
Layer 3 (agent):  draft MDR (Form 3500A sections) for reportable/unsure, Telegram alert
Layer 4 (human):  'approve <id>' in Telegram; every decision logged to decisions.csv

Usage:
  python3 vigil.py test                      # check model + Telegram
  python3 vigil.py replay --limit 20 --delay 5     # replay Philips complaints in date order
  python3 vigil.py replay --file demo_complaints.txt  # one illustrative complaint per line
  python3 vigil.py replay --csv demo_set.csv --delay 5  # curated MAUDE-format CSV, in file order
  python3 vigil.py replay --csv demo_set.csv --limit 3 --step  # presenter mode: Enter for the next complaint
  python3 vigil.py sync                      # pull 'approve ID' from the OpenClaw sandbox skill (skill/vigil)
  python3 vigil.py import-history            # build history.csv (long-term memory) from hackathon_data, no model
  python3 vigil.py reset                     # clean slate: decisions.csv, reports/, outbox.txt, sandbox copies, group session
  python3 vigil.py listen                    # standalone Telegram commands (only if OpenClaw is NOT running)
"""
import argparse, contextlib, csv, datetime as dt, fcntl, json, os, re, shutil, subprocess, sys, tempfile, time
from collections import Counter, defaultdict, deque

import requests

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from fpdf.fonts import FontFace
except Exception:
    FPDF = None
    # fpdf2 lives in ~/hackathon/venv; a plain `python3 vigil.py` would silently skip every MDR PDF.
    _venv_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "venv", "bin", "python")
    if __name__ == "__main__" and os.path.exists(_venv_py) and not sys.prefix.startswith(os.path.dirname(os.path.dirname(_venv_py))):
        os.execv(_venv_py, [_venv_py, *sys.argv])
    print("WARNING: fpdf2 not installed - MDR PDFs will NOT be generated (pip install fpdf2 in ~/hackathon/venv)")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # ~/hackathon
DATA = os.path.join(ROOT, "hackathon_data")
LOG = os.path.join(HERE, "decisions.csv")
REPORTS = os.path.join(HERE, "reports")

# ---------------------------------------------------------------- config
def load_env():
    for p in [os.path.join(ROOT, "secrets.env"), os.path.join(HERE, "secrets.env")]:
        if os.path.exists(p):
            for line in open(p):
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)
load_env()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
LLM_BASE = os.environ.get("VIGIL_LLM_BASE", "http://localhost:8000/v1")  # local vLLM (OpenAI-compatible)
LLM_MODEL = os.environ.get("VIGIL_LLM_MODEL", "")  # auto-detected if empty

# ---------------------------------------------------------------- layer 1: rules
RED_FLAGS = {
    "death": 10, "died": 10, "expired": 10, "fatal": 10, "deceased": 10,
    "cardiac arrest": 9, "unconscious": 8, "resuscitat": 8, "icu": 7, "hospital": 6,
    "emergency": 6, "ER": 5, "surgery": 6, "burn": 6, "fire": 7, "smoke": 6, "explod": 7,
    "choking": 7, "could not breathe": 8, "couldn't breathe": 8, "shortness of breath": 6,
    "bleeding": 6, "injur": 5, "overdose": 7, "shock": 6,
    "foam": 4, "particle": 4, "black dust": 4, "debris": 3, "headache": 2, "cough": 2,
    "stopped working": 3, "alarm": 2, "failure": 3, "malfunction": 3,
}
EVENT_WEIGHT = {"Death": 10, "Injury": 6, "Malfunction": 2}

# Whole-word matching (substrings gave fake points: 'er' inside 'every' / 'mother').
# Stems match any word starting with them (resuscitated, injury, exploded, particles, hospitalized);
# other keywords allow plain inflections (deaths, burns, coughing). "ER" is case-sensitive (ER, ER visit).
_STEMS = {"resuscitat", "injur", "explod", "particle", "hospital"}
_FLAG_RE = {k: re.compile(r"\bER\b") if k == "ER" else
            re.compile(r"\b" + re.escape(k) + (r"\w*" if k in _STEMS else r"(?:s|es|ed|ing)?") + r"\b", re.I)
            for k in RED_FLAGS}


def red_flag_hits(text):
    """[(keyword, weight)] for each red flag present in the text, as whole words."""
    return [(k, w) for k, w in RED_FLAGS.items() if _FLAG_RE[k].search(text or "")]

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
except Exception:
    _vader = None
try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None


def distress_score(text):
    """0-5. Only ever used to RAISE priority."""
    s = 0
    if _vader:
        neg = _vader.polarity_scores(text)["neg"]
        s += min(3, int(neg * 10))
    s += min(1, text.count("!") // 2)
    if re.search(r"\b(scared|terrified|panic|screaming|help)\b", text, re.I):
        s += 1
    return min(5, s)


def priority(c):
    score = sum(w for _, w in red_flag_hits(c["text"]))
    score += EVENT_WEIGHT.get(c.get("event_type") or "", 0)
    if "death" in (c.get("outcomes") or "").lower():
        score += 10
    elif c.get("outcomes"):
        score += 4
    d = distress_score(c["text"] or "")
    score += d * 2  # distress pushes UP only
    level = "URGENT" if score >= 15 else "HIGH" if score >= 8 else "NORMAL"
    return score, level, d


def missing_fields(c):
    miss = []
    if not c.get("device"): miss.append("device model")
    if not c.get("event_date"): miss.append("event date")
    if not c.get("outcomes") and not c.get("event_type"): miss.append("patient outcome")
    if len((c.get("text") or "").split()) < 8: miss.append("detailed description")
    return miss


_recent = deque(maxlen=300)
def duplicate_of(c):
    if not fuzz:
        return None
    for prev in _recent:
        if prev["device"] == c["device"] and fuzz.token_set_ratio(prev["text"], c["text"]) >= 92:
            return prev["id"]
    _recent.append(c)
    return None


# ---------------------------------------------------------------- device family + failure mode (no model)
# Grouping key for memory, spike alerts and the console: brand/common name -> product family.
FAMILIES = [("DREAMSTATION", r"DREAM\s?STATION"), ("SYSTEM ONE", r"SYSTEM\s?ONE"), ("REMSTAR", r"REMSTAR"),
            ("TRILOGY", r"TRILOGY"), ("MINIMED", r"MINIMED|\bMMT-|\b[67][5-9]0G\b"), ("HEARTWARE", r"HEARTWARE|\bHVAD\b"),
            ("HEARTMATE", r"HEARTMATE"), ("DEXCOM", r"DEXCOM"), ("IMPELLA", r"IMPELLA"), ("OMNIPOD", r"OMNIPOD"),
            ("T:SLIM", r"T:SLIM|TANDEM"), ("LIFEVEST", r"LIFEVEST"), ("ALARIS", r"ALARIS")]
MAKER_WORDS = {"PHILIPS", "RESPIRONICS", "PHILIPS-RESPIRONICS", "MEDTRONIC", "THORATEC"}


def device_family(device, generic=""):
    t = f"{device or ''} {generic or ''}".upper()
    for fam, pat in FAMILIES:
        if re.search(pat, t):
            return fam
    words = [w for w in re.split(r"[^A-Z0-9:+.-]+", (device or generic or "").upper()) if w and w not in MAKER_WORDS]
    return words[0] if words else "UNKNOWN"


# Fixed failure-mode list, most severe first: FDA product_problems terms decide; free-text keywords are the
# fallback (most MAUDE rows only say "Adverse Event Without Identified Device or Use Problem").
FAILURE_MODES = [
    ("electrical/shock/fire", ["Electrical /Electronic Property Problem", "Circuit Failure", "Overheating of Device",
                               "Fire", "Smoking", "Sparking", "Burn of Device or Device Component", "Melted",
                               "Short Circuit", "Arcing"],
     r"\b(?:fire|smoke|smoking|spark\w*|electric(?:al)? shock|shocked|overheat\w*|melt\w*|burn(?:t|ed|ing)? (?:smell|odor))"),
    ("material degradation/particles", ["Degraded", "Particulates", "Material Integrity Problem",
                                        "Material Fragmentation", "Material Disintegration"],
     r"\b(?:foam|particle\w*|particulate\w*|black dust|debris|degrad\w*|disintegrat\w*)"),
    ("alarm failure", ["Device Alarm System", "No Audible Alarm", "Alarm Not Visible", "Failure to Alarm",
                       "Inaudible or Unclear Audible Prompt/Feedback"],
     r"\balarm\w* (?:did not|didn't|failed|not audible|never)|\bno alarm|\bwithout (?:an )?alarm"),
    ("power/shutdown", ["Battery Problem", "Power Problem", "Complete Loss of Power", "Failure to Charge",
                        "Charging Problem", "Premature Discharge of Battery", "Failure to Power Up",
                        "Unexpected Shutdown", "Pumping Stopped", "Premature End-of-Life Indicator",
                        "Intermittent Loss of Power", "Loss of Power"],
     r"\b(?:batter\w*|power\w*|shut ?down|shut off|shuts off|turned off|stopped working|won't turn on)"),
    ("pressure/airflow", ["Pumping Problem", "Obstruction of Flow", "Increase in Suction", "Infusion or Flow Problem",
                          "Insufficient Flow or Under Infusion", "Restricted Flow rate", "Excess Flow or Over-Infusion",
                          "Increase in Pressure", "Decrease in Pressure", "Gas/Air Leak", "Failure to Pump",
                          "Low Pressure", "High Pressure"],
     r"\b(?:low pressure|high pressure|pressure (?:drop|loss|too)|air ?flow|suction|occlu\w*|obstruct\w*|under.?infus\w*|over.?infus\w*)"),
    ("contamination", ["Contamination", "Contamination /Decontamination Problem",
                       "Device Contamination with Chemical or Other Material", "Microbial Contamination of Device"],
     r"\b(?:contaminat\w*|water ingress|mold|mould|dirt\w*)"),
    ("software", ["Application Program Problem", "Computer Software Problem", "Data Problem",
                  "Date/Time-Related Software Problem", "Unintended Application Program Shut Down",
                  "Wireless Communication Problem", "Communication or Transmission Problem",
                  "Device Difficult to Program or Calibrate", "Incorrect, Inadequate or Imprecise Result or Readings",
                  "Failure to Recalibrate", "Low Readings", "High Readings", "Incorrect Measurement",
                  "No Display/Image", "Display or Visual Feedback Problem", "Erratic or Intermittent Display"],
     r"\b(?:software|firmware|error code|app\b|reading\w*|display|bluetooth|sensor error)"),
    ("mechanical", ["Break", "Fracture", "Crack", "Material Twisted/Bent", "Material Split, Cut or Torn",
                    "Material Deformation", "Material Rupture", "Mechanical Problem", "Connection Problem",
                    "Disconnection", "Detachment of Device or Device Component", "Loose or Intermittent Connection",
                    "Key or Button Unresponsive/not Working", "Fluid/Blood Leak", "Leak/Splash", "Device Fell",
                    "Device Dislodged or Dislocated", "Migration", "Noise, Audible", "Vibration"],
     r"\b(?:broke\w*|break\w*|crack\w*|fractur\w*|disconnect\w*|leak\w*|loose|detach\w*|noise|noisy)"),
]
_FM_TERMS = [(m, {t.lower() for t in terms}, re.compile(rx, re.I)) for m, terms, rx in FAILURE_MODES]


def failure_mode(product_problems="", text=""):
    probs = {p.strip().lower() for p in (product_problems or "").split(";") if p.strip()}
    for mode, terms, _ in _FM_TERMS:
        if probs & terms:
            return mode
    t = re.sub(r"(?i)(continuous |bi-?level )?positive airway pressure", " ", text or "")  # device name, not a problem
    for mode, _, rx in _FM_TERMS:
        if rx.search(t):
            return mode
    return "other"


_by_device = defaultdict(list)
def spike(c):
    """Alert when a device gets >=5 complaints in 30 days and >=3x its previous 30-day count."""
    try:
        d = dt.datetime.strptime(c["received"], "%Y%m%d").date()
    except Exception:
        return None
    key = device_family(c.get("device"), c.get("generic_name"))
    hist = _by_device[key]
    hist.append(d)
    last30 = [x for x in hist if (d - x).days < 30]
    prev30 = [x for x in hist if 30 <= (d - x).days < 60]
    if len(last30) >= 5 and len(last30) >= 3 * max(1, len(prev30)) and len(last30) in (5, 10, 20, 40):
        return f"{key}: {len(last30)} complaints in 30 days (previous 30 days: {len(prev30)})"
    return None

# ---------------------------------------------------------------- layer 2/3: local AI
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


def model_name():
    global LLM_MODEL
    if not LLM_MODEL:
        r = requests.get(f"{LLM_BASE}/models", timeout=10)
        LLM_MODEL = r.json()["data"][0]["id"]
    return LLM_MODEL


def llm(prompt, max_tokens=600, temperature=0.1):
    r = requests.post(f"{LLM_BASE}/chat/completions", timeout=180, json={
        "model": model_name(), "temperature": temperature, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
    })
    r.raise_for_status()
    out = r.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def classify(c, memory=""):
    raw = llm(CLASSIFY.format(memory=memory or "No prior complaints on this device family.", **c), 400,
              temperature=0)  # same complaint -> same decision and deadline on every run
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"decision": "NEEDS_INFO", "category": "NONE", "reason": "model output unreadable - human review",
                "deadline_days": 30, "missing_info": [], "confidence": 0}

# 5-day trigger words: fire, smoke, explosion, electrical shock to a patient (21 CFR 803.53 remedial-action cases).
_FIVE_DAY = re.compile(r"\b(?:fire|flames?|caught fire|smok(?:e|ed|ing)|explo(?:de|ded|des|ding|sion|sions)|"
                       r"electric(?:al)? shock\w*|electrocut\w*|shocked)\b", re.I)


def deadline_days(c, res):
    """Deterministic deadline: None if NOT_REPORTABLE; 5 (work days) only for fire / smoke / explosion / electrical
    shock in the complaint, or when the model says remedial action is needed; otherwise 30 (calendar days)."""
    if res.get("decision") == "NOT_REPORTABLE":
        return None
    text = f"{c.get('text') or ''} {c.get('manufacturer_narrative') or ''}"
    remedial = str(res.get("remedial_action_needed")).strip().lower() == "true"
    return 5 if _FIVE_DAY.search(text) or remedial else 30

# ---------------------------------------------------------------- Telegram
# Telegram is the only network dependency. It must never crash the pipeline:
# retry, then park the message in outbox.txt and carry on.
OUTBOX = os.path.join(HERE, "outbox.txt")
TG_RETRIES, TG_WAIT = 3, 3


def _outbox(kind, body):
    try:
        with open(OUTBOX, "a", encoding="utf-8") as f:
            f.write(f"===== {dt.datetime.now().isoformat(timespec='seconds')} {kind}\n{body}\n\n")
    except Exception as e:
        print(f"WARNING: could not write outbox: {e}")


def _tg_call(method, timeout, path=None, **kw):
    """POST to the Telegram API: 1 try + TG_RETRIES retries, TG_WAIT s apart. Returns error text or None."""
    err = None
    for attempt in range(1 + TG_RETRIES):
        if attempt: time.sleep(TG_WAIT)
        try:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/{method}"
            if path:  # re-open each attempt so a retry never sends an exhausted file handle
                with open(path, "rb") as f:
                    r = requests.post(url, timeout=timeout, **kw,
                                      files={"document": (os.path.basename(path), f, "application/pdf")})
            else:
                r = requests.post(url, timeout=timeout, **kw)
            if r.ok:
                return None
            err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    return err


def tg(text, reply_markup=None):
    if not (TG_TOKEN and TG_CHAT):
        print("[telegram off]\n" + text)
        return
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for n, chunk in enumerate(chunks):
        body = {"chat_id": TG_CHAT, "text": chunk}
        if reply_markup and n == len(chunks) - 1:  # buttons go under the last chunk
            body["reply_markup"] = reply_markup
        err = _tg_call("sendMessage", 20, json=body)
        if err:
            print(f"WARNING: Telegram sendMessage failed after {1 + TG_RETRIES} attempts ({err}); saved to {OUTBOX}")
            _outbox("sendMessage", chunk)


def alert_buttons(cid, decision):
    """Inline buttons that pre-fill the chat box (switch_inline_query_current_chat): OpenClaw owns bot updates,
    so callback_data would never reach Vigil; the prefilled text goes to the OpenClaw vigil skill instead."""
    def b(label, q): return {"text": label, "switch_inline_query_current_chat": q}
    rows = []
    if decision in ("REPORTABLE", "NEEDS_INFO"):
        rows.append([b("✅ Approve", f"approve {cid}"), b("❓ Request info", f"need info {cid}")])
    rows.append([b("📋 What's due", "what's due in the next 31 days?"), b("📊 Status", "status")])
    return {"inline_keyboard": rows}


def tg_doc(path, caption=""):
    if not (TG_TOKEN and TG_CHAT):
        print(f"[telegram off] document: {path}")
        return
    err = _tg_call("sendDocument", 60, path=path, data={"chat_id": TG_CHAT, "caption": caption[:1000]})
    if err:
        print(f"WARNING: Telegram sendDocument failed after {1 + TG_RETRIES} attempts ({err}); saved to {OUTBOX}")
        _outbox("sendDocument", f"file: {path}\ncaption: {caption}")

# ---------------------------------------------------------------- MDR PDF (FDA Form 3500A draft)
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

B2_OPTIONS = ["Death", "Life-threatening", "Hospitalization (initial or prolonged)", "Disability or permanent damage",
              "Congenital anomaly/birth defect", "Required intervention to prevent permanent impairment/damage",
              "Other serious (important medical event)"]
FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def deadline_text(days):
    return "5 work days (urgent remedial action needed)" if str(days) == "5" else "30 calendar days"


def mdr_fields(c, row):
    raw = llm(MDR_FIELDS.format(decision=row["decision"], category=row["category"],
                                deadline=deadline_text(row.get("deadline_days")), missing=row["missing"] or "none listed",
                                **{"generic_name": "", "product_code": "", "manufacturer": "",
                                   "manufacturer_narrative": "none", **c}), 1500)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        f = json.loads(m.group(0))
    except Exception:
        f = {"H10_manufacturer_narrative": "Model output unreadable - complete all fields manually."}
    # Set by Vigil, not the model: today's date and the report type that matches the computed deadline.
    f["B4_date_of_report"] = dt.date.today().isoformat()
    f["G7_report_type"] = "5-day" if str(row.get("deadline_days")) == "5" else "30-day"
    f["H3_device_evaluated"] = device_evaluated(c) or f.get("H3_device_evaluated") or "UNKNOWN"
    # Replay treats each complaint as received today (the deadline clock starts at awareness).
    orig = c.get("received") or ""
    orig = f"{orig[:4]}-{orig[4:6]}-{orig[6:8]}" if re.fullmatch(r"\d{8}", orig) else (orig or "UNKNOWN")
    f["G4_date_received_by_manufacturer"] = f"{row.get('awareness') or dt.date.today().isoformat()}"
    f["G4_note"] = f"(original FDA receipt: {orig})"
    return f


_NOT_EVAL = re.compile(r"not (?:yet )?(?:been )?(?:returned|evaluated|available for (?:evaluation|return))|"
                       r"no device (?:was )?returned|unable to (?:evaluate|retrieve)|discarded|"
                       r"(?:device|it) (?:was|has) not (?:yet )?(?:been )?(?:returned|received)", re.I)
_EVAL = re.compile(r"returned to the manufacturer|was (?:returned|received) (?:for|and)|was evaluated|"
                   r"investigation laborator|visually inspected|(?:tested|inspected|analy[sz]ed) the device|"
                   r"device (?:was|were) (?:tested|inspected|analy[sz]ed)|event log was reviewed", re.I)


def device_evaluated(c):
    """H3 from the complaint + manufacturer narrative: 'NO' if not returned/evaluated, 'YES' if evaluated, else None."""
    t = f"{c.get('text') or ''} {c.get('manufacturer_narrative') or ''}"
    if _NOT_EVAL.search(t): return "NO"  # checked first: "has not yet returned to the manufacturer"
    if _EVAL.search(t): return "YES"
    return None


def _v(f, k):
    v = f.get(k)
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    v = str(v).strip() if v not in (None, "") else "UNKNOWN"
    return v.replace("_", " ") if k in ("B1_event_type", "H1_type_of_reportable_event") else v


def _checks(selected, options):
    sel = {s.strip().lower() for s in selected}
    return "   ".join(("[X] " if o.lower() in sel else "[  ] ") + o for o in options)


def render_mdr_pdf(c, row, f):
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"MDR_{c['id']}.pdf")
    due = row.get("due_date") or "n/a"

    class PDF(FPDF):
        def header(self):
            self.set_font(FONT, "B", 9)
            self.set_text_color(90)
            self.cell(0, 5, f"VIGIL   |   Complaint #{c['id']}   |   Due: {due}", align="L")
            self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_draw_color(0); self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(2); self.set_text_color(0)

        def footer(self):
            self.set_y(-12)
            self.set_font(FONT, "", 8)
            self.set_text_color(90)
            self.cell(0, 5, "Generated locally on Dell Pro Max GB10, no data left the device", align="C")

    pdf = PDF(format="Letter")
    if os.path.exists(f"{FONT_DIR}/DejaVuSans.ttf"):
        pdf.add_font("DejaVu", "", f"{FONT_DIR}/DejaVuSans.ttf")
        pdf.add_font("DejaVu", "B", f"{FONT_DIR}/DejaVuSans-Bold.ttf")
        FONT = "DejaVu"
    else:
        FONT = "Helvetica"
    pdf.set_margins(14, 12, 14)
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()

    pdf.set_font(FONT, "B", 14)
    pdf.cell(0, 7, "MEDWATCH FDA Form 3500A, Mandatory Reporting", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(FONT, "B", 10)
    pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 6, "DRAFT for human review", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0)
    pdf.set_font(FONT, "", 8)
    pdf.cell(0, 5, f"Vigil decision: {row['decision']} ({row['category']}), confidence {row['confidence']}%   "
                   f"|   Priority: {row['priority']}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    def section(title, rows):
        pdf.set_font(FONT, "", 8)
        with pdf.table(col_widths=(52, 136), line_height=4.6, padding=1.2, text_align="LEFT", first_row_as_headings=True,
                       headings_style=FontFace(emphasis="BOLD", size_pt=9, fill_color=(225, 225, 225))) as t:
            t.row().cell(title, colspan=2)
            for label, val in rows:
                r = t.row()
                r.cell(label, style=FontFace(emphasis="BOLD"))
                r.cell(val)
        pdf.ln(2.5)

    section("A. PATIENT INFORMATION", [
        ("1. Patient identifier", _v(f, "A1_patient_identifier")),
        ("2. Age", _v(f, "A2_age")),
        ("3. Sex", _v(f, "A3_sex")),
        ("4. Weight", _v(f, "A4_weight")),
    ])
    b1 = _v(f, "B1_event_type").upper()
    section("B. ADVERSE EVENT OR PRODUCT PROBLEM", [
        ("1. Check all that apply", _checks([o for o in ("Adverse event", "Product problem")
                                             if b1 == "BOTH" or b1.startswith(o.split()[0].upper())],
                                            ["Adverse event", "Product problem"])),
        ("2. Outcome attributed to adverse event", _checks(f.get("B2_outcomes") or [], B2_OPTIONS)),
        ("3. Date of event", _v(f, "B3_date_of_event")),
        ("4. Date of this report", _v(f, "B4_date_of_report")),
        ("5. Describe event or problem", _v(f, "B5_event_description")),
    ])
    section("D. SUSPECT MEDICAL DEVICE", [
        ("1. Brand name", _v(f, "D1_brand_name")),
        ("2a. Common device name", _v(f, "D2_common_device_name")),
        ("2b. Procode", _v(f, "D2b_product_code")),
        ("3. Manufacturer name", _v(f, "D3_manufacturer")),
        ("4. Model # / Lot # / Serial #",
         f"Model: {_v(f, 'D4_model')}   Lot: {_v(f, 'D4_lot')}   Serial: {_v(f, 'D4_serial')}"),
    ])
    section("G. ALL MANUFACTURERS", [
        ("4. Date received by manufacturer", f"{_v(f, 'G4_date_received_by_manufacturer')}   {f.get('G4_note', '')}"),
        ("7. Type of report", _checks([f["G7_report_type"]], ["5-day", "30-day"])),
    ])
    h1 = _v(f, "H1_type_of_reportable_event").upper()
    qs = (f.get("follow_up_questions") or [])[:5]
    section("H. DEVICE MANUFACTURERS ONLY", [
        ("1. Type of reportable event", _checks([o for o in ("Death", "Serious injury", "Malfunction")
                                                 if o.upper() == h1], ["Death", "Serious injury", "Malfunction"])),
        ("3. Device evaluated by manufacturer?", _checks([_v(f, "H3_device_evaluated").capitalize()],
                                                          ["Yes", "No", "Unknown"])),
        ("10. Additional manufacturer narrative", _v(f, "H10_manufacturer_narrative")),
        ("10. Follow-up questions", "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1)) or "None"),
    ])
    pdf.set_font(FONT, "", 7)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 3.5, "Fields marked UNKNOWN were not stated in the complaint and must be obtained before submission. "
                           "This draft is not an FDA submission; a qualified reviewer must verify every field.")
    pdf.output(path)
    return path


def make_mdr(c, row):
    """Draft Form 3500A PDF for a REPORTABLE / NEEDS_INFO complaint. Returns the file path, or None."""
    if FPDF is None:
        print("fpdf2 not installed - skipping MDR PDF")
        return None
    return render_mdr_pdf(c, row, mdr_fields(c, row))

# ---------------------------------------------------------------- log
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text",
          "product_code", "memory", "failure_mode"]

# replay (append) and sync (read-modify-write) run as separate processes: every access to decisions.csv
# holds an exclusive flock on decisions.csv.lock. Re-entrant within a process, so write_log() can run
# inside a caller's `with log_lock():` read-modify-write block.
_lock_depth, _lock_fd = 0, None

@contextlib.contextmanager
def log_lock():
    global _lock_depth, _lock_fd
    if _lock_depth == 0:
        _lock_fd = open(LOG + ".lock", "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX)
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if _lock_depth == 0:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()

def log(row):
    with log_lock():
        if os.path.exists(LOG) and next(csv.reader(open(LOG)), None) != FIELDS:
            write_log(read_log())  # older header: rewrite once with the current columns before appending
        new = not os.path.exists(LOG)
        with open(LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new: w.writeheader()
            w.writerow(row)
        push_log()

def read_log():
    """One row per complaint id: a re-processed complaint (e.g. replayed twice without reset) replaces its
    earlier row, so /due, /status, the console and sync never double-count."""
    with log_lock():
        if not os.path.exists(LOG): return []
        latest = {}
        for r in csv.DictReader(open(LOG)):
            latest[r["id"]] = r  # keeps first-seen order, latest content
        return list(latest.values())

def write_log(rows):
    with log_lock():
        with open(LOG, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
        push_log()

# ---------------------------------------------------------------- OpenClaw sandbox sync (vigil skill)
# The sandbox gets a read-only copy of decisions.csv; the skill appends 'approve <id>' to approvals.csv there.
# Host decisions.csv stays the source of truth: push after every write, pull approvals with `vigil.py sync`.
SANDBOX = os.environ.get("VIGIL_SANDBOX", "my-assistant")
SANDBOX_DIR = "/sandbox/vigil"
TG_SESSION = os.environ.get("VIGIL_TG_SESSION", "agent:main:telegram:group:-5193984181")  # OpenClaw group chat

# nemoclaw takes its own host lock (~/.nemoclaw-portable-host.lock) and gives up after 120 retries when replay,
# sync, reset and the console call it at once. All our calls queue on one fcntl lock instead, so they run one at
# a time; a failed upload is remembered in .push_pending and retried by the next sync cycle (never dropped).
NEMOCLAW_LOCK = os.path.join(HERE, ".nemoclaw.lock")
PUSH_PENDING = os.path.join(HERE, ".push_pending")
NEMOCLAW_WAIT = 600  # seconds to wait for our turn

def _nemoclaw(*args):
    try:
        with open(NEMOCLAW_LOCK, "a") as lk:
            end = time.time() + NEMOCLAW_WAIT
            while True:
                try:
                    fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.time() > end:
                        raise TimeoutError(f"waited {NEMOCLAW_WAIT}s for {NEMOCLAW_LOCK}")
                    time.sleep(0.2)
            return subprocess.run(["nemoclaw", SANDBOX, *args], capture_output=True, text=True, timeout=120)
    except Exception as e:
        print("nemoclaw unavailable:", e)
        return None

def push_log():
    if not (SANDBOX and os.path.exists(LOG)):
        return
    r = _nemoclaw("upload", LOG, SANDBOX_DIR + "/")
    if r is not None and r.returncode == 0:
        if os.path.exists(PUSH_PENDING): os.remove(PUSH_PENDING)
        return
    open(PUSH_PENDING, "w").write(dt.datetime.now().isoformat(timespec="seconds"))
    err = (r.stderr or r.stdout)[-160:].strip() if r is not None else "nemoclaw unavailable"
    print(f"Sandbox upload deferred (next sync cycle retries): {err}")

def _pull(name):
    """Download a sandbox-side CSV (time,id,by) written by the vigil skill; [] if absent."""
    with tempfile.TemporaryDirectory() as tmp:
        r = _nemoclaw("download", f"{SANDBOX_DIR}/{name}", tmp + "/")
        path = os.path.join(tmp, name)
        if r is None or r.returncode or not os.path.exists(path):
            return []
        return list(csv.DictReader(open(path)))

def pull_approvals():
    """Apply 'approve <id>' and 'need info <id>' made in Telegram (OpenClaw vigil skill) to decisions.csv.
    Returns the newly applied entries, each with a 'kind' of APPROVED or INFO REQUESTED."""
    approvals, requests_ = _pull("approvals.csv"), _pull("info_requests.csv")
    if not (approvals or requests_):
        return []
    # Read-modify-write under the lock (replay must not append in between). Statuses are updated in place on
    # the existing row; write_log() rewrites the de-duplicated rows, so sync never adds a row.
    with log_lock():
        rows, new = read_log(), []
        for a in approvals:
            for x in rows:
                if x["id"] == a["id"] and not x["status"].startswith("APPROVED"):
                    x["status"] = f"APPROVED by {a['by']}"
                    new.append({**a, "kind": "APPROVED"})
        for q in requests_:  # same rule as the skill: INFO REQUESTED never overrides an approval
            for x in rows:
                if x["id"] == q["id"] and x["status"] == "PENDING_REVIEW":
                    x["status"] = f"INFO REQUESTED by {q['by']}"
                    new.append({**q, "kind": "INFO REQUESTED"})
        if new:
            write_log(rows)
    return new

# ---------------------------------------------------------------- long-term memory
# history.csv = past FDA MAUDE reports (built once by `import-history`, no model) + decisions.csv = live complaints.
HISTORY = os.path.join(HERE, "history.csv")
HISTORY_SOURCES = ["philips_cpap_reports_2019_2021.csv", "medtronic_heartware_hvad_reports.csv",
                   "medtronic_minimed_insulin_pumps_reports.csv", "industry_sample_2024_2025.csv",
                   "mixed_test_reports_2025.csv"]
HISTORY_FIELDS = ["id", "date_received", "device", "device_family", "product_code", "manufacturer", "event_type",
                  "product_problems", "failure_mode", "text"]
_history = {"mtime": None, "by_family": {}}


def load_history():
    """{device_family: [rows]} from history.csv, cached until the file changes."""
    if not os.path.exists(HISTORY):
        return {}
    m = os.path.getmtime(HISTORY)
    if _history["mtime"] != m:
        by = defaultdict(list)
        for r in csv.DictReader(open(HISTORY, encoding="utf-8")):
            by[r["device_family"]].append(r)
        _history.update(mtime=m, by_family=dict(by))
    return _history["by_family"]


def _iso(yyyymmdd):
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}" if re.fullmatch(r"\d{8}", yyyymmdd or "") else ""


LIVE_EVENT = {"DEATH": "Death", "SERIOUS_INJURY": "Injury", "MALFUNCTION": "Malfunction"}  # as MAUDE event_type


def device_memory(c):
    """Prior complaints on the same device family: FDA history + complaints Vigil already processed.
    Returns (prompt summary, card line) or ("", "") when there are none."""
    fam = device_family(c.get("device"), c.get("generic_name"))
    hist = [r for r in load_history().get(fam, []) if r["id"] != c["id"]]
    live = [r for r in read_log() if r["id"] != c["id"] and device_family(r.get("device")) == fam]
    if not (hist or live):
        return "", ""
    # (date, id, failure mode, event) per prior complaint; live ones count from when Vigil processed them
    prior = [(r["date_received"], r["id"], r["failure_mode"], r["event_type"]) for r in hist] + \
            [((r.get("time") or "")[:10], r["id"], r.get("failure_mode") or failure_mode("", r.get("text")),
              LIVE_EVENT.get(r.get("category") or "", "")) for r in live]
    modes = Counter(m for _, _, m, _ in prior if m and m != "other") or Counter(m for _, _, m, _ in prior)
    top = [m for m, _ in modes.most_common(3)]
    events = Counter(e for _, _, _, e in prior if e)
    recent = sorted(prior, reverse=True)[:2]
    last = recent[0][0]
    try:
        d = dt.date.fromisoformat(last); last_txt = f"{d.day} {d:%b %Y}"
    except Exception:
        last_txt = last or "unknown"
    n = len(prior)
    summary = (f"{n} prior complaints on {fam} ({len(hist)} in FDA history, {len(live)} processed by Vigil). "
               f"Events: {', '.join(f'{e} {k}' for e, k in events.most_common(4)) or 'unknown'}.\n"
               f"Top failure modes: {', '.join(f'{m} ({modes[m]})' for m in top) or 'unknown'}.\n"
               f"Most recent: {', '.join(f'#{i} ({d})' for d, i, _, _ in recent)}.")
    card = f"🧠 Memory: {n} prior complaint{'s' * (n != 1)} on {fam} (top issue: {top[0] if top else 'unknown'}, last: {last_txt})"
    return summary, card


def cmd_import_history(_):
    """Build history.csv from hackathon_data MAUDE exports. Pure code, no model calls; demo_set ids excluded."""
    csv.field_size_limit(sys.maxsize)  # some MAUDE narratives exceed the default 128 KB field limit
    demo = {r["mdr_report_key"] for r in csv.DictReader(open(os.path.join(HERE, "demo_set.csv"), encoding="utf-8"))}
    seen, out, skipped = set(), [], 0
    for name in HISTORY_SOURCES:
        path = os.path.join(DATA, name)
        if not os.path.exists(path):
            print("missing:", path); continue
        n0 = len(out)
        for r in csv.DictReader(open(path, encoding="utf-8")):
            rid = r["mdr_report_key"]
            if rid in demo or rid in seen:
                skipped += 1; continue
            seen.add(rid)
            text = (r["event_description"] or r["manufacturer_narrative"] or "").strip()
            out.append(dict(id=rid, date_received=_iso(r["date_received"]), device=r["brand_name"] or r["generic_name"] or "",
                            device_family=device_family(r["brand_name"], r["generic_name"]),
                            product_code=r["product_code"] or "", manufacturer=r["manufacturer"] or "",
                            event_type=r["event_type"] or "", product_problems=r["product_problems"] or "",
                            failure_mode=failure_mode(r["product_problems"], f"{text} {r['manufacturer_narrative'] or ''}"),
                            text=" ".join(text.split())[:300]))
        print(f"{name}: {len(out) - n0} reports")
    tmp = HISTORY + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writeheader(); w.writerows(out)
    os.replace(tmp, HISTORY)
    print(f"wrote {HISTORY}: {len(out)} reports ({skipped} skipped: demo_set ids or duplicates)")
    fams, modes = Counter(r["device_family"] for r in out), Counter(r["failure_mode"] for r in out)
    print("\nTop device families:"); [print(f"  {k:24} {v}") for k, v in fams.most_common(15)]
    print("\nFailure modes:"); [print(f"  {k:32} {v}") for k, v in modes.most_common()]


# ---------------------------------------------------------------- pipeline
def add_deadline(start, days):
    """21 CFR 803: 30 calendar days, but the 5-day report counts work days (Mon-Fri; federal holidays not modeled)."""
    if int(days) != 5:
        return start + dt.timedelta(days=int(days))
    d, left = start, 5
    while left:
        d += dt.timedelta(days=1)
        if d.weekday() < 5: left -= 1
    return d


def short_words(text, n):
    """First sentence, capped at n words (Telegram card stays compact)."""
    t = re.split(r"(?<=[.;])\s", (text or "").strip(), 1)[0].rstrip(".;")
    w = t.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def process(c, demo_today=None):
    score, level, dist = priority(c)
    dup = duplicate_of(c)
    miss = missing_fields(c)
    memory, memory_line = device_memory(c)
    res = classify(c, memory)  # EVERY complaint gets an AI check
    days = deadline_days(c, res)
    base = demo_today or dt.date.today()
    due = add_deadline(base, days).isoformat() if days else ""
    row = dict(time=dt.datetime.now().isoformat(timespec="seconds"), id=c["id"], received=c["received"],
               device=c["device"], priority=level, score=score, distress=dist, decision=res.get("decision"),
               category=res.get("category"), reason=res.get("reason"), deadline_days=days or "", due_date=due,
               confidence=res.get("confidence"), missing="; ".join(miss + list(res.get("missing_info") or [])),
               duplicate_of=dup or "", product_code=c.get("product_code") or "", memory=memory_line,
               failure_mode=failure_mode(c.get("product_problems"), f"{c['text']} {c.get('manufacturer_narrative') or ''}"),
               status="PENDING_REVIEW" if res.get("decision") != "NOT_REPORTABLE" else "LOGGED",
               text=c["text"][:500])
    log(row)
    row["awareness"] = base.isoformat()  # not logged; used for 3500A G4
    icon = {"URGENT": "🔴", "HIGH": "🟠", "NORMAL": "🟢"}.get(level, "⚪")
    reportable = row["decision"] in ("REPORTABLE", "NEEDS_INFO")
    lines = [f"{icon} {level} · {row['decision']} ({row['category']}) · {row['confidence']}%",
             f"#{c['id']} · {c['device']}",
             f"Why: {short_words(row['reason'], 20)}"]
    if due and row["decision"] != "NOT_REPORTABLE":
        d = dt.date.fromisoformat(due)
        lines.append(f"⏰ Due {d.day} {d:%b %Y} ({'5-day' if str(days) == '5' else '30-day'} report)")
    missing = [short_words(re.sub(r"\s*\(.*?\)", "", m), 5) for m in row["missing"].split(";") if m.strip()]
    if missing: lines.append("❓ Missing: " + " · ".join(missing[:3]))
    if memory_line: lines.append(memory_line)
    if dup: lines.append(f"Possible duplicate of #{dup}")
    if reportable: lines += ["📄 Draft FDA 3500A attached", f"Reply: approve {c['id']}"]
    msg = "\n".join(lines)
    tg(msg, reply_markup=alert_buttons(c["id"], row["decision"]))
    if row["decision"] in ("REPORTABLE", "NEEDS_INFO"):
        try:
            pdf = make_mdr(c, row)
            if not pdf:
                raise RuntimeError("fpdf2 not installed")
            tg_doc(pdf, f"📄 Draft FDA Form 3500A for #{c['id']} (due {due or 'n/a'}). Review before submission.")
        except Exception as e:
            print(f"MDR PDF failed for #{c['id']}: {e}")
            tg(f"⚠️ MDR PDF for #{c['id']} could not be generated ({e}). Draft the Form 3500A manually.")
    alert = spike(c)
    if alert:
        tg(f"📈 TREND ALERT\n{alert}\nRecommend: open an investigation / CAPA and review all related complaints.")
    return row


def load_philips(limit):
    return load_csv(os.path.join(DATA, "philips_cpap_reports_2019_2021.csv"), limit, sort=True)


def load_csv(path, limit=None, sort=False):
    """Any CSV with the MAUDE export columns (e.g. demo_set.csv). Keeps file order unless sort=True."""
    if not os.path.exists(path) and os.path.exists(os.path.join(HERE, path)):
        path = os.path.join(HERE, path)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if sort:
        rows.sort(key=lambda r: r["date_received"] or "")
    out = []
    for r in rows:
        text = (r["event_description"] or r["manufacturer_narrative"] or "").strip()
        if not text: continue
        out.append(dict(id=r["mdr_report_key"], text=text, device=r["brand_name"] or r["generic_name"] or "",
                        manufacturer=r["manufacturer"] or "", event_date=r["date_of_event"] or "",
                        received=r["date_received"] or "", event_type=r["event_type"] or "",
                        outcomes=r["patient_outcomes"] or "", generic_name=r.get("generic_name") or "",
                        product_code=r.get("product_code") or "", product_problems=r.get("product_problems") or "",
                        manufacturer_narrative=(r.get("manufacturer_narrative") or "").strip()))
    return out[:limit] if limit else out


def load_txt(path):
    out = []
    for i, line in enumerate(open(path, encoding="utf-8")):
        if line.strip():
            out.append(dict(id=f"D{i+1}", text=line.strip(), device="DreamStation CPAP (illustrative)",
                            manufacturer="", event_date="", received=dt.date.today().strftime("%Y%m%d"),
                            event_type="", outcomes=""))
    return out

# ---------------------------------------------------------------- commands
def cmd_test(_):
    print("Model:", model_name(), "at", LLM_BASE)
    print("Model says:", llm("Reply with exactly: Vigil online.", 20))
    tg("Vigil is online. Watching complaints.")
    print("Telegram message sent (check the group).")


def cmd_replay(a):
    if a.csv: items = load_csv(a.csv, a.limit)
    elif a.file: items = load_txt(a.file)[:a.limit]
    else: items = load_philips(a.limit)
    tg(f"▶️ Replay started: {len(items)} complaints.")
    for n, c in enumerate(items, 1):
        r = process(c)
        print(r["id"], r["priority"], r["decision"], r["due_date"])
        if n == len(items):
            break
        if a.step:  # presenter mode: the demo advances only when someone presses Enter
            try:
                answer = input(f"[{n}/{len(items)}] Press Enter for next complaint (q to quit) ")
            except EOFError:
                answer = "q"
            if answer.strip().lower() == "q":
                print("Replay stopped.")
                break
        else:
            time.sleep(a.delay)
    tg("⏹ Replay finished. Send /due for open deadlines.")


def cmd_sync(a):
    push_log()
    print(f"Syncing with sandbox '{SANDBOX}' every {a.interval}s (approvals from the OpenClaw vigil skill) ...")
    while True:
        if os.path.exists(PUSH_PENDING):  # an earlier upload failed: the whole file is re-sent, so one retry covers all
            push_log()
        for x in pull_approvals():
            print(f"{x['time']} #{x['id']} {x['kind']} by {x['by']}")
        if a.once: break
        time.sleep(a.interval)


def cmd_reset(_):
    """Clean slate for a rehearsal / the demo: host log, PDFs, outbox, and the sandbox copies."""
    with log_lock():
        for p in (LOG, OUTBOX):
            if os.path.exists(p): os.remove(p); print("removed", p)
        if os.path.isdir(REPORTS):
            shutil.rmtree(REPORTS); print("removed", REPORTS)
    r = _nemoclaw("exec", "--", "rm", "-f", *(f"{SANDBOX_DIR}/{n}" for n in
                                               ("decisions.csv", "approvals.csv", "info_requests.csv")))
    ok = r is not None and r.returncode == 0
    print(f"sandbox '{SANDBOX}': " + ("cleared decisions.csv, approvals.csv, info_requests.csv" if ok else
          f"FAILED to clear ({(r.stderr or r.stdout)[-200:] if r else 'nemoclaw unavailable'})"))
    # Fresh OpenClaw conversation for the Telegram group, so the agent forgets earlier rehearsal turns.
    r = _nemoclaw("sessions", "reset", TG_SESSION, "--reason", "reset")
    ok = r is not None and r.returncode == 0
    print(f"OpenClaw session {TG_SESSION}: " + ("reset" if ok else
          f"FAILED to reset ({(r.stderr or r.stdout)[-200:] if r else 'nemoclaw unavailable'})"))


def cmd_listen(_):
    """Standalone fallback. Do not run while the OpenClaw sandbox owns the bot (Telegram allows one poller)."""
    offset = None
    print("Listening for approve ID, /due, /status ...")
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                             params={"timeout": 30, "offset": offset}, timeout=40).json()
        except Exception as e:  # network blip: wait and poll again, never exit
            print(f"WARNING: Telegram getUpdates failed ({type(e).__name__}: {e}); retrying in {TG_WAIT}s")
            time.sleep(TG_WAIT)
            continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            text = (u.get("message") or {}).get("text") or ""
            who = ((u.get("message") or {}).get("from") or {}).get("first_name", "someone")
            m = re.match(r"^/?approve\b[:\s#]*(\S*)", text.strip(), re.I)  # "approve ID" (OpenClaw owns /approve)
            if m:
                cid = m.group(1)
                with log_lock():
                    rows = read_log()
                    hit = [x for x in rows if cid and x["id"] == cid]
                    for x in hit: x["status"] = f"APPROVED by {who}"
                    write_log(rows)
                tg(f"✅ #{cid} approved by {who}. Logged." if hit else "Usage: approve ID (unknown complaint id).")
            elif text.startswith("/due"):
                rows = [x for x in read_log() if x["due_date"] and not x["status"].startswith("APPROVED")]
                rows.sort(key=lambda x: x["due_date"])
                tg("Open deadlines:\n" + "\n".join(f"#{x['id']} {x['decision']} due {x['due_date']} ({x['device'][:30]})"
                                                   for x in rows[:20]) if rows else "No open deadlines.")
            elif text.startswith("/status"):
                rows = read_log()
                c = defaultdict(int)
                for x in rows: c[x["decision"]] += 1
                tg(f"Processed {len(rows)} complaints: " + ", ".join(f"{k} {v}" for k, v in c.items()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    rp = sub.add_parser("replay")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--delay", type=float, default=3)
    rp.add_argument("--file")
    rp.add_argument("--csv", help="MAUDE-format CSV, e.g. demo_set.csv")
    rp.add_argument("--step", action="store_true", help="wait for Enter after each complaint (q to quit)")
    sub.add_parser("listen")
    sp = sub.add_parser("sync")
    sp.add_argument("--interval", type=float, default=10)
    sp.add_argument("--once", action="store_true")
    sub.add_parser("reset")
    sub.add_parser("import-history")
    a = p.parse_args()
    {"test": cmd_test, "replay": cmd_replay, "listen": cmd_listen, "sync": cmd_sync, "reset": cmd_reset, "import-history": cmd_import_history}[a.cmd](a)

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
  python3 vigil.py sync                      # pull 'approve ID' from the OpenClaw sandbox skill (skill/vigil)
  python3 vigil.py listen                    # standalone Telegram commands (only if OpenClaw is NOT running)
"""
import argparse, csv, datetime as dt, json, os, re, subprocess, sys, tempfile, time
from collections import defaultdict, deque

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
    "emergency": 6, "er ": 5, "surgery": 6, "burn": 6, "fire": 7, "smoke": 6, "explod": 7,
    "choking": 7, "could not breathe": 8, "couldn't breathe": 8, "shortness of breath": 6,
    "bleeding": 6, "injur": 5, "overdose": 7, "shock": 6,
    "foam": 4, "particle": 4, "black dust": 4, "debris": 3, "headache": 2, "cough": 2,
    "stopped working": 3, "alarm": 2, "failure": 3, "malfunction": 3,
}
EVENT_WEIGHT = {"Death": 10, "Injury": 6, "Malfunction": 2}

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
    t = (c["text"] or "").lower()
    score = sum(w for k, w in RED_FLAGS.items() if k in t)
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


_by_device = defaultdict(list)
def spike(c):
    """Alert when a device gets >=5 complaints in 30 days and >=3x its previous 30-day count."""
    try:
        d = dt.datetime.strptime(c["received"], "%Y%m%d").date()
    except Exception:
        return None
    key = (c["device"] or "unknown").split()[0].upper()
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
A complaint is REPORTABLE if the information reasonably suggests the device:
- may have caused or contributed to a DEATH, or
- may have caused or contributed to a SERIOUS INJURY (life-threatening, permanent impairment, or needing medical/surgical intervention to prevent permanent damage), or
- MALFUNCTIONED and the malfunction would be likely to cause death or serious injury if it recurred.
Deadlines: 30 calendar days from awareness; 5 work days if remedial action is needed to prevent substantial harm to the public.
When unsure, lean toward REPORTABLE or NEEDS_INFO and say what is missing. Never discard a complaint.

Complaint: {text}
Device: {device}   Event date: {event_date}   Received: {received}

Answer ONLY with JSON:
{{"decision": "REPORTABLE|NOT_REPORTABLE|NEEDS_INFO", "category": "DEATH|SERIOUS_INJURY|MALFUNCTION|NONE",
 "reason": "one sentence citing the rule", "deadline_days": 30 or 5 or null, "missing_info": [], "confidence": 0-100}}"""

DRAFT = """You are Vigil. Draft an FDA MDR (Form 3500A style) for human review. Be factual; never invent facts.
In sections 1-4 write "UNKNOWN" for any fact not in the complaint.
Only use company and device names that appear in the complaint data below. Never add or guess any other manufacturer, brand or model.
Deadline rule (21 CFR 803): 5 work days only when urgent remedial action is needed to prevent substantial harm to the public; otherwise 30 calendar days. Use the deadline given below; do not recalculate it.
Plain text only: no markdown, no asterisks, no bold.
Complaint: {text}
Device: {device}  Manufacturer: {manufacturer}  Event date: {event_date}
Decision: {decision}  Category: {category}  Deadline: {deadline}  Due: {due}
Missing information: {missing}
Sections, short and plain:
1. Patient outcome
2. Event description
3. Device information
4. Report type and due date
5. Follow-up questions for the customer: a numbered list of AT MOST 5 specific questions, most important
   first (what is needed to confirm reportability and the deadline comes first). Cover the items in
   "Missing information" and other gaps in this complaint (e.g. exact event date, device serial number,
   what medical treatment was given, current patient condition, whether the device is available for return).
   Refer to the details of this complaint. Never write "UNKNOWN" or "follow up" on its own in this section."""


def model_name():
    global LLM_MODEL
    if not LLM_MODEL:
        r = requests.get(f"{LLM_BASE}/models", timeout=10)
        LLM_MODEL = r.json()["data"][0]["id"]
    return LLM_MODEL


def llm(prompt, max_tokens=600):
    r = requests.post(f"{LLM_BASE}/chat/completions", timeout=180, json={
        "model": model_name(), "temperature": 0.1, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
    })
    r.raise_for_status()
    out = r.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def classify(c):
    raw = llm(CLASSIFY.format(**c), 400)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"decision": "NEEDS_INFO", "category": "NONE", "reason": "model output unreadable - human review",
                "deadline_days": 30, "missing_info": [], "confidence": 0}

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
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text"]

def log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new: w.writeheader()
        w.writerow(row)
    push_log()

def read_log():
    if not os.path.exists(LOG): return []
    return list(csv.DictReader(open(LOG)))

def write_log(rows):
    with open(LOG, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    push_log()

# ---------------------------------------------------------------- OpenClaw sandbox sync (vigil skill)
# The sandbox gets a read-only copy of decisions.csv; the skill appends 'approve <id>' to approvals.csv there.
# Host decisions.csv stays the source of truth: push after every write, pull approvals with `vigil.py sync`.
SANDBOX = os.environ.get("VIGIL_SANDBOX", "my-assistant")
SANDBOX_DIR = "/sandbox/vigil"

def _nemoclaw(*args):
    try:
        return subprocess.run(["nemoclaw", SANDBOX, *args], capture_output=True, text=True, timeout=60)
    except Exception as e:
        print("nemoclaw unavailable:", e)
        return None

def push_log():
    if SANDBOX and os.path.exists(LOG):
        r = _nemoclaw("upload", LOG, SANDBOX_DIR + "/")
        if r is not None and r.returncode:
            print("Sandbox upload failed:", (r.stderr or r.stdout)[-200:])

def pull_approvals():
    """Apply approvals made in Telegram (via the OpenClaw vigil skill) to decisions.csv. Returns new approvals."""
    with tempfile.TemporaryDirectory() as tmp:
        r = _nemoclaw("download", SANDBOX_DIR + "/approvals.csv", tmp + "/")
        path = os.path.join(tmp, "approvals.csv")
        if r is None or r.returncode or not os.path.exists(path):
            return []
        approvals = list(csv.DictReader(open(path)))
    rows, new = read_log(), []
    for a in approvals:
        for x in rows:
            if x["id"] == a["id"] and not x["status"].startswith("APPROVED"):
                x["status"] = f"APPROVED by {a['by']}"
                new.append(a)
    if new:
        write_log(rows)
    return new

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


def process(c, demo_today=None):
    score, level, dist = priority(c)
    dup = duplicate_of(c)
    miss = missing_fields(c)
    res = classify(c)  # EVERY complaint gets an AI check
    days = res.get("deadline_days") or (30 if res.get("decision") != "NOT_REPORTABLE" else None)
    if days: days = 5 if str(days).strip() == "5" else 30  # 21 CFR 803: 5 only for urgent remedial action, else 30
    base = demo_today or dt.date.today()
    due = add_deadline(base, days).isoformat() if days else ""
    row = dict(time=dt.datetime.now().isoformat(timespec="seconds"), id=c["id"], received=c["received"],
               device=c["device"], priority=level, score=score, distress=dist, decision=res.get("decision"),
               category=res.get("category"), reason=res.get("reason"), deadline_days=days or "", due_date=due,
               confidence=res.get("confidence"), missing="; ".join(miss + list(res.get("missing_info") or [])),
               duplicate_of=dup or "", status="PENDING_REVIEW" if res.get("decision") != "NOT_REPORTABLE" else "LOGGED",
               text=c["text"][:500])
    log(row)
    row["awareness"] = base.isoformat()  # not logged; used for 3500A G4
    icon = {"REPORTABLE": "🔴", "NEEDS_INFO": "🟠", "NOT_REPORTABLE": "🟢"}.get(row["decision"], "⚪")
    msg = (f"{icon} Complaint #{c['id']}  [{level} priority, score {score}]\n"
           f"Device: {c['device']}\n"
           f"Decision: {row['decision']} ({row['category']}), confidence {row['confidence']}%\n"
           f"Why: {row['reason']}\n")
    if due: msg += f"Deadline: {deadline_text(days)} -> due {due}\n"
    if row["missing"]: msg += f"Missing: {row['missing']}\n"
    if dup: msg += f"Possible duplicate of #{dup}\n"
    if row["decision"] != "NOT_REPORTABLE":
        draft = llm(DRAFT.format(decision=row["decision"], category=row["category"], due=due,
                                 deadline=deadline_text(days),
                                 missing=row["missing"] or "none listed - check the complaint for gaps",
                                 **{"manufacturer": "", **c}), 700)
        draft = draft.replace("**", "")  # Telegram plain text shows markdown asterisks raw
        msg += f"\nDraft MDR (Form 3500A fields):\n{draft}\n\nReply: approve {c['id']}"
    else:
        msg += "Logged with reason for audit. Nothing is dropped."
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
                        product_code=r.get("product_code") or "",
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
    elif a.file: items = load_txt(a.file)
    else: items = load_philips(a.limit)
    tg(f"▶️ Replay started: {len(items)} complaints.")
    for c in items:
        r = process(c)
        print(r["id"], r["priority"], r["decision"], r["due_date"])
        time.sleep(a.delay)
    tg("⏹ Replay finished. Send /due for open deadlines.")


def cmd_sync(a):
    push_log()
    print(f"Syncing with sandbox '{SANDBOX}' every {a.interval}s (approvals from the OpenClaw vigil skill) ...")
    while True:
        for x in pull_approvals():
            print(f"{x['time']} #{x['id']} approved by {x['by']}")
        if a.once: break
        time.sleep(a.interval)


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
    sub.add_parser("listen")
    sp = sub.add_parser("sync")
    sp.add_argument("--interval", type=float, default=10)
    sp.add_argument("--once", action="store_true")
    a = p.parse_args()
    {"test": cmd_test, "replay": cmd_replay, "listen": cmd_listen, "sync": cmd_sync}[a.cmd](a)

# Design Document

## Overview

The **report-front-door** feature adds a public, no-login "Report a device problem" web flow to the existing Thirty / Vigil system. A reporter (nurse/clinician, patient/family, or company staff) scans a per-device QR code or opens `/report`, picks a language (English, Spanish, Portuguese, Haitian Creole), answers an adaptive one-question-at-a-time interview driven by the active `Agent`, reviews a plain-words summary, confirms, and receives a reference number plus a downloadable PDF receipt. The confirmed report enters the **existing** intake pipeline via `intake.submit(...)` with `source="reporter"`, so it is scored, classified, drafted, and clocked exactly like every other channel.

### How it fits the existing architecture

- **Single pipeline entry.** The Front_Door submits through `intake.submit(payload, kind="reporter", default_source="reporter", ...)` only. It never calls `vigil.process()` directly and never edits `vigil.py`. Dedupe, raw storage, the background worker, and the `(http_status, response_dict)` contract all come for free from `intake.py`.
- **Agent abstraction, extended.** The interview and translation reuse the `Agent` interface in `thirty/agents/base.py`. Two new methods are added — `next_question(answers_so_far)` and `translate_to_english(text, source_language)` — implemented on `Agent`/`NoAgent` (base), `SampleAgent` (scripted, offline), `LocalModelAgent`, and `ClaudeAgent`. `get_agent()` (in `thirty/agents/__init__.py`) selects the active one unchanged.
- **Console integration.** Routes live on a new Flask blueprint (`thirty/reporter/front_door.py`) mounted into the console app via an `init_app(app)` call, mirroring how `intake.init_app(app)` is mounted. The Integrations page gains a QR panel; the complaints views gain a "Reporter" badge and a completeness score. Templates are treated as an integration surface (see the note at the end).
- **100% local and offline.** No CDNs, no third-party services, no outbound calls on the reporter path. QR codes are generated as inline SVG in pure Python (a small vendored generator — no new network dependency). PDFs use `fpdf2` (already a dependency; bundled `DejaVuSans` fonts cover all four Latin-script languages). In Demo_Mode the SampleAgent drives everything with zero network calls.

### Key grounding facts (verified in the codebase)

- `intake.submit` maps fields via `settings.json["field_map"][kind]`, validates (`to_complaint`), dedupes by `vigil_id(source, external_id)` (`= SRC-<sha1[:8]>`), writes raw, queues, and returns `(202,"queued")`, `(200,"duplicate")`, or `(400,"rejected")`. Recognised payload fields: `text, device, manufacturer, event_date (YYYYMMDD|YYYY-MM-DD), external_id, source, reporter, product_code`.
- `vigil_id("reporter", ext)` → `REP-xxxxxxxx` (the `Reference_Number` format in the requirements).
- `DEVICES` in `thirty/sample_data.py` has 8 entries keyed `AF, PG, NS, TC, CL, VV, LM, SP`, each `(device_name, common_name, product_code)`; `MAKER = "Northwind Medical"`.
- `UNKNOWN` is the literal string `"UNKNOWN"` used throughout `sample_data.fields_for` and the 3500A field shapes.
- Console reads `decisions.csv` whose `FIELDS` already include a `source` column; it serves PDFs from `../reports`.
- `segno`/`qrcode` are **not** installed; `fpdf2==2.8.9`, `Flask==3.1.3`, `hypothesis==6.170.9`, `pytest==9.1.1` are.

## Architecture

```mermaid
flowchart TD
    QR["Per-device QR code (SVG)\n/report/&lt;device_slug&gt;"] --> Landing
    URL["/report (no slug)"] --> Landing
    Landing["Landing: language + reporter-type\n(+ device resolve/select)"] --> StartIv{Reporter-type\nand language set?}
    StartIv -- no --> Landing
    StartIv -- yes --> Loop

    subgraph Interview["Adaptive interview (Front_Door controls the loop)"]
      Loop["POST answer -> append to Answers_So_Far"] --> Cap{questions_asked &gt;= 8?}
      Cap -- yes --> Review
      Cap -- no --> NQ["agent.next_question(answers_so_far)"]
      NQ --> Dispatch{result}
      Dispatch -- question --> Ask["render one question\n(+ 'I don't know')"]
      Ask --> Loop
      Dispatch -- '\"complete\"' --> Review
      Dispatch -- malformed/other --> Review
    end

    Review["Review (plain words,\nUNKNOWN -> 'not known', editable)"] --> Confirm{Reporter confirms?}
    Confirm -- no / edit --> Review
    Confirm -- yes --> Translate["Fill missing fields -> UNKNOWN\nTranslate free-text via active agent\nor Translation_Pending_Marker"]
    Translate --> Submit["intake.submit(payload, source='reporter')"]
    Submit --> Result{http_status}
    Result -- "202 queued" --> Receipt["Show REP-xxxxxxxx\n+ build PDF receipt"]
    Result -- "200 duplicate" --> Dup["Show existing REP-xxxxxxxx\n'already received'"]
    Result -- "400 rejected" --> Err["Plain-language error,\nkeep answers, require re-confirm"]
    Receipt --> PDF["GET /report/receipt/&lt;ref&gt;.pdf"]

    Submit -. same pipeline .-> Pipe["intake worker -> vigil.process()\n(score, classify, draft, clock)"]
    Pipe --> Console["Console: 'Reporter' badge\n+ Completeness_Score"]
```

The Front_Door owns the interview loop and the 8-question cap. The agent only *supplies* the next question (or `complete`); it never controls termination. This keeps Property 1 (termination) true even if an agent misbehaves.

## Components and Interfaces

### 1. Front_Door blueprint — `thirty/reporter/front_door.py`

A new package `thirty/reporter/` with:

- `front_door.py` — the Flask `Blueprint` and routes.
- `interview.py` — pure interview-state logic (reducer functions, field mapping, UNKNOWN handling, cap). Pure and import-light so property tests can drive it without Flask.
- `qr.py` — pure-Python QR→SVG generator.
- `receipt.py` — `fpdf2` PDF receipt builder.

`init_app(app)` registers the blueprint and is called from the console's init block right next to `intake_mod().init_app(app)`.

Routes (all no-auth):

| Method & path | Purpose | Requirements |
|---|---|---|
| `GET /report` | Landing without pre-filled device | 1.1, 1.4, 1.5 |
| `GET /report/<device_slug>` | Landing; pre-fill device if slug matches a catalogue key (case-insensitive), else prompt to select | 1.2, 1.3, 1.4 |
| `POST /report/start` | Record language + reporter-type (+ device), begin interview; reject if reporter-type missing | 2.2, 3.2, 3.4, 4.1 |
| `GET /report/interview` | Render the current single question (or redirect to review) | 4.1, 4.4, 4.6 |
| `POST /report/answer` | Append answer (or UNKNOWN for "I don't know"), enforce cap, call `next_question`, advance or go to review | 4.2, 4.3, 4.5, 4.7, 4.9 |
| `GET /report/review` | Plain-words review, UNKNOWN shown as "not known", editable | 5.1, 5.2, 5.3 |
| `POST /report/review/edit` | Revise an answer, return to review | 5.3 |
| `POST /report/confirm` | Finalize → fill missing→UNKNOWN, translate, build payload, `intake.submit`, handle 202/200/400 | 5.4, 5.5, 6.1–6.8, 7.1 |
| `GET /report/done/<ref>` | Show reference number + receipt download link | 6.4, 6.5, 7.3 |
| `GET /report/receipt/<ref>.pdf` | Serve the generated PDF receipt | 7.1–7.5 |

**Session / state.** Interview state is held server-side keyed by an opaque `session_id` (random token in a cookie — no login, no PII in the token). State is a plain dict (see Data Models) persisted to a small per-session JSON file under `VIGIL_DIR/reporter_sessions/<session_id>.json` so the flow survives a worker restart and is testable without a live cookie jar. The pure reducers in `interview.py` take and return this dict.

**Mobile-first rendering (R1.6, R2 UI).** The landing/interview/review templates set `viewport` and a CSS base of `font-size: 16px` on body text and `min-width/min-height: 44px` on every button, link-button, and option control. These rules live in a dedicated partial/stylesheet block so they are easy to review and don't collide with concurrent template edits.

**Patient/family plain language (R1.7, R7.5).** When `reporter_type == "patient_family"`, templates and the PDF summary select a "plain" string table with no statute/clause/form-number citations. A single helper `plain_mode(reporter_type)` centralizes the choice.

**Render failure (R1.9).** Each `GET` wraps rendering in a try/except that returns a simple no-auth error page ("The reporting page could not be loaded. Please try again.") with a retry link to the same URL — never a login redirect.

**Performance (R1.8).** Landing render is a static template + in-memory catalogue lookup; no network, no model call on `GET`. The agent is only invoked on `POST /report/answer`.

### 2. Interview state model (`interview.py`)

The Front_Door, not the agent, runs the loop. Core pure functions:

```python
QUESTION_CAP = 8
IDK = "__IDK__"          # internal marker for an "I don't know" answer
UNKNOWN = "UNKNOWN"      # the system-wide sentinel

def start_state(reporter_type, language, device_key) -> dict
def record_answer(state, field, raw_value, idk: bool) -> dict   # append; map IDK -> UNKNOWN
def should_continue(state) -> bool                              # questions_asked < QUESTION_CAP and not ended
def end_interview(state, reason) -> dict                        # reason in {"complete","cap","malformed"}
def to_draft_3500a(state) -> dict                               # fill missing required fields with UNKNOWN
def to_intake_payload(state, free_text, english_text) -> dict
```

Loop driver (in the route; equivalently a pure `run_interview(agent, state, answer_source)` used by tests):

```
on POST /report/answer:
    state = record_answer(state, current_field, value, idk)
    if state["questions_asked"] >= QUESTION_CAP:
        state = end_interview(state, "cap"); -> review
    else:
        q = safe_next_question(agent, answers_view(state))   # never raises
        if q is COMPLETE:            state = end_interview(state, "complete"); -> review
        elif is_valid_question(q):   state["current"] = q; -> interview
        else:                        state = end_interview(state, "malformed"); -> review  # R4.9
```

`safe_next_question` wraps the agent call in try/except and validates the shape; any exception or malformed value is treated as `malformed` (ends the interview, preserves answers). This guarantees termination and tolerates a misbehaving agent.

### 3. Agent interface additions (`thirty/agents/base.py`)

Two new methods on `class Agent`, documented in the module docstring.

**`next_question(answers_so_far) -> dict | "complete"`**

- Input `answers_so_far` (see Data Models): `{reporter_type, language, device, answers: {field: value}, asked: [field, ...]}`.
- Returns **exactly one** of:
  - the sentinel string `"complete"` (constant `COMPLETE = "complete"`), or
  - a **question object** (dict):
    ```python
    {
      "field": "d1_brand_name",        # target field key (see mapping table)
      "prompt": "What is the brand name on the device?",  # in answers_so_far["language"]
      "language": "es",                # the language the prompt is in
      "type": "text" | "choice",       # input kind
      "options": [ {"value": "death", "label": "..."} , ... ],  # for type == "choice"
      "allow_idk": True,               # Front_Door always renders an "I don't know" affordance
    }
    ```
- Contract: while the Requirement-4 field set is not fully requested, return one question (R8.8); once fully requested, return `"complete"` (R8.9). The Front_Door still enforces the 8-cap independently.

**`translate_to_english(text, source_language) -> str | None`**

- Model-backed agents return an English translation string; they MUST return `None` (never a fabricated translation) if they cannot translate (R8.11).
- `source_language == "en"` → callers short-circuit and don't invoke this (R2.5).
- `SampleAgent` and `NoAgent` return `None` (they do not translate); the Front_Door then stores the `Translation_Pending_Marker` (R8.10, R2.6).

Base defaults:

```python
class Agent:
    def next_question(self, answers_so_far): raise NotImplementedError
    def translate_to_english(self, text, source_language): return None  # safe default: defer
```

**`NoAgent`** (R8.7): `next_question` returns `"complete"` immediately so no adaptive loop runs; the Front_Door detects `agent.id == "none"` on `POST /report/start` and renders a **single-screen fixed checklist** collecting every Requirement-4 field at once. On submit, the checklist maps straight into `to_draft_3500a`/`to_intake_payload` (any blank/"I don't know" → UNKNOWN). `translate_to_english` → `None`.

**`SampleAgent`** (`thirty/agents/sample.py`) (R8.2–8.4, R8.10):
- A scripted ordered list of the Requirement-4 fields. `next_question` looks at `answers_so_far["asked"]`, finds the first field not yet asked, and returns its question object with `prompt`/`options.label` taken from a 4-language string table (`en`, `es`, `pt`, `ht`). When all scripted fields have been asked → `"complete"`.
- Unsupported language → fall back to the default (`en`) strings (R8.3).
- Fully offline, zero network (R8.4); honors `THIRTY_SAMPLE_DELAY` via the existing `_wait()` so console loading states stay visible.
- `translate_to_english` → `None` (defers; marker stored by the Front_Door) (R8.10).

**`LocalModelAgent`** / **`ClaudeAgent`** (R8.5, R8.6, R8.11):
- Add a `NEXT_Q` prompt (in `local_model.py`, reused by `ClaudeAgent` like the other prompts) that is given `answers_so_far` (role, language, device, answers-so-far, and the target field set) and must return JSON that is **either** a single question object **or** `{"complete": true}`. Parsed with the existing `_json`/`_extract_json`; on parse failure or an empty/invalid object the method returns `"complete"` (safe termination) — the Front_Door's cap and `safe_next_question` also guard this.
- Add a `TRANSLATE` prompt: translate `text` from `source_language` to English, "return only the translation; if you cannot, return the exact token `CANNOT_TRANSLATE`". `translate_to_english` returns the stripped output, or `None` when the output is empty/`CANNOT_TRANSLATE` or any exception occurs. Never fabricates (R8.11).
- Each agent returns exactly one value that is a question object or `"complete"` (R8.1, R8.5, R8.6).

### 4. QR SVG generator (`thirty/reporter/qr.py`) (R10)

Decision: **vendor a small, self-contained pure-Python QR encoder that emits SVG**, rather than add a dependency. Rationale: neither `segno` nor `qrcode` is installed; the project pins exact versions and prizes "no network, no CDNs"; the payload is tiny and fixed (`/report/<slug>`, well under a byte-mode QR version's capacity), so a minimal byte-mode encoder (QR version chosen by length, error-correction level M, fixed mask) is sufficient and auditable. If a maintainer later prefers a library, `segno` (pure-Python, offline) pinned to an exact version is the drop-in alternative — stated here as the explicit fallback, not the default.

Interface:

```python
def qr_svg(data: str, *, module_px: int = 4, quiet: int = 4) -> str
    # returns a complete <svg ...>...</svg> string (black modules on white),
    # sized for inline embedding; raises QRError on encode failure.
```

The Integrations page calls `qr_svg(f"/report/{slug}")` per device. Failures for one device are caught so the others still render (R10.6).

### 5. PDF receipt builder (`thirty/reporter/receipt.py`) (R7)

Mirrors `vigil.py`'s fpdf2 setup (same `DejaVuSans`/`DejaVuSans-Bold` from `thirty/fonts`, with `Helvetica` fallback). The Latin-script fonts render English/Spanish/Portuguese/Haitian-Creole text.

```python
def build_receipt(ref_number, summary, reporter_type, language) -> bytes  # PDF bytes
```

Contents: title, `Reference_Number` (`REP-xxxxxxxx`), a plain-words summary of the submitted answers (UNKNOWN rendered as "not known"), and the submission date. When `reporter_type == "nurse_clinician"`, append the exact line `Copy for your facility's records (user facility reporting, 21 CFR 803.30)` (R7.4). When `reporter_type == "patient_family"`, the summary uses plain strings with no regulatory citations (R7.5). The route writes the bytes to `VIGIL_DIR/reports/receipts/REP-xxxxxxxx.pdf` and serves them via `send_from_directory` (R7.3).

### 6. Console badge + completeness score (`dashboard_v2/app.py` + templates) (R9)

- **Badge (R9.1, R9.2, R9.7):** a template helper `is_reporter(row)` returns `row.get("source") == "reporter"`. Where true, render a "Reporter" badge (reuse the existing `SOURCES` styling; add `"reporter": ("Reporter","user")`). Absent/empty source → not reporter, no badge.
- **Completeness_Score (R9.3–9.6):** add `completeness_score(row)` in `app.py`:
  ```python
  REQUIRED_3500A = ["D1_brand_name","D4_model","D4_lot_or_serial","B5_event_description",
                    "B2_outcomes","H3_device_evaluated","B3_date_of_event",
                    "date_noticed","follow_up_contact"]   # the Requirement-4 data set
  def completeness_score(row):
      fields = draft_fields_for(row)          # from the drafted 3500A / stored answers
      known = sum(1 for f in REQUIRED_3500A if present_and_not_unknown(fields.get(f)))
      return round(100 * known / len(REQUIRED_3500A))
  ```
  Score is an integer 0–100; all-known → 100 (R9.4); all-UNKNOWN → 0 (R9.5). Only computed/shown for reporter-source rows (R9.7). The drafted fields are read from the existing per-complaint draft the pipeline already produces (`reports`/draft JSON), so the score reflects the Draft_3500A.

## Data Models

### Answers_So_Far (interview state)

```python
{
  "session_id": "a1b2c3...",
  "reporter_type": "nurse_clinician" | "patient_family" | "company_staff",
  "language": "en" | "es" | "pt" | "ht",
  "device": {"key": "AF", "brand": "AeroFlow A200 CPAP",
             "common": "CPAP", "product_code": "BZD"} | None,
  "answers": { "<field>": "<value or UNKNOWN>", ... },   # one entry per answered field
  "asked":   ["<field>", ...],                            # fields already presented
  "questions_asked": 3,                                   # == len(asked); the cap counter
  "current": { ...question object... } | None,
  "ended": False,
  "end_reason": None | "complete" | "cap" | "malformed",
  "free_text_original": "",        # the reporter's description in their language
}
```

Key invariants: `questions_asked == len(asked)`; an `"I don't know"` answer stores `UNKNOWN` in `answers[field]` and is never overwritten (Property 2).

### Question object

See the `next_question` contract above (`field, prompt, language, type, options?, allow_idk`).

### Field → 3500A and → intake payload mapping

| Interview field (R4.8) | Draft_3500A field | Intake payload field |
|---|---|---|
| device brand name | `D1_brand_name` | `device` |
| device model | `D4_model` | (narrative) |
| lot or serial number | `D4_lot` / `D4_serial` | (narrative) |
| description of what happened | `B5_event_description` | `text` (combined) |
| patient outcome (death/hospitalisation/injury/none) | `B2_outcomes` + derived `H1_type_of_reportable_event` | (narrative) |
| device malfunctioned? (yes/no/UNKNOWN) | `H3_device_evaluated` context / `B1_event_type` | (narrative) |
| date of event | `B3_date_of_event` | `event_date` (YYYYMMDD) |
| date problem noticed | `date_noticed` (stored) | (narrative) |
| follow-up contact | `follow_up_contact` (stored) → `reporter` | `reporter` |
| (fixed) | `D2b_product_code`, `D3_manufacturer` | `product_code` (from device), `manufacturer` = `MAKER` |

Any required field absent when the interview ends is stored as `UNKNOWN` (R4.10). `event_date` is normalized to `YYYYMMDD` for intake; a missing/UNKNOWN date maps to an empty `event_date` (intake accepts empty).

### Bilingual text storage (R2.4–2.8)

The complaint `text` sent to intake carries **both** the original and the English form so reviewers and the pipeline see both:

- `language == "en"`: `english = original` (no translation call) (R2.5).
- non-English + model-backed agent: `english = agent.translate_to_english(original, language)`; if that returns `None`, `english = Translation_Pending_Marker` (R2.4, R8.11).
- non-English + SampleAgent/NoAgent: `english = Translation_Pending_Marker` (= literal `"translation pending (no model)"`) (R2.6).

Composed intake `text`:

```
<english-or-marker>

[Original (<language>)]: <free_text_original>
[Reporter type: <reporter_type>]
```

The Front_Door never stores a fabricated/machine-guessed translation (R2.8): `english` is only an active-agent translation, identical English text, or the marker.

### Intake payload (R6.1–6.3)

```python
payload = {
  "source": "reporter",                         # R6.1 (literal)
  "text": composed_text,                         # R6.3
  "device": device["brand"],
  "manufacturer": MAKER,
  "event_date": yyyymmdd_or_empty,
  "product_code": device["product_code"],
  "reporter": follow_up_contact or "",
  "external_id": session_submission_id,          # stable per confirmation -> stable REP id + dedupe
  "reporter_type": reporter_type,                # R6.2 (passed through)
}
code, res = intake.submit(payload, kind="reporter", default_source="reporter")
```

`external_id` is a deterministic id derived from the confirmed session (e.g. the `session_id`), so one confirmation always yields the same `vigil_id` and a re-POST is de-duplicated rather than creating a second complaint (Property 3).

**Field-map note:** `intake.settings()["field_map"]` has no `"reporter"` kind, so `apply_map` passes these already-Vigil-named fields through unchanged (first-non-empty-wins). `reporter_type` is not a recognised `to_complaint` field, so it is also carried inside the composed `text`; no `vigil.py` or `intake.py` edits are required.

## Error Handling

| Condition | Handling | Requirement |
|---|---|---|
| Unknown `device_slug` | Serve landing with no pre-filled device; require device selection before submit | 1.4 |
| Reporter-type not chosen | Block interview start; prompt to choose | 3.4 |
| Empty free-text description | Reject submission with "a description is required"; keep all prior answers | 2.7 |
| Non-English + no model-backed agent | Store `Translation_Pending_Marker`; never fabricate | 2.6, 2.8 |
| Model-backed agent cannot translate | `translate_to_english` → `None` → store marker | 8.11, 2.4 |
| `next_question` returns neither question nor `complete` (or raises) | End interview, preserve answers, go to review with "ended without completion" indication | 4.9 |
| `intake.submit` → 400 `rejected` | Show plain-language error from `res["error"]`; keep answers; require re-confirm; create no complaint | 6.6, 6.8 |
| `intake.submit` → 200 `duplicate` | Show existing `REP-xxxxxxxx` + "already received"; create no new complaint | 6.5, 6.8 |
| `intake.submit` → 202 `queued` | Show `REP-xxxxxxxx`; build receipt | 6.4, 6.7, 7.1 |
| QR SVG generation fails for a device | Omit that QR, show an error indication naming the device, keep rendering the rest | 10.6 |
| Empty device catalogue | Show zero QRs + "no devices available" message | 10.5 |
| Reporting page render fails | No-auth error page with retry to the same URL | 1.9 |

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — a formal statement about what the system should do, bridging human-readable specifications and machine-verifiable guarantees.*

### Property 1: Question-loop termination

For all `(reporter_type, reporter_language, answer_sequence)` and any `Agent` implementation, running the interview loop ends after at most 8 questions, in a terminal state that is either `next_question` returned `complete` or the Question_Cap of 8 was reached. The invariant `questions_asked <= 8` holds at every step; no input yields an unbounded interview.

**Validates: Requirements 4.5, 4.3, 11.1**

### Property 2: UNKNOWN preservation

For all `(field, answer_sequence)` where the reporter answered "I don't know" for `field`, the value of that field in the resulting Draft_3500A is exactly `UNKNOWN`, never overwritten by a guessed, blank, or defaulted value.

**Validates: Requirements 4.7, 4.10, 11.2**

### Property 3: Single complaint on submit

For all confirmed `(reporter_type, reporter_language, collected_answers)`, submitting through `intake.submit` results in exactly one complaint whose `source` is `reporter` for that confirmation; the payload always carries `source == "reporter"`, and re-submitting the same confirmation is de-duplicated by the existing `vigil_id` mechanism (no second complaint).

**Validates: Requirements 6.1, 6.7, 6.8, 11.3**

## Testing Strategy

Tests go under `tests/` alongside `test_agents.py`, `test_pipeline.py`, `test_console.py`, using the existing `conftest.py` fixtures (`data_dir`, `console`, `client`) which already force `THIRTY_AGENT=sample`, `THIRTY_SAMPLE_DELAY=0`, and a temp `VIGIL_DIR`. Everything runs offline in Demo_Mode (SampleAgent, no network).

### Property-based tests (Hypothesis) — `tests/test_front_door_properties.py`

Hypothesis is already available. Each property test runs ≥ 100 iterations and is tagged:
`# Feature: report-front-door, Property N: <text>`.

**P1 — Question-loop termination (stateful / generated sequences).**
- Strategies: `reporter_type ∈ sampled_from(["nurse_clinician","patient_family","company_staff"])`; `language ∈ sampled_from(["en","es","pt","ht","zz"])` (includes an unsupported code to exercise fallback); `answer_sequence = lists(one_of(text(), just("I don't know")), max_size=40)` — deliberately longer than the cap.
- Also run against an **adversarial agent** fixture whose `next_question` always returns a question (never `complete`) and a **malformed agent** that returns junk, to prove the Front_Door's cap/`safe_next_question` enforce termination regardless of the agent.
- Drive `run_interview(agent, start_state(...), feed(answer_sequence))`. Assert: at every step `state["questions_asked"] <= 8`; the loop returns; `end_reason ∈ {"complete","cap","malformed"}`; and `questions_asked <= 8` at the end.
- A small stateful model (`RuleBasedStateMachine`) can alternatively model answer/`idk` steps with an invariant `questions_asked <= 8` and a termination check.

**P2 — UNKNOWN preservation.**
- Strategy: generate an answer map over the Requirement-4 fields where each field is either a random non-empty value or the "I don't know" marker; record which fields were "I don't know".
- Feed through `record_answer` + `to_draft_3500a`. Assert: for every field marked "I don't know", the Draft_3500A value is exactly `UNKNOWN`; and no non-IDK field that was answered is `UNKNOWN` unless left blank (guards against accidental overwrite).

**P3 — Single complaint on submit.**
- Strategy: generate confirmed `(reporter_type, language, collected_answers)`; build the payload via `to_intake_payload`.
- Use a real temp `VIGIL_DIR` (point `intake.INTAKE/RAW/INDEX` at it) so `intake.submit` runs its real dedupe. Call `intake.submit(payload, kind="reporter", default_source="reporter")`.
- Assert: exactly one new row appears in `intake.index.csv` for the returned `vigil_id`; the stored complaint JSON has `source == "reporter"`; the `vigil_id` matches `REP-...`. Then **call submit a second time with the same payload** and assert the result is `duplicate` and the index row count is unchanged (single-complaint invariant under re-submission). Monkeypatch `vigil.process` to a no-op so the test stays offline and fast.

### Unit / integration tests (example-based)

- `tests/test_front_door.py` (Flask `client`): `GET /report` and `/report/<slug>` return 200 within the budget; known slug pre-fills device, unknown slug prompts selection (R1.3/1.4); language picker has exactly 4 options (R2.1); reporter-type gate (R3.4); empty description rejected with answers retained (R2.7); review shows "not known" for UNKNOWN (R5.2); confirm with sample agent → `REP-xxxxxxxx` and a downloadable PDF (R6.4, 7.1–7.3); duplicate and rejected paths (R6.5, 6.6); NoAgent → single-screen checklist (R8.7).
- `tests/test_agents.py` additions: every agent exposes `next_question` and `translate_to_english`; SampleAgent returns questions in each of the 4 languages and falls back for an unknown language (R8.2, R8.3); SampleAgent/NoAgent `translate_to_english` return `None` (R8.10); SampleAgent makes zero network calls (assert via a patched `requests` that raises if used) (R8.4).
- `tests/test_console.py` additions: a `source="reporter"` row renders the badge and a 0–100 score; a non-reporter/empty-source row renders neither (R9.1, 9.2, 9.7); all-known → 100, all-UNKNOWN → 0 (R9.4, 9.5).
- QR tests: `qr_svg("/report/AF")` returns a well-formed `<svg>`; the integrations view renders exactly 8 inline SVGs encoding `/report/<slug>` (R10.2, R10.3, R10.4); a forced `QRError` for one device omits it and shows an error indication while the rest render (R10.6); empty catalogue → zero QRs + message (R10.5).
- Receipt tests: nurse/clinician receipt contains the exact `21 CFR 803.30` line; patient/family receipt omits regulatory citations (R7.4, R7.5).

**Why these test types.** The three core behaviours are universal over inputs (termination, value-preservation, submission count), so they are property tests. QR rendering, PDF content, badge/score display, and route wiring are example/integration checks — behaviour that does not vary meaningfully across 100 random inputs, so example-based tests are the right tool there.

## Templates — concurrent-edit note

Templates in `dashboard_v2/templates/` are being edited in another session concurrently. To avoid collisions, all Front_Door template work is isolated into clearly named, self-contained partials and a dedicated stylesheet block rather than large inline edits to shared files:

- New: `templates/report/landing.html`, `report/interview.html`, `report/review.html`, `report/done.html`, `report/checklist.html`, and `report/_mobile.css` (16px/44px rules).
- Additions to shared files are confined to small, named includes: a `{% include "integrations/_qr_panel.html" %}` on `integrations.html`, and a `{% include "_reporter_badge.html" %}` / `{% include "_completeness.html" %}` on `complaints.html` / `complaint.html`.
- The task plan sequences template work so it can be coordinated/merged after the concurrent edits land; the Python blueprint, interview logic, QR, receipt, and agent methods are independent of the template merge and can proceed first.

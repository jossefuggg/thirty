# Implementation Plan: report-front-door

## Overview

This plan implements the public, no-login "Report a device problem" front door as a new `thirty/reporter/` package plus `Agent` interface additions and console integration, submitting confirmed reports through the existing `intake.submit(...)` only (never editing `vigil.py`). Everything runs local/offline.

Tasks are ordered so dependencies are respected and so the shared template surface is isolated into one contiguous, clearly labelled block:

1. Pure logic (`interview.py`, `qr.py`, `receipt.py`) and `Agent` methods first — these are Flask- and template-independent, so the property tests can run against them without templates.
2. The Flask blueprint and routes.
3. Console logic (`is_reporter`, `completeness_score`) in `dashboard_v2/app.py`.
4. **TEMPLATE BLOCK** — all `dashboard_v2/templates/` work grouped together so it can be merged after the concurrent template edits land. No Python/logic task depends on this block.
5. Wiring (`init_app` mount into the console, `get_agent` check).
6. Tests, co-located right after the unit they cover plus the dedicated property-based test file, ending with a full-suite run.

Unit/integration test sub-tasks and property-based test sub-tasks are marked optional with `*`.

## Tasks

- [x] 1. Create the reporter package and pure interview state model
  - [x] 1.1 Scaffold the `thirty/reporter/` package
    - Create `thirty/reporter/__init__.py` exporting the public surface (`init_app`, `qr_svg`, `build_receipt`, and the `interview` reducers)
    - Add module docstrings describing the single-pipeline-entry rule (submission only via `intake.submit`, never `vigil.process`)
    - _Requirements: 6.1_
    - _Design: Components and Interfaces §1 (Front_Door blueprint package layout)_

  - [x] 1.2 Implement the pure interview state model in `thirty/reporter/interview.py`
    - Define constants `QUESTION_CAP = 8`, `IDK = "__IDK__"`, `UNKNOWN = "UNKNOWN"`, and the Requirement-4 field order
    - Implement pure reducers: `start_state(reporter_type, language, device_key)`, `record_answer(state, field, raw_value, idk)` (IDK maps to `UNKNOWN` and is never overwritten), `should_continue(state)`, `end_interview(state, reason)` with `reason in {"complete","cap","malformed"}`
    - Maintain the invariant `questions_asked == len(asked)` and keep `questions_asked <= 8`
    - _Requirements: 4.2, 4.5, 4.7, 4.10_
    - _Design: Components and Interfaces §2 (Interview state model); Data Models (Answers_So_Far)_

  - [x] 1.3 Implement field mapping and the loop driver in `thirty/reporter/interview.py`
    - Implement `to_draft_3500a(state)` (fill every missing required field with `UNKNOWN`) and `to_intake_payload(state, free_text, english_text)` using the field→3500A→intake mapping table
    - Implement `safe_next_question(agent, answers_view)` that wraps the agent call in try/except, validates the question-object shape, and returns `"complete"`/validated question/`malformed`
    - Implement `run_interview(agent, state, answer_source)` (pure driver reused by tests) enforcing the cap independently of the agent and ending on `complete`/`cap`/`malformed`
    - Normalize `event_date` to `YYYYMMDD`; missing/UNKNOWN date → empty `event_date`
    - _Requirements: 4.1, 4.3, 4.5, 4.9, 4.10, 6.3_
    - _Design: Components and Interfaces §2 (loop driver, safe_next_question); Data Models (Field → 3500A and → intake payload mapping)_

- [x] 2. Implement the pure-Python QR→SVG generator in `thirty/reporter/qr.py`
  - Implement `qr_svg(data, *, module_px=4, quiet=4) -> str` as a vendored, self-contained byte-mode encoder (EC level M, fixed mask) emitting a complete `<svg>` string (black modules on white), raising `QRError` on encode failure
  - No network, no CDN, no new dependency; payload is the fixed `/report/<slug>` form
  - _Requirements: 10.3, 10.4, 10.6_
  - _Design: Components and Interfaces §4 (QR SVG generator)_

  - [x] 2.1 Write unit tests for the QR generator
    - Assert `qr_svg("/report/AF")` returns a well-formed `<svg>` element; assert a `QRError` is raised on a forced encode failure
    - Add these to `tests/test_front_door.py`
    - _Requirements: 10.3, 10.4, 10.6_

- [x] 3. Implement the fpdf2 PDF receipt builder in `thirty/reporter/receipt.py`
  - Implement `build_receipt(ref_number, summary, reporter_type, language) -> bytes` mirroring `vigil.py`'s fpdf2 setup (bundled `DejaVuSans`/`DejaVuSans-Bold` from `thirty/fonts`, `Helvetica` fallback)
  - Include title, `Reference_Number` (`REP-xxxxxxxx`), plain-words summary (UNKNOWN rendered as "not known"), and submission date
  - When `reporter_type == "nurse_clinician"`, append the exact line `Copy for your facility's records (user facility reporting, 21 CFR 803.30)`; when `patient_family`, omit all regulatory citations
  - _Requirements: 7.1, 7.2, 7.4, 7.5_
  - _Design: Components and Interfaces §5 (PDF receipt builder)_

  - [x] 3.1 Write unit tests for the receipt builder
    - Assert the nurse/clinician receipt contains the exact `21 CFR 803.30` line; assert the patient/family receipt omits regulatory citations
    - Add these to `tests/test_front_door.py`
    - _Requirements: 7.4, 7.5_

- [x] 4. Extend the Agent interface with `next_question` and `translate_to_english`
  - [x] 4.1 Add the two methods to the base in `thirty/agents/base.py`
    - Define `COMPLETE = "complete"` and document `next_question(answers_so_far)` (returns a question object or `COMPLETE`) and `translate_to_english(text, source_language)` in the module/class docstring
    - Base `Agent.next_question` raises `NotImplementedError`; base `Agent.translate_to_english` returns `None` (safe defer)
    - Implement `NoAgent.next_question` → returns `COMPLETE` immediately; `NoAgent.translate_to_english` → `None`
    - _Requirements: 8.1, 8.7, 8.11_
    - _Design: Components and Interfaces §3 (Agent interface additions; NoAgent)_

  - [x] 4.2 Implement the SampleAgent methods in `thirty/agents/sample.py`
    - Scripted ordered list over the Requirement-4 fields; `next_question` returns the first not-yet-`asked` field's question object with a 4-language string table (`en`, `es`, `pt`, `ht`), returning `COMPLETE` when all scripted fields have been asked
    - Unsupported language → fall back to `en` strings; honor `THIRTY_SAMPLE_DELAY` via existing `_wait()`; zero network calls
    - `translate_to_english` → `None` (defers; marker stored by Front_Door)
    - _Requirements: 8.2, 8.3, 8.4, 8.8, 8.9, 8.10_
    - _Design: Components and Interfaces §3 (SampleAgent)_

  - [x] 4.3 Implement the model-backed agent methods in `thirty/agents/local_model.py` and `thirty/agents/claude_model.py`
    - Add a `NEXT_Q` prompt (in `local_model.py`, reused by `ClaudeAgent`) fed `answers_so_far`; parse with existing `_json`/`_extract_json` to one question object or `{"complete": true}`; on parse failure/empty/invalid → return `COMPLETE`
    - Add a `TRANSLATE` prompt; `translate_to_english` returns the stripped output or `None` on empty/`CANNOT_TRANSLATE`/exception — never fabricates
    - _Requirements: 8.5, 8.6, 8.8, 8.9, 8.11_
    - _Design: Components and Interfaces §3 (LocalModelAgent / ClaudeAgent)_

  - [x] 4.4 Add agent tests to `tests/test_agents.py`
    - Assert every agent exposes `next_question` and `translate_to_english`; SampleAgent returns questions in all 4 languages and falls back for an unknown language; SampleAgent/NoAgent `translate_to_english` return `None`; SampleAgent makes zero network calls (patched `requests` that raises if used)
    - _Requirements: 8.2, 8.3, 8.4, 8.10_

- [x] 5. Checkpoint - pure logic and agents
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Write the property-based tests in `tests/test_front_door_properties.py` (PBT)
  - [x] 6.1 **[PBT]** Property 1 — Question-loop termination
    - **Property 1: Question-loop termination**
    - **Validates: Requirements 4.3, 4.5, 11.1**
    - Strategies: `reporter_type` sampled from the three types; `language` sampled from `["en","es","pt","ht","zz"]` (unsupported `zz` exercises fallback); `answer_sequence = lists(one_of(text(), just("I don't know")), max_size=40)` (longer than the cap)
    - Also run against an adversarial agent (`next_question` always returns a question, never `complete`) and a malformed agent (returns junk) to prove the Front_Door cap/`safe_next_question` enforce termination regardless of the agent
    - Drive `run_interview(agent, start_state(...), feed(answer_sequence))`; assert `state["questions_asked"] <= 8` at every step, the loop returns, and `end_reason in {"complete","cap","malformed"}`
    - Tag: `# Feature: report-front-door, Property 1`; ≥ 100 iterations
    - _Design: Testing Strategy (P1); Correctness Properties §Property 1_

  - [x] 6.2 **[PBT]** Property 2 — UNKNOWN preservation
    - **Property 2: UNKNOWN preservation**
    - **Validates: Requirements 4.7, 4.10, 11.2**
    - Strategy: generate an answer map over the Requirement-4 fields where each field is a random non-empty value or the "I don't know" marker; record which fields were "I don't know"
    - Feed through `record_answer` + `to_draft_3500a`; assert every "I don't know" field is exactly `UNKNOWN` in the Draft_3500A, and no answered non-IDK field is `UNKNOWN` unless left blank
    - Tag: `# Feature: report-front-door, Property 2`; ≥ 100 iterations
    - _Design: Testing Strategy (P2); Correctness Properties §Property 2_

  - [x] 6.3 **[PBT]** Property 3 — Single complaint on submit
    - **Property 3: Single complaint on submit**
    - **Validates: Requirements 6.1, 6.7, 6.8, 11.3**
    - Strategy: generate confirmed `(reporter_type, language, collected_answers)`; build the payload via `to_intake_payload`
    - Point `intake.INTAKE/RAW/INDEX` at a real temp `VIGIL_DIR` so real dedupe runs; monkeypatch `vigil.process` to a no-op (stays offline); call `intake.submit(payload, kind="reporter", default_source="reporter")`
    - Assert exactly one new `intake.index.csv` row for the returned `vigil_id`, stored complaint `source == "reporter"`, `vigil_id` matches `REP-...`; then re-submit the same payload and assert `duplicate` with unchanged row count
    - Tag: `# Feature: report-front-door, Property 3`; ≥ 100 iterations
    - _Design: Testing Strategy (P3); Correctness Properties §Property 3_

- [x] 7. Implement the Front_Door blueprint and routes in `thirty/reporter/front_door.py`
  - [x] 7.1 Create the blueprint, session store, and landing/start routes
    - Define the Flask `Blueprint` and `init_app(app)`; implement opaque `session_id` cookie + per-session JSON state under `VIGIL_DIR/reporter_sessions/<session_id>.json`
    - `GET /report` and `GET /report/<device_slug>` (case-insensitive catalogue match from `DEVICES`; unknown slug → no pre-fill, prompt selection); wrap each `GET` render in try/except returning a no-auth retry error page; `GET` does no model call
    - `POST /report/start` records language + reporter-type (+ device), rejects if reporter-type missing; detect `agent.id == "none"` to route to the single-screen checklist
    - Add `plain_mode(reporter_type)` helper for patient/family plain-language selection
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 1.8, 1.9, 2.1, 2.2, 3.1, 3.2, 3.4, 8.7_
    - _Design: Components and Interfaces §1 (routes, session/state, render failure, performance)_

  - [x] 7.2 Implement the interview and review routes
    - `GET /report/interview` (render current single question with "I don't know" affordance, or redirect to review); `POST /report/answer` (append answer or UNKNOWN, enforce 8-cap, call `safe_next_question`, advance or end)
    - `GET /report/review` (plain-words summary, UNKNOWN shown as "not known", editable) and `POST /report/review/edit` (revise an answer, return to review)
    - Accept free-text up to 5,000 characters in the selected language
    - _Requirements: 2.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 5.1, 5.2, 5.3, 5.5_
    - _Design: Components and Interfaces §1 (interview/review routes); §2 (loop driver)_

  - [x] 7.3 Implement confirm, done, and receipt routes with bilingual text and intake submission
    - `POST /report/confirm`: reject empty free-text ("a description is required", keep answers); fill missing→UNKNOWN; compose bilingual `text` (en → identical; non-en model agent → `translate_to_english` or `Translation_Pending_Marker`; non-en Sample/NoAgent → marker; never fabricate); build payload with `source="reporter"`, `reporter_type`, deterministic `external_id` from the confirmed session; call `intake.submit(payload, kind="reporter", default_source="reporter")`
    - Handle 202 queued → `/report/done/<ref>`; 200 duplicate → existing `REP-...` + "already received"; 400 rejected → plain-language error from `res["error"]`, retain answers, require re-confirm
    - `GET /report/done/<ref>` shows the Reference_Number + receipt link; `GET /report/receipt/<ref>.pdf` builds via `build_receipt`, writes to `VIGIL_DIR/reports/receipts/REP-...pdf`, serves via `send_from_directory`
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 2.8, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.1, 7.2, 7.3_
    - _Design: Components and Interfaces §1; Data Models (bilingual text storage, intake payload); Error Handling_

  - [x] 7.4 Write route unit/integration tests in `tests/test_front_door.py`
    - Using the Flask `client` fixture: `GET /report` and `/report/<slug>` return 200 within budget; known slug pre-fills, unknown slug prompts selection; language picker has exactly 4 options; reporter-type gate; empty description rejected with answers retained; review shows "not known"; confirm (sample agent) → `REP-xxxxxxxx` + downloadable PDF; duplicate and rejected paths; NoAgent → single-screen checklist
    - _Requirements: 1.3, 1.4, 2.1, 2.7, 3.4, 5.2, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 8.7_

- [x] 8. Implement console badge and completeness-score logic in `dashboard_v2/app.py`
  - Add `is_reporter(row)` (`row.get("source") == "reporter"`; absent/empty → False) and register the `"reporter": ("Reporter","user")` entry in `SOURCES`
  - Add `completeness_score(row)` over `REQUIRED_3500A` reading drafted fields: integer 0–100, all-known → 100, all-UNKNOWN → 0, computed only for reporter-source rows
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  - _Design: Components and Interfaces §6 (Console badge + completeness score)_

  - [x] 8.1 Add console tests to `tests/test_console.py`
    - A `source="reporter"` row renders the badge and a 0–100 score; a non-reporter/empty-source row renders neither; all-known → 100, all-UNKNOWN → 0
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.7_

- [ ] 9. TEMPLATE BLOCK — all `dashboard_v2/templates/` work (shared integration surface; do as one contiguous, coordinated block; no Python task depends on this)
  - [x] 9.1 Create the Front_Door template partials and mobile stylesheet
    - New files: `dashboard_v2/templates/report/landing.html`, `report/interview.html`, `report/review.html`, `report/done.html`, `report/checklist.html`, and `report/_mobile.css`
    - `_mobile.css` sets `viewport`, body text `font-size: 16px`, and `min-width/min-height: 44px` on every button/link-button/option control; patient/family text omits regulatory citations
    - _Requirements: 1.6, 1.7, 2.1, 3.1, 4.6, 5.1, 5.2, 8.7_
    - _Design: Templates — concurrent-edit note; Components and Interfaces §1 (mobile-first rendering, patient/family plain language)_

  - [x] 9.2 Create the integrations QR panel partial `dashboard_v2/templates/integrations/_qr_panel.html`
    - Render exactly 8 inline SVGs (one per `DEVICES` entry) via `qr_svg("/report/<slug>")`; per-device try/except omits a failed device with a named error indication while others render; empty catalogue → zero QRs + "no devices available" message
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_
    - _Design: Components and Interfaces §4; Error Handling_

  - [x] 9.3 Create the console badge/score include partials
    - New files `dashboard_v2/templates/_reporter_badge.html` and `_completeness.html` driven by `is_reporter(row)` / `completeness_score(row)`
    - _Requirements: 9.1, 9.2, 9.6, 9.7_
    - _Design: Components and Interfaces §6; Templates — concurrent-edit note_

  - [ ] 9.4 Wire the partials into the shared templates via small named includes only
    - Add `{% include "integrations/_qr_panel.html" %}` to `integrations.html`; add `{% include "_reporter_badge.html" %}` and `{% include "_completeness.html" %}` to `complaints.html` and `complaint.html`
    - Keep edits to shared files confined to these include lines to avoid collisions with the concurrent template edits
    - _Requirements: 9.1, 9.6, 10.1_
    - _Design: Templates — concurrent-edit note_

- [x] 10. Wire the blueprint and agent selection into the console
  - Call `thirty.reporter.init_app(app)` from the console init block in `dashboard_v2/app.py`, right next to the existing `intake.init_app(app)` mount
  - Confirm `get_agent()` in `thirty/agents/__init__.py` selects the active agent unchanged and that the Front_Door reads `agent.id` for the NoAgent checklist branch (add wiring only if a selector hook is missing)
  - _Requirements: 6.1, 8.7_
  - _Design: Overview (Console integration); Components and Interfaces §1 (init_app), §3 (get_agent wiring)_

  - [x] 10.1 Write a wiring/integration test
    - Assert the `/report` routes are registered on the console app and that a confirmed sample-agent submission appears as a `reporter`-source complaint in the console views (badge + score) end-to-end through `intake.submit`
    - Add to `tests/test_front_door.py`
    - _Requirements: 6.1, 6.7, 9.1_

- [x] 11. Final checkpoint - run the full suite
  - Run `.venv/bin/python -m pytest -q` and ensure all tests pass; ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (unit/integration and property-based tests) and can be skipped for a faster MVP.
- Property-based test sub-tasks are labelled **[PBT]** and each references its property number and the requirement clauses it validates.
- All Front_Door template work is grouped into Task 9 (TEMPLATE BLOCK) so it can be merged after the concurrent `dashboard_v2/templates/` edits land; no Python/logic task depends on it.
- No task edits `vigil.py`; submission is only through `intake.submit(...)` with `source="reporter"`.
- Everything is local/offline: pure-Python QR→SVG, `fpdf2` receipts, SampleAgent in Demo_Mode, no network calls.
- Each task references the requirement numbers it implements and the relevant design component.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2", "3", "4.1"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.1", "4.2", "4.3", "8"] },
    { "id": 3, "tasks": ["4.4", "6.1", "6.2", "6.3", "7.1", "8.1", "9.1", "9.2", "9.3"] },
    { "id": 4, "tasks": ["7.2", "9.4"] },
    { "id": 5, "tasks": ["7.3", "10"] },
    { "id": 6, "tasks": ["7.4", "10.1"] }
  ]
}
```

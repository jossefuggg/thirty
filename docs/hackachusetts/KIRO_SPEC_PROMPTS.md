# Kiro spec prompts (paste one at a time, in this order)

Setup, before spec 1:
1. Open the thirty repo folder in Kiro, on the `hackachusetts` branch.
2. The steering file `.kiro/steering/hackathon.md` is already in this branch.
3. Kiro panel > Generate Steering Docs. Read them, fix anything wrong, commit:
   `git add .kiro && git commit -m "Kiro steering for Hackachusetts"`.
4. For each spec below: Kiro panel > Specs > new spec, paste the prompt, review requirements,
   design and tasks, then run the tasks. Commit after each spec (keep the `.kiro/specs/` files).

Time boxes: spec 1 by 11:30, spec 2 by 15:00, spec 3 by 17:00, spec 4 only if ahead.
Record the video by 18:30 whatever state you are in.

---

## Spec 1 - Claude agent plugin (about 45 min)

Add a built-in agent plugin "Claude agent" at thirty/plugins/builtin/claude/ that implements the Agent
interface in thirty/agents/base.py (classify, draft_report, follow_up_questions, health) using the
Anthropic Messages API (POST https://api.anthropic.com/v1/messages) with the requests library, no SDK.

- Settings (plugin.json): api_key (secret, falls back to env ANTHROPIC_API_KEY), model (string, default
  "claude-sonnet-5-5"), timeout (number, default 60).
- Reuse the prompts and JSON parsing from thirty/agents/local_model.py so decisions stay comparable;
  ask for JSON only, strip code fences, fall back to the UNREADABLE result on bad output.
- temperature 0. Return exactly the documented result shapes.
- health() does a 1-token call and reports latency, model name and ok/error.
- Plugins screen shows it like the other agents. When it is the active agent, replace the
  "0 bytes to cloud AI" badge with "Cloud model (demo, sample data)".
- Tests: mock HTTP and check each method returns the right shape, including bad-JSON fallback.
- Update docs/PLUGINS.md and README (one paragraph each).

---

## Spec 2 - Reporter front door (main feature, about 3 h)

Build a public "Report a device problem" page for nurses, doctors and patients, served by the console at
/report (and /report/<device_slug> so each device can have its own QR code). No login.

Flow:
1. Reporter picks who they are (nurse or clinician / patient or family / company staff) and describes what
   happened in plain words. The device is pre-filled when they came from a device QR code.
2. A new agent call next_question(answers_so_far) returns either the next single follow-up question
   (plain language, one at a time, adapted to the reporter type) or "complete". It must collect what
   Form 3500A and 21 CFR 803 need: device and model, lot or serial if known, what happened, patient
   outcome (death, hospitalisation, injury, none), whether the device malfunctioned, date of the event,
   date the reporter noticed, and contact details for follow-up. "I don't know" is a valid answer and
   becomes UNKNOWN. Max 8 questions.
3. A review screen shows the summary in plain words; the reporter confirms.
4. On confirm, submit through intake.submit() with source "reporter" and the reporter type, so the
   existing pipeline scores, classifies, drafts and starts the clock. Show a reference number.
5. A downloadable PDF receipt (fpdf2) for the reporter. For a clinician at a hospital, label it
   "Copy for your facility's records (user facility reporting, 21 CFR 803.30)".

Also:
- Add next_question() to the Agent interface with implementations in the sample agent (scripted
  questions, works offline), the local model agent and the Claude agent. NoAgent returns a fixed
  checklist form.
- In the console, complaints from the front door show a "Reporter" source badge and the
  completeness score at intake.
- Add a "QR codes" panel on the Integrations page: one QR per sample device linking to
  /report/<device_slug> (generate the QR as SVG in Python, no external service).
- Mobile-first layout using thirty.css. Large tap targets. Plain language, no regulation jargon
  shown to patients.
- Optional, only if time: a photo upload (stored locally with the complaint) and browser dictation
  for the description.
- Tests: the question loop stops at complete or 8 questions; submit creates a complaint with
  source "reporter"; UNKNOWN answers stay UNKNOWN in the draft.

---

## Spec 3 - Signal radar (about 1.5 h)

Add a "Radar" screen that watches public FDA data for the product codes the site cares about.

- Settings: list of product codes (pre-fill from the sample devices' codes).
- Fetch from the openFDA device event API (https://api.fda.gov/device/event.json) and device recall API
  (https://api.fda.gov/device/recall.json): monthly counts of reports per product code and per
  manufacturer for the last 24 months, plus recent recalls. Cache results locally; work offline
  from the cache; show "data as of <date>".
- Flag a spike when a month is above the trailing 6-month mean plus 2 standard deviations.
- Screen: one chart per product code (own reports vs other manufacturers), list of spikes,
  list of recent recalls on the same codes, each with a link to the FDA record.
- A spike on a code that matches an open internal complaint pattern raises a "Check this" card on
  the Command Center linking to both.
- Public data only; this module sends no complaint data anywhere. Say so on the screen.
- Tests with recorded openFDA responses (no network in tests).

---

## Spec 4 - Recall copilot (stretch)

From a pattern alert or a radar spike, a "Start field action review" button opens a draft workspace:
- Health hazard evaluation draft (hazard, affected population, severity, likelihood) with UNKNOWN
  where facts are missing.
- 21 CFR 806 check: does this correction or removal need a report within 10 working days, with the
  reason.
- Affected lots and devices from the complaints in the pattern.
- Draft customer letter and patient letter.
- Every section needs a named reviewer's approval, written to the signed audit trail. Nothing is sent.

---

## Write-up line to use
"Thirty 1.2.1 (the reporting core) existed before today. Today, in Kiro, we built the Claude agent
plugin, the reporter front door, the signal radar[, and the recall copilot]. Specs are in .kiro/specs."

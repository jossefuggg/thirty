---
inclusion: always
---

# Hackachusetts (24 Oct 2026): context for every task

## What this repo is
Thirty: medical device complaint reporting software. Manufacturers must report deaths, serious injuries
and dangerous malfunctions to the FDA within 30 calendar days (5 work days when remedial action is needed),
21 CFR 803. Thirty scores each complaint, an agent pre-decides REPORTABLE / NEEDS_INFO / NOT_REPORTABLE,
drafts Form 3500A, and a named human approves and files. "Thirty drafts; a human files."

Thirty 1.2.1 existed before today (built after the Dell x NVIDIA hackathon, 3 Oct 2026). Today's work is
new modules built in Kiro on the `hackachusetts` branch. Keep the line between the two clear in commits
and docs.

## Today's goal
Track: Biotech & healthcare. Submission 20:00 sharp. Close the loop around the existing reporting core:
1. Claude agent plugin (cloud model for the demo, sample data only).
2. Reporter front door: nurses, doctors and patients report a device problem in plain language; the agent
   asks follow-up questions until the FDA fields are complete, then submits into the existing intake API.
3. Signal radar: openFDA MAUDE and recall data for the same product codes; alert on spikes.
4. Recall copilot (stretch): from a pattern alert, draft the health hazard evaluation, the 21 CFR 806
   check, affected lots and customer/patient letters for human approval.

## How the code works (do not break)
- Agent interface: `thirty/agents/base.py` (classify, draft_report, follow_up_questions, health).
  Result shapes are documented there; new agents must return exactly those shapes.
- Plugins: `thirty/plugins/builtin/<id>/plugin.json` + `plugin.py` with `create(settings) -> Agent`.
  Contract in `docs/PLUGINS.md`. The local-model agent (`thirty/agents/local_model.py`) talks to any
  OpenAI-compatible server, including Ollama at http://localhost:11434/v1.
- Intake: `intake.py`, `POST /api/v1/complaints` (header X-API-Key, JSON with `text`, `device`,
  `event_date`, `reporter`, `external_id`, `source`, `manufacturer`, `product_code`). New intake channels
  call `intake.submit()` or this endpoint; they never write to `decisions.csv` directly.
- Console: Flask app in `dashboard_v2/app.py` (run: `cd dashboard_v2 && python3 app.py`, port 5001),
  Jinja templates in `dashboard_v2/templates/`, styles in `dashboard_v2/static/thirty/css/thirty.css`.
  Reuse its tokens and components; add no new CSS framework.
- Demo mode: sample agent and 40 invented complaints (Northwind Medical) when no model is configured.
- Tests: `pytest` (58 passing at start of day) must pass before every commit. Add tests for new modules.

## Rules
- Python 3.11, Flask, requests, fpdf2. Prefer `requests` over adding SDKs.
- Secrets only via plugin settings of type `secret` or environment variables. Never commit keys.
- Use only invented companies, devices and people in sample data. Real public FDA data is fine for the radar.
- The agent never invents facts: unknown fields are "UNKNOWN". Signals only raise priority, never lower it.
- A human approves every decision. Nothing is filed automatically.
- Brand: Paper #F7F5F0, Ink #15181D, Coral #FF5A3C (one key action per screen, deadlines under 7 days,
  REPORTABLE), Amber #F2B134 (NEEDS INFO only). Instrument Serif for headlines, Manrope for the rest.
- UI copy: plain, specific, numbers first, no drama.
- Small commits with clear messages, one feature per commit.

## Never say (UI, docs, README, commits)
"The only offline tool", "fully automated", "replaces your QMS", "Thirty submits to the FDA",
"email intake works", "$2.4M penalties", "FDA approved/cleared", "open source".
When the Claude plugin is active the app must NOT show "0 bytes to cloud AI"; show
"Cloud model (demo, sample data)" instead. The local-model plugin keeps the 0-bytes badge.

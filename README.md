# Thirty

**Medical device complaint reporting, on the clock. Thirty drafts; a human files.**

Manufacturers must report deaths, serious injuries and dangerous malfunctions to the FDA within 30 days
(5 work days when urgent action is needed) under 21 CFR 803. Thirty reads every complaint the minute it
arrives, scores it, decides what the FDA must be told, drafts the Form 3500A, and hands it to a named
person who approves and files. The agent runs on a local model: 0 bytes to cloud AI.

Thirty started as "Vigil" at the Dell x NVIDIA AI Hackathon (Boston, 3 October 2026). The product plan
and progress are in [`docs/THIRTY_PLAN.md`](docs/THIRTY_PLAN.md); the code tour is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## What it does

1. **Rules (every complaint, instant):** priority score from red-flag words, event type and distress;
   completeness and duplicate checks; spike detection per device family. Signals only raise priority.
2. **AI check (every complaint):** reportable / not reportable / needs info, the legal reason, the deadline.
3. **Agent (reportable or unsure):** starts the clock, drafts the Form 3500A, alerts the team, writes
   trend alerts against FDA history.
4. **Human:** approves every decision in the console (or in Telegram). Nothing is silently dropped;
   every decision is logged with its reason.

## Run it in development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cd dashboard_v2 && python3 app.py        # http://localhost:5001
```

The console runs without a model: pages load, the system panel shows the local model as offline, and
complaints can be reviewed from an existing `decisions.csv`. Processing new complaints needs an
OpenAI-compatible local model at `VIGIL_LLM_BASE` (default `http://localhost:8000/v1`).

Tests and screenshots:

```bash
pip install -r requirements-dev.txt
pytest                                   # console + pipeline tests
python3 tools/screenshots.py             # every screen -> docs/screenshots/ (headless Chromium)
```

## Pipeline CLI (`vigil.py`)

```
python3 vigil.py test                              # check model + Telegram
python3 vigil.py replay --csv demo_set.csv --delay 5
python3 vigil.py sync                              # pull approvals made in Telegram
python3 vigil.py import-history                    # build history.csv (long-term memory), no model
python3 vigil.py reset                             # clean slate
```

## Brand

The UI uses the Thirty brand kit (`brand/`): Paper & Coral palette, Instrument Serif for headlines and
big numbers, Manrope for everything else, self-hosted fonts, vector logos. Coral marks one key action
per screen, deadlines under 7 days and REPORTABLE; amber marks NEEDS INFO; nothing else is coloured.
Dark mode: the moon button in the sidebar (`data-theme="dark"`).

## Data

Public FDA data via openFDA (MAUDE device reports) for the long-term memory. All sample complaints,
companies, devices and people in this repository are invented.

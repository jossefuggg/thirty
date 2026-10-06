# Thirty

**Medical device complaint reporting, on the clock. Thirty drafts; a human files.**

Manufacturers must report deaths, serious injuries and dangerous malfunctions to the FDA within 30 days
(5 work days when urgent action is needed) under 21 CFR 803. Thirty reads every complaint the minute it
arrives, scores it, decides what the FDA must be told, drafts the Form 3500A, and hands it to a named
person who approves and files. The agent runs on a local model: **0 bytes to cloud AI**.

Thirty is a desktop app (macOS, Windows, Linux) with a local web console inside. It started as "Vigil"
at the Dell x NVIDIA AI Hackathon (Boston, 3 October 2026). Progress and plan:
[`docs/THIRTY_PLAN.md`](docs/THIRTY_PLAN.md); code tour and decisions: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## What it does

1. **Rules (every complaint, instant):** priority score from red-flag words, event type and distress;
   completeness and duplicate checks; spike detection per device family. Signals only raise priority.
2. **Agent (every complaint):** reportable / not reportable / needs info, the legal reason, the deadline,
   a drafted Form 3500A and follow-up questions. The agent is a plugin: sample agent, local model, or your own.
3. **Human:** approves every decision in the console (or in Telegram on the hackathon setup). Nothing
   is silently dropped; every decision is logged with its reason.

Screens: Command Center, Complaints, complaint detail (with the reportability decision record),
Compliance Clock, Trends, Audit Log, Intake inbox, Integrations, Demo Control, Plugins, Licence &
updates, first-run setup. Screenshots in [`docs/screenshots/`](docs/screenshots/).

## Compliance record

What an inspector asks for, built in and model-free ([`docs/COMPLIANCE.md`](docs/COMPLIANCE.md)):

* **Reportability decision record** (21 CFR 803.18): a seven-question tree pre-filled by the agent,
  confirmed by a named reviewer with a written rationale, also for "not reportable". Optional
  21 CFR 820.35 complaint-record fields.
* **Reporting clocks per jurisdiction** from the awareness date: US FDA 30 / 5 work days, EU MDR and
  UK MHRA 2 / 10 / 15 days, Health Canada 10 / 30 days. Enabled per site under Licence & updates.
* **Signed, hash-chained audit trail**: every approve, info request, undo and recorded decision is
  written with the reviewer's name, the meaning of the signature and the time; the Audit Log verifies
  the chain and exports it.
* **Submission pack**: one zip per complaint with the drafted 3500A, the decision record, the clocks
  and the signed audit entries. A human files it through the regulator's channel.

## Run it in development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cd dashboard_v2 && python3 app.py          # http://localhost:5001
```

With no model configured this starts in **demo mode** (see below) and opens the first-run setup. Data
goes to the repository root unless `VIGIL_DIR` points elsewhere.

Desktop app in development (Electron window around the same console):

```bash
cd desktop && npm install && npm start
```

Tests and screenshots:

```bash
pytest                                     # console, pipeline, agents, plugins, setup, licensing
python3 tools/screenshots.py               # every screen -> docs/screenshots/ (headless Chromium)
```

## Build installers

Locally, one OS at a time:

```bash
pip install -r requirements.txt pyinstaller
cd desktop && npm ci && npm run dist       # freezes the backend, then electron-builder -> desktop/dist/
```

In CI: push a tag `v1.2.0` and `.github/workflows/release.yml` builds macOS (dmg), Windows (NSIS) and
Linux (AppImage, deb) installers and attaches them to a draft GitHub Release. Builds are unsigned until
the secrets in [`docs/RELEASING.md`](docs/RELEASING.md) are added. The app stores its data in the OS
app-data folder and works fully offline.

## Demo mode

When no model is configured (no `VIGIL_LLM_BASE`, no local-model plugin chosen), Thirty runs on the
**Sample agent** and seeds **sample data**: 40 invented complaints (Northwind Medical, eight invented
devices) covering every state of the 30-day clock, invented device history, and drafted PDFs. Dates
are relative to today and reseed once a day. A "Sample data" label shows in the top bar; Demo Control
replays six more complaints through the pipeline or resets the sample data. Choose "Start with my
site" in setup (or Settings → Licence & updates → Run first-run setup again) to start empty.

`THIRTY_AGENT=sample|local|none` forces the agent; `THIRTY_SAMPLE_DELAY` sets the sample agent's fake
latency; `python3 -m thirty.sample_data <folder>` reseeds by hand.

## Write a plugin

A plugin is a folder with `plugin.json` (id, name, version, capabilities, settings schema) and
`plugin.py` exposing `create(settings) -> Agent`, where `Agent` implements `classify`, `draft_report`,
`follow_up_questions` and `health`. Drop it into `<data folder>/plugins/` and enable it under
**Plugins**. Contract, result shapes and a working example:
[`docs/PLUGINS.md`](docs/PLUGINS.md), [`examples/plugins/keyword-agent/`](examples/plugins/keyword-agent/).

## Pipeline CLI (`vigil.py`, hackathon setup)

```
python3 vigil.py test                              # check the active agent (+ Telegram)
python3 vigil.py replay --csv demo_set.csv --delay 5
python3 vigil.py sync                              # pull approvals made in Telegram
python3 vigil.py import-history                    # build history.csv from MAUDE exports, no model
python3 vigil.py reset                             # clean slate
```

## Brand

The UI uses the Thirty brand kit (`brand/`): Paper & Coral palette, Instrument Serif for headlines and
big numbers, Manrope for everything else, self-hosted fonts, vector logos. Coral marks one key action
per screen, deadlines under 7 days and REPORTABLE; amber marks NEEDS INFO; nothing else is coloured.
Dark mode: the moon button in the sidebar.

## Data

Public FDA data via openFDA (MAUDE device reports) can be imported as long-term memory. All sample
complaints, companies, devices and people in this repository are invented.

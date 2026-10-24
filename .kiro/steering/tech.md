# Tech stack

## Languages & runtime

- **Python 3.11+** — pipeline, agents, console backend. Keep code 3.11-compatible (e.g. no backslashes in f-string expression parts).
- **JavaScript (vanilla)** — console frontend. No bundler, no framework.
- **Node.js / Electron** — desktop shell only.

## Backend / console

- **Flask 3 + Jinja2** templates (`dashboard_v2/`), served straight from templates with no build step.
- Vanilla JS, inline CSS (brand tokens), inline SVG icons. Pages poll JSON endpoints every 2–5 s; no websockets.
- `requests` for HTTP, `fpdf2` for Form 3500A PDFs.
- Optional signal libraries used by the rules layer, degrade gracefully if absent: `vaderSentiment`, `rapidfuzz`.

## AI agents

- Any **OpenAI-compatible** server (local model via `VIGIL_LLM_BASE`, default `http://localhost:8000/v1`).
- Agent is a single seam (`thirty/agents/base.py`) with three synchronous calls returning plain dicts: `classify`, `draft_report`, `follow_up_questions`, plus `health`.
- Agents are plugins (`thirty/plugins/`): a folder with `plugin.json` and `plugin.py` exposing `create(settings) -> Agent`.

## Data

- **Flat files only — no database.** CSV + JSON. System of record is `decisions.csv` (serialised with an flock on `decisions.csv.lock`). Compliance records in `decisions/<id>.json`; hash-chained audit in `audit.jsonl`.
- Code and data are separate: `CODE_DIR` (repo / frozen app) vs the data folder (`VIGIL_DIR`, else repo root). In the desktop app, data lives in the OS app-data folder.

## Desktop packaging

- **Electron shell + PyInstaller-frozen backend** spawned as a sidecar (`desktop/`). `electron-builder` produces DMG / NSIS / AppImage + deb. Auto-update via `electron-updater` against GitHub Releases, off by default.

## Common commands

### Development
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cd dashboard_v2 && python3 app.py          # console at http://localhost:5001
```
With no model configured this starts in **demo mode**. Data goes to the repo root unless `VIGIL_DIR` is set.

### Desktop app (development)
```bash
cd desktop && npm install && npm start
```

### Tests & screenshots
```bash
pytest                                     # console, pipeline, agents, plugins, setup, licensing
python3 tools/screenshots.py               # every screen -> docs/screenshots/ (headless Chromium)
```

### Build installers (one OS at a time)
```bash
pip install -r requirements.txt pyinstaller
cd desktop && npm ci && npm run dist       # freeze backend, then electron-builder -> desktop/dist/
```
In CI: push a tag `v1.2.0`; `.github/workflows/release.yml` builds and attaches installers to a draft GitHub Release.

### Pipeline CLI
```bash
python3 vigil.py test                              # check active agent (+ Telegram)
python3 vigil.py replay --csv demo_set.csv --delay 5
python3 vigil.py sync                              # pull Telegram approvals
python3 vigil.py import-history                    # build history.csv from MAUDE exports, no model
python3 vigil.py reset                             # clean slate
python3 -m thirty.sample_data <folder>             # reseed sample data by hand
```

## Key environment variables

- `VIGIL_DIR` — data folder (defaults to repo root).
- `VIGIL_LLM_BASE` / `VIGIL_LLM_MODEL` — local model endpoint; presence switches the default agent to `local`.
- `THIRTY_AGENT=sample|local|none` — force the active agent (`none` = manual review).
- `THIRTY_SAMPLE_DELAY` — sample agent fake latency.

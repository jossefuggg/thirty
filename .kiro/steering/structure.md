# Project structure

```
thirty/
├── vigil.py              # pipeline library + CLI (process, replay, sync, reset, test, import-history)
├── intake.py             # intake channels (REST / CSV / email); standalone on :5050 or mounted on console
├── pyproject.toml        # project metadata, deps, pytest config
├── requirements.txt      # runtime deps  |  requirements-dev.txt adds pytest + playwright
│
├── thirty/               # core package (the "thirty" namespace)
│   ├── config.py         # data_dir(), agent_id(), demo_mode(); CODE_DIR vs data folder
│   ├── agents/           # Agent seam: base.py (interface), local_model.py, sample.py, __init__ (get_agent)
│   ├── plugins/          # plugin registry; plugins/builtin/ holds sample + local built-ins
│   ├── decisions.py      # 21 CFR 803 decision tree + reportability records (decisions/<id>.json)
│   ├── jurisdictions.py  # reporting clocks per jurisdiction (US / EU / UK / CA)
│   ├── audit.py          # SHA-256 hash-chained audit trail (audit.jsonl)
│   ├── licensing.py      # offline Ed25519-signed licence key check
│   ├── sample_data.py    # 40 invented, date-relative complaints + history (demo mode)
│   ├── setup.py          # first-run setup flow
│   ├── filelock.py       # POSIX + Windows flock wrapper
│   └── fonts/            # DejaVu fonts bundled for the PDF
│
├── dashboard_v2/         # web console (Flask)
│   ├── app.py            # single-process Flask server on 127.0.0.1:5001 + background threads
│   ├── templates/        # Jinja2: base.html + one per screen + _detail_*.html partials
│   └── static/thirty/    # brand css + self-hosted fonts
│
├── desktop/              # Electron shell (main.js, electron-builder.yml, backend.spec, updater.js)
├── tools/                # build_backend.py, screenshots.py, set_version.py, make_licence.py
├── skill/                # OpenClaw/Telegram approval skill (hackathon setup)
├── examples/plugins/     # keyword-agent example plugin
├── brand/                # brand kit: palette, fonts, logos (source of truth for static/thirty)
├── docs/                 # ARCHITECTURE.md, COMPLIANCE.md, PLUGINS.md, THIRTY_PLAN.md, screenshots/
├── tests/                # pytest suite (run on the sample agent; local model tested via fake HTTP)
└── .github/workflows/    # ci.yml (tests + frozen boot), release.yml (tagged installer builds)
```

## Where things live

- **Code vs data:** code is in the repo / frozen app (`CODE_DIR`); data (`decisions.csv`, `reports/`, `history.csv`, `actions.csv`, settings, `decisions/`, `audit.jsonl`) lives in the data folder resolved by `thirty/config.py` — the repo root in dev, the OS app-data folder in the desktop app.
- **System of record:** `decisions.csv`, one row per complaint. Columns are defined by `vigil.FIELDS`; old files are upgraded on read. Access is serialised with the `decisions.csv.lock` flock.
- **AI boundary:** nothing in the pipeline or console talks to a model directly — everything goes through `thirty.agents.get_agent()`. Add new AI behaviour as an Agent/plugin, not inline.

## Conventions

- **Console pages:** each screen is a route in `dashboard_v2/app.py` + a template; pages fetch rendered fragments or JSON from `/api/...` endpoints and poll every few seconds. Keep the frontend framework-free (vanilla JS, Jinja, inline CSS/SVG).
- **Graceful degradation:** optional libs (`fpdf2`, `vaderSentiment`, `rapidfuzz`) and a broken/absent agent must never stop the pipeline — fall back (e.g. `NoAgent` = manual review) rather than crash.
- **Brand:** UI uses the Thirty brand kit (Paper & Coral palette, Instrument Serif headlines, Manrope body, self-hosted fonts). Coral marks one key action per screen, deadlines under 7 days and REPORTABLE; amber marks NEEDS INFO; nothing else is coloured.
- **Naming:** user-facing name is "Thirty"; file names, env vars (`VIGIL_*`), the Telegram handle and the sandbox skill keep their original "vigil" names (see `docs/RENAME_TODO.md`).
- **Invented data:** all sample complaints, companies, devices and people must remain fictional.

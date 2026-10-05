# Thirty — architecture

Thirty (formerly "Vigil") is medical device complaint reporting software. A manufacturer receives
complaints; each must be assessed for whether it is reportable to the FDA under 21 CFR 803 and, if so,
filed within 30 calendar days (5 work days when urgent remedial action is needed). The agent classifies
each complaint and drafts the report; a human reviews, approves and files. **Thirty drafts; a human files.**

This document describes the code as found at the start of the Thirty work (hackathon state) and is
updated as each phase lands. Decisions taken during the phases are recorded at the end.

## 1. Stack

| Layer | Technology | Where |
|---|---|---|
| Pipeline / agent | Python 3.11+, `requests`, optional `fpdf2`, `vaderSentiment`, `rapidfuzz` | `vigil.py` |
| Intake channels | Python, Flask blueprint, `imaplib` | `intake.py` |
| Console (web UI) | Flask 3 + Jinja2 templates, vanilla JS (no bundler, no framework), inline CSS, inline SVG icons | `dashboard_v2/` |
| Old console (v1) | Flask, superseded by `dashboard_v2` | `dashboard/` |
| Chat approvals | OpenClaw skill run inside a NemoClaw sandbox, driven from a Telegram group | `skill/vigil/` |
| Local model | Any OpenAI-compatible server (vLLM on the hackathon box), `VIGIL_LLM_BASE`, default `http://localhost:8000/v1` | env |
| Data | Flat files: CSV + JSON next to the code, no database | repo root / `dashboard_v2/` |

There is no package manifest (`requirements.txt`, `pyproject.toml`) in the hackathon state; the code
assumed a venv at `~/hackathon/venv`. No build step: the console is served straight from the templates.
Nothing is loaded from a CDN; fonts were system fonts.

## 2. Processes

```
 complaints ──► intake.py / console upload / REST ──► queue ──► vigil.process(c)
                                                                   │
                                            ┌──────────────────────┼──────────────────────┐
                                            ▼                      ▼                      ▼
                                   decisions.csv (log)     reports/MDR_<id>.pdf     Telegram alert
                                            │                                              │
                                            ▼                                              ▼
                                   dashboard_v2/app.py (console) ◄──── approvals ──── skill/vigil (sandbox)
```

* `vigil.py` is both a library (`process()`) and a CLI (`replay`, `sync`, `reset`, `test`,
  `import-history`, `listen`). The console imports it lazily (`vigil()` in `app.py`) and also launches it
  as a subprocess for demo replays.
* `dashboard_v2/app.py` is a single-process Flask server on `127.0.0.1:5001` with background threads:
  a health poller (model, Telegram, sync process), an intake worker (one complaint at a time through the
  model), and the demo runner (a `vigil.py replay` subprocess whose stdout is streamed to the Demo page).
* `intake.py` can run standalone on port 5050 or be mounted on the console (`init_app`).

## 3. Data model

Everything is a file. Paths are relative to the repo root unless noted.

### `decisions.csv` — the system of record
One row per processed complaint, written by `vigil.log()`; the console rewrites rows in place to change
`status`. Access is serialised with an `flock` on `decisions.csv.lock`. Columns (`vigil.FIELDS`):

| column | meaning |
|---|---|
| `time` | when the agent processed it (ISO) |
| `id` | complaint id (MAUDE report key, or `SRC-xxxx` for intake items) |
| `received` | date received, `YYYYMMDD` |
| `device` | brand / device name |
| `priority`, `score`, `distress` | layer-1 rule output: `URGENT` / `HIGH` / `NORMAL`, numeric score, distress 0-5 |
| `decision` | `REPORTABLE` / `NEEDS_INFO` / `NOT_REPORTABLE` |
| `category` | `DEATH` / `SERIOUS_INJURY` / `MALFUNCTION` / `NONE` |
| `reason` | one sentence citing the rule |
| `deadline_days` | `30`, `5` or empty |
| `due_date` | ISO date, empty if not reportable |
| `confidence` | 0-100 |
| `missing` | `;`-separated missing items |
| `duplicate_of` | id of a near-duplicate, if any |
| `status` | `PENDING_REVIEW`, `LOGGED`, `APPROVED by <name>`, `INFO REQUESTED by <name>` |
| `text` | first 500 chars of the complaint |
| `product_code`, `memory`, `failure_mode`, `source` | FDA product code, memory summary line, failure-mode label, intake source |

Old files with fewer columns are upgraded on read (`parse_log`).

### Other files
* `reports/MDR_<id>.pdf` — drafted Form 3500A (fpdf2), one per REPORTABLE / NEEDS_INFO complaint.
* `outbox.txt` — Telegram messages that could not be sent.
* `history.csv` — long-term memory built from FDA MAUDE exports (`import-history`); grouped by device family.
* `demo_set.csv` — curated MAUDE rows replayed by the demo.
* `dashboard_v2/actions.csv` — who approved / requested info / undid, and when (console audit trail).
* `dashboard_v2/settings.json` — console settings: API key, field mapping, IMAP, connector credentials (mode 0600).
* `dashboard_v2/intake.json` — the console's intake queue (items + status).
* `intake/index.csv`, `intake/raw/*` — `intake.py`'s queue and raw payloads.
* Sandbox side: `/sandbox/vigil/decisions.csv` (copy), `approvals.csv`, `info_requests.csv`, `names.json`.

### Derived values (not stored)
`days_left`, `is_open` (has a deadline, not NOT_REPORTABLE, not approved), `status_kind`
(`pend` / `appr` / `info`), device family (`vigil.device_family`), pattern alerts (same family + same
failure mode recurring live and in history), KPIs and sparklines.

## 4. Screens (console v2)

| Route | Template | What it shows |
|---|---|---|
| `/` | `home.html` | Command Center: 6 KPI cards, live intake feed, "Needs your decision" queue with Approve / Request info, pattern alerts, FDA-history card, pipeline strip |
| `/complaints` | `complaints.html` | Table: sort, facet chips, search, device-family filter, optional FDA-history rows, pagination |
| `/complaint/<id>` | `complaint.html` + `_detail_*.html` partials | Full record: decision hero with countdown, legal basis, reason, confidence, complaint text, priority breakdown, missing info, follow-up questions, review actions (approve / info / undo), timeline, device memory, Form 3500A preview |
| `/clock` | `clock.html` | Compliance Clock: open reports sorted by time left, 30-day bar per report, 4 summary tiles |
| `/trends` | `trends.html` | Complaints per month (history + live), failure modes ranked, deaths / injuries / malfunctions per quarter, Philips chart |
| `/audit` | `audit.html` | Event log (agent + human actions), filter chips, CSV export |
| `/intake` | `intake.html` | Intake inbox: items from REST / CSV / email with status |
| `/integrations` | `integrations.html` | REST endpoint + API key, file upload, IMAP settings, connector placeholders, field mapping |
| `/demo` | `demo.html` | Demo Control: reset, start replay, stop; streamed `vigil.py` output |
| (404) | `missing.html` | Complaint not found |

Shared chrome in `base.html`: sidebar with nav + system health LEDs + "0 bytes to cloud AI" badge,
top bar with org, global search (`/`), LIVE indicator, clock; detail drawer; reviewer-name modal; toasts.
Pages poll their JSON endpoints every 2–5 s; there are no websockets.

### JSON API used by the pages
`/api/state`, `/api/health`, `/api/complaints/list`, `/api/complaint/<id>` (rendered fragments),
`/api/complaint/<id>/action` (approve / info / undo), `/api/summary/<id>`, `/api/search`, `/api/audit`,
`/audit.csv`, `/api/trends`, `/api/notifications`, `/api/demo`, `/api/demo/<action>`, `/api/intake`,
`/api/intake/upload`, `/api/complaints` (REST intake), `/api/integrations/*`, `/api/settings/*`,
`/reports/<id>.pdf`, `/chart.png`. `intake.py` adds `/api/v1/complaints` (+ `/csv`, `/<id>`).

## 5. How the console calls the agent (hackathon state)

The "agent" is spread across `vigil.py` and reached in four ways:

1. **In-process** — `app.py` imports `vigil` and calls `vigil().process(complaint)` from the intake
   worker thread (`_intake_loop`). `process()` runs the whole pipeline: rules → `classify()` (one LLM
   call) → `deadline_days()` → `log()` → Telegram → `make_mdr()` (second LLM call + PDF) → `spike()`.
2. **Subprocess** — the Demo page runs `python3 vigil.py replay --csv demo_set.csv` and `vigil.py reset`
   and streams stdout.
3. **Health check** — `_check_model()` in `app.py` pings `VIGIL_LLM_BASE/models` and sends a one-token
   chat completion directly (not through `vigil.py`).
4. **Sandbox skill** — `skill/vigil/vigil_tool.py` calls the model itself (via the sandbox's inference
   route) to write follow-up questions for `need info <id>`.

LLM calls inside `vigil.py` go through one helper, `llm(prompt, max_tokens, temperature)`, which POSTs
to an OpenAI-compatible `/chat/completions` endpoint. Two prompts exist: `CLASSIFY` (decision JSON) and
`MDR_FIELDS` (Form 3500A field JSON). The model name is auto-detected from `/models`.

**Since Phase 2** the pipeline no longer talks to a model directly. `vigil.classify()` and
`vigil.mdr_fields()` call `thirty.agents.get_agent()`, the single seam between the pipeline/console and
any AI:

```
thirty/agents/base.py        Agent interface: classify(), draft_report(), follow_up_questions(), health()
thirty/agents/local_model.py LocalModelAgent: the hackathon prompts + OpenAI-compatible HTTP calls, unchanged
thirty/agents/sample.py      SampleAgent: pre-written results for the sample complaints, rule fallback, fake delay
thirty/agents/__init__.py    get_agent() / set_agent(): picks by thirty.config.agent_id()
thirty/config.py             data_dir(), agent_id(), demo_mode()
thirty/sample_data.py        40 invented complaints + 6 incoming, invented history, seed(data_dir)
```

Selection: `THIRTY_AGENT=sample|local|none`; default `local` when `VIGIL_LLM_BASE`/`VIGIL_LLM_MODEL` is
set, otherwise `sample` = **demo mode**. In demo mode the console seeds the data folder on first start
(and once a day, so deadlines stay relative to today), shows a "Sample data" label, runs the demo replay
in-process (no subprocess, no sandbox), and skips the Telegram probe. The console's health panel asks the
active agent (`agent.health()`) instead of pinging the model itself.

Code and data are now separate: `CODE_DIR` (repo / installed app: `vigil.py`, `thirty/`, `demo_set.csv`)
vs `VIGIL_DIR` (data: `decisions.csv`, `reports/`, `history.csv`, `actions.csv`, settings). The console
points `vigil.py`'s file paths at the data folder after import.

## 6. Known constraints found while reading

* `app.py` had an f-string with a backslash in its expression part (valid on Python 3.12, a
  `SyntaxError` on 3.11). Fixed without changing behaviour.
* `vigil.py` re-execs itself into `~/hackathon/venv` and expects `~/hackathon/hackathon_data` for the
  Philips replay and `import-history`; neither is in the repo.
* `start_console.sh` uses `sg docker` and `nemoclaw`, both specific to the hackathon box.
* The console's `DEMO_COMMANDS` call `vigil.py` through `sg docker`, which does not exist elsewhere.
* The brand kit was delivered as `thirty-brand-kit.zip` at the repo root (not a `/thirty-brand-kit`
  folder); the parts the UI needs are copied to `dashboard_v2/static/thirty/`.

## 7. Decisions log

Recorded per phase as they are made. (Phase 4 packaging decision will be added here before building.)

* **Phase 2** — One agent interface, two implementations; demo mode on by default when no model is
  configured; sample data is invented and date-relative; the hackathon Philips chart is no longer shown
  (Trends draws from `history.csv`, which the seeder also writes). `tests/` run entirely on the sample
  agent; the local-model agent is tested against a fake HTTP server.
* **Phase 1** — Restyle only. The console keeps its Flask/Jinja/vanilla-JS structure; the design
  system in `base.html` is replaced by the brand kit tokens (`css/thirty.css`), fonts are self-hosted,
  logos come from the kit's SVGs. User-facing "Vigil" becomes "Thirty"; file names, env vars, the
  Telegram handle and the sandbox skill keep their names (see `docs/RENAME_TODO.md`).

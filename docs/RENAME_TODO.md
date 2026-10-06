# Rename: what still says "Vigil"

Phase 1 renamed every user-facing "Vigil" to "Thirty": console UI text, page titles, the audit actor
("Thirty agent"), the drafted Form 3500A header/footer, the console's start/stop script messages, the
README and the package name (`pyproject.toml`: `thirty`). `dashboard/` (console v1), `philips_chart.png`, `make_chart_and_demo.py` and the brand-kit zip were
deleted after Phase 7 (the trimmed kit lives in `brand/`). The items below were left alone on purpose,
either because the brief says to, because a rename would change behaviour, or because they are internal
identifiers nobody sees.

| Where | What | Why it stays (for now) |
|---|---|---|
| Telegram | bot handle `@VigilMDR_bot` | Brief: leave the Telegram bot handle alone |
| Environment | `VIGIL_DIR`, `VIGIL_LLM_BASE`, `VIGIL_LLM_MODEL`, `VIGIL_SANDBOX`, `VIGIL_TG_SESSION`, `VIGIL_VENV_BIN`, `VIGIL_CONSOLE_*`, `VIGIL_SESSIONS` | Brief: leave environment variable names alone |
| Files | `vigil.py`, `skill/vigil/`, `dashboard_v2/` folder name, `decisions.csv` etc. | Renaming files breaks the hackathon box's scripts and the sandbox skill path; do it once the desktop app replaces those entry points (Phase 4) |
| `vigil.py` prompts | `CLASSIFY` and `MDR_FIELDS` start with "You are Vigil" | Changing the prompt text changes model output; keep the prompts byte-identical until the local model can be re-tested |
| `vigil.py` CLI | `python3 vigil.py replay / sync / reset …` and the `[telegram off]` console output | Internal operator tooling; superseded by the app in later phases |
| `vigil.py` Telegram cards | Replay start/finish messages still read "Replay started…", "Type due…" (no brand name); `cmd_test` now says "Thirty is online" | Fine as is |
| `skill/vigil/SKILL.md`, `vigil_tool.py` | "Vigil complaint tracker", "Vigil commands: status · due …", `VIGIL_DIR` | Runs inside the OpenClaw sandbox; its text is what the Telegram agent prints. Rename together with the sandbox deployment (needs the hackathon box) |
| Console JS | `vigil:changed` DOM event, `vigil-reviewer` localStorage key | Internal identifiers; renaming the storage key would forget every reviewer's saved name on upgrade |
| `dashboard_v2/app.py` | Code comments ("vigil.py bridge", "Vigil field") and the `vigil()` import helper | Comments and identifiers, not UI |
| `.gitignore`, `secrets.env` | Comment lines | Not user-facing |

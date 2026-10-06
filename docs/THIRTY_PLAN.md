# Thirty — product plan and progress

This file is the working brief. Tick a phase when it is done so a new session can continue from here.
Branch: `Thirty`. One or more commits per phase; a draft pull request is opened after Phase 1 and updated
as phases land.

## Status

- [x] Phase 0 — Read the repo, write `docs/ARCHITECTURE.md`, save this plan
- [x] Phase 1 — Visuals and rebrand (reviewed: "continue")
- [x] Phase 2 — Demo mode with sample data, mock agent (reviewed)
- [x] Phase 3 — The agent becomes a plugin
- [x] Phase 4 — Desktop app
- [x] Phase 5 — First-run setup
- [x] Phase 6 — Installers
- [x] Phase 7 — Licensing and updates (scaffold only)
- [x] Phase 8 — Compliance record: decision tree, jurisdiction clocks, signed audit chain, submission pack (`docs/COMPLIANCE.md`)
- [x] Finish — README, final PR summary

## Product context

Thirty (formerly "Vigil") is medical device complaint reporting software. A manufacturer receives
complaints; each one must be assessed for whether it is reportable to the FDA, and reportable ones must
be filed within 30 days (5 days for urgent ones). The AI agent classifies each complaint and drafts the
report; a human reviews, approves and files. Product line: "Thirty drafts; a human files." The agent
runs on a local model, so nothing is sent to cloud AI. We currently have no access to the local model
hardware, so for now the whole app must run on sample data with a mock agent.

## How to work

- First, read the whole repo. Write `docs/ARCHITECTURE.md` describing the current stack, screens, data
  model and how the console calls the agent.
- Save this brief as `docs/THIRTY_PLAN.md` with a checkbox per phase and tick phases off as you finish,
  so a new session can continue from it.
- One commit (or more) per phase, on one branch, with a draft pull request opened after Phase 1 and
  updated as you go.
- Keep existing behaviour working. Add tests for anything you restructure and run the test suite before
  each commit.
- After Phase 1 and after Phase 2: run the app, take a screenshot of every screen with a headless
  browser, save them in `docs/screenshots/`, show them to me and WAIT for my reply. For the other
  phases, continue without stopping unless you are blocked or a decision would be hard to reverse.
- Never add calls to any cloud AI service, analytics or external CDN. Never commit secrets. Use only
  invented companies, devices and people in data.
- If something in this brief conflicts with what the code can reasonably do, say so and propose the
  closest alternative instead of guessing.

## Phase 1 — Visuals and rebrand (do this first)

Use the brand kit in `/thirty-brand-kit`: read its `README.md`, `css/thirty.css` and `components.html`,
and build on those tokens and components. If the folder is missing, use the values below, use a plain
"Thirty" text wordmark as a placeholder logo, and tell me the kit was not found.

- Colours: Paper `#F7F5F0` (ground), Ink `#15181D` (text, primary buttons), Coral `#FF5A3C` (the single
  accent), Slate `#5B6470` (secondary text), Stone `#DDD8CE` (rules, dividers, tracks), Stone-light
  `#EDEAE3` (hover panels), Amber `#F2B134` (NEEDS INFO only). Small coral text on paper uses `#C2381A`.
  Hover: ink `#2A2F37`, coral `#E84E31`.
- Coral is used for one key action per screen, deadlines under 7 days, REPORTABLE, and nothing else.
  Never coral body text or coral panels.
- Type: Instrument Serif 400 for headlines and big numbers only; Manrope for everything else (500 body,
  700 buttons and labels, 800 pills and wordmark). Bundle the font files locally from the kit; no Google
  Fonts requests.
- Buttons: 44px high, radius 10, 2px border. Primary = ink. Accent = coral with INK text (never paper
  text), one per screen. Secondary = outlined.
- Pills: 28px, fully round, uppercase Manrope 800 12px. REPORTABLE coral, NEEDS INFO amber,
  NOT REPORTABLE ink outline, APPROVED ink fill, 5-DAY ink with coral text.
- Deadline ring: track Stone, elapsed Ink, first five days Coral. Deadline bar: full width = 30 days,
  ink on stone, coral when under 7 days or a 5-day report.
- Radius 10 for buttons, inputs, cards; 14 for panels; 8px spacing grid.
- Dark mode: ink ground, paper text, coral accent, via `data-theme="dark"`.
- Logo: use the vector files from the kit (lockup in the sidebar, favicons, app icon). Never redraw the
  "30" mark with a font.
- Rename every user-facing "Vigil" to "Thirty" (UI text, page titles, README, package name). Keep the
  "0 bytes to cloud AI" badge. Leave the Telegram bot handle and environment variable names alone and
  list anything still named Vigil in `docs/RENAME_TODO.md`.
- Voice for all UI copy: plain, specific, numbers first, no drama.
- Restyle only. No logic changes in this phase. Check contrast and keyboard focus on every screen. Then
  screenshots, and wait for me.

## Phase 2 — Demo mode with sample data (no AI)

- Put every call the console makes to the agent behind one interface with two implementations: the
  existing local-model one and a new mock agent.
- The mock agent returns realistic pre-written results in exactly the same shape as the real agent
  (classification, reasoning, drafted report), with a short fake delay so loading states show.
- Seed about 40 fictional complaints covering every state: REPORTABLE, NEEDS INFO, NOT REPORTABLE,
  APPROVED, 5-day reports, and deadlines spread across the 30-day clock including due today and overdue.
  Dates should be relative to today so the demo never looks stale.
- Demo mode is on automatically when no model is configured. While it is on, show a small "Sample data"
  label in the UI.
- Every screen gets proper empty, loading and error states.
- Add a "Reset sample data" action. Then screenshots, and wait for me.

## Phase 3 — The agent becomes a plugin

- Define a plugin contract: a manifest (id, name, version, capabilities, settings schema) plus the agent
  interface from Phase 2. Document it in `docs/PLUGINS.md` with a minimal example plugin.
- Ship two built-in plugins: "Sample agent" (the mock) and "Local model agent" (the existing code, moved
  behind the contract, unchanged in behaviour).
- Add a Plugins screen in settings: list installed plugins, enable or disable, choose the active agent,
  edit its settings, and show its status (ready, not configured, error).
- The core app must run with no agent plugin active (manual review only).

## Phase 4 — Desktop app

- Based on the stack you found, choose the packaging approach that needs the least rewriting (for
  example Tauri or Electron for a web UI) and record the decision and trade-offs in
  `docs/ARCHITECTURE.md` before building.
- The app starts with one click: it launches any backend it needs itself, stores data in the user's
  app-data folder, and works fully offline.
- App name Thirty, kit icons, proper window title, menu and About box.

## Phase 5 — First-run setup

- A short setup flow on first launch: welcome, choose "Explore with sample data" or "Start with my
  site", pick an agent plugin (sample agent, local model, or none), and for the local model show what is
  required and a connection test.
- Everything chosen here can be changed later in settings.

## Phase 6 — Installers

- A GitHub Actions workflow that builds installers for macOS, Windows and Linux when a version tag is
  pushed and attaches them to a GitHub Release.
- Builds are unsigned for now. Read signing credentials from repository secrets if present and skip
  signing cleanly if not. Document in `docs/RELEASING.md` exactly which certificates and secrets I need
  to add.

## Phase 7 — Licensing and updates (scaffold only)

- A licence screen and a licence-check interface with an offline implementation (a signed key file),
  designed for per-site annual licences. No payment provider yet.
- Auto-update wired to GitHub Releases, switched off by default behind a setting, documented in
  `docs/RELEASING.md`.

## Finish

- Update `README.md`: what Thirty is, how to run it in development, how to build installers, how demo
  mode works, how to write a plugin.
- Final summary in the pull request: what was done per phase, what was left out and why, and a list of
  decisions that need me.

## Phase 8 — Compliance record (from the market research)

Built after v1.1.1 from `docs/MARKET.md` §5 P0 rows; details and status in `docs/COMPLIANCE.md`.

- [x] Reportability decision tree with recorded rationale, reviewer, awareness date, 820.35 fields
- [x] Reporting clocks per jurisdiction (US, EU, UK, CA) from the awareness date; site setting
- [x] Hash-chained audit trail with e-signature meaning; verify + export on the Audit Log
- [x] Submission pack zip per complaint
- [ ] HL7 ICSR XML (eMDR) and EU MIR 7.3.1 XML: needs exact IMDRF code tables, not attempted blind
- [ ] Validation package, per-user login (P0/P1 rows still open)

## Notes for the next session

- Python 3.11 in the dev container; install with `pip install -r requirements.txt` (added in Phase 1).
- Run the console: `cd dashboard_v2 && python3 app.py` → http://localhost:5001.
- Tests: `pytest` from the repo root.
- Screenshots: `python3 tools/screenshots.py` (Playwright, Chromium) writes `docs/screenshots/`; set
  `THIRTY_CHROMIUM=/path/to/chrome` when Playwright's own browser download is unavailable.
- Demo mode: no `VIGIL_LLM_BASE` -> sample agent + sample data (`THIRTY_AGENT=sample|local|none` overrides).
  `python3 -m thirty.sample_data <dir>` reseeds by hand.

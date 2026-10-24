# Product

**Thirty** — medical device complaint reporting software. Tagline: *"Thirty drafts; a human files."*

Manufacturers must report deaths, serious injuries and dangerous malfunctions to the FDA within 30 calendar days (5 work days when urgent remedial action is needed) under **21 CFR 803**. Thirty reads each complaint as it arrives, scores it, decides what the FDA must be told, drafts the **Form 3500A**, and hands it to a named human who approves and files.

## Core principles

- **Local-first / privacy:** the agent runs on a local model. **0 bytes to cloud AI.** The app works fully offline and stores data in the OS app-data folder. Exception for the Hackachusetts demo: an optional Claude agent plugin may call the Anthropic API on invented sample data only. When it is active, the UI shows "Cloud model (demo, sample data)" instead of "0 bytes to cloud AI". See hackathon.md.
- **Human in the loop:** the agent drafts and recommends; a named reviewer approves and files every decision. Nothing is silently dropped.
- **Auditable by design:** every approve, info request, undo and recorded decision is written to a signed, hash-chained audit trail with the reviewer's name and the time.
- **Compliance record built in:** reportability decision records (21 CFR 803.18), per-jurisdiction reporting clocks (US / EU MDR / UK MHRA / Health Canada), and a per-complaint submission pack.

## Pipeline layers

1. **Rules (code, instant):** priority score from red-flag words, event type and distress; completeness and duplicate checks; spike detection per device family. Signals only raise priority.
2. **Agent (AI):** reportable / not reportable / needs info, the legal reason, the deadline, a drafted Form 3500A, and follow-up questions. The agent is a pluggable component (sample agent, local model, or a user-written plugin).
3. **Human:** approves every decision in the console (or in Telegram on the hackathon setup).

## Shipping form

Desktop app (macOS, Windows, Linux) that wraps a local web console. Originated as "Vigil" at the Dell x NVIDIA AI Hackathon. **Demo mode** runs on the sample agent with 40 invented, date-relative complaints when no model is configured. All sample companies, devices and people in the repo are invented.

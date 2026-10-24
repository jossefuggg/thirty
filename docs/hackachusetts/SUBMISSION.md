# Thirty — Hackachusetts submission

## What Thirty is (150 words)

Thirty is medical device complaint reporting software: "Thirty drafts; a human files."
Manufacturers must report deaths, serious injuries and dangerous malfunctions to the FDA within
30 calendar days (5 work days when remedial action is needed) under 21 CFR 803. Thirty scores each
complaint, an agent pre-decides reportable / needs info / not reportable with the legal reason and
deadline, drafts Form 3500A, and a named human approves and files.

Before today (Thirty 1.2.1): the scoring rules, the decision tree, per-jurisdiction clocks, the
pluggable agent seam, the local-model and sample agents, the intake API, the Flask console, and the
signed hash-chained audit trail.

Built today in Kiro, on the `hackachusetts` branch: a Claude agent plugin (cloud model, sample data
only); a public reporter front door where nurses, patients and staff report in plain language through
an adaptive interview; and a Device readiness page assessing wellness-vs-device status against public
openFDA data.

## How we used Kiro

Every module below was built today in Kiro on the `hackachusetts` branch; Thirty 1.2.1 existed before.

### IDE and CLI

We worked in the Kiro IDE across the day, using its spec and hook features directly in the editor.
Kiro also drove the terminal for us: it booted gunicorn to verify the public-demo deployment, and
caught that start-up only ran under `__main__` — meaning gunicorn would have served an empty app —
and moved initialisation to import time before any deploy.

### Specs vs vibe

Most of the day ran through structured specs rather than free-form vibe coding:

- **Spec 1 — Claude agent plugin.** Requirements first, with Autopilot off so we reviewed each stage.
  The design and task list were generated next, and the plan was reviewed before any code was written.
- **Spec 2 — reporter front door.** Kiro read the intake, agents and sample-data code, then ran seven
  requirement-detailer sub-agents in parallel and wrote a correctness-properties section. Requirements
  matched the real code, and this caught an impossible "offline translation" claim before any code.
- **Quick Specs.** A public-demo quick spec produced render.yaml, gunicorn, a locked public mode
  (14 write routes refuse), a banner, no secrets rendered, and a mobile complaint page — 96 tests
  passing, with Kiro booting gunicorn to verify.

We reached for quick specs when the task was small and self-contained (the public-demo wiring), and
full specs with requirements → design → tasks for the larger features.

### Steering

Steering gave every task the same shared context from the first prompt:

- We wrote `hackathon.md` (context, code map, brand rules, do-not-say list), always included, so every
  task started knowing the FDA rules and our limits.
- "Generate Steering Docs" produced `product.md`, `tech.md` and `structure.md` from the codebase in a
  few minutes, so Kiro learned the agent/plugin seam and data paths.
- We added the cloud-demo exception to `product.md`, which stopped a conflict between the
  "0 bytes to cloud" claim and the new Claude plugin.

### Hooks

Two agent hooks ran continuously:

- **run-tests** — a shell command on save, so tests ran on every edit for free.
- **compliance-guard** — an agent hook that checked changes (for example `integrations.html`) against
  the do-not-say list automatically, catching wording mistakes before the demo.

When run-tests kept failing one test, Kiro found the cause — tests were reading runtime files from the
repo — isolated the test data folder in `conftest.py`, and proved the fix with a hostile `plugins.json`.

### MCP

The local-model agent talks to any OpenAI-compatible server, which let us point the agent at a local
model during development without changing the agent seam.

### Property-based tests

We asked for property-based tests alongside the specs, and they caught real bugs:

- In the front-door spec, a sub-agent smoke test hung for 120 seconds because an agent re-asking the
  same field looped forever — the question cap counted distinct fields. We fixed it to count asks,
  matching Property 1 (the interview always ends), before any reporter could hit it.
- The PBT work on Spec 1 was requested specifically for malformed model output, so the agent's
  fallback shapes stay correct.

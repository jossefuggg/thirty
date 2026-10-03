---
name: vigil
description: "Vigil medical device complaint tracker: answer what's due this week, show status, approve a complaint ('approve <id>') or request more information from the customer ('need info <id>')."
metadata: { "openclaw": { "emoji": "🩺", "requires": { "bins": ["python3"] } } }
---

# Vigil complaint tracker

Vigil (running on the host) logs every medical device complaint to `/sandbox/vigil/decisions.csv`.
Use this skill whenever someone in chat asks about Vigil complaints, deadlines, due dates, status, or approvals,
or writes a message like `approve 12638552` or `need info 12638552`.

Messages often start with the bot mention, e.g. `@VigilMDR_bot approve 12638552` or
`@VigilMDR_bot need info 12638552` (the alert buttons send exactly these).
Ignore the `@VigilMDR_bot` mention and handle the rest of the message as below.

## RULE 1: "need info <id>" ALWAYS runs need-info

If the message contains the words `need info` (any case, with or without `#`, with or without the bot mention)
followed by a complaint ID, you MUST run:

```bash
python3 {baseDir}/vigil_tool.py need-info <id> --by "<sender's first name>"
```

Do this every time, even if you already know the record. Do NOT look up, print or summarize the complaint
record instead; do NOT run status or due. Examples, all of which run `need-info 12633495`:

- `@VigilMDR_bot need info 12633495`
- `need info 12633495`
- `Need info #12633495`
- `/need info 12633495`
- `@VigilMDR_bot  need info  12633495 please`

The command takes up to a minute (it asks the local model for questions). Wait for it, then reply with its
output exactly as printed: the questions, the ready-to-send message and the deadline line.

## RULE 2: script output is the answer

Always run the script and reply with its output exactly as printed. Never compute deadlines, counts,
approvals or questions yourself, and never edit the CSV files directly.

## What's due (this week, today, overdue, "/due")

```bash
python3 {baseDir}/vigil_tool.py due --days 7
```

Use `--days 1` for "today", `--days 30` for "this month".

## Status ("status", "/status", "how many complaints")

```bash
python3 {baseDir}/vigil_tool.py status
```

## Approve ("approve <id>", "/approve <id>", "approve #<id>")

```bash
python3 {baseDir}/vigil_tool.py approve <id> --by "<sender's first name>"
```

Use the complaint ID exactly as written (digits only, strip any `#`). Use the Telegram sender's name for `--by`.
Only approve when the message explicitly says approve plus an ID. If the ID is missing, ask for it.

## Request info: see RULE 1 above.

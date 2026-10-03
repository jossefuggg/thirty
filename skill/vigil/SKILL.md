---
name: vigil
description: 'Vigil complaint tracker (status, due, approve <id>, need info <id>; messages may start with @VigilMDR_bot). There is NO tool named vigil and no need to read this file. Make exactly one call, with this exact shape (id at the top level, never inside args): tool_call {"id": "exec", "args": {"command": "python3 /sandbox/.openclaw/workspace/skills/vigil/vigil_tool.py msg <message words> --by <sender first name>", "yieldMs": 180000}}. Leave out --by unless you are sure of the sender first name; the script finds the name itself. If the output asks Who should I log this under?, send that question, and when the user answers with a name run the same call with msg <their answer>. The script does the approval or info request itself; never mention approval buttons or cards, and never suggest slash commands: suggest plain text such as need info <id> or approve <id>. Your reply must be the command output exactly as printed, with no words added before or after it.'
metadata: { "openclaw": { "emoji": "🩺", "requires": { "bins": ["python3"] } } }
---

# Vigil complaint tracker

## How to run it (one call, nothing else)

There is no tool called `vigil`. Do not search for one, and do not read files first. Make exactly one call:

```
tool_call  id: "exec"
           args: {"command": "python3 /sandbox/.openclaw/workspace/skills/vigil/vigil_tool.py msg <message words> --by <sender first name>", "yieldMs": 180000}
```

Pass the user's message words as they are (letters, digits, `#` and spaces only; drop quotes and other
symbols). The script ignores the `@VigilMDR_bot` mention and extra words and works out the command itself:

- `@VigilMDR_bot status` → `... vigil_tool.py msg status --by Youssef`
- `@VigilMDR_bot need info 12633495` → `... vigil_tool.py msg need info 12633495 --by Youssef`
- `@VigilMDR_bot approve #12638552 please` → `... vigil_tool.py msg approve #12638552 please --by Youssef`
- `what is due this week?` → `... vigil_tool.py msg what is due this week --by Youssef`

Then reply with the output exactly as printed, even when it says there is no change. Never suggest slash
commands; tell people to type plain text like `need info <id>` or `approve <id>`. If the output asks
"Who should I log this under?", send it; when they answer, run `msg <their answer>` the same way.
The subcommands below still work and do the same thing.

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
- `@VigilMDR_bot  need info  12633495 please`

The command takes up to a minute (it asks the local model for questions). Wait for it, then reply with its
output exactly as printed: the questions, the ready-to-send message and the deadline line.

## RULE 2: script output is the answer

Always run the script and reply with its output exactly as printed. Never compute deadlines, counts,
approvals or questions yourself, and never edit the CSV files directly.

## What's due (this week, today, overdue)

```bash
python3 {baseDir}/vigil_tool.py due --days 7
```

Use `--days 1` for "today", `--days 30` for "this month".

## Status ("status", "how many complaints")

```bash
python3 {baseDir}/vigil_tool.py status
```

## Approve ("approve <id>", "approve #<id>")

```bash
python3 {baseDir}/vigil_tool.py approve <id> --by "<sender's first name>"
```

Use the complaint ID exactly as written (digits only, strip any `#`). Use the Telegram sender's name for `--by`.
Only approve when the message explicitly says approve plus an ID. If the ID is missing, ask for it.

## Request info: see RULE 1 above.

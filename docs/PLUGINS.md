# Thirty plugins

A plugin gives Thirty an **agent**: the thing that classifies each complaint under 21 CFR 803 and drafts
the Form 3500A. Thirty ships two (the Sample agent and the Local model agent); you can add your own.
One agent is active at a time; with none active, every complaint waits for a human (manual review).

## Layout

A plugin is a folder with two files:

```
<plugin-id>/
  plugin.json     manifest
  plugin.py       create(settings) -> Agent
```

Built-in plugins live in `thirty/plugins/builtin/`. User plugins go in the data folder:
`<data folder>/plugins/<plugin-id>/` (the Plugins screen shows the exact path). Thirty rescans the folder
when the Plugins screen loads; no restart needed. A user plugin cannot reuse a built-in id.

## Manifest (`plugin.json`)

```json
{
  "id": "keyword-agent",
  "name": "Keyword agent (example)",
  "version": "0.1.0",
  "description": "One sentence shown on the Plugins screen.",
  "capabilities": ["agent"],
  "settings": [
    {"key": "words",  "label": "Reportable words", "type": "string", "default": "death, injury", "required": false, "help": "Comma-separated."},
    {"key": "strict", "label": "Treat short complaints as needs-info", "type": "bool", "default": true}
  ]
}
```

| field | meaning |
|---|---|
| `id` | letters, digits, `-` or `_`; must equal the folder name |
| `name`, `version`, `description` | shown on the Plugins screen |
| `capabilities` | must include `"agent"` (the only capability today; others may come) |
| `settings` | schema for the settings form; each entry has `key`, `label`, `type`, optional `default`, `required`, `help` |

Setting types: `string`, `url`, `secret` (stored, never shown back; blank keeps the stored value),
`number` (stored as float), `bool`, `select`. Values are saved in `<data folder>/plugins.json`
(mode 0600) and passed to `create()` merged over the defaults.

## Module (`plugin.py`)

```python
from thirty.agents.base import Agent

class MyAgent(Agent):
    id = "my-agent"
    name = "My agent"

    def classify(self, complaint, memory=""): ...
    def draft_report(self, complaint, row): ...
    def follow_up_questions(self, row, missing): ...
    def health(self): ...

def create(settings):
    return MyAgent(settings["some_key"])
```

`create(settings)` is called once per settings change; the instance is reused. All four methods are
synchronous and must return plain Python values in these shapes (see `thirty/agents/base.py`):

**`classify(complaint, memory) -> dict`**
```python
{"decision": "REPORTABLE" | "NOT_REPORTABLE" | "NEEDS_INFO",
 "category": "DEATH" | "SERIOUS_INJURY" | "MALFUNCTION" | "NONE",
 "reason": "one sentence citing the rule",
 "remedial_action_needed": bool,      # True -> 5-work-day report, else 30 calendar days
 "missing_info": ["lot number", ...], # 2-4 word items
 "confidence": 0..100}
```
`complaint` has `id, text, device, manufacturer, event_date, received (YYYYMMDD), event_type, outcomes,
generic_name, product_code, product_problems, manufacturer_narrative`. `memory` is a short text summary
of prior complaints on the same device family (may be empty).

**`draft_report(complaint, row) -> dict`** — Form 3500A fields (`A2_age`, `B1_event_type`, `B2_outcomes`
list, `B5_event_description`, `D1_brand_name` … `H10_manufacturer_narrative`, `follow_up_questions` list).
Use `"UNKNOWN"` for anything not stated; never invent facts. Thirty fills in the report date, report type
and G4 itself. `row` is the decisions.csv row (`decision`, `category`, `deadline_days`, `missing`, …).

**`follow_up_questions(row, missing) -> (list[str], str)`** — 3–5 questions for the reporter and a short
ready-to-send message.

**`health() -> dict`** — `{"ok": bool, "label": "short status", "name": "...", "ms": latency or None}`.
Shown in the sidebar and on the Plugins screen; `ok=False` shows the plugin as **Error** with the label.

Raise an exception for anything unrecoverable; Thirty catches it, marks the plugin **Error** and falls
back to manual review so the pipeline never stops.

## Status on the Plugins screen

| status | meaning |
|---|---|
| Ready | enabled, required settings present, `health()` returned `ok` |
| Not configured | a required setting is empty |
| Error | manifest/import problem, `create()` raised, or `health()` returned not ok |
| Disabled | switched off; cannot be the active agent |

## Example

`examples/plugins/keyword-agent/` is a complete, working plugin (a word list decides reportability). To
try it: copy the folder to `<data folder>/plugins/keyword-agent/`, open **Plugins**, enable it, choose it
as the active agent, then post a complaint on **Integrations → Send test complaint**.

## Choosing the active agent without the UI

`plugins.json` in the data folder: `{"active_agent": "local", "plugins": {"local": {"enabled": true,
"settings": {"base_url": "http://localhost:8000/v1"}}}}`. The environment variable
`THIRTY_AGENT=sample|local|none` overrides the file (used by tests and scripts). With neither, Thirty
uses the local model when `VIGIL_LLM_BASE` is set, otherwise the sample agent (demo mode).

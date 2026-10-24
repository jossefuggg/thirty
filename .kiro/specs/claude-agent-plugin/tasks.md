# Implementation Plan: Claude agent plugin

## Overview

Build the Claude agent as a thin, cloud-calling member of the existing agent architecture. The agent
reuses the local model's prompts and JSON parser and talks to the Anthropic Messages API directly over
HTTP. The work proceeds bottom-up: the agent module first, then the built-in plugin package that exposes
it, then the console badge swap, then test dependencies, then the full property/example test suite, and
finally documentation and an end-to-end verification pass. Each step builds on the previous one so there
is no orphaned code.

## Tasks

- [ ] 1. Create the Claude agent module scaffold and HTTP transport
  - Create `thirty/agents/claude_model.py` with the module docstring and imports (`json`, `os`, `re`, `time`, `requests`, `from .base import Agent, UNREADABLE`, `from . import local_model as lm`)
  - Define module constants `API_URL = "https://api.anthropic.com/v1/messages"`, `ANTHROPIC_VERSION = "2023-06-01"`, `DEFAULT_MODEL = "claude-sonnet-5-5"`
  - Implement `resolve_key(api_key)`: return the stripped setting value when it has a non-whitespace char, else stripped `ANTHROPIC_API_KEY` env, else `""`
  - Implement `_extract_json(text)`: strip Markdown code fences with a regex, then delegate to `lm._json`
  - Define `class ClaudeAgent(Agent)` with `id`/`name` and `__init__(self, api_key="", model="", timeout=60)` storing `api_key`, `model` (default `DEFAULT_MODEL`), `timeout` (float)
  - Implement `_messages(self, prompt, max_tokens, temperature=0.1)`: raise `RuntimeError` when `resolve_key` is empty; POST to `API_URL` with `x-api-key` + `anthropic-version` + `content-type` headers, the `timeout`, and body `{model, max_tokens, temperature, messages:[{role:"user", content:prompt}]}`; call `raise_for_status()`; return `content[0]["text"]` or `""`
  - _Requirements: 1.5, 1.6, 2.1, 2.2, 2.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [ ] 2. Implement the agent pipeline methods and health check
  - [ ] 2.1 Implement `classify`, `draft_report`, and `follow_up_questions`
    - `classify(self, complaint, memory="")`: build prompt from `lm.CLASSIFY.format(...)` (verbatim args from `LocalModelAgent`), call `_messages(prompt, 400, temperature=0)`, return `_extract_json(...)`; on any exception return `dict(UNREADABLE)`
    - `draft_report(self, complaint, row)`: build prompt from `lm.MDR_FIELDS.format(...)` with `lm.deadline_text(...)` and the same default field padding as the local agent, call `_messages(prompt, 1500)`, return `_extract_json(...)`; on any exception return `{"H10_manufacturer_narrative": "Model output unreadable - complete all fields manually."}`
    - `follow_up_questions(self, row, missing)`: build prompt from `lm.ASK.format(...)`, call `_messages(prompt, 700, temperature=0.2)`, parse, keep the first 5 non-empty question strings and the message; on any exception return `([], "")`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4_

  - [ ] 2.2 Implement `health`
    - Time a single `_messages("ping", 1, temperature=0)` call (`max_tokens=1`); on success return `{ok: True, name: model, ms: int, label}`; on any exception return `{ok: False, name, ms: None, label: "offline (<ErrorType>)"}` without raising
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 3. Create the built-in Claude plugin package
  - [ ] 3.1 Create `thirty/plugins/builtin/claude/plugin.json`
    - Manifest with `id` `"claude"` (matching the folder name), `name` `"Claude agent"`, MAJOR.MINOR.PATCH `version`, a 1–500 char `description`, and `capabilities` containing `"agent"`
    - Settings schema: `api_key` type `secret` (NOT marked `required`, with env-fallback help text), `model` type `string` default `"claude-sonnet-5-5"`, `timeout` type `number` default `60`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.2_

  - [ ] 3.2 Create `thirty/plugins/builtin/claude/plugin.py`
    - Define `create(settings)` that returns `ClaudeAgent(api_key=..., model=..., timeout=float(...))`, mirroring `local/plugin.py`
    - _Requirements: 1.5, 1.6_

- [ ] 4. Checkpoint - agent and plugin wired
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Add the cloud badge swap in the console
  - [ ] 5.1 Compute `CLOUD_AGENT` in `dashboard_v2/app.py`
    - In the `_globals()` context processor add `"CLOUD_AGENT": tconfig.agent_id() == "claude"` alongside `AGENT` / `LOCAL_AGENT`
    - _Requirements: 9.1, 9.5, 9.6_

  - [ ] 5.2 Update the badge templates
    - `dashboard_v2/templates/base.html` sidebar `div.cloud0`: render `"Cloud model (demo, sample data)"` when `CLOUD_AGENT` else `"0 bytes to cloud AI"`
    - `dashboard_v2/templates/setup.html` footer badge and the "what happens on this machine" list item: use the same `CLOUD_AGENT` guard so both surfaces match
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6_

- [ ] 6. Add Hypothesis to the dev/test dependencies
  - Add `hypothesis>=6` to `pyproject.toml` `[project.optional-dependencies] dev` and to `requirements-dev.txt`
  - _Requirements: 11.1_

- [ ] 7. Write property-based tests for the Claude agent
  - [ ]* 7.1 Write Property 1 test (response-robustness / shape stability)
    - New file `tests/test_claude_agent.py`; add a mock HTTP helper that builds a fake response whose `.json()` returns `{"content":[{"type":"text","text":<supplied>}]}` and optionally raises in `raise_for_status()`, and captures `json=`/`headers=`
    - **Property 1: Response-robustness (shape stability, no raises)** — over `st.text()` model output, `classify`→dict, `draft_report`→dict, `follow_up_questions`→(list, str), none raise; min 100 examples; tag `# Feature: claude-agent-plugin, Property 1: ...`
    - **Validates: Requirements 3.3, 3.4, 4.2, 4.3, 5.2, 5.4**

  - [ ]* 7.2 Write Property 2 test (fallback determinism on unparseable output)
    - Over non-JSON / fence-wrapped non-JSON text, `classify`==`dict(UNREADABLE)`, `draft_report` has `H10_manufacturer_narrative`, `follow_up_questions`==`([], "")`; min 100 examples; tag `# Feature: claude-agent-plugin, Property 2: ...`
    - **Validates: Requirements 3.4, 4.3, 5.4**

  - [ ]* 7.3 Write Property 3 test (question-count bound)
    - Over `st.lists(st.text())` of arbitrary length supplied as the `questions` field, `follow_up_questions` returns at most 5 questions preserving the first 5 in order; min 100 examples; tag `# Feature: claude-agent-plugin, Property 3: ...`
    - **Validates: Requirements 5.2, 5.3**

  - [ ]* 7.4 Write Property 4 test (temperature-0 classification determinism)
    - Over generated complaint/memory dicts, assert every captured `classify` request body carries `temperature == 0`; min 100 examples; tag `# Feature: claude-agent-plugin, Property 4: ...`
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 7.5 Write Property 5 test (request-contract invariants)
    - Over any valid JSON body, assert the captured request is a POST to `API_URL`, carries non-empty `x-api-key` and `anthropic-version` headers, and sends a `messages` list with exactly one `{role:"user", content:prompt}` entry; min 100 examples; tag `# Feature: claude-agent-plugin, Property 5: ...`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

- [ ] 8. Write example-based tests for the agent and plugin
  - [ ]* 8.1 Write happy-path shape tests
    - In `tests/test_claude_agent.py`, mocked valid JSON → `classify` returns the documented classification dict, `draft_report` returns the Form 3500A dict, `follow_up_questions` returns `(list[str], str)`; include a fence-wrapped valid-JSON case exercising `_extract_json`
    - _Requirements: 11.2_

  - [ ]* 8.2 Write key-resolution tests
    - Setting value takes precedence over env; blank setting falls back to `ANTHROPIC_API_KEY`; resolved key is sent as the `x-api-key` header; no key anywhere → `_messages` raises and the pipeline methods fall back
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 8.3 Write health success/error tests
    - Mocked success → `{ok: True, name, ms (int), label}` with `max_tokens == 1` in the captured body; mocked raise → `{ok: False, label}` with no exception escaping
    - _Requirements: 7.1, 7.2, 7.3, 11.4_

  - [ ]* 8.4 Write plugin discovery and status tests
    - `plugins.discover()` lists `claude` with capability `agent` and no manifest error; `create()` returns an object with the four callable methods; `status("claude")` with a configured key and mocked-ok health → `ready`; with mocked-raising health → `error`
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 8.1, 8.2, 8.4_

- [ ] 9. Write console badge-swap tests
  - [ ]* 9.1 Add badge-swap tests alongside the console test conventions
    - In `tests/test_console.py` conventions, assert that with a non-cloud active agent rendered pages contain `"0 bytes to cloud AI"` (keep `test_pages_render_as_thirty` green); with the Claude agent pinned active the sidebar and setup badges render `"Cloud model (demo, sample data)"` and do not contain `"0 bytes to cloud AI"`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 11.5_

- [ ] 10. Update documentation
  - Add a Claude agent section to `docs/PLUGINS.md`: purpose, how to enable, and each setting (`api_key` secret with `ANTHROPIC_API_KEY` fallback, `model` default `claude-sonnet-5-5`, `timeout` default `60`; note it sends complaint text to the cloud and is demo-only)
  - Add a matching Claude agent subsection to `README.md` with the same purpose/enable/settings summary
  - _Requirements: 10.1, 10.2_

- [ ] 11. Final checkpoint - wire and verify
  - Run the full test suite with `pytest` (including the Hypothesis property tests) and confirm the new Claude agent tests pass and the existing console tests (`tests/test_console.py`, including `test_pages_render_as_thirty`) still pass; fix any failures before finishing
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement clauses (or correctness properties) for traceability.
- Property tests use Hypothesis with at least 100 examples each; each property has exactly one property-based test tagged with its design property.
- All HTTP is mocked in tests; no outbound request reaches the Anthropic Messages API.
- Checkpoints ensure incremental validation at natural breaks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "5.1"] },
    { "id": 2, "tasks": ["3.1", "5.2", "6"] },
    { "id": 3, "tasks": ["3.2", "7.1", "7.2", "7.3", "7.4", "7.5", "8.1", "8.2", "8.3", "9.1"] },
    { "id": 4, "tasks": ["8.4", "10"] }
  ]
}
```

# Requirements Document

## Introduction

This feature adds a built-in "Claude agent" plugin to Thirty. The plugin implements the existing Agent
interface (classify, draft_report, follow_up_questions, health) by calling the Anthropic Messages API
directly over HTTP with the `requests` library, without any Anthropic SDK. It reuses the local-model
agent's prompts and JSON parsing so decisions remain comparable with the existing local model agent.

Because the Claude agent sends complaint text to a cloud model, the console must stop displaying the
"0 bytes to cloud AI" badge while the Claude agent is the active agent and instead display
"Cloud model (demo, sample data)". The local-model plugin and all other local agents keep the
"0 bytes to cloud AI" badge. This is a Hackachusetts demo feature that operates on invented sample
data only.

## Glossary

- **Claude_Plugin**: The built-in agent plugin located at `thirty/plugins/builtin/claude/`, with
  manifest id `claude`, that creates a Claude_Agent instance.
- **Claude_Agent**: The `Agent` implementation that calls the Anthropic Messages API and returns the
  result shapes documented in `thirty/agents/base.py`.
- **Agent_Interface**: The `Agent` base class in `thirty/agents/base.py` defining classify,
  draft_report, follow_up_questions and health.
- **Anthropic_Messages_API**: The HTTP endpoint `POST https://api.anthropic.com/v1/messages`.
- **Plugin_System**: The discovery, validation, state and status code in `thirty/plugins/__init__.py`.
- **Console**: The Flask application in `dashboard_v2/` that renders the Thirty UI.
- **Active_Agent**: The agent selected as active by the Plugin_System (`active_agent_id()`).
- **Cloud_Badge**: The UI element currently rendering the text "0 bytes to cloud AI" in
  `dashboard_v2/templates/base.html` and `dashboard_v2/templates/setup.html`.
- **UNREADABLE**: The documented fallback classification dict defined in `thirty/agents/base.py`.
- **Form_3500A_Fields**: The MedWatch Form 3500A field dictionary shape documented in
  `thirty/agents/base.py` for draft_report.

## Requirements

### Requirement 1: Plugin manifest and discovery

**User Story:** As a Thirty operator, I want the Claude agent to appear as a built-in plugin, so that I can enable and select it from the Plugins screen like any other agent.

#### Acceptance Criteria

1. THE Claude_Plugin SHALL provide a manifest file `plugin.json` at `thirty/plugins/builtin/claude/` with id `claude`, a human-readable name `Claude agent`, a version string in MAJOR.MINOR.PATCH form, a description of 1 to 500 characters, and capabilities containing `agent`.
2. THE Claude_Plugin manifest id SHALL exactly and case-sensitively equal the folder name `claude` so that Plugin_System manifest validation accepts the plugin.
3. THE Claude_Plugin manifest SHALL define a settings schema containing a setting `api_key` of type `secret`, a setting `model` of type `string` with default `claude-sonnet-5-5`, and a setting `timeout` of type `number` with default `60`.
4. WHEN the Plugin_System discovers built-in plugins, THE Plugin_System SHALL list the Claude_Plugin with capabilities containing `agent` and with no recorded manifest error.
5. THE Claude_Plugin SHALL provide a module file `plugin.py` at `thirty/plugins/builtin/claude/` that defines a callable `create(settings)` returning a Claude_Agent instance.
6. WHEN `create(settings)` is called with valid settings, THE Claude_Plugin SHALL return an object that provides callable `classify`, `draft_report`, `follow_up_questions` and `health` methods.

### Requirement 2: API key resolution

**User Story:** As a Thirty operator, I want the Claude agent to use my configured API key or an environment variable, so that I can supply credentials without committing secrets.

#### Acceptance Criteria

1. WHEN the `api_key` setting holds a value that contains at least one non-whitespace character, THE Claude_Agent SHALL treat the `api_key` setting as the resolved API key and authenticate to the Anthropic_Messages_API using that resolved key, taking precedence over the environment variable.
2. IF the `api_key` setting is empty or contains only whitespace characters, THEN THE Claude_Agent SHALL use the value of the environment variable `ANTHROPIC_API_KEY` as the resolved API key.
3. WHEN a resolved API key is available, THE Claude_Agent SHALL send the resolved API key as the value of the `x-api-key` request header.

### Requirement 3: Classification via the Anthropic Messages API

**User Story:** As a quality reviewer, I want the Claude agent to classify complaints under 21 CFR 803, so that its decisions are comparable with the local model agent.

#### Acceptance Criteria

1. WHEN `classify(complaint, memory)` is called, THE Claude_Agent SHALL send a request to the Anthropic_Messages_API using the same classification prompt text used by the local model agent.
2. THE Claude_Agent SHALL send the classification request with temperature `0` so that identical `complaint` and `memory` inputs produce an identical `decision` and deadline value across repeated calls.
3. WHEN the Anthropic_Messages_API returns parseable JSON containing the keys `decision`, `category`, `reason`, `remedial_action_needed`, `missing_info` and `confidence`, THE Claude_Agent SHALL return a classification dictionary with those keys.
4. IF the classification response cannot be parsed into JSON, THEN THE Claude_Agent SHALL return a copy of the UNREADABLE dictionary.
5. IF the request to the Anthropic_Messages_API raises an error, THEN THE Claude_Agent SHALL return a copy of the UNREADABLE dictionary without raising an exception to the caller.

### Requirement 4: Form 3500A drafting

**User Story:** As a quality reviewer, I want the Claude agent to draft the Form 3500A fields, so that a human can review and file the report.

#### Acceptance Criteria

1. WHEN `draft_report(complaint, row)` is called, THE Claude_Agent SHALL send a request to the Anthropic_Messages_API using the same Form 3500A prompt text used by the local model agent.
2. WHEN the Anthropic_Messages_API returns parseable JSON, THE Claude_Agent SHALL return the Form_3500A_Fields dictionary produced from that JSON.
3. IF the draft response cannot be parsed into JSON, THEN THE Claude_Agent SHALL return a dictionary containing an `H10_manufacturer_narrative` value instructing a human to complete the fields manually.
4. IF the request to the Anthropic_Messages_API raises an error, THEN THE Claude_Agent SHALL return a dictionary containing an `H10_manufacturer_narrative` value instructing a human to complete the fields manually, without raising an exception to the caller.

### Requirement 5: Follow-up questions

**User Story:** As a complaint investigator, I want the Claude agent to produce follow-up questions and a ready-to-send message, so that I can request the missing information from the reporter.

#### Acceptance Criteria

1. WHEN `follow_up_questions(row, missing)` is called, THE Claude_Agent SHALL send a request to the Anthropic_Messages_API using the same follow-up prompt text used by the local model agent.
2. WHEN the Anthropic_Messages_API returns parseable JSON, THE Claude_Agent SHALL return a tuple whose first element is a list of question strings and whose second element is a message string.
3. THE Claude_Agent SHALL limit the returned question list to at most 5 questions, keeping the first 5 in order and discarding the rest.
4. IF the follow-up response cannot be parsed into JSON, THEN THE Claude_Agent SHALL return a tuple of an empty list and an empty string.

### Requirement 6: Anthropic Messages API request format

**User Story:** As a developer, I want the Claude agent to call the Anthropic Messages API with the correct contract, so that requests succeed and errors surface clearly.

#### Acceptance Criteria

1. THE Claude_Agent SHALL send each request as an HTTP POST to `https://api.anthropic.com/v1/messages`.
2. THE Claude_Agent SHALL include the request headers `x-api-key` and `anthropic-version`, each with a non-empty string value.
3. THE Claude_Agent SHALL send a JSON request body containing `model`, `max_tokens`, `temperature` and a `messages` list whose single entry has role `user` and content set to the prompt text.
4. WHEN the Anthropic_Messages_API returns an HTTP success status with a non-empty `content` list whose first element contains a `text` value, THE Claude_Agent SHALL read the model output from the `text` value of that first element.
5. THE Claude_Agent SHALL apply the `timeout` setting value as the HTTP request timeout in seconds.
6. IF the Anthropic_Messages_API returns an HTTP error status, THEN THE Claude_Agent SHALL raise an error for that status.

### Requirement 7: Health check

**User Story:** As a Thirty operator, I want to see the Claude agent's health, so that I know whether it is reachable before I rely on it.

#### Acceptance Criteria

1. WHEN `health()` is called, THE Claude_Agent SHALL send a request to the Anthropic_Messages_API with `max_tokens` set to `1`.
2. WHEN the health request succeeds, THE Claude_Agent SHALL return a dictionary with key `ok` set to true, a `label` string, a `name` value identifying the configured model, and an `ms` value equal to the measured round-trip latency in whole milliseconds.
3. IF the health request raises an error, THEN THE Claude_Agent SHALL return a dictionary with key `ok` set to false and a `label` describing the error, without raising the error to the caller.

### Requirement 8: Plugins screen status

**User Story:** As a Thirty operator, I want the Claude agent to show its status on the Plugins screen, so that I can tell whether it is ready, needs configuration, or has an error.

#### Acceptance Criteria

1. WHEN the Plugin_System builds the Plugins screen overview, THE Plugin_System SHALL include the Claude_Plugin entry with a status value derived from the Claude_Agent health check.
2. WHILE the Claude_Plugin is enabled and configured and the health check completes successfully, THE Plugin_System SHALL report its status as `ready`.
3. IF the Claude_Plugin is enabled but required configuration values are missing or empty, THEN THE Plugin_System SHALL report its status as `not-configured` with a label identifying the missing configuration.
4. IF the Claude_Plugin health check raises an error, THEN THE Plugin_System SHALL report its status as `error` with a label describing the failure cause.

### Requirement 9: Cloud badge swap

**User Story:** As a compliance-conscious operator, I want the "0 bytes to cloud AI" badge to disappear when the Claude agent is active, so that the UI never claims nothing goes to the cloud while a cloud model is in use.

#### Acceptance Criteria

1. WHILE the Claude_Agent is the Active_Agent, THE Console SHALL render the Cloud_Badge text as "Cloud model (demo, sample data)".
2. WHILE the Claude_Agent is the Active_Agent, THE Console SHALL NOT render the text "0 bytes to cloud AI" in the Cloud_Badge.
3. WHILE a non-cloud agent is the Active_Agent, THE Console SHALL render the Cloud_Badge text as "0 bytes to cloud AI".
4. THE Console SHALL render identical Cloud_Badge text, matching the text determined by the Active_Agent, in both the base layout sidebar and the setup page footer.
5. WHEN the Active_Agent changes, THE Console SHALL update the Cloud_Badge text to match the new Active_Agent on the next page render.
6. IF no Active_Agent is set or the Active_Agent cannot be determined, THEN THE Console SHALL render the Cloud_Badge text as "0 bytes to cloud AI".

### Requirement 10: Documentation

**User Story:** As a developer, I want the Claude agent documented, so that I understand how to enable and configure it.

#### Acceptance Criteria

1. THE Claude_Plugin SHALL be documented in `docs/PLUGINS.md` with content stating the plugin's purpose, how to enable it, and a description of each configurable setting including its name, accepted values, and default value.
2. THE Claude_Plugin SHALL be documented in `README.md` with content stating the plugin's purpose, how to enable it, and a description of each configurable setting including its name, accepted values, and default value.

### Requirement 11: Tests

**User Story:** As a developer, I want automated tests for the Claude agent, so that its result shapes and fallbacks stay correct as the code changes.

#### Acceptance Criteria

1. WHEN the test suite exercises any Claude agent method that would otherwise call the Anthropic_Messages_API, THE test suite SHALL substitute a mocked HTTP layer such that no outbound network request reaches the Anthropic_Messages_API.
2. WHEN the mocked response body contains valid JSON conforming to the documented schema, THE test suite SHALL assert that `classify`, `draft_report`, and `follow_up_questions` each return a result matching its documented result shape.
3. IF the mocked response body contains invalid JSON that cannot be parsed, THEN THE test suite SHALL assert that `classify`, `draft_report`, and `follow_up_questions` each return their documented fallback result.
4. WHEN the mocked request succeeds, THE test suite SHALL assert that `health` returns a success-shaped dictionary; and IF the mocked request raises an error, THEN THE test suite SHALL assert that `health` returns an error-shaped dictionary.
5. WHILE a non-cloud agent is the Active_Agent, THE test suite SHALL assert that rendered pages display the text "0 bytes to cloud AI".

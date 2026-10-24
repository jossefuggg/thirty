# Requirements Document

## Introduction

This feature adds a public "Report a device problem" front door to the existing Thirty / Vigil system. It lets nurses, clinicians, patients, families, and company staff report a suspected medical-device problem from a phone, without logging in, by scanning a per-device QR code. The reporter answers an adaptive, one-question-at-a-time interview conducted in their own language (English, Spanish, Portuguese, or Haitian Creole). The front door collects the data that FDA Form 3500A and 21 CFR 803 require, reviews a plain-words summary with the reporter, and on confirmation submits the complaint into the existing intake pipeline with the source `reporter` so the pipeline scores, classifies, drafts, and starts the reporting clock exactly as it does for other channels. The reporter receives a reference number and a downloadable PDF receipt.

The feature is entirely local and offline: no external network calls, no CDNs, no third-party services. QR codes are rendered as SVG in pure Python, the adaptive interview is driven by the existing Agent abstraction (extended with a new `next_question` call), and PDFs are produced with `fpdf2`.

## Glossary

- **Front_Door**: The public, no-login web interface served at `/report` and `/report/<device_slug>` for submitting a device-problem report.
- **Reporter**: A person submitting a report through the Front_Door. One of three Reporter_Types.
- **Reporter_Type**: The self-selected category of a Reporter: `nurse_clinician` (nurse or clinician), `patient_family` (patient or family member), or `company_staff`.
- **Device_Slug**: A short URL-safe identifier that maps to one device in the sample device catalogue (the `DEVICES` dict in `thirty/sample_data.py`, keys such as `AF`, `PG`, `NS`, `TC`, `CL`, `VV`, `LM`, `SP`).
- **Reporter_Language**: The language a Reporter selects for the interview. One of: English, Spanish, Portuguese, Haitian Creole.
- **Interview**: The adaptive sequence of follow-up questions asked one at a time until the Agent returns `complete` or the question cap is reached.
- **Agent**: The AI agent abstraction defined in `thirty/agents/base.py` (`class Agent`), with implementations `NoAgent`, `SampleAgent`, the local-model agent, and the Claude agent.
- **next_question**: A new Agent method, `next_question(answers_so_far)`, that returns either the next single follow-up question (adapted to Reporter_Type and Reporter_Language) or the sentinel `complete`.
- **Answers_So_Far**: The accumulated set of Reporter answers and known context (Reporter_Type, Reporter_Language, device) passed to `next_question`.
- **Translation_Pending_Marker**: The literal English-translation placeholder value `translation pending (no model)` stored when no model-backed Agent is available to translate a Reporter's free-text answers. It signals that translation is deferred and MUST NOT be replaced by a fabricated translation.
- **UNKNOWN**: The established sentinel string used throughout the system (see `thirty/sample_data.py` and `base.py`) to represent a value a Reporter does not know.
- **Question_Cap**: The maximum number of Interview questions, fixed at 8.
- **Draft_3500A**: The FDA Form 3500A field set produced for a complaint, in the field shape documented in `base.py` and `thirty/sample_data.py` (fields such as `A2_age`, `B1_event_type`, `B2_outcomes`, `B3_date_of_event`, `B5_event_description`, `D1_brand_name`, `D4_model`, `D4_lot`, `D4_serial`, `H1_type_of_reportable_event`, `H3_device_evaluated`).
- **Intake_Submit**: The existing `intake.submit(payload, kind, default_source, raw, raw_ext)` function in `intake.py` that maps, validates, de-duplicates, saves raw, queues, and returns `(http_status, response_dict)`.
- **Reference_Number**: The stable complaint identifier returned by the intake pipeline (the `vigil_id` value, e.g. `REP-xxxxxxxx`).
- **PDF_Receipt**: A PDF document generated with `fpdf2` summarising the submitted report, given to the Reporter after confirmation.
- **Completeness_Score**: A numeric measure (0–100) of how many required Draft_3500A fields the Reporter supplied with a known (non-UNKNOWN) value.
- **Console**: The existing Flask dashboard application at `dashboard_v2/app.py` and its templates.
- **Integrations_Page**: The existing `dashboard_v2/templates/integrations.html` view in the Console.
- **Demo_Mode**: The state detected by `demo_mode()` / `sample_data_mode()` in which the SampleAgent is active and the system runs fully offline with sample data.
- **QR_Panel**: A panel on the Integrations_Page listing one QR code per sample device, each linking to that device's Front_Door URL.

## Requirements

### Requirement 1: Public mobile-first reporting entry point

**User Story:** As a Reporter without an account, I want to open a reporting page from my phone or a device QR code, so that I can report a device problem without signing in.

#### Acceptance Criteria

1. THE Front_Door SHALL serve a reporting page at the path `/report`.
2. THE Front_Door SHALL serve a reporting page at the path `/report/<device_slug>`.
3. WHERE a request includes a Device_Slug that case-insensitively matches one of the eight catalogue keys (AF, PG, NS, TC, CL, VV, LM, SP), THE Front_Door SHALL pre-fill the device for the report from the matching catalogue entry and SHALL allow the Reporter to change the pre-filled device to any other catalogue entry.
4. IF a request includes a Device_Slug that does not match any of the eight catalogue keys, THEN THE Front_Door SHALL serve the reporting page without a pre-filled device and SHALL prompt the Reporter to select a device from the catalogue before the report can be submitted.
5. THE Front_Door SHALL serve the reporting page without requiring authentication or a login session.
6. THE Front_Door SHALL render the reporting page body text at a minimum font size of 16 CSS pixels and SHALL render every interactive tap target at a minimum size of 44 by 44 CSS pixels.
7. WHERE the Reporter_Type selected on the reporting page is `patient_family`, THE Front_Door SHALL present all page text without regulatory citation references (such as statute, clause, or form-number citations).
8. WHEN a Reporter requests the reporting page at `/report` or `/report/<device_slug>`, THE Front_Door SHALL return the rendered page within 2 seconds under normal local/offline operating conditions.
9. IF rendering the reporting page fails, THEN THE Front_Door SHALL display an error message indicating the page could not be loaded and SHALL not require the Reporter to authenticate to retry.

### Requirement 2: Language selection and bilingual storage

**User Story:** As a Reporter who speaks Spanish, Portuguese, or Haitian Creole, I want to answer in my own language, so that I can describe the problem accurately.

#### Acceptance Criteria

1. THE Front_Door SHALL offer a Reporter_Language picker with exactly four options: English, Spanish, Portuguese, and Haitian Creole.
2. WHEN the Reporter selects a Reporter_Language, THE Front_Door SHALL present all subsequent interface text and Interview questions in the selected Reporter_Language.
3. THE Front_Door SHALL accept the Reporter's free-text description and answers in the selected Reporter_Language, accepting a free-text description of up to 5,000 characters.
4. WHEN a report is submitted in a non-English Reporter_Language AND the active Agent is a model-backed agent (the Claude agent or the local-model agent), THE Front_Door SHALL store the Reporter's original-language free-text together with an English translation produced by the active Agent, retaining both the original text and the translation.
5. WHERE the selected Reporter_Language is English, THE Front_Door SHALL store the original free-text and the English translation as identical text without invoking translation.
6. WHEN a report is submitted in a non-English Reporter_Language AND no model-backed agent is available to translate (for example, the active Agent is the SampleAgent or NoAgent), THE Front_Door SHALL store the Reporter's original-language free-text and SHALL set the English translation to the Translation_Pending_Marker.
7. IF the Reporter submits a report with an empty free-text description, THEN THE Front_Door SHALL reject the submission and present an error message indicating that a description is required, retaining all previously entered answers.
8. THE Front_Door SHALL NOT store any fabricated or machine-guessed English translation; the English translation value SHALL be either an active model-backed Agent translation, identical to the original English text, or the Translation_Pending_Marker.

### Requirement 3: Reporter-type selection

**User Story:** As a Reporter, I want to say who I am, so that the questions I am asked match my role.

#### Acceptance Criteria

1. THE Front_Door SHALL present a Reporter_Type selection with the options nurse or clinician, patient or family, and company staff.
2. WHEN the Reporter selects a Reporter_Type, THE Front_Door SHALL record the selected Reporter_Type for the report.
3. THE Front_Door SHALL pass the selected Reporter_Type to the Agent for use in adapting Interview questions.
4. IF the Reporter has not selected a Reporter_Type, THEN THE Front_Door SHALL prevent the Interview from starting and SHALL prompt the Reporter to choose a Reporter_Type.

### Requirement 4: Adaptive one-question-at-a-time interview

**User Story:** As a Reporter, I want to be asked one simple question at a time, so that I can give the needed facts without being overwhelmed by a long form.

#### Acceptance Criteria

1. WHEN the Interview starts, THE Front_Door SHALL call `next_question` with the Answers_So_Far and SHALL present exactly one returned question to the Reporter.
2. WHEN the Reporter submits an answer, THE Front_Door SHALL add the answer to Answers_So_Far and SHALL call `next_question` again with the updated Answers_So_Far.
3. WHEN `next_question` returns `complete`, THE Front_Door SHALL end the Interview and proceed to the review step.
4. THE Front_Door SHALL present each Interview question adapted to the recorded Reporter_Type and the selected Reporter_Language.
5. WHEN the Reporter has submitted answers to 8 questions, THE Front_Door SHALL end the Interview and proceed to the review step without calling `next_question` again, regardless of any pending `next_question` result.
6. THE Front_Door SHALL present each question with a selectable "I don't know" response option in addition to the answer input.
7. WHEN the Reporter selects "I don't know" for a field, THE Front_Door SHALL record the value for that field as the UNKNOWN sentinel and SHALL advance to the next question.
8. THE Interview SHALL collect the following Form 3500A / 21 CFR 803 data fields: device brand name, device model, lot number or serial number, a free-text description of what happened, patient outcome (exactly one of death, hospitalisation, injury, or none), whether the device malfunctioned (one of yes, no, or UNKNOWN), date of the event, date the problem was noticed, and a follow-up contact.
9. IF `next_question` returns neither a question nor `complete`, THEN THE Front_Door SHALL end the Interview, preserve all answers recorded in Answers_So_Far, and proceed to the review step with an indication that the Interview ended without completion.
10. WHERE a required Form 3500A field has no answer in Answers_So_Far when the Interview ends, THE Front_Door SHALL record that field as the UNKNOWN sentinel.

### Requirement 5: Plain-words review and confirmation

**User Story:** As a Reporter, I want to see a readable summary of what I reported before it is sent, so that I can correct mistakes and confirm.

#### Acceptance Criteria

1. WHEN the Interview ends, THE Front_Door SHALL present a review screen summarising the collected answers in plain language.
2. WHERE a collected value is UNKNOWN, THE Front_Door SHALL display that value on the review screen as a plain-language "not known" indication rather than the raw sentinel text.
3. WHEN the Reporter requests a change on the review screen, THE Front_Door SHALL allow the Reporter to revise the collected answers before confirming.
4. WHEN the Reporter confirms the review, THE Front_Door SHALL submit the report.
5. IF the Reporter has not confirmed the review, THEN THE Front_Door SHALL NOT submit the report.

### Requirement 6: Submission into the existing pipeline

**User Story:** As a compliance operator, I want front-door reports to enter the same intake pipeline as other channels, so that they are scored, classified, drafted, and clocked consistently.

#### Acceptance Criteria

1. WHEN the Reporter confirms the review, THE Front_Door SHALL submit the report through Intake_Submit with the payload `source` field set to the literal value `reporter`.
2. WHEN the Front_Door submits the report, THE Front_Door SHALL include the selected Reporter_Type in the submitted payload.
3. WHEN the Front_Door submits the report, THE Front_Door SHALL map the collected answers onto the intake payload fields recognised by Intake_Submit (`text`, `device`, `manufacturer`, `event_date`, `product_code`, `reporter`, `external_id`).
4. WHEN Intake_Submit returns an HTTP status of 202 with a response status of `queued`, THE Front_Door SHALL display the returned Reference_Number (the `vigil_id` value, formatted as `REP-xxxxxxxx`) to the Reporter.
5. IF Intake_Submit returns an HTTP status of 200 with a response status of `duplicate`, THEN THE Front_Door SHALL display the existing Reference_Number (the `vigil_id` value, formatted as `REP-xxxxxxxx`) to the Reporter and SHALL display an indication that the report was already received.
6. IF Intake_Submit returns an HTTP status of 400 with a response status of `rejected`, THEN THE Front_Door SHALL display a plain-language error message derived from the returned `error` value to the Reporter, SHALL retain all previously entered answers unchanged for correction, and SHALL NOT submit a new report until the Reporter re-confirms.
7. WHEN a confirmed report is submitted and Intake_Submit returns a `queued` result, THE Front_Door SHALL cause exactly one complaint to be created for that confirmation.
8. IF Intake_Submit returns a `duplicate` or `rejected` result, THEN THE Front_Door SHALL NOT create an additional complaint for that confirmation.

### Requirement 7: PDF receipt

**User Story:** As a Reporter, I want a PDF copy of my report, so that I have a record of what I submitted.

#### Acceptance Criteria

1. WHEN a report is successfully submitted, THE Front_Door SHALL generate a PDF_Receipt using `fpdf2`.
2. THE PDF_Receipt SHALL include the Reference_Number and a plain-words summary of the submitted report.
3. THE Front_Door SHALL make the PDF_Receipt available to the Reporter for download after submission.
4. WHERE the Reporter_Type is `nurse_clinician`, THE PDF_Receipt SHALL include the line "Copy for your facility's records (user facility reporting, 21 CFR 803.30)".
5. WHERE the Reporter_Type is `patient_family`, THE PDF_Receipt SHALL omit regulatory citation jargon from the Reporter-facing summary text.

### Requirement 8: next_question on the Agent interface

**User Story:** As a developer, I want `next_question` to be part of the Agent interface with an implementation for every agent, so that the Front_Door works with any configured agent.

#### Acceptance Criteria

1. THE Agent interface SHALL define a `next_question(answers_so_far)` method that accepts the Answers_So_Far collection as input and returns exactly one value that is either a single follow-up question object or the sentinel value `complete`.
2. THE SampleAgent SHALL implement `next_question` as a scripted, offline function that returns each follow-up question in the Reporter_Language currently selected, and SHALL provide scripted question text for all four Reporter_Languages.
3. IF the SampleAgent is invoked with a Reporter_Language that is not one of the four supported Reporter_Languages, THEN THE SampleAgent SHALL return the follow-up question in the default Reporter_Language.
4. WHILE Demo_Mode is active, THE SampleAgent SHALL drive the Interview using only scripted responses and SHALL make zero outbound network calls.
5. THE local-model agent SHALL implement `next_question` such that it returns exactly one value that is either a single follow-up question object or the sentinel value `complete`.
6. THE Claude agent SHALL implement `next_question` such that it returns exactly one value that is either a single follow-up question object or the sentinel value `complete`.
7. WHEN the active Agent is NoAgent, THE Front_Door SHALL present a fixed checklist form that collects every field of the Requirement 4 data set on a single screen.
8. WHILE the Requirement 4 data set has not been fully requested, THE active Agent's `next_question` implementation SHALL return exactly one follow-up question.
9. WHEN the Requirement 4 data set has been fully requested, THE active Agent's `next_question` implementation SHALL return the sentinel value `complete`.
10. THE SampleAgent SHALL NOT translate Reporter free-text, and SHALL defer translation by leaving the English translation as the Translation_Pending_Marker.
11. WHEN the active Agent is a model-backed agent (the Claude agent or the local-model agent), THE active Agent SHALL translate the Reporter's non-English free-text to English, and SHALL NOT return a fabricated translation when it cannot translate.

### Requirement 9: Console source badge and completeness score

**User Story:** As a compliance reviewer, I want to see which complaints came through the front door and how complete they are, so that I can triage reporter submissions.

#### Acceptance Criteria

1. WHERE a complaint has the source value `reporter`, THE Console SHALL display a source badge labeled "Reporter" for that complaint.
2. WHERE a complaint has a source value other than `reporter`, THE Console SHALL NOT display the "Reporter" source badge for that complaint.
3. THE Console SHALL compute a Completeness_Score for each `reporter`-source complaint as an integer from 0 to 100 equal to the proportion of required Draft_3500A fields holding a non-UNKNOWN value, rounded to the nearest integer.
4. WHEN all required Draft_3500A fields of a `reporter`-source complaint hold a non-UNKNOWN value, THE Console SHALL compute a Completeness_Score of 100.
5. WHEN every required Draft_3500A field of a `reporter`-source complaint holds the value UNKNOWN, THE Console SHALL compute a Completeness_Score of 0.
6. THE Console SHALL display the Completeness_Score for each `reporter`-source complaint as an integer value from 0 to 100.
7. IF the `source` column is absent or holds an empty value for a complaint, THEN THE Console SHALL treat that complaint as non-`reporter` source and SHALL NOT display the "Reporter" source badge or a Completeness_Score for that complaint.

### Requirement 10: QR codes panel on the integrations page

**User Story:** As an operator, I want a QR code for each device, so that I can print and place one QR code per device for reporters to scan.

#### Acceptance Criteria

1. WHEN the Integrations_Page is rendered, THE Integrations_Page SHALL display a QR_Panel.
2. WHEN the QR_Panel is rendered, THE QR_Panel SHALL display exactly 8 QR codes, one for each device in the sample device catalogue.
3. THE QR_Panel SHALL encode in each QR code the Front_Door URL formed by concatenating `/report/` with that device's device_slug.
4. THE QR_Panel SHALL render each QR code as an inline SVG element generated entirely within the application's Python process, without making any external service request or network call.
5. IF the sample device catalogue contains zero devices, THEN THE QR_Panel SHALL display zero QR codes and SHALL display a message indicating that no devices are available.
6. IF generating the SVG for a device's QR code fails, THEN THE QR_Panel SHALL omit that device's QR code and SHALL display an error indication identifying the affected device, while continuing to render the QR codes for the remaining devices.

### Requirement 11: Correctness properties

**User Story:** As a developer, I want the core behaviours expressed as formal, testable properties, so that property-based tests can verify them across many inputs.

#### Acceptance Criteria

1. FOR ALL sequences of Reporter answers, THE Interview SHALL terminate with the Interview ending either because `next_question` returned `complete` or because 8 questions were answered (question-loop termination property).
2. FOR ALL Reporter answers equal to "I don't know", THE corresponding field in the Draft_3500A SHALL have the value UNKNOWN (UNKNOWN-preservation property).
3. FOR ALL confirmed report submissions, Intake_Submit SHALL result in exactly one complaint with source `reporter` for that confirmation (single-complaint property).

## Correctness Properties

The following properties restate the core behaviours in a form suitable for property-based testing with Hypothesis. Each is universally quantified over generated inputs and must hold for every generated case.

### Property 1: Question-loop termination

- **Statement:** For any Agent implementation and any generated sequence of Reporter answers (including arbitrary "I don't know" answers), running the Interview loop ends after at most 8 questions, and it ends either because `next_question` returned `complete` or because the Question_Cap of 8 was reached.
- **Quantification:** For all `(reporter_type, reporter_language, answer_sequence)`.
- **Invariant:** `questions_asked <= 8` at every step, and the loop always reaches a terminal state (`complete` or cap). No input produces an unbounded or non-terminating Interview.
- **Pattern:** Invariant / termination.

### Property 2: UNKNOWN preservation

- **Statement:** For any field for which the Reporter answered "I don't know", the value of that field in the resulting Draft_3500A is exactly UNKNOWN.
- **Quantification:** For all `(field, answer_sequence)` where the answer for `field` is "I don't know".
- **Invariant:** An "I don't know" answer maps to UNKNOWN and is never overwritten by a guessed, blank, or defaulted value in the Draft_3500A.
- **Pattern:** Invariant / metamorphic (a specific input class maps deterministically to a specific stored value).

### Property 3: Single complaint on submit

- **Statement:** For any confirmed report, submitting it through Intake_Submit results in exactly one complaint whose source is `reporter`.
- **Quantification:** For all confirmed `(reporter_type, reporter_language, collected_answers)`.
- **Invariant:** One confirmation yields exactly one `reporter`-source complaint; the submitted payload always carries source `reporter`. (Re-submitting the same confirmation is de-duplicated by the existing `vigil_id` mechanism and does not create a second complaint.)
- **Pattern:** Invariant / model-based (count of created complaints for a confirmation equals 1).

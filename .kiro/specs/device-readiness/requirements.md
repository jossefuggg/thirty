# Requirements Document

## Introduction

This feature adds a public **Device readiness** page at `/readiness` to the Thirty / Vigil console. It is aimed at wellness and wearable companies with a health feature who need to understand, before they ship, whether that feature is likely general wellness or a medical device under current FDA policy, what has already gone wrong with similar devices in public FDA data, and exactly which obligations begin on day one if the feature is a device.

The motivation: in January 2026 the FDA updated its **General Wellness: Policy for Low Risk Devices** and **Clinical Decision Support Software** guidance documents, widening what wearables can present as general wellness. Companies with health features keep crossing the line between wellness and device. Thirty is the postmarket reporting system they need the day they become a device manufacturer, so the readiness page ends by showing which day-one obligations Thirty itself handles.

The page runs as a four-step flow:

1. **The feature** — plain-language questions about what the feature claims to do (one screen, large tap targets).
2. **Likely category** — a deterministic, rule-based verdict (general wellness / borderline / device Class I / II / III), with the two to four answers that drove it.
3. **What goes wrong with devices like this** — patterns from public openFDA MAUDE and recall data for a chosen FDA product code, served from a local cache so it works offline and in the public demo.
4. **What starts on day one** — a checklist of device-manufacturer obligations with citations, tagging which ones Thirty handles.

The page then offers a PDF download and a link to start setup (or, in the public demo, to the Command Center). It carries a disclaimer at the top and bottom of the result.

### Decision support, not regulatory advice

This feature is **decision support, not regulatory advice**. The category logic is deterministic and rule-based — no AI decides the outcome. Every outcome is phrased as "likely", cites its source, and directs the user to confirm with a regulatory professional or to ask the FDA directly through a 513(g) Request for Information or a Q-Submission. The feature must **never invent** regulations, guidance names, dates, or URLs. Only the sources enumerated in the Citation Catalogue below may be cited.

### Boundaries (do not change)

- **No edits to `report_*` templates or routes.** This feature does not touch the Form 3500A / reporter reporting surfaces.
- **Build sequencing:** implementation (code and tests) begins only after the public-demo spec has finished. This requirements document and the design document may be written now; no readiness code is written until that dependency clears.
- **Invented only:** all example companies, devices, and people used in the UI must be fictional. Real public FDA data (openFDA) is fine for the "what goes wrong" step.

## Glossary

- **Readiness_Page**: The public, no-login page served at `/readiness` in the console (`dashboard_v2/app.py` + a template), reachable from a new sidebar group "Plan" with the item "Device readiness".
- **Flow**: The four-step sequence a user completes on the Readiness_Page: Feature_Questions → Category_Result → Signals_View → Day_One_Checklist.
- **Feature_Questions**: The six plain-language questions of Step 1 (Q1 claims, Q2 invasive/energy, Q3 named disease, Q4 worst outcome, Q5 users, Q6 cleared predicate).
- **Claim_Option**: One of the "all that apply" choices for Q1: `wellness` (support general fitness or wellness — sleep, activity, recovery, stress), `measure` (estimate a body measurement — heart rate, blood pressure, oxygen, ECG, glucose, temperature), `flag` (flag a possible disease or condition), `diagnose` (diagnose a disease), `treat` (guide treatment, dosing or therapy), `replace` (replace a clinician's judgement).
- **Worst_Outcome**: The Q4 answer, one of: `none` (no harm), `minor`, `serious` (serious injury), `death`.
- **Users_Answer**: The Q5 answer, one of: `consumers`, `clinicians`, `both`.
- **Predicate_Answer**: The Q6 answer about an already-cleared device that does the same thing, one of: `yes`, `no`, `unsure`.
- **Category_Result**: The Step 2 outcome, exactly one of: `general_wellness` ("Likely general wellness (not a device)"), `borderline` ("Borderline"), `class_i` ("Likely device: Class I"), `class_ii` ("Likely device: Class II, 510(k) if a predicate exists, otherwise De Novo"), `class_iii` ("Likely device: Class III, PMA").
- **Driver**: A short plain-language statement of one Feature_Questions answer that contributed to the Category_Result. Between two and four Drivers are shown with every result.
- **Readiness_Rules**: The deterministic rule set stored in the data file `thirty/readiness_rules.json`, read by the category logic. The rules are data, not hard-coded in templates.
- **Device_Verdict**: Whether the Category_Result is a device category (`class_i`, `class_ii`, or `class_iii`) as opposed to `general_wellness` or `borderline`.
- **Product_Code**: A three-letter FDA device product code used to query openFDA (for example the sample devices' codes BZD, FRN, QBJ, DWJ, MWI, NOU, DQA, FLE).
- **Product_Code_List**: The searchable list of Product_Codes offered in Step 3: the eight sample devices' codes plus a small set of common wearable/monitor codes, each with a human-readable label.
- **OpenFDA_Event_API**: The openFDA device adverse-event endpoint `https://api.fda.gov/device/event.json`.
- **OpenFDA_Recall_API**: The openFDA device recall endpoint `https://api.fda.gov/device/recall.json`.
- **Signals_View**: The Step 3 result for a chosen Product_Code: top device problems, top patient problems, reports per year, and recent recalls with their stated reason.
- **Where_To_Look_First**: The Step 3 panel that maps openFDA patterns to the Step 1 answers (for example, accuracy/false-reading problems highlighted for `measure` features; software/connectivity problems highlighted for connected features), each item shown with the count behind it and its source.
- **OpenFDA_Cache**: On-disk cached JSON under `data/openfda_cache/`, one file per Product_Code per API, each recording the query URL and the fetch date, so the Signals_View works offline and in the public demo.
- **Refresh_Button**: The "Refresh from openFDA" control that may update the OpenFDA_Cache when online, and is disabled in the public demo.
- **Day_One_Checklist**: The Step 4 list of device-manufacturer obligations that begin on day one, each with a Citation and, where applicable, a Thirty_Tag.
- **Thirty_Tag**: A label on a Day_One_Checklist item indicating Thirty's relationship to that obligation: "Thirty handles this" or "Thirty flags these".
- **Citation**: A reference to a source drawn only from the Citation Catalogue (a regulation, a named FDA guidance, or an openFDA API URL). A Citation names the source and, where listed, its effective date.
- **Disclaimer**: The exact sentence "Decision support only, not regulatory advice. Confirm with a regulatory professional or ask FDA (513(g) request or Q-Submission)."
- **Example_Preset**: The "Try an example: Stride Band" control that fills the Feature_Questions with answers producing a borderline result in one tap. Stride Band is an invented wellness wearable with a blood-pressure trend feature.
- **Public_Demo**: The locked public deployment state reported by `config.public_demo()` (env `THIRTY_PUBLIC_DEMO`), in which settings surfaces are read-only and setup is skipped.
- **Demo_Mode**: The state reported by `config.demo_mode()` in which the sample agent runs on sample data with no model configured.

## Citation Catalogue

Only the following sources may be cited by this feature. The feature MUST NOT introduce any other regulation, guidance name, date, or URL. Each entry lists the citation label and, where applicable, the effective date and URL as used by this feature.

| Key | Citation label | Effective date (where cited) | URL (where cited) |
|---|---|---|---|
| `gw_guidance` | FDA guidance "General Wellness: Policy for Low Risk Devices" (updated January 2026) | January 2026 | — |
| `cds_guidance` | FDA guidance "Clinical Decision Support Software" (updated January 2026) | January 2026 | — |
| `reg_807` | 21 CFR Part 807 (establishment registration and device listing) | — | — |
| `reg_820_qmsr` | 21 CFR Part 820, the Quality Management System Regulation (QMSR), aligned with ISO 13485 | In effect since 2 February 2026 | — |
| `reg_803` | 21 CFR Part 803 (Medical Device Reporting) | — | — |
| `reg_806` | 21 CFR Part 806 (reports of corrections and removals) | — | — |
| `reg_830` | 21 CFR Part 830 (Unique Device Identification) | — | — |
| `reg_801` | 21 CFR Part 801 (device labeling) | — | — |
| `fdc_524b` | FD&C Act section 524B (cybersecurity for cyber devices) | — | — |
| `path_513g` | 513(g) Request for Information | — | — |
| `path_qsub` | Q-Submission | — | — |
| `openfda_event` | openFDA device adverse-event API | — | `https://api.fda.gov/device/event.json` |
| `openfda_recall` | openFDA device recall API | — | `https://api.fda.gov/device/recall.json` |

The exact day-one deadlines that may be stated: Medical Device Reporting within **30 calendar days**, and within **5 work days** when remedial action is needed (`reg_803`); reports of corrections and removals within **10 working days** (`reg_806`).

## Requirements

### Requirement 1: Device readiness page and navigation entry

**User Story:** As a company with a health feature, I want a Device readiness page reachable from the console and the public demo, so that I can assess my feature before I ship.

#### Acceptance Criteria

1. THE Readiness_Page SHALL be served at the path `/readiness`.
2. THE Console SHALL present in its sidebar a navigation group labeled "Plan" containing an item labeled "Device readiness" that links to `/readiness`.
3. THE Readiness_Page SHALL be reachable without requiring authentication or a login session.
4. WHILE Public_Demo is active, THE Readiness_Page SHALL be served and fully navigable through all four steps.
5. THE Readiness_Page SHALL use the existing Thirty console look (the shared base template, brand tokens, inline SVG icons) and SHALL NOT introduce a new CSS framework.
6. THE Readiness_Page SHALL render its interactive controls as large tap targets sized at least 44 by 44 CSS pixels.

### Requirement 2: Step 1 — the feature questions

**User Story:** As a non-regulatory founder, I want to describe my feature in plain language on one screen, so that I can get a category without learning FDA terminology first.

#### Acceptance Criteria

1. THE Readiness_Page SHALL present Step 1 as a single screen containing the six Feature_Questions.
2. THE Readiness_Page SHALL present Q1 ("What does the feature claim to do?") as a choose-all-that-apply control offering exactly the six Claim_Options: support general fitness or wellness; estimate a body measurement; flag a possible disease or condition; diagnose a disease; guide treatment, dosing or therapy; replace a clinician's judgement.
3. THE Readiness_Page SHALL present Q2 ("Is the feature invasive, implanted, or does it deliver energy or a substance into the body?") as a yes/no control.
4. THE Readiness_Page SHALL present Q3 ("Does the marketing or app mention a specific disease or condition?") as a yes/no control, with examples (hypertension, atrial fibrillation, sleep apnoea, diabetes) shown as illustration only.
5. THE Readiness_Page SHALL present Q4 ("If the output were wrong, what is the worst realistic outcome?") as a single-choice control offering exactly the four Worst_Outcome values: no harm, minor, serious injury, death.
6. THE Readiness_Page SHALL present Q5 ("Who uses it?") as a single-choice control offering exactly the three Users_Answer values: consumers, clinicians, both.
7. THE Readiness_Page SHALL present Q6 ("Is there an already-cleared device that does the same thing?") as a single-choice control offering exactly the three Predicate_Answer values: yes, no, unsure.
8. THE Readiness_Page SHALL use plain-language wording for all Step 1 questions and SHALL NOT require the user to enter free text to obtain a Category_Result.
9. WHEN the user submits Step 1 with at least one Claim_Option selected and an answer to Q2, Q4, Q5, and Q6, THE Readiness_Page SHALL compute a Category_Result and proceed to Step 2.
10. IF the user submits Step 1 without selecting at least one Claim_Option, THEN THE Readiness_Page SHALL NOT compute a Category_Result and SHALL prompt the user to select at least one claim.

### Requirement 3: Step 2 — likely category from deterministic rules

**User Story:** As a company, I want a clear likely category with the reasons behind it, so that I understand whether and how my feature is regulated.

#### Acceptance Criteria

1. THE Category_Result SHALL be computed by a deterministic, rule-based function that reads Readiness_Rules from `thirty/readiness_rules.json`, with no AI or model involvement in deciding the outcome.
2. THE Readiness_Page SHALL display the Category_Result as exactly one of: "Likely general wellness (not a device)", "Borderline", "Likely device: Class I", "Likely device: Class II, 510(k) if a predicate exists, otherwise De Novo", or "Likely device: Class III, PMA".
3. THE Readiness_Page SHALL display between two and four Drivers that state, in plain language, the Step 1 answers that drove the Category_Result.
4. WHEN any of the following are true — a `diagnose` claim, a `treat` claim, a `replace` claim, Q2 answered yes (invasive/implanted/energy/substance), or Q3 answered yes (named disease claim) — THEN THE Category_Result SHALL NOT be `general_wellness`.
5. WHEN Q1 selects only `wellness` (no other Claim_Option), AND Q2 is no, AND Q3 is no, AND Worst_Outcome is `none` or `minor`, THEN THE Category_Result SHALL be `general_wellness`.
6. WHEN Q1 includes `measure`, AND there is no `flag`/`diagnose`/`treat`/`replace` claim, AND Q2 is no, AND Q3 is no, THEN THE Category_Result SHALL be `borderline`, AND THE Readiness_Page SHALL show both paths: that it may be general wellness under the January 2026 guidance if presented as wellness information with no disease claims and no diagnostic use, and that it is otherwise a device.
7. WHEN the feature is a device (Device_Verdict is true) AND Worst_Outcome is `death`, OR the feature is invasive/implanted (Q2 yes) with Worst_Outcome `serious`, THEN THE Category_Result SHALL be `class_iii`.
8. WHEN the feature is a device AND (Worst_Outcome is `serious` OR a `flag` claim is present) AND the Category_Result is not `class_iii`, THEN THE Category_Result SHALL be `class_ii`, AND WHERE Predicate_Answer is `yes` THE Readiness_Page SHALL indicate the 510(k) path, AND WHERE Predicate_Answer is `no` THE Readiness_Page SHALL indicate the De Novo path, AND WHERE Predicate_Answer is `unsure` THE Readiness_Page SHALL show both the 510(k) and the De Novo paths.
9. WHEN the feature is a device AND Worst_Outcome is `minor` AND Q2 is no AND the Category_Result is neither `class_iii` nor `class_ii`, THEN THE Category_Result SHALL be `class_i`, AND THE Readiness_Page SHALL note that many Class I devices are exempt from 510(k) and that the classification regulation should be checked.
10. FOR ANY combination of Feature_Questions answers, THE category logic SHALL return exactly one Category_Result.
11. THE Readiness_Page SHALL phrase the Category_Result using the word "likely" and SHALL display at least one Citation drawn from the Citation Catalogue with the Category_Result.

### Requirement 4: Step 3 — product code selection for the signals view

**User Story:** As a company, I want to pick the FDA product code closest to my feature, so that the public-data patterns I see are relevant.

#### Acceptance Criteria

1. THE Readiness_Page SHALL present a searchable Product_Code_List containing the eight sample devices' Product_Codes and a small set of common wearable/monitor Product_Codes, each entry showing the three-letter code and a human-readable label.
2. THE Readiness_Page SHALL allow the user to select exactly one Product_Code from the Product_Code_List for the Signals_View.
3. WHERE the Category_Result and the Step 1 answers indicate a closest Product_Code, THE Readiness_Page SHALL suggest that Product_Code as the default selection.
4. WHEN the user selects a Product_Code, THE Readiness_Page SHALL render the Signals_View for that Product_Code.
5. THE Product_Code_List SHALL contain only Product_Codes that have a corresponding OpenFDA_Cache entry available, so that every selectable code renders a Signals_View offline.

### Requirement 5: Step 3 — public FDA data patterns

**User Story:** As a company, I want to see what has already gone wrong with similar devices in public FDA data, so that I know where to look first.

#### Acceptance Criteria

1. FOR the selected Product_Code, THE Signals_View SHALL display the top device problems and the top patient problems reported in the last three years, each with the count behind it, computed from the OpenFDA_Event_API count over the device-problem and patient-problem fields.
2. FOR the selected Product_Code, THE Signals_View SHALL display the number of reports per year.
3. FOR the selected Product_Code, THE Signals_View SHALL display recent recalls with their stated reason, computed from the OpenFDA_Recall_API, each recall linking to its FDA record.
4. THE Signals_View SHALL present a Where_To_Look_First panel that maps the openFDA patterns to the Step 1 answers, highlighting accuracy and false-reading problems where Q1 includes `measure`, and highlighting software and connectivity problems where the feature is connected.
5. THE Where_To_Look_First panel SHALL display, for each item, the count behind it and the source of that count.
6. THE Signals_View SHALL display the exact wording: "Patterns from public FDA reports for similar devices. Reports are incomplete and have no usage denominator, so counts are not failure rates. Use this to decide where to look first, not to predict your device's faults."
7. WHERE the OpenFDA_Cache for the selected Product_Code is missing or holds no matching records, THE Signals_View SHALL display a plain-language "no data available for this code" indication for the affected section rather than failing, AND SHALL still display the wording of acceptance criterion 6.
8. THE Signals_View SHALL NOT present any openFDA count as a failure rate or probability for the user's own device.

### Requirement 6: openFDA data caching and refresh

**User Story:** As a maintainer, I want the signals data cached on disk, so that the page works offline and in the public demo, and can be refreshed when online.

#### Acceptance Criteria

1. THE Signals_View SHALL read its openFDA data from the OpenFDA_Cache under `data/openfda_cache/` and SHALL NOT make an outbound network call during normal page rendering.
2. EACH OpenFDA_Cache file SHALL record the query URL used and the date the data was fetched.
3. THE OpenFDA_Cache SHALL be populated during the build for every Product_Code in the Product_Code_List, using the fetch tooling to pull the OpenFDA_Event_API and OpenFDA_Recall_API results for those Product_Codes.
4. THE Readiness_Page SHALL present a Refresh_Button labeled "Refresh from openFDA" that, when activated while online and not in Public_Demo, updates the OpenFDA_Cache for the selected Product_Code from the openFDA APIs.
5. WHILE Public_Demo is active, THE Refresh_Button SHALL be disabled and SHALL NOT make any outbound network call.
6. IF a Refresh_Button request fails or times out, THEN THE Readiness_Page SHALL retain the existing OpenFDA_Cache unchanged and SHALL display a plain-language indication that the refresh did not complete.
7. THE cache loader SHALL handle a missing cache file, an empty cache file, and a cache file with zero matching records without raising an error, returning an empty result that the Signals_View renders as "no data available".

### Requirement 7: Step 4 — day-one obligations checklist

**User Story:** As a company that has just become a device manufacturer, I want to know exactly what obligations start on day one and which ones Thirty handles, so that I can plan.

#### Acceptance Criteria

1. THE Day_One_Checklist SHALL contain the following items, each with its Citation from the Citation Catalogue: establishment registration and device listing (`reg_807`); quality management system QMSR aligned with ISO 13485, in effect since 2 February 2026 (`reg_820_qmsr`); complaint handling and complaint files (`reg_820_qmsr`); Medical Device Reporting — deaths, serious injuries and malfunctions within 30 calendar days, 5 work days when remedial action is needed (`reg_803`); reports of corrections and removals within 10 working days (`reg_806`); Unique Device Identification and labeling (`reg_830` and `reg_801`); cybersecurity for connected cyber devices (`fdc_524b`); audit trail of who decided what and when.
2. THE Day_One_Checklist SHALL show a Thirty_Tag "Thirty handles this" on the complaint-handling item, the Medical Device Reporting item, and the audit-trail item.
3. THE Day_One_Checklist SHALL show a Thirty_Tag "Thirty flags these" on the reports-of-corrections-and-removals item.
4. THE Day_One_Checklist SHALL NOT show a Thirty_Tag on the establishment-registration, QMSR, UDI/labeling, or cybersecurity items.
5. THE Day_One_Checklist SHALL always include the Medical Device Reporting item citing `reg_803`, regardless of the Category_Result.
6. EACH Day_One_Checklist item SHALL display its Citation using only labels, dates, and URLs from the Citation Catalogue.

### Requirement 8: Disclaimer and confirm-with-a-professional guidance

**User Story:** As a user and as a regulator-minded reviewer, I want the page to make clear this is not regulatory advice, so that no one treats the output as a filing decision.

#### Acceptance Criteria

1. THE Readiness_Page SHALL display the exact Disclaimer text "Decision support only, not regulatory advice. Confirm with a regulatory professional or ask FDA (513(g) request or Q-Submission)." at the top of the result.
2. THE Readiness_Page SHALL display the exact Disclaimer text at the bottom of the result.
3. EVERY Category_Result SHALL be phrased with the word "likely" and SHALL direct the user to confirm with a regulatory professional or ask FDA through a 513(g) request or a Q-Submission.
4. THE Readiness_Page SHALL NOT present any Category_Result as a definitive or final regulatory determination.

### Requirement 9: PDF download and start-setup action

**User Story:** As a company, I want to download the result as a PDF and start setting up Thirty, so that I can share the assessment and act on it.

#### Acceptance Criteria

1. THE Readiness_Page SHALL present a "Download as PDF" button that generates a PDF of the result using `fpdf2`.
2. THE generated PDF SHALL include the Category_Result, the Drivers, the Signals_View summary, the Day_One_Checklist, the Disclaimer, every Citation shown on the page, and the openFDA data sources used.
3. IF `fpdf2` is not available, THEN THE Readiness_Page SHALL degrade gracefully by disabling or hiding the "Download as PDF" button without failing the page.
4. THE Readiness_Page SHALL present a "Start a 30-day trial setup" button.
5. WHILE Public_Demo is not active, THE "Start a 30-day trial setup" button SHALL link to first-run setup.
6. WHILE Public_Demo is active, THE "Start a 30-day trial setup" button SHALL link to the Command Center.

### Requirement 10: Example preset

**User Story:** As a judge or first-time visitor, I want a one-tap example, so that I can see a complete borderline result immediately.

#### Acceptance Criteria

1. THE Readiness_Page SHALL present an Example_Preset button labeled "Try an example: Stride Band (invented wellness wearable with a blood-pressure trend feature)".
2. WHEN the user activates the Example_Preset, THE Readiness_Page SHALL fill the Feature_Questions with answers that produce a `borderline` Category_Result.
3. THE Example_Preset SHALL reference only invented companies and products.
4. WHEN the user activates the Example_Preset and proceeds, THE Readiness_Page SHALL reach the `borderline` Category_Result in a single tap of the preset followed by viewing the result.

### Requirement 11: Rules live in data, not templates

**User Story:** As a maintainer, I want the category rules in a data file, so that the policy can be reviewed and changed without editing templates or Python control flow.

#### Acceptance Criteria

1. THE category rules SHALL be stored in the data file `thirty/readiness_rules.json`.
2. THE category logic SHALL read its thresholds and mappings from `thirty/readiness_rules.json` rather than from hard-coded values embedded in templates.
3. THE Day_One_Checklist content and its Citations SHALL be defined as data (drawn from the Citation Catalogue) rather than hard-coded in templates.

### Requirement 12: Correctness properties

**User Story:** As a developer, I want the core behaviours expressed as formal, testable properties, so that property-based tests can verify them across every answer combination.

#### Acceptance Criteria

1. FOR ALL combinations of Feature_Questions answers, THE category logic SHALL produce exactly one Category_Result (single-category property).
2. FOR ALL combinations in which any of `diagnose`, `treat`, `replace`, Q2 yes, or Q3 yes is present, THE Category_Result SHALL NOT be `general_wellness` (never-wellness property).
3. FOR ALL combinations in which Worst_Outcome is `death`, THE Category_Result SHALL NOT be `class_i` (death-is-not-Class-I property).
4. FOR ALL Category_Results, THE result SHALL include the Disclaimer and at least one Citation (disclaimer-and-citation property).
5. FOR ALL Category_Results, THE Day_One_Checklist SHALL include the Medical Device Reporting item citing `reg_803` (always-803 property).
6. FOR ALL Product_Codes with missing or empty OpenFDA_Cache data, THE cache loader SHALL return an empty result without error, AND the Signals_View SHALL render "no data available" (empty-cache property).
7. FOR ALL Where_To_Look_First items shown, THE item SHALL display its count and its source (count-and-source property).

## Correctness Properties

The following properties restate the core behaviours in a form suitable for property-based testing with Hypothesis. Each is universally quantified over generated inputs and must hold for every generated case. The input space is the full cross-product of Feature_Questions answers: every subset of the six Claim_Options, Q2 ∈ {yes, no}, Q3 ∈ {yes, no}, Worst_Outcome ∈ {none, minor, serious, death}, Users_Answer ∈ {consumers, clinicians, both}, Predicate_Answer ∈ {yes, no, unsure}.

### Property 1: Exactly one category

- **Statement:** For every combination of Feature_Questions answers, the category logic returns exactly one Category_Result from the fixed set of five.
- **Quantification:** For all `(claims, q2, q3, worst, users, predicate)`.
- **Invariant:** The result is a member of `{general_wellness, borderline, class_i, class_ii, class_iii}`; never zero results, never more than one.
- **Pattern:** Invariant / totality.

### Property 2: Never general wellness when a device trigger is present

- **Statement:** If any of `diagnose`, `treat`, `replace` is a selected claim, or Q2 is yes, or Q3 is yes, the Category_Result is not `general_wellness`.
- **Quantification:** For all combinations containing at least one such trigger.
- **Invariant:** A device-triggering answer forecloses the general-wellness outcome.
- **Pattern:** Invariant / metamorphic (a specific input class maps away from one output class).

### Property 3: Death is never Class I

- **Statement:** If Worst_Outcome is `death`, the Category_Result is not `class_i`.
- **Quantification:** For all combinations with Worst_Outcome `death`.
- **Invariant:** The worst-harm answer `death` can never land in the lowest device class.
- **Pattern:** Invariant.

### Property 4: Every result carries the disclaimer and a citation

- **Statement:** Every Category_Result produced is accompanied by the exact Disclaimer text and at least one Citation from the Citation Catalogue.
- **Quantification:** For all combinations.
- **Invariant:** No result is ever rendered without the disclaimer and a source.
- **Pattern:** Invariant.

### Property 5: The checklist always includes 21 CFR 803

- **Statement:** For every result, the Day_One_Checklist contains the Medical Device Reporting item citing `reg_803`.
- **Quantification:** For all combinations.
- **Invariant:** The MDR obligation is present regardless of category.
- **Pattern:** Invariant.

### Property 6: Empty cache is safe and visible

- **Statement:** For any Product_Code whose OpenFDA_Cache file is missing, empty, or has zero matching records, the cache loader returns an empty result without raising, and the Signals_View renders a "no data available" indication while still showing the incomplete-data wording.
- **Quantification:** For all Product_Codes and all empty/missing cache states.
- **Invariant:** Missing or empty data degrades to a visible, non-failing empty state.
- **Pattern:** Invariant / graceful degradation.

### Property 7: Every Where-to-look-first item shows a count and a source

- **Statement:** For every item shown in the Where_To_Look_First panel, the item carries a numeric count and a named source.
- **Quantification:** For all rendered Where_To_Look_First items across all Product_Codes with data.
- **Invariant:** No pattern is shown without its count and its source.
- **Pattern:** Invariant.

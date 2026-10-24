# Implementation Plan: device-readiness

## Overview

This plan implements the public **Device readiness** page at `/readiness` as a new `thirty/readiness/` package plus a rules data file (`thirty/readiness_rules.json`), an on-disk openFDA cache under `data/openfda_cache/`, and a small, additive console integration (one `NAV_GROUPS` tuple, one `/readiness` + `/api/readiness/*` route block, one template, one `LOCKED_ENDPOINTS` entry). The category logic is pure, deterministic, and data-driven — no agent or model decides the outcome. Nothing in this plan edits `report_*` templates or routes.

**Build gate:** implementation (every task below) begins **only after the public-demo spec is finished**. The requirements and this design/plan may be written now; no readiness code is committed until that dependency clears.

Tasks are ordered so dependencies are respected and so the shared console surface is isolated into one contiguous, clearly labelled block:

1. The rules data file and the pure category engine first — Flask- and template-independent, so property tests run against them without a web server.
2. The openFDA cache loader (pure, empty-safe) and the network fetcher (used only by build/refresh).
3. Build-time cache population, including confirming any extra product codes via the openFDA fetch MCP tool.
4. The PDF builder.
5. Property-based tests over the full answer space.
6. Console routes (`/readiness`, `/api/readiness/*`), then the `LOCKED_ENDPOINTS` addition.
7. **TEMPLATE BLOCK** — all `dashboard_v2/templates/` work grouped together so it merges cleanly alongside any concurrent template edits. No Python/logic task depends on this block.
8. Tests co-located with the unit they cover plus the dedicated property-based test file, ending with a full-suite run.

Property-based test sub-tasks are labelled **[PBT]** and reference their property number and the requirement clauses they validate.

## Tasks

- [ ] 0. Confirm the public-demo spec is finished before starting
  - Verify the public-demo spec is complete; do not begin any implementation task below until it is. Requirements and design for device-readiness are already written and may be reviewed now.
  - _Design: Build-sequencing and shared-file note_

- [ ] 1. Author the rules data file `thirty/readiness_rules.json`
  - Create `thirty/readiness_rules.json` with: `categories` (five labels + "likely" headlines), `driver_text`, `paths` (510k, denovo, borderline dual paths), `citations` (the full Citation Catalogue — only these keys may ever be cited), `day_one_checklist` (8 items with citation keys and `thirty` tags: `handles` on complaints/mdr/audit, `flags` on corrections, none elsewhere), `product_codes` (the 8 sample codes to start), `example_preset` (Stride Band, invented), `disclaimer` (exact sentence), `incomplete_data_notice` (exact wording)
  - Use only labels, dates and URLs from the Citation Catalogue; QMSR dated "in effect since 2 February 2026"; openFDA URLs `https://api.fda.gov/device/event.json` and `https://api.fda.gov/device/recall.json`
  - _Requirements: 3.2, 7.1, 7.2, 7.3, 7.4, 8.1, 10.1, 11.1, 11.3_
  - _Design: Components and Interfaces §2 (Rules data file)_

- [ ] 2. Scaffold the `thirty/readiness/` package and the pure category engine
  - [ ] 2.1 Scaffold `thirty/readiness/`
    - Create `thirty/readiness/__init__.py` exporting the public surface (`load_rules`, `normalize`, `categorize`, `load_signals`, `where_to_look_first`, `build_pdf`, `available`)
    - Module docstring stating the core stance: deterministic, data-driven, no AI in the outcome; cites only the catalogue; never invents sources
    - _Requirements: 3.1, 11.1, 11.2_
    - _Design: Overview; Components and Interfaces §1_

  - [ ] 2.2 Implement the rules loader and answer normalizer in `thirty/readiness/engine.py`
    - Define `CLAIM_OPTIONS`, `WORST_OUTCOMES`, `USERS`, `PREDICATE`, `CATEGORIES`, and the module-level `DISCLAIMER`
    - `load_rules()` reads + caches `thirty/readiness_rules.json` by file mtime (mirror the `history_context()`/plugins caching pattern)
    - `normalize(raw)` is total: unknown claims dropped, missing booleans → False, out-of-set scalars → safest default (`worst`→`none`, `users`→`consumers`, `predicate`→`unsure`); never raises on arbitrary input
    - _Requirements: 2.10, 11.1, 11.2_
    - _Design: Components and Interfaces §1 (answer model, load_rules, normalize)_

  - [ ] 2.3 Implement `categorize(answers)` — the deterministic decision in `thirty/readiness/engine.py`
    - Compute the device-trigger predicate (`diagnose`/`treat`/`replace` claim, or invasive, or disease claim)
    - First-match-wins ladder: Class III (death, or invasive+serious) → Class II (device + serious or flag; attach 510(k)/De Novo/both from predicate) → Class I (device + minor non-invasive, with the exemption note; and the device default) → general_wellness (only `wellness`, non-invasive, no disease, worst none/minor) → borderline (measure-only dual paths, and the non-device default)
    - Return exactly one `Result` with `category`, `label`, `headline` (always contains "likely"), 2–4 `drivers` from `driver_text`, `paths`, `citations` (≥ 1 from the catalogue), `suggested_product_code`, and `disclaimer`
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 8.3_
    - _Design: Components and Interfaces §1 (decision procedure, Result shape)_

  - [ ] 2.4 Add engine example-based tests to `tests/test_readiness.py`
    - Rules integrity: every citation key referenced by categories/drivers/paths/checklist resolves in `citations`; checklist tags are exactly `handles` on complaints/mdr/audit, `flags` on corrections, none elsewhere; `product_codes` non-empty
    - Named cases: pure-wellness → `general_wellness`; measure-only → `borderline` with both paths; device+death → `class_iii`; invasive+serious → `class_iii`; device+serious with predicate yes/no/unsure → `class_ii` + 510(k)/De Novo/both; device+minor non-invasive → `class_i` with exemption note; drivers count 2–4
    - Example preset: `categorize(normalize(rules["example_preset"]["answers"]))` is `borderline`; preset names are invented
    - _Requirements: 3.3, 3.5, 3.6, 3.7, 3.8, 3.9, 7.2, 7.3, 7.4, 10.2, 10.3_

- [ ] 3. Implement the openFDA cache loader and fetcher in `thirty/readiness/openfda.py`
  - [ ] 3.1 Implement the pure, empty-safe loader
    - `cache_dir()` → `config.data_dir() + "/openfda_cache"` (created lazily); `load_signals(product_code)` reads `<CODE>_event.json` / `<CODE>_recall.json` and returns the well-formed result `{code, device_problems[], patient_problems[], reports_per_year[], recalls[], fetched{event,recall}, has_data}`; missing/empty/invalid/zero-record → empty result, never raises
    - `where_to_look_first(signals, answers)` maps patterns to Step 1 answers (accuracy/false-reading terms for `measure`; software/connectivity terms for connected features) using the keyword tables; every returned item carries `{label, count, source}`; returns `[]` when no data
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.7_
    - _Design: Components and Interfaces §3 (loader interface); Data Models (Signals, where-to-look-first item)_

  - [ ] 3.2 Implement the network fetcher (build/refresh only)
    - `fetch_and_cache(product_code, *, timeout=20)`: build the event (two `count=...exact` queries + a year-bucket query) and recall query URLs, GET via `requests`, reduce to the stored payload, write each file atomically (tmp + `os.replace`) recording `url` + `fetched`; raise `RefreshError` on any HTTP error/timeout/parse failure
    - Never called on page render; only by the build step and the refresh route
    - _Requirements: 6.2, 6.3, 6.4, 6.6_
    - _Design: Components and Interfaces §3 (network fetcher); Data Models (openFDA cache file)_

  - [ ] 3.3 Add openFDA loader/fetcher tests to `tests/test_readiness.py`
    - Seed a temp `openfda_cache/` under `data_dir`: `load_signals` returns the stored buckets; missing/empty/zero-record files each return the empty result with `has_data=False`; `where_to_look_first` items all carry `count` + `source`; a `measure` feature surfaces accuracy terms, a connected feature surfaces connectivity terms
    - Refresh with patched `requests.get` (contextmanager pattern from `test_claude_agent.py`): canned JSON → cache written atomically with `url` + `fetched`; raising/timeout → `RefreshError`, existing cache untouched
    - _Requirements: 5.4, 5.5, 6.2, 6.6, 6.7_

- [ ] 4. Populate the openFDA cache at build time (fetch MCP tool; confirm extra codes, never guess)
  - For each of the 8 sample product codes (BZD, FRN, QBJ, DWJ, MWI, NOU, DQA, FLE), pull the openFDA event + recall results via the fetch MCP tool and save the reduced JSON cache files (recording query URL + fetch date) under `data/openfda_cache/`
  - For any candidate common wearable/monitor product code: query `device/event.json` for that `product_code` via the fetch MCP tool first; include the code in `readiness_rules.json` `product_codes` and write its cache files **only if the query returns results**; omit any candidate that returns nothing; if none are confirmed, keep just the 8 sample codes
  - Every entry in `product_codes` must have a corresponding cache file so every selectable code renders offline
  - _Requirements: 4.1, 4.5, 6.2, 6.3_
  - _Design: Components and Interfaces §2 (Extra wearable product codes — confirmed, never guessed); §3 (network fetcher)_

- [ ] 5. Implement the PDF builder in `thirty/readiness/pdf.py`
  - Guarded `fpdf2` import (`FPDF = None` on failure); `available()` → `FPDF is not None`
  - `build_pdf(result, signals, checklist, *, product_code) -> bytes | None` mirroring `vigil.render_mdr_pdf` (bundled DejaVu fonts, Helvetica fallback, `pdf.table`/`FontFace` sections): disclaimer top; category result + drivers + paths; signals summary with the incomplete-data notice; day-one checklist with citations + Thirty tags; a "Sources" block listing every citation label/URL and the openFDA query URLs/fetch dates used; disclaimer bottom
  - Render strictly from the engine result, loaded signals, and the rules checklist — invent nothing
  - _Requirements: 9.1, 9.2, 9.3_
  - _Design: Components and Interfaces §4 (PDF builder)_

  - [ ] 5.1 Add PDF tests to `tests/test_readiness.py`
    - When `fpdf2` present: `build_pdf(...)` returns non-empty bytes starting with `%PDF`; the "Sources" section lists the citations and openFDA URLs used
    - When `FPDF` monkeypatched to `None`: `available()` is False and `build_pdf` returns `None`
    - _Requirements: 9.2, 9.3_

- [ ] 6. Checkpoint - pure logic, data, cache, and PDF
  - Ensure all tests so far pass; ask the user if questions arise.

- [ ] 7. Write the property-based tests in `tests/test_readiness_properties.py` (PBT)
  - Shared strategies: `claims = st.sets(st.sampled_from(CLAIM_OPTIONS))`, `invasive/disease = st.booleans()`, `worst/users/predicate = st.sampled_from(...)`; `@settings(max_examples=100)`

  - [ ] 7.1 **[PBT]** Property 1 — Exactly one category
    - **Property 1: Exactly one category**
    - **Validates: Requirements 3.10, 12.1**
    - For every generated tuple, `categorize(normalize(...))["category"] in CATEGORIES` and the call returns a single result; also feed malformed raw dicts through `normalize`→`categorize` to prove totality
    - Tag: `# Feature: device-readiness, Property 1`
    - _Design: Testing Strategy (P1); Correctness Properties §Property 1_

  - [ ] 7.2 **[PBT]** Property 2 — Never general wellness on a trigger
    - **Property 2: Never general wellness when a device trigger is present**
    - **Validates: Requirements 3.4, 12.2**
    - Restrict to tuples with at least one trigger (diagnose/treat/replace, invasive, or disease_claim); assert `category != "general_wellness"`
    - Tag: `# Feature: device-readiness, Property 2`
    - _Design: Testing Strategy (P2); Correctness Properties §Property 2_

  - [ ] 7.3 **[PBT]** Property 3 — Death is never Class I
    - **Property 3: Death is never Class I**
    - **Validates: Requirements 3.9, 12.3**
    - Fix `worst="death"`; assert `category != "class_i"`
    - Tag: `# Feature: device-readiness, Property 3`
    - _Design: Testing Strategy (P3); Correctness Properties §Property 3_

  - [ ] 7.4 **[PBT]** Property 4 — Disclaimer and citation always present
    - **Property 4: Every result carries the disclaimer and a citation**
    - **Validates: Requirements 3.11, 8.1, 8.3, 12.4**
    - For every tuple, assert `result["disclaimer"] == DISCLAIMER`, `len(result["citations"]) >= 1`, and every citation key resolves in the rules catalogue
    - Tag: `# Feature: device-readiness, Property 4`
    - _Design: Testing Strategy (P4); Correctness Properties §Property 4_

  - [ ] 7.5 **[PBT]** Property 5 — The checklist always includes 21 CFR 803
    - **Property 5: The checklist always includes 21 CFR 803**
    - **Validates: Requirements 7.1, 7.5, 12.5**
    - For every tuple, build the day-one checklist and assert an item with citation `reg_803` is present
    - Tag: `# Feature: device-readiness, Property 5`
    - _Design: Testing Strategy (P5); Correctness Properties §Property 5_

  - [ ] 7.6 **[PBT]** Property 6 — Empty cache is safe and visible
    - **Property 6: Empty cache is safe and visible**
    - **Validates: Requirements 5.7, 6.7, 12.6**
    - For generated product codes with missing/empty/invalid/zero-record cache files, assert `load_signals` returns the empty result without raising and `has_data` is False
    - Tag: `# Feature: device-readiness, Property 6`
    - _Design: Testing Strategy; Correctness Properties §Property 6_

  - [ ] 7.7 **[PBT]** Property 7 — Where-to-look-first items show count and source
    - **Property 7: Every where-to-look-first item shows a count and a source**
    - **Validates: Requirements 5.5, 12.7**
    - For generated signals + answers, assert every `where_to_look_first` item has a numeric `count` and a non-empty `source`
    - Tag: `# Feature: device-readiness, Property 7`
    - _Design: Testing Strategy; Correctness Properties §Property 7_

- [ ] 8. Implement the console routes in `dashboard_v2/app.py` (one contiguous, additive block)
  - [ ] 8.1 Add the page and JSON routes
    - `GET /readiness` → `render_template("readiness.html", page="readiness", title="Device readiness")`
    - `POST /api/readiness/category` → `categorize(normalize(json))` as JSON; `GET /api/readiness/signals?code=XXX` → `load_signals(code)` + `where_to_look_first(...)` as JSON; `GET /api/readiness/pdf` → rebuild result+signals from submitted answers, `build_pdf(...)`, return `application/pdf` (404/empty when `fpdf2` missing)
    - All no-auth; the engine runs server-side only
    - _Requirements: 1.1, 1.3, 2.9, 2.10, 3.*, 4.4, 5.*, 6.1, 6.7, 9.1, 9.2, 9.3_
    - _Design: Components and Interfaces §5 (routes)_

  - [ ] 8.2 Add the refresh route and lock it in the public demo
    - `POST /api/readiness/refresh`: when online and not public demo, `fetch_and_cache(code)` and return the refreshed signals; on `RefreshError`, keep the existing cache and return "refresh did not complete"
    - Add `api_readiness_refresh` to `LOCKED_ENDPOINTS` so `_public_demo_lock()` returns 403 in the public demo
    - _Requirements: 6.4, 6.5, 6.6_
    - _Design: Components and Interfaces §5 (refresh, LOCKED_ENDPOINTS); Error Handling_

  - [ ] 8.3 Add route tests to `tests/test_readiness.py`
    - Flask `client`: `GET /readiness` 200; `POST /api/readiness/category` returns expected categories for known answer sets; `GET /api/readiness/signals?code=BZD` returns seeded signals; with `THIRTY_PUBLIC_DEMO=1`, `POST /api/readiness/refresh` returns 403
    - _Requirements: 1.1, 2.9, 4.4, 5.1, 6.5_

- [ ] 9. TEMPLATE BLOCK — all `dashboard_v2/templates/` work (shared surface; do as one contiguous, coordinated block; no Python task depends on this)
  - [ ] 9.1 Add the "Plan" sidebar group
    - Add `("Plan", [("readiness", "/readiness", "Device readiness", "shield")])` to `NAV_GROUPS` in `dashboard_v2/app.py`; if the chosen icon key is not in `ICONS`, add one SVG entry in the same block
    - _Requirements: 1.2_
    - _Design: Components and Interfaces §6 (Navigation)_

  - [ ] 9.2 Create `dashboard_v2/templates/readiness.html`
    - Extends `base.html`, fills `{% block body %}`, self-contained; a scoped `{% block head %}` CSS block gives 44×44 tap targets and the one-screen Step 1 layout (no new CSS framework)
    - Step 1 six questions (Q1 choose-all claims, Q2/Q3 yes-no, Q4/Q5/Q6 single-choice); the example-preset button fills the controls from `example_preset` via a tiny inline script; results/signals/checklist regions populated from `/api/readiness/*` JSON
    - Disclaimer rendered verbatim at the top **and** bottom of the result; the incomplete-data notice rendered verbatim in the Signals view (including the empty state); every result phrased with "likely"
    - Buttons: "Download as PDF" (hidden/disabled when `fpdf2` unavailable), "Refresh from openFDA" (disabled when `PUBLIC_DEMO`), "Start a 30-day trial setup" (href `"/" if PUBLIC_DEMO else "/setup"`); coral reserved for the single key action
    - _Requirements: 1.4, 1.5, 1.6, 2.1–2.9, 3.2, 3.3, 4.1, 4.2, 4.3, 5.4, 5.6, 5.7, 6.5, 7.*, 8.1, 8.2, 8.3, 8.4, 9.1, 9.4, 9.5, 9.6, 10.1, 10.4_
    - _Design: Components and Interfaces §5, §6 (template)_

- [ ] 10. Final checkpoint - run the full suite
  - Run `.venv/bin/python -m pytest -q` and ensure all tests pass; clean up any temp files; ask the user if questions arise
  - _Requirements: 12.1–12.7_

## Notes

- **Build gate:** Task 0 must pass (public-demo spec finished) before any other task starts. Requirements/design are written now; code is not.
- **No `report_*` edits:** this feature touches no reporter/Form-3500A templates or routes.
- **Rules are data:** all category labels, driver phrasings, paths, citations, the day-one checklist, and the product-code list live in `thirty/readiness_rules.json`; templates and Python read them, never hard-code them.
- **Cite only the catalogue:** no regulation, guidance name, date, or URL outside the Citation Catalogue may appear anywhere in the feature.
- **Extra product codes are confirmed via the openFDA fetch MCP tool at build time (Task 4), never guessed;** unconfirmed codes are omitted.
- **Offline-first:** page render reads the cache only; the network is used solely by build-time population and the refresh route (locked in the public demo).
- Property-based test sub-tasks are labelled **[PBT]** and each references its property number and the requirement clauses it validates.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0"] },
    { "id": 1, "tasks": ["1", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "3.1", "3.2"] },
    { "id": 4, "tasks": ["2.4", "3.3", "4", "5"] },
    { "id": 5, "tasks": ["5.1", "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7"] },
    { "id": 6, "tasks": ["6", "8.1"] },
    { "id": 7, "tasks": ["8.2"] },
    { "id": 8, "tasks": ["8.3", "9.1", "9.2"] },
    { "id": 9, "tasks": ["10"] }
  ]
}
```

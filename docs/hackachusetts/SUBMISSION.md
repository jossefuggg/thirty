# Thirty: Hackachusetts submission (Healthcare & Biotech)

## Text description (paste into the form)

Medical device makers must tell the FDA about deaths, serious injuries and dangerous malfunctions within 30 days (5 work days when urgent), under 21 CFR 803. Reports arrive late and incomplete: of 277,055 infusion-pump reports to the FDA in 2023 to 2025, about 1 in 18 had no date of event (openFDA, pulled today).

Thirty fixes the report at the source and runs the clock after it. A nurse, patient or company employee scans a QR code on the device and reports the problem in English, Spanish, Portuguese or Haitian Creole. An AI interview asks one question at a time until every fact the FDA needs is there, and "I don't know" stays UNKNOWN: it never invents facts. Thirty then scores the complaint, pre-decides Reportable, Needs info or Not reportable with the rule cited, starts the deadline, and drafts Form 3500A. A named person approves; Thirty drafts, a human files. Clinicians get a PDF copy for their facility's own reporting duty.

Also new today: Device readiness. A wearable or wellness company answers six questions and sees whether a feature is likely general wellness or a medical device under FDA's January 2026 guidance, what has already gone wrong with similar devices in FDA data, and what obligations start on day one. Decision support, not regulatory advice.

Existed before today (Thirty 1.2.1): scoring rules, decision record, reporting clocks, plugin agents (sample and local model), intake API, console, signed audit trail.
Built today in Kiro: the Claude agent plugin, the multilingual reporter front door with QR codes and receipts, Device readiness, a public demo anyone can open on a phone, and a redesigned console in our pitch-deck look. 173 automated tests pass (57 this morning).

Try it: https://thirty-public-demo.onrender.com (invented sample data; open /report to file a report as a nurse, /readiness for the device check). The free server sleeps when idle; the first load can take up to a minute. Run locally without any API key: see README.

## How we used Kiro

Our strategy: specs for anything that touches an FDA rule, vibe coding only for the look, and checks that run without us.

**Tools: Kiro IDE and Kiro CLI.** We built in the IDE all day, with up to four sessions in parallel (specs, quick specs and a vibe chat), each owning its own files; edits to shared files were held and released in order, so no session overwrote another. We then installed kiro-cli and used it from the terminal to draft this write-up from our log and specs. The CLI was faster for one-shot, file-in-file-out jobs; the IDE was better for specs, hooks and reviewing diffs. Our hooks fired in both.

**Spec-driven development (3 full specs, 2 quick specs, plus vibe mode for the look).**
- Claude agent plugin: requirements, design, tasks, with Autopilot off so we reviewed each stage before code.
- Reporter front door: Kiro read our intake, agent and sample-data code, ran seven requirement-detailer sub-agents in parallel, and wrote a correctness-properties section. Reviewing the requirements caught an impossible promise (offline translation of free text in Haitian Creole) before any code: translation now comes from the active model, and the offline sample agent marks it "translation pending" instead of faking it.
- Device readiness: rules in a data file, a citation catalogue so no regulation or date can be invented, and properties over every possible answer combination. Our own review caught a rule gap (high-risk body measurements labelled "borderline"), fixed with a new property test.
- Public demo (Quick Spec): render.yaml, gunicorn, a locked public mode where 14 write routes refuse, a banner, no secrets rendered, a phone-sized complaint page. Kiro booted gunicorn to check it and found that start-up only ran under `__main__`, so the deployed app would have been empty. It fixed that before we deployed.
- Specs versus vibe: the specs were slower to start but caught problems on paper. Vibe mode was right for the console redesign (6 number cards to 3, 4 status pills to 1, grouped sidebar; before/after screenshots in docs/), but it also hid the Form 3500A PDF in a tab, which we only noticed by using the app. We fixed that with a follow-up prompt. That is why the FDA rules stayed in specs.
- Verify, don't trust ticks: Kiro once marked six tasks done while the plugin folder did not exist. We caught it by comparing git status with tasks.md and re-ran the tasks. Since then we check files, not checkboxes.

**Steering.** One always-included file, hackathon.md, holds the context, a map of the code, the brand rules and a list of phrases we must never claim (for example that Thirty files with the FDA or is fully automated). "Generate Steering Docs" added product.md, tech.md and structure.md from the codebase. When the new cloud plugin clashed with our local-first privacy principle, we added a written exception to the steering instead of arguing with every task. The biggest win was the never-say list: it turned a pitch rule into something Kiro enforced.

**Accessibility.** When the readiness page broke in light mode, Kiro moved every colour to theme tokens and computed WCAG contrast for every text pair, raising the weakest from 3.84:1 to 6.47:1.

**Agent hooks.** run-tests runs pytest as a shell command on every save (no credits used). compliance-guard is an agent hook that checks every saved template, README or doc against the never-say list and the privacy-badge rule, and suggests fixes without editing. It reviewed every page the public-demo spec changed, flagged "cleared" in a readiness question (now "authorized", the FDA's umbrella term), and in the CLI it flagged a line in this write-up, which we fixed. run-tests also exposed tests that read leftover runtime files from the repo; Kiro isolated the test data folder and proved the fix with a deliberately conflicting config file.

**MCP.** We added the fetch MCP server so Kiro could query the live openFDA API while working. It pulled the numbers in our description: 277,055 infusion-pump reports (2023 to 2025), 15,038 with no date of event, and 269,760 with a blank or placeholder lot number ("NA", "N/A", "UNKNOWN" and similar). Kiro also noticed that openFDA's missing-field search counted those placeholders as present, so we measured the real values instead. The same server cached openFDA problem and recall data for Device readiness, so the page works offline and in the public demo, and showed that our design used the wrong openFDA field names; Kiro corrected them against the live API.

**Property-based testing (Hypothesis).**
- Claude agent: for any malformed or random model output, every agent call returns the documented shape and never crashes.
- Front door: the interview always ends at "complete" or 8 questions; an "I don't know" answer stays UNKNOWN in the draft Form 3500A; each confirmation creates exactly one complaint. While implementing the first property, a smoke test hung for 120 seconds: an agent that kept asking for the same field looped forever, because the cap counted distinct fields, not questions asked. Kiro fixed the cap before any reporter could hit it.
- Device readiness, over all 9,216 answer combinations: every combination gives exactly one category; a diagnosis, treatment, invasive or disease claim never gives "general wellness"; a possible death never gives Class I; every result carries the disclaimer and the 21 CFR 803 reporting duty.


## Honesty notes for the team
- The public demo and the Claude plugin use a cloud model or the sample agent on invented data only. In production the local-model plugin keeps patient data on site.
- Device readiness and the FDA patterns are decision support, not regulatory advice; report counts are not failure rates.

# How we used Kiro (Hackachusetts, 24 Oct 2026)

Thirty 1.2.1 existed before today. Everything below was built today in Kiro on the hackachusetts branch.

| Time | Kiro feature | What we did | Why it helped |
|---|---|---|---|
| 12:15 | Steering | Wrote hackathon.md: context, code map, brand rules, do-not-say list, always included | Every task starts knowing the FDA rules and our limits |
| 12:50 | Steering | Generate Steering Docs created product.md, tech.md, structure.md from the codebase | Kiro learned the agent/plugin seam and data paths in 3 minutes |
| 12:55 | Steering | Added the cloud-demo exception to product.md | Stopped a conflict between "0 bytes to cloud" and the Claude plugin |
| 13:00 | Specs | Spec 1 (Claude agent plugin): requirements first, Autopilot off to review each stage | |
| 13:15 | Specs + PBT | Spec 1 design and task list generated; property-based tests requested for malformed model output | Plan reviewed before any code was written |
| 13:30 | Agent hooks | run-tests (shell command on save) and compliance-guard (agent checks the do-not-say list) | Tests run on every save for free; wording mistakes are caught before the demo |
| 14:25 | Hooks + tests | The run-tests hook kept failing one test; cause: tests read runtime files from the repo. Kiro isolated the test data folder in conftest.py and proved the fix with a hostile plugins.json | Clean test runs for the rest of the day |
| 14:35 | Specs (sub-agents) | Spec 2 requirements: Kiro read intake, agents and sample data, then ran 7 requirement-detailer sub-agents in parallel and wrote a correctness-properties section for PBT | Requirements matched the real code; we caught an impossible "offline translation" claim before any code |
| 15:20 | Specs + PBT | Spec 2 sub-agent smoke test hung (120 s): an agent re-asking the same field looped forever because the cap counted distinct fields. Fixed to count asks; matches Property 1 (interview always ends) | Bug caught before any reporter could hit it |
| 15:25 | Hooks | Run-tests hook fired on every edit; compliance-guard hook checked integrations.html changes against the do-not-say list automatically | Continuous checks with no manual step |
| 15:25 | Quick Spec | Public-demo spec found that app start-up only ran under __main__, so gunicorn would have served an empty app; moved init to import time | Caught a deploy failure before deploying |
| 15:38 | Quick Spec | Public demo: render.yaml, gunicorn, locked public mode (14 write routes refuse), banner, no secrets rendered, mobile complaint page; 96 tests pass; Kiro booted gunicorn to verify | Judges can test on their own phones |
| 15:55 | Kiro CLI | Installed kiro-cli and used it from the terminal to draft SUBMISSION.md from the log and specs | Compared CLI (fast, one-shot, scriptable) with the IDE (specs, hooks, visual diffs) |
| 15:55 | Kiro CLI + hooks | Used kiro-cli to draft SUBMISSION.md from the log and specs; the compliance-guard hook also fired inside the CLI and flagged one line, which we fixed | Hooks follow the work across IDE and CLI |
| 16:25 | Specs (verification) | Spec 2 checked an interrupted task before trusting it and found a broken redirect (url_for pointed to a non-existent route); after answering a question the page would have crashed | Verify interrupted work, do not assume |
| 16:25 | Parallel sessions | 3 Kiro sessions at once (front door, readiness, console layout); each owns its files and shared-file edits are sequenced, the last one waiting for our go | No overwritten work |
| 17:45 | Specs | Spec 2 complete: 31 of 33 tasks, /report mounted additively; caught a test regression from new template folders; 172 tests pass | Main feature live |
| 16:15 | Steering (fileMatch) | design.md loads only when Kiro edits templates or CSS; mood board attached in chat only, never committed | One visual direction for every UI task without bloating other tasks |
| 16:25 | Parallel sessions | 3-4 Kiro sessions at once (front door, readiness, console layout, landing); each owns its files, shared-file edits sequenced and held until we released them | No overwritten work |
| 16:50 | Spec + MCP + PBT | Readiness built: rules as data, citation catalogue, property tests over all 9,216 answer combinations; MCP showed the design used wrong openFDA field names, Kiro corrected them against the live API | Facts checked at the source |
| 16:55 | Hooks | Compliance guard flagged "cleared" in a readiness question; we switched to "authorized", the FDA's umbrella term | Hook improved accuracy, not just wording |
| 17:00 | Review | We caught a rule gap: high-risk body measurements were labelled "borderline"; added the rule and a property test (measurement + serious injury or death is never wellness) | Domain review on top of the spec |
| 17:45 | Specs | Front door complete: 31 of 33 tasks, /report mounted additively in the shared app file; Kiro fixed a test regression caused by new template folders; 172 tests pass | Main feature live |
| 18:00 | Vibe | Console restyled to the pitch-deck dark theme with our team's brand assets (dial, ribbon), full-window layout, light mode kept as toggle | One look across deck, app and video |
| 18:10 | Vibe + audit | Readiness light-mode bug (invisible text): Kiro moved every colour to theme tokens and computed WCAG ratios for every text pair; fixed selected pills from 3.84:1 to 6.47:1 | Accessible in both themes |
| 18:30 | Quick Spec | Public landing page /start in the deck's hero style, three doors (report, console, readiness), public-demo safe | One front door for judges and the QR code |
| 18:45 | Specs (verification) | /report restyled with theme tokens only (grep-verified, no hard-coded colours); Kiro found /report sat behind the operator setup screen on a fresh install and exempted it | A reporter scanning a QR code never sees setup |

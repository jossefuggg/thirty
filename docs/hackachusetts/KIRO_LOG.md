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

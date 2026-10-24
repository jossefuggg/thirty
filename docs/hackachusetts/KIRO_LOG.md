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

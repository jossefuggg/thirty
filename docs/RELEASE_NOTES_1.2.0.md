## Thirty 1.2.0 — compliance record

Unsigned builds for macOS (Apple Silicon and Intel), Windows and Linux. macOS: after installing, run `xattr -cr /Applications/Thirty.app` once, or right-click → Open. Windows: "More info" → "Run anyway".

### New
- **Reportability decision record** (21 CFR 803.18) on every complaint: a seven-question tree pre-filled by the agent, confirmed by a named reviewer with a written rationale, also for "not reportable". Optional 21 CFR 820.35 complaint-record fields.
- **Reporting clocks per jurisdiction** from the awareness date: US FDA 30 / 5 work days, EU MDR and UK MHRA 2 / 10 / 15 days, Health Canada 10 / 30 days. Enabled per site under Licence & updates → Workspace.
- **Signed, hash-chained audit trail**: approve, request info, undo and recorded decisions are written with the reviewer's name, the meaning of the signature and the time. The Audit Log verifies the chain and exports it.
- **Submission pack**: one zip per complaint with the drafted Form 3500A, the decision record, the clocks and the signed audit entries.

### Fixed
- Sidebar no longer scrolls off the top of the window; logo and page titles stay visible.
- Narrow windows (1280–1500 px): KPI cards, top bar, home grid, complaints and audit tables, trends chips and plugin cards now fit.
- First-run setup showed the local-model fields while "Sample agent" was selected.
- Windows: file encodings and a CSV field-size overflow.

Details: `docs/COMPLIANCE.md`. Thirty drafts; a human files.

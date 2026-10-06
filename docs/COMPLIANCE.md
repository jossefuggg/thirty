# Compliance features

What Thirty records, where, and the regulation each piece answers to. Everything here is deterministic
(no model) and works in demo mode with the sample agent. The research behind the priorities is in
[`MARKET.md`](MARKET.md) §5.

## 1. Reportability decision record (21 CFR 803.18, ISO 13485 8.2.2)

Every complaint page has a **Reportability decision** card: seven yes / no / unknown questions, pre-filled
from the agent's classification, that a named reviewer confirms or changes:

| # | Question | Drives |
|---|---|---|
| 1 | Death? | 803.50(a)(1) · EU/UK 10-day · CA 10-day |
| 2 | Serious injury / serious deterioration? | 803.50(a)(1) · EU/UK · CA |
| 3 | Malfunction likely to cause either if it recurred? | 803.50(a)(2) |
| 4 | Remedial action needed to prevent substantial public harm? | 803.53 5-work-day report |
| 5 | Serious public health threat? | EU/UK 2-day |
| 6 | Unanticipated serious deterioration? | EU/UK 10-day instead of 15 |
| 7 | Similar complaint already investigated? | 820.35(a) reference instead of a repeat investigation |

The outcome (Reportable · category · 5-day, Needs info, or Not reportable) is computed live in the page
and again on the server (`thirty/decisions.py: evaluate`). Recording needs the **reviewer's name**, a
**rationale** (also for Not reportable) and the **awareness date**; optional 21 CFR 820.35(a) fields
(UDI / lot / serial, complainant contact, similar-complaint reference, correction, reply) sit under
"Complaint record fields".

Recording a decision:

* appends the record to `<data>/decisions/<id>.json` (history kept, newest last);
* updates the complaint's row in `decisions.csv` (decision, category, deadline days, US due date, reason)
  so every screen reflects the human decision; Not reportable sets the status to `LOGGED`, Reportable
  puts a logged complaint back into the review queue;
* writes a signed entry to the audit chain (below) with the meaning "I have reviewed the facts and
  record this reportability decision and its rationale."

## 2. Reporting clocks per jurisdiction (`thirty/jurisdictions.py`)

Enabled under **Licence & updates → Workspace** (US FDA always on). From the awareness date:

| Jurisdiction | Rule | Clock |
|---|---|---|
| US FDA | 21 CFR 803.50 / 803.53 | 30 calendar days; 5 work days (Mon–Fri) when remedial action is needed |
| EU MDR | 2017/745 Art. 87 | 2 days public-health threat · 10 days death or unanticipated serious deterioration · 15 days other serious incident |
| UK MHRA | SI 2024/1368 | same 2 / 10 / 15 ladder |
| Health Canada | SOR/98-282 s.59 | 10 days death or serious deterioration · 30 days when a recurrence could cause either |

The complaint page lists every applicable clock with its due date, days left and the channel to file
through. The Compliance Clock shows the non-US clocks as chips under each due date. The row's own due
date stays the US one (what the 3500A draft is for). Public holidays are not modelled.

Awareness date: taken from the decision record when there is one; otherwise inverted from the US due
date (`due − 30 days`, or 5 work days back); otherwise the processing day.

## 3. Signed, hash-chained audit trail (`thirty/audit.py`)

`<data>/audit.jsonl`: one JSON object per line. Each entry holds `seq`, `time`, `actor`, `action`,
`id`, `detail`, `meaning` (the e-signature statement), `prev` (the previous entry's hash) and `hash`
(SHA-256 over `prev` + the entry's canonical JSON). Editing or deleting any line breaks every later hash.

Written on: approve, request info, undo (with the meaning shown in the confirmation dialog), decision
recorded, workspace changed. The Audit Log page shows **Chain verified · N signed entries** (or the
first broken entry) from `GET /api/audit/verify`, and **Signed chain** downloads the file. `actions.csv`
and `decisions.csv` are unchanged, so the hackathon pipeline and Telegram sync keep working.

What this is not: there is no per-user login. The desktop app runs on one reviewer's machine; the
reviewer types their name, and the signature is name + meaning + time. Multi-user roles are a P1 item
in `MARKET.md`.

## 4. Submission pack

**Download submission pack** on a complaint page (`/complaint/<id>/pack.zip`) bundles:

* `MDR_<id>.pdf` and `MDR_<id>.json`: the drafted Form 3500A and its fields;
* `complaint.json`: the complaint row;
* `decision-record.json`: every recorded decision with answers, rationale, reviewer and clocks;
* `clocks.json`: the applicable deadlines;
* `audit-entries.jsonl`: the signed entries for this complaint;
* `README.txt`: what each file is and the chain verification state.

Thirty drafts; a human files, through the regulator's own channel (FDA ESG / eSubmitter, the competent
authority, the MORE portal). HL7 ICSR XML for eMDR and the EU MIR 7.3.1 XML are not produced yet; they
are the next items on the roadmap and need IMDRF code tables that must be exact.

## 5. Status against the research roadmap (`MARKET.md` §5)

| Item | State |
|---|---|
| Decision tree with justification capture | **Shipped** (§1) |
| Awareness date + multi-jurisdiction clock | **Shipped** (§2), work-day calendar for the US 5-day clock, no public holidays |
| 820.35 record fields, similar-complaint reference | **Shipped** as optional fields on the decision record (§1) |
| Part 11-style controls | **Partly**: e-signature meaning + hash-chained audit trail + export (§3); no per-user login |
| HL7 ICSR XML / eSubmitter package | Not yet; submission pack (§4) is the interim |
| Validation package | Not yet; `tests/test_compliance.py` is the start of the OQ evidence |

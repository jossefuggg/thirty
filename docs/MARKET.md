# Thirty — Market Research Report

*Prepared 2026-10-06. Desk research from public web sources; every URL is listed under "Sources". Figures marked **(est.)** are the author's estimates, not sourced numbers. Several primary pages (fda.gov, pmc.ncbi.nlm.nih.gov, a few vendor sites) were unreachable from this environment; where that happened the claim is tied to a secondary source that quotes the primary.*

---

## 0. Headline numbers

| Metric | Value | Source |
|---|---|---|
| Device-related FDA Form 483 citations, FY2025 | 2,660 across 185 provisions | meddeviceguide / intuitionlabs |
| Complaint handling (820.198(a)) share of those | 211 obs., 7.9% (#2 after CAPA at 10.5%) | same |
| MDR procedures (803.17) | 63 obs., 2.4% | same |
| Device warning letters FY2025 citing complaint files | 23 of 44 (QS-related: 38) | gmp-compliance.org |
| Manufacturer MDRs filed late (Sept 2019–Dec 2022) | 13.6% late + 15.5% missing/invalid dates ≈ 29% not demonstrably on time, of 4.43M reports | BMJ 2025 (via RAPS/HealthDay) |
| MDRs FDA receives per year | ~2M+ (one analysis: 1.57M in 2020 → 2.89M in 2025) | fda.gov MDR data files / meddeviceguide |
| US device companies with <50 employees | >80% | AdvaMed / Dept. of Commerce via massdevice |
| Typical eQMS spend, small device company | $15k–$60k/yr (Greenlight Guru), $17.5k/yr Starter (SimplerQMS), $25k/yr floor (MasterControl) | openregulatory, softwareadvice, capterra |
| Quality leaders using AI in workflows today | 10% (ZenQMS, n=100); 5% with AI agents in production (Cenevo, n=110) | zenqms.com, technologynetworks |
| Local-JSON benchmark | Qwen3-4B Q4_K_M: 98.9% schema-valid JSON at 142 tok/s on 8GB GPU; Qwen3-4B 52 tok/s on an 8GB M2 | bestllmfor.com, llmcheck.net |

---

## 1. Market landscape

### 1.1 Who sells complaint handling / MDR / vigilance software

| Vendor | Positioning | Pricing signal | Strengths | What buyers complain about |
|---|---|---|---|---|
| **TrackWise / TrackWise Digital (Honeywell, ex-Sparta)** | Enterprise QMS for pharma + device; Complaints module; eMDR gateway | ~$200/user/month shown as a starting point; quote-based; year-one rises with validation/config | Deep workflow engine; incumbent at large firms; direct eMDR/MIR | "Hangs", slow at peak, "not user friendly", needs admin to move records back; legacy UI; cost of add-ons |
| **MasterControl (Quality Excellence, Qx complaint module)** | Large regulated manufacturers, pharma-heavy | Starts at $25,000/yr; quote-based | Breadth, strong support (4.5/5, 527 Capterra reviews) | Licensing + implementation "high for smaller organizations"; module bugs, slow resolution |
| **Greenlight Guru** | Purpose-built medical-device eQMS (design control, risk, complaints) | ~$15k/yr entry rising to $50–60k; Vendr median ~$44k/yr; 2026 "package separation" price rises reported at up to +100% | Device-specific workflows, audit readiness; 4.5/5 G2 (398 reviews) | Cost and opaque escalation; rigid quality-event language; customers reported migrating away after 2025–26 increases |
| **Qualio** | Cloud QMS for startups/scale-ups; Foundation/Growth/Scale; "AI-assisted" | ~$12k base + ~$3k/user/yr (third-party estimate) | Easy document control; fast onboarding | Setup complexity; editor/UI gripes; frequent changes to keep up with |
| **Veeva Vault QMS / Vault Product Surveillance** | Enterprise life-sciences cloud; Product Surveillance = complaints + reportability + eMDR/MIR | Enterprise; not published | Global Reportability Decision Tree, reporting-timeline management, built-in eMDR XML + ESG gateway, MIR XML; "Quality Event Agent" AI | Enterprise price and implementation; AI agents still rolling out through 2026 |
| **ETQ Reliance (now "Octave")** | Multi-industry QMS + EHS; 40+ apps incl. complaint handling and eMDR | Subscription by users/modules/sites; not public | Breadth; eMDR app | Generalist, not device-native |
| **Arena QMS (PTC)** | PLM + QMS for hardware companies | Not published; per deployment | PLM linkage (BOM, change) | Not complaint-specialist |
| **AssurX** | Configurable eQMS; dedicated **AssurX eMDR** product submitting 3500A via WebTrader or AS2; AI IMDRF coding partnership (3Analytics) | Quote | eMDR direct submission; submission mgmt | Mid-market pricing; quote only |
| **Dot Compliance** | Salesforce-native QMS with "Dottie" AI assistant, pre-validated | Not published; peers at $24–60k/yr | Pre-validated; practical AI assistant | Salesforce dependency |
| **ComplianceQuest** | Salesforce-native EQMS, mid-market device | $60k–$200k+/yr typical | Platform breadth | Price; Salesforce dependency |
| **IQVIA SmartSolve** | eQMS + RIM; Complaint Management with UDI capture, decision trees, global regulatory reporting | Enterprise | Decision trees, global reporting | Enterprise |
| **Matrix Requirements (MatrixQMS)** | ALM + QMS for device startups | Published: $920–$3,390/month flat tiers, or $15–$125/user/month | Transparent pricing; requirements/traceability | Complaint handling is not its core |
| **SimplerQMS** | Small/mid life-science QMS | Published Starter: $17,500/yr up to 15 users, validation docs included | Transparent, all-inclusive | Smaller ecosystem |
| **Ennov** | Pharma-leaning quality + RIM + PV | ~$2,500 start (per-user model, one listing) | PV heritage | Not device-centric |
| **PTC Windchill QMS** | Enterprise; eMDR via file-drop to customer's AS2 server | Enterprise | Documented eMDR flow | Heavy |
| **AI-native newcomers** | **Smarteeva** (AI post-market quality: intake → AE reporting → recalls; Salesforce-based), **Flinn.ai** (Vienna; AI regulatory monitoring, complaint handling, PMS/PSUR; €6M seed, €10M 2024, $20M Series A 2026; "200+ MedTech/IVD" customers), **Tata Elxsi ComplaintIQ**, **3Analytics** (AI IMDRF coding) | None publish pricing | Speed-to-value claims ("70% faster processing") | Cloud-only; AI claims unvalidated publicly |

Sources for this table: see §Sources (compliancequest, stackbriefly, openregulatory, rfp.wiki, capterra, G2, Vendr via rfp.wiki, veeva.com features briefs, assurx.com, iqvia.com, softwareadvice, siliconcanals, vestbee, smarteeva.com, flinn.ai).

### 1.2 Where Thirty fits

- **Price whitespace.** The documented floor for a device eQMS is roughly $15k–$25k/yr, and the market leader for small companies has reportedly doubled prices for 2026. Nobody in the table sells a complaint/MDR-only tool at a low-five-figure per-site price with no per-seat meter. **Thirty can credibly sit at $4k–$12k/site/yr (est.)** as a "complaint and reporting workbench" that coexists with (rather than replaces) a document-control QMS.
- **Deployment whitespace.** Every vendor above is cloud/SaaS (TrackWise classic on-prem is legacy). A local-first desktop tool with offline licence keys is unique; the question is whether that is a feature buyers want (see §4) or an obstacle to multi-user collaboration (see §7).
- **AI whitespace is narrower than it looks.** Veeva (decision tree + agents), AssurX/3Analytics (IMDRF coding), Smarteeva, Flinn, Dot "Dottie" all claim AI triage. Thirty's differentiator is not "AI drafts" but **"AI drafts locally, with the rationale captured and a named human filing"**.
- **Risk of being a feature, not a product.** Complaint handling is one module in every suite. Thirty needs either (a) a wedge the suites do badly (reportability rationale, deadline clock, MAUDE trending, eMDR XML for firms with no gateway) or (b) to be the system of record for complaints at firms that have no eQMS at all (spreadsheets/email), which is the stated target.

---

## 2. Regulatory reality check

### 2.1 US FDA — 21 CFR 803 (MDR) and eMDR

| Requirement | Detail a tool must implement |
|---|---|
| **803.50 30-day report** | ≤30 calendar days after the day the manufacturer "receives or otherwise becomes aware" of information that *reasonably suggests* death, serious injury, or a malfunction likely to cause/contribute to one if it recurs. Clock starts at awareness by *any* employee, not at QA logging. |
| **803.53 5-day report** | ≤5 **work** days when the event requires remedial action to prevent an unreasonable risk of substantial harm to public health, or on FDA written request. |
| **803.56 supplemental** | Information unavailable at initial report must be filed within one month (30 days) of receipt. Tool needs follow-up tracking and re-submission with H10 related report numbers. |
| **803.17 / 803.18** | Written MDR procedures and MDR event files (retain 2 years or device life, whichever longer); files must show the information evaluated and the deliberations for *every* reportability decision, including "not reportable". |
| **eMDR mandate** | Since **14 Aug 2015** manufacturers and importers must file electronically via the FDA Electronic Submissions Gateway (ESG), either with FDA **eSubmitter** (low volume, via WebTrader — replaced by the **ESG NextGen Unified Submission Portal on 14 Apr 2025**) or as **HL7 ICSR XML** over **AS2** (high volume). Three acknowledgements: ACK1 (received), ACK2 (routed to CDRH), ACK3 (HL7 validation pass/fail). A paper/PDF 3500A is **not** a valid manufacturer submission. |
| **IMDRF adverse-event codes** | Since **31 Mar 2025** (production), every initial manufacturer/importer report must carry at least one valid code of each type in **F10** (device problem; IMDRF Annex A) and **H6** (patient problem/health effects; Annexes E/F etc.) or it gets an ACK3 rejection. eSubmitter users could start 8 Nov 2024. IMDRF updated the terminology again (36 new, 56 changed, 8 retired terms). |
| **Form 3500A revisions** | 2023: A3b patient sex, D4 additional UDI, F3 organization name, H10 related report numbers. Aug 2024 version; Feb 2025 removed "gender" wording; **Sept 2025 version** published; Jan 2026 UDI fields reject spaces. |
| **eSubmitter status** | Still maintained for eMDR (v3.99.00 released 29 Jan 2026); only the tobacco (CTP) eSubmitter forms are being phased out by Nov 2026. |

**Implication for "Thirty drafts; a human files":** the slogan is *exactly* aligned with the mandate, because the human must file through ESG anyway. But today the human has to re-key Thirty's draft into eSubmitter. Producing a **validated HL7 ICSR XML** (or an eSubmitter-importable payload) is the single biggest workflow gap; without it, Thirty is a triage/drafting aid, not a reporting tool.

### 2.2 QMSR (21 CFR 820, effective 2 Feb 2026) and ISO 13485:2016

- QMSR incorporates ISO 13485:2016 by reference. **Complaint handling now lives in ISO 13485 clause 8.2.2**; FDA-specific additions for complaint records are in **820.35(a)**: device name, date received, UDI/UPC and other identifiers, complainant name/address/phone, nature and details, any correction/corrective action, any reply to the complainant; plus a documented justification when a similar complaint has already been investigated.
- ISO 13485 8.2.2 requires timely handling, evaluation for reportability, investigation (or justified non-investigation), correction/corrective action, and that **records** of complaint handling be maintained; 8.2.3 requires reporting to regulatory authorities; 8.4 requires analysis of data (trending).
- **FDA replaced QSIT** with a risk-based, Total-Product-Life-Cycle inspection model (Compliance Program 7382.850). Investigators now start from the risk management file and pre-read MAUDE/recall data for similar products before arriving; complaint trends and MDR patterns are explicitly in scope.
- Part 11 (e-records/e-signatures) remains applicable; FDA's **Computer Software Assurance** guidance (final Sept 2025) endorses risk-based validation and explicitly covers AI tools used in quality systems; GAMP 5 2nd ed. Appendix D11 gives an AI/ML lifecycle.

**Implication:** A tool that (a) captures the 820.35 fields as a schema, (b) records "not investigated because similar complaint already investigated — ref #", and (c) ships a CSA-style validation pack is speaking the inspector's new language. Risk-file-first inspections also reward **linking complaints to hazards/failure modes** (Thirty's "trends by failure mode").

### 2.3 EU MDR 2017/745 vigilance

| Item | Detail |
|---|---|
| **Art. 87 timelines** | Serious public-health threat: ≤2 days; death or unanticipated serious deterioration: ≤10 days; any other serious incident: ≤15 days, all from the manufacturer's awareness; incomplete initial report allowed to meet the clock. |
| **MIR form** | **v7.3.1** (released 5 May 2025, with XSD/XML); optional until Nov 2025, mandatory **1 May 2026**. New field 1.2 "manufacturer awareness date of reportability". The PDF form is *not* itself EUDAMED-compatible for XML upload. |
| **EUDAMED** | Decision (EU) 2025/2371 (OJ 27 Nov 2025) made Actor, UDI/Device, NB&Certificates, Market Surveillance modules mandatory from **28 May 2026**. **Vigilance module not yet declared functional; expected mandatory ~2027** (six months after an OJ notice). Until then MIRs go to the national competent authority. |
| **Art. 88 trend reporting** | Statistically significant increase in frequency/severity of non-serious incidents or expected side-effects must be reported; MDCG 2023-3 defines terms. Requires per-device-family baseline rates. |
| **PSUR / periodic summary reports** | Complaint data feeds PSUR (Art. 86) and PMS plan; periodic summary reporting of similar serious incidents needs CA agreement. |

### 2.4 UK MHRA

PMS regulations SI 2024/1368 effective **16 June 2025** (Great Britain). Timelines: 2 days (public-health threat), 10 days (death/unanticipated serious deterioration), **15 days** (anticipated serious deterioration; was 30). All vigilance via the **MORE portal** (mandatory since 1 Sept 2023); MHRA is updating MIR/FSCA XML schemas for GB.

### 2.5 Health Canada

Medical Devices Regulations s.59–61.1: preliminary report **≤10 days** for death/serious deterioration, **≤30 days** if it could recur and cause such; submitted on the Mandatory Medical Device Problem Reporting Form by email/fax/mail to Canada Vigilance (no XML gateway for industry found).

### 2.6 What strengthens / weakens "Thirty drafts; a human files"

- **Stronger:** every jurisdiction requires a named responsible person and documented rationale; the FDA eMDR mandate means a human *must* push the button in ESG; QMSR's 820.35 lists exact record fields; CSA/GAMP D11 expect a human-in-the-loop for AI in QS software; 1.2M+ late/undated MDRs show the clock, not the prose, is the problem.
- **Weaker:** "drafts" without an HL7 payload means double entry; MDR 15/10/2-day clocks in EU/UK make a US-only 30/5-day clock look parochial; MIR 7.3.1 and IMDRF codes are *structured* outputs a small model must get exactly right (a wrong IMDRF code = ACK3 rejection); EUDAMED vigilance XML will arrive ~2027 and a desktop tool with no gateway cannot "file".

---

## 3. Buyer pain and jobs-to-be-done

**Evidence of failure modes (quantified):**

1. **Complaint handling is the #2 device 483 citation.** FY2025: 211 observations under 820.198(a) (7.9% of 2,660), behind CAPA (279, 10.5%); MDR procedures 803.17 added 63 (2.4%). Warning letters FY2025: 23 of 44 cited complaint files; CAPA (26), design controls (25) led. Device warning letters rose 17% YoY (46 → 54 per Emergo's count).
2. **Late reporting is structural.** BMJ 2025 (Everhart et al., WashU): of 4,432,548 manufacturer MDRs Sept 2019–Dec 2022, 71.0% on time, 4.5% 31–180 days late, 9.1% >180 days late, 15.5% missing/invalid dates; >400k reports were >6 months late; 3 manufacturers and 13 devices account for 54.8% of late reports (concentrated in large firms: BD, Medtronic, Abbott, Boston Scientific). Reporting volume has grown ~84% 2020→2025.
3. **Missed reportability** is what warning letters actually describe: MAST Biosurgery (Dec 2025, internal MDR numbers but nothing received by FDA, >30 days); InSung Medical (Sept 2025, malfunction known May 2022, never filed); Augustine (2024, burn with graft not filed in 30 days); Olympus (2022, breakage complaints not filed); Smiths Medical (2021, battery depletion complaints not filed though later recalled). Common 483 language: "did not document" reportability rationale, no decision tree, complaints not reviewed for MDR.
4. **Poor trending / reactive remediation.** Greenlight Guru 2025 report (n=536): post-market companies spend **52 hours/month** on reactive remediation vs 17 for pre-market; **34%** of post-market teams found critical process gaps only during audits; only **16%** of pre-commercial companies felt highly prepared for QMSR.
5. **Small firms dominate and under-tool.** >80% of US device companies have <50 employees; 85–90% of ~18,000 firms have <100. Greenlight Guru's 2022 study found a third of pre-market firms still run quality on general-purpose tools (spreadsheets, email, Word).

**Jobs-to-be-done (ranked by what inspections punish):**
1. *Never miss or mis-date the clock* — capture awareness date at first contact (sales, service, email), not at QA entry.
2. *Make and document a defensible reportability decision for every complaint*, including the "no" decisions, with reviewer name and date.
3. *File a valid eMDR* (codes present, ACK3 pass) and track supplementals.
4. *Prove trending* by device family/failure mode with a documented threshold for CAPA escalation and EU trend reporting.
5. *Survive an audit* — show the complete record set (820.35), audit trail, who did what when.

---

## 4. AI in regulatory/quality today

**Competitor claims.** Veeva: "Quality Event Agent" narrative summaries, more agents through 2026; Vault Product Surveillance has a rules-based Global Reportability Decision Tree. AssurX + 3Analytics: AI IMDRF coding suggestions ranked by confidence. Smarteeva: AI intake-to-AE-reporting, "70% faster processing" (self-reported). Flinn.ai: AI complaint handling, PMS/PSUR drafting, $20M Series A. Dot Compliance "Dottie": workflow-scoped assistant. MedTech Intelligence feature: AI triage cuts time 40–60% but "can bury a reportable event at the bottom of a queue while the MDR clock runs" — hence validation, monitoring, audit trails, human-in-the-loop. ZenQMS positions "compliant AI: simple, safe, optional, validated".

**How buyers feel.** ZenQMS survey (n=100 quality leaders): **10%** use AI in workflows; ~50% open to it "with the right controls". Broader life-sciences surveys: 60% using or open to AI, but **80%** have at least one major concern; data security/privacy, unclear ROI and regulatory constraints lead; **58%** of lab researchers cite privacy/security; only **5%** have AI agents in production (Cenevo, n=110). Enterprise-wide, 55% of inference is reported as on-prem/edge in 2025 (up from 12% in 2023) and on-prem held ~52% of regulated-industry AI spend; one healthcare stat claims 67% of 2025 HIPAA breaches involving AI tools came from data sent to third-party cloud services (secondary source; treat as directional). Complaint files contain patient narratives (PHI-adjacent) and unreleased failure data — the local-model story addresses the #1 stated objection.

**What runs on a laptop.** Benchmarks relevant to JSON classification:
- 8,400 schema-constrained extractions across 11 open models: **Qwen3-4B-Instruct-2507 Q4_K_M reached 98.9% schema-valid JSON at 142 tok/s on an 8GB GPU**, beating Llama-3.x-8B on every schema; Qwen3-14B Q5 hit 99.6%. Key finding: **constrained decoding (llama.cpp GBNF, XGrammar, Outlines) matters more than model size** — any model with grammar-constrained output beats prompt-only JSON from frontier models.
- Apple Silicon: Qwen3-4B Q4_K_M ≈ **52 tok/s on an 8GB M2**; Llama-3.2-3B Q5 ≈ 31 tok/s on a 16GB M2 Air. An 8B Q4 model (~5GB) runs on a 16GB laptop at roughly 10–20 tok/s **(est.)**. A 500-token reportability JSON therefore takes ~10–50 s per complaint on CPU/Apple Silicon — fine for batch triage, marginal for interactive use.
- Qwen2.5-3B was found Pareto-optimal for CPU edge inference; Llama 3.1 8B remains the tooling favourite; Gemma-3-4B and Phi-4-mini are competitive on reasoning. Long-context NIAH: Llama3.1-8B 99.8%, Gemma3-4B 99.5%, Qwen3-4B 83% — relevant if whole email threads are fed in.

**Practical conclusion:** a 4B-class instruct model with **grammar-constrained JSON** is realistic on the founder's laptop for (a) field extraction into the 820.35 schema, (b) red-flag/event-type classification, (c) IMDRF code *suggestion* restricted to the valid code list. Free-text *reportability reasoning* from a 4B model should be presented as a draft rationale against an explicit decision tree, never as the decision. Keep the agent optional and ship a deterministic rules path.

---

## 5. Value-proposition recommendations

Implementation status of the P0 rows is tracked in [`COMPLIANCE.md`](COMPLIANCE.md) §5.

| P | Feature / change | Why (evidence) | Effort | Needs model? |
|---|---|---|---|---|
| **P0** | **Reportability decision tree with justification capture** (FDA 803 + EU Art. 87 + HC + MHRA branches; every "no" gets a rationale, reviewer, timestamp) | "did not document rationale" is the recurring 483/WL finding; Veeva/SmartSolve sell decision trees; 803.18 requires deliberations on file | M | No (model drafts the rationale text; tree is deterministic) |
| **P0** | **Awareness-date discipline and multi-jurisdiction clock** (US 30 cal / 5 work; EU 2/10/15; UK 2/10/15; CA 10/30; supplemental 30) with work-day calendars and who-became-aware-when | 29% of MDRs late or undated; new MIR field 1.2 "awareness date of reportability"; MHRA and EU 15-day make a US-only clock insufficient | S–M | No |
| **P0** | **HL7 ICSR XML export validated against FDA's current eMDR schema, with IMDRF F10/H6 codes enforced** (plus a one-click eSubmitter-ready package) | eMDR mandatory since 2015; ACK3 rejects reports missing codes since 31 Mar 2025; without it "a human files" means re-keying | L | No (code suggestion can use model, constrained to the list) |
| **P0** | **820.35 record schema + ISO 13485 8.2.2 fields as the complaint object**, including "not investigated — similar complaint ref" | QMSR effective Feb 2026; inspectors start from records | S | No |
| **P0** | **Part 11-style controls**: per-user login, e-signature on approve/file (meaning, name, date/time), tamper-evident hash-chained audit trail, audit-trail export | 11.10(e), 11.50, 11.200; buyers cannot buy QS software without it | M | No |
| **P0** | **Validation package** (URS, risk assessment, IQ/OQ test scripts, traceability matrix, CSA-style summary, model-validation protocol per GAMP 5 D11 with a frozen test set of complaints and acceptance metrics) | SimplerQMS/Dot sell "pre-validated" as a feature; CSA final guidance Sept 2025 covers AI in QS; small firms lack validation staff | M | Partly (model eval set) |
| **P1** | **EU MIR 7.3.1 PDF + XML output** and UK MORE-compatible MIR; EUDAMED vigilance XML when the module is declared functional (~2027) | MIR 7.3.1 mandatory 1 May 2026; XSD published | M | No |
| **P1** | **MAUDE similar-event lookup** (openFDA device/event API, cached locally) shown beside each complaint: counts by product code/problem code, and "how did peers code this?" | FDA investigators now pre-read MAUDE for similar products; helps consistency of reportability calls | M | Optional (embedding search) |
| **P1** | **Trend thresholds + EU Art. 88 trend detection** with documented statistical method, baseline per device family, CAPA-escalation record and export for PSUR/management review | ISO 13485 8.4; Art. 88; 52 h/month reactive remediation | M | No |
| **P1** | **Multi-user roles + read-only auditor view** on the local web console (LAN), with per-site licence covering unlimited named users | A single-laptop tool cannot be the system of record for a 10-person QA/RA team; auditor view is a demo-closer | M | No |
| **P1** | **Email and form intake that stamps awareness date and captures complainant fields; Outlook/Gmail add-in or IMAP poll** | Awareness starts with any employee; most complaints arrive by email/phone | S–M | Optional (extraction) |
| **P1** | **Investigation checklist and CAPA hand-off record** (not a full CAPA module): root-cause fields, device returned?, lot/UDI, link to CAPA ID in the customer's QMS | CAPA is the #1 citation; linkage is what inspectors trace | S | No |
| **P2** | **QMS/CRM connectors** (CSV/REST to Greenlight Guru, Qualio, Salesforce Service Cloud; TrackWise import) | Target buyers may already own a QMS; Thirty as the complaint/MDR workbench beside it | M–L | No |
| **P2** | **Device registry / UDI-DI lookup** (GUDID local cache) auto-filling D-section fields | 3500A D4–D6 UDI validation (no spaces, Jan 2026); 820.35 requires UDI | S | No |
| **P2** | **Management-review dashboard** (open clocks, late risk, trends, decisions by reviewer) exportable to PDF | ISO 13485 5.6 input; sells to the QA manager's boss | S | No |
| **P2** | **Offline-first sync** (file-based replication of the local DB between two laptops/sites, or an optional self-hosted sync server) | Collaboration without cloud; preserves "0 bytes to cloud AI" | L | No |
| **P2** | **Health Canada form auto-fill** (PDF) | 10/30-day rule; low effort once schema exists | S | No |

Explicitly deprioritise: Telegram approvals (not Part 11-friendly as a signature channel — keep as notification only); a general chat agent; plugin marketplace before the core schema is stable.

---

## 6. Pricing and packaging

**Comparables (annual):**
- Greenlight Guru: ~$15k entry → $50–60k; median deal ~$44k; 2026 rises up to +100%.
- Qualio: ~$12k base + ~$3k/user (est. from third-party).
- SimplerQMS: $17.5k Starter (≤15 users, validation docs included).
- MasterControl: from $25k.
- TrackWise Digital: ~$200/user/month listed (≈$2.4k/user/yr) plus implementation.
- Matrix Requirements: $920–$3,390/month flat tiers ($11k–$41k/yr) or $15–$125/user/month.
- ComplianceQuest: $60k–$200k+/yr mid-market.

**Suggested Thirty packaging (est.):**

| Tier | Scope | Price/site/yr |
|---|---|---|
| **Core** | Complaint record (820.35/8.2.2), rules triage, US clock, 3500A draft PDF, audit log, 3 named users, sample agent | **$3,600** |
| **Reporting** | + HL7 ICSR XML/eSubmitter package, IMDRF code enforcement, EU/UK/CA clocks, MIR 7.3.1, unlimited users, auditor view, validation pack | **$9,000** |
| **Signal** | + MAUDE lookup, trend/Art. 88 detection, management dashboard, QMS/CRM connectors, local-model agent support | **$15,000** |
| Add-ons | Extra site −30%; validation-pack refresh per major release; optional paid onboarding ($2–5k) | |

Rationale: well under the $15–25k eQMS floor so it can be bought on a QA manager's budget, while the Reporting tier captures the firms who today pay a consultant $150–300/h to prepare MDRs (est.). Per-site, not per-seat, directly counters the "opaque escalation as seats grow" complaint about Greenlight Guru.

**Trial/demo structure:** 30-day fully-featured trial with an offline key; ships with a synthetic complaint set (50 cases spanning reportable/not/needs-info across jurisdictions) so the clock, decision tree and XML validator demo without customer data; "bring your spreadsheet" CSV import on day one; a 45-minute guided demo that ends with a validated HL7 file and the auditor view. Offer a paid pilot ($1.5k, credited to year one) that includes the validation pack — this is the real closing document for QA.

---

## 7. Risks and open questions

1. **Single-machine system of record.** Complaint files must be retained for 2 years / device life and be retrievable during an inspection; a laptop-resident SQLite database is a liability unless backups, LAN multi-user and export are first-class. Buyers will ask "what happens when the laptop dies or the QA lead leaves?".
2. **Filing gap.** Until Thirty emits validated HL7 ICSR XML (and ideally AS2 via a partner), "a human files" means a human re-types. Decide early: eSubmitter package (cheaper, low volume) vs AS2 (needs a gateway product or partner such as AssurX-style services).
3. **Model quality vs regulatory exposure.** A 4B model's free-text reportability reasoning will be wrong sometimes; a wrong "not reportable" that a tired reviewer rubber-stamps is a warning-letter scenario. Mitigation: deterministic decision tree gates the outcome, model only drafts rationale/fields; publish a model validation protocol and test-set accuracy; log model version and prompt hash in the audit trail.
4. **Validation burden on buyers.** Every release changes a validated system; buyers need release notes with impact assessment and re-test scripts. Budget for this in engineering cadence.
5. **Market timing on EU.** EUDAMED vigilance (~2027) will shift EU filing to XML; MIR 7.3.1 is already mandatory. Build the EU path on the published XSD now or accept being US-only for 18 months.
6. **Regulatory clock semantics.** "Work days" for 803.53 and awareness-date rules differ by jurisdiction; holidays and time zones need a configurable calendar; mistakes here are the whole product.
7. **Is "0 bytes to cloud AI" a purchase driver or a nice-to-have?** Survey data says privacy is the top concern, but 90% of quality leaders are not using AI at all; the deciding factor may be the clock + decision tree + XML, with local AI as a tie-breaker. Validate with 10 QA/RA interviews before investing more in agent plumbing.
8. **Importer/distributor segment.** Importers have the same 803 duties (30-day) and are even less tooled; EU importers/distributors must relay complaints to manufacturers. Could be an easier first market with lower feature demands.
9. **Incumbent response.** Greenlight Guru, Qualio and Dot can add "AI reportability draft" in a quarter; Thirty's defensible edge is local execution, transparent per-site pricing and eMDR XML done right for small firms. Speed on P0 items matters more than breadth.
10. **Open questions for the founder:** Which eMDR path (eSubmitter package vs AS2 partner)? Who is the buyer — QA manager (wants audit defence) or RA lead (wants filing speed)? Will customers accept a desktop install under IT policy, or is a self-hosted Docker image needed? What is the plan for MDR "supplemental" and FDA follow-up requests (Form 3500A H-section round-trips)?

---

## Sources

Market landscape
- https://www.compliancequest.com/cq-guide/best-qms-for-medical-device/
- https://stackbriefly.com/blog/quality-management-software-2026-mastercontrol-etq-reliance-qualio-greenlight-guru-veeva-qms
- https://openregulatory.com/articles/qms-software-iso-13485-comparison
- https://openregulatory.com/articles/greenlight-guru-price
- https://openregulatory.com/qms_software/greenlight-guru
- https://openregulatory.com/qms_software/dot-compliance
- https://openregulatory.com/qms_software/compliancequest
- https://openregulatory.com/qms_software/etq-reliance
- https://openregulatory.com/qms_software/arena-qms
- https://www.rfp.wiki/specialty-industries/manufacturing/quality-management-system-software/greenlight-guru/mastercontrol-quality
- https://www.rfp.wiki/specialty-industries/manufacturing/quality-management-system-software/trackwise-digital
- https://www.rfp.wiki/vendors/greenlight-guru
- https://www.capterra.ie/reviews/148577/mastercontrol
- https://www.capterra.ie/reviews/175662/trackwise-digital
- https://www.capterra.ie/reviews/134050/quality-management-software
- https://www.capterra.com/p/136111/ComplianceQuest/
- https://www.capterra.com/p/140578/greenlight-guru
- https://www.g2.com/products/honeywell-trackwise/reviews
- https://www.g2.com/products/sparta-systems-trackwise/reviews
- https://softwareconnect.com/reviews/qualio/
- https://www.softwareadvice.com/audit/simplerqms-profile/
- https://www.softwareadvice.com/ehs/etq-reliance-profile
- https://www.arenasolutions.com/pricing/
- https://www.g2.com/products/ennov-quality/pricing
- https://softwareconnect.com/reviews/matrix-quality/
- https://openregulatory.com/articles/matrix-requirements-alternative
- https://www.iqvia.com/locations/united-states/library/fact-sheets/smartsolve-complaint-management
- https://www.assurx.com/wp-content/uploads/resources/brochures/assurx-emdr-software-ds.pdf
- https://www.assurx.com/overcoming-the-challenges-of-medical-device-complaint-handling-with-ai-how-3analytics-leads-the-way/
- https://www.veeva.com/medtech/wp-content/uploads/2026/01/MedTech_Veeva-Product-Surveillance_Features-Briefs-1.pdf
- https://www.veeva.com/medtech/wp-content/uploads/2024/04/MedTech_Veeva-Product-Surveillance_Features-Briefs.pdf
- https://support.ptc.com/help/wnc/r12.1.0.0/en/Windchill_Help_Center/wqcem/WQCEMRegReportEMDRGetStarted.html
- https://www.smarteeva.com/platform/complaints-management
- https://www.smarteeva.com/
- https://www.flinn.ai/
- https://siliconcanals.com/flinn-ai-secures-e6m-in-seed-round/
- https://vestbee.com/blog/articles/flinn-raises-20-m
- https://www.tataelxsi.com/platforms/complaintiq-ai-complaint-management-platform
- https://gxpsoft.ai/blog/current-state-of-ai-in-quality-management-vendors-2026-08-20
- https://intuitionlabs.ai/articles/gxp-compliance-software-eqms-comparison-2026
- https://www.verdantix.com/insights/report/buyer-s-guide--quality-management-software-2026
- https://costbench.com/changelog/guru-price-increase-2026-02-2/

Regulatory
- https://www.registrarcorp.com/blog/medical-devices/medical-device-regulations/emdr/
- https://www.raps.org/resource/fda-finalizes-electronic-medical-device-reporting.html
- https://www.govinfo.gov/link/fr/79/8843
- https://www.fda.gov/medical-devices/emdr-electronic-medical-device-reporting/emdr-system-enhancements
- https://www.fda.gov/medical-devices/emdr-electronic-medical-device-reporting/emdr-help-and-faqs
- https://www.fda.gov/industry/fda-esubmitter/esubmitter-application-history
- https://www.raps.org/resource/cdrh-ushers-in-changes-to-device-submission-system.html
- https://medtech.citeline.com/MT142233/FDA-Tweaks-3500A-Form-For-Reporting-Adverse-Events-Plans-September-Changes-To-eMDR-System
- https://www.medtechdive.com/news/fda-aims-to-harmonize-adverse-event-reporting-with-emdr-updates-makes-pati/584964/
- https://criterionedge.com/fdas-updated-electronic-medical-device-reporting-emdr-system-aims-to-harmonize-adverse-event-reporting/
- https://safety.veevavault.help/en/gr/780867/index.md
- https://www.lachmanconsultants.com/2025/06/fdas-adverse-event-reporting-forms-to-be-revised/
- https://medenvoyglobal.com/standardizing-adverse-event-reporting-imdrf-terminology/
- https://www.emergobyul.com/news/imdrf-updates-terminologies-categorized-adverse-event-reporting
- https://www.fda.gov/medical-devices/guidance-documents-medical-devices-and-radiation-emitting-products/attachment-c-summary-mdr-reporting-requirements
- https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-803/subpart-A/section-803.18
- https://syfert.com/cfr/sections/21-803.53.html
- https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-820/subpart-B/section-820.35
- https://www.law.cornell.edu/cfr/text/21/820.35
- https://intuitionlabs.ai/articles/fda-qmsr-iso-13485-changes-2026
- https://compliancenavigator.bsigroup.com/en/medicaldeviceblog/the-new-fda-21-cfr-part-820--quality-management-system-regulation/
- https://www.thefdalawblog.com/2026/02/understanding-fdas-risk-based-inspection-model-under-qmsr/
- https://hlc.com/en/publications/fda-updates-compliance-program-inspection-manual-for-the-qmsr-age
- https://www.complifegroup.com/2026/02/24/compliance-program-fda-inspections/
- https://www.thefdagroup.com/blog/qmsr-inspections
- https://medicaldevicehq.com/articles/mdr-article-87-reporting-of-serious-incidents/
- https://eumdr.com/?p=384
- https://health.ec.europa.eu/system/files/2023-02/mdcg_2023-3_en_0.pdf
- https://medicaldevices.ipn.pt/wp-content/uploads/2025/09/Questions-and-Answers-on-Trend-Reporting.pdf
- https://www.emergobyul.com/sites/default/files/2024-04/PMS-and-PSUR-Requirements-Under-European-MDR.pdf
- https://www.emergobyul.com/news/european-commission-releases-new-manufacturer-incident-report-form-and-help-text
- https://casusconsulting.com/manufacturer-vigilance-updated-incident-report-mir-pdf-form-version-7-3-1/
- https://meddeviceguide.com/blog/mir-form-7-3-1-mandatory-update-vigilance-reporting-guide
- https://bivdanewsletter.com/regulatory-affairs-newsletter/eu-mir-form-updated-to-version-7-3-1/
- https://www.tuev-nord.de/en/knowledge/standards-in-focus/eudamed-mandatory-use-of-first-four-modules-from-may-28-2026/
- https://www.regdesk.co/blog/milestone-for-eu-medical-device-regulation-four-eudamed-modules-declared-fully-functional/
- https://osapiens.com/blog/eudamed-is-mandatory-how-to-prepare/
- https://www.gov.uk/government/publications/medical-devices-post-market-surveillance-requirements/vigilance-reporting-requirements
- https://www.dqsglobal.com/en/explore/blog/uk-pms-regulations-vigilance-reporting-requirements
- https://casusconsulting.com/mhra-updates-more-platform-vigilance-reporting-guidance-due-to-new-uk-pms-regulation/
- https://laws-lois.justice.gc.ca/eng/regulations/SOR-98-282/page-5.html
- https://canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/adverse-reaction-reporting/mandatory-medical-device-problem-reporting-form-industry-adverse-reaction-reporting.html
- https://www.regdesk.co/health-canada-on-incident-reporting-timelines-and-content
- https://simplerqms.com/21-cfr-part-11-electronic-records/
- https://softwareconnect.com/learn/21-cfr-part-11/
- https://info.qbdgroup.com/en/blog/gamp-5-guide-2nd-edition-whats-new
- https://www.pharmanow.live/regulatory-intelligence/future-of-computerized-systems-validation-csv
- https://intuitionlabs.ai/resources/gamp-5-compliance-checklist/

Buyer pain / enforcement
- https://meddeviceguide.com/blog/fda-medical-device-warning-letter-trends-2024-2026-enforcement-analysis-guide
- https://intuitionlabs.ai/articles/fda-form-483-warning-letter-statistics
- https://mingyuefeng.com/fda-483-data-analysis
- https://investigationsquality.com/2025/01/16/2024-fda-483-data/
- https://gmp-compliance.org/gmp-news/fda-warning-letter-statistics-on-medical-devices-in-the-past-fiscal-year-2025
- https://www.hoganlovells.com/en/publications/fda-medical-device-inspections-in-2025
- https://www.cov.com/-/media/files/corporate/publications/2025/05/quarterly-medical-device-warning-letters-update-january-march-2025.pdf
- https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/warning-letters/mast-biosurgery-usa-inc-720661-12172025
- https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/warning-letters/insung-medical-co-ltd-712545-09232025
- https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/warning-letters/augustine-temperature-management-llc-671243-03212024
- https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/warning-letters/olympus-medical-systems-corporation-649726-12122022
- https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/warning-letters/smiths-medical-asd-inc-617147-10012021
- https://www.thefdalawblog.com/?p=4974
- https://elsmar.com/elsmarqualityforum/threads/interpretation-of-mdr-reportable-event-fda-guidance-on-medical-device-reporting.41324/page-2
- https://www.raps.org/resource/study-nearly-one-third-of-device-adverse-event-rep.html
- https://bmjgroup.com/over-1-2-million-medical-device-side-effect-reports-not-submitted-within-legal-timeframe/
- https://www.healthday.com/healthpro-news/public-health/considerable-proportion-of-medical-device-adverse-events-reported-late
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11898541
- https://www.fda.gov/medical-devices/medical-device-reporting-mdr-how-report-medical-device-problems/mdr-data-files
- https://meddeviceguide.com/blog/fda-maude-adverse-event-medical-device-safety-trends-analysis-2026
- https://open.fda.gov/apis/device/event
- https://www.greenlight.guru/blog/2025-medical-device-industry-report
- https://www.greenlight.guru/blog/2022-medical-device-industry-benchmark-study
- https://www.massdevice.com/?p=27051
- https://www.assemblymag.com/articles/94272-mep-aids-medical-device-manufacturers?v=preview
- https://grandavenue.com/resource/webinar-beyond-spreadsheets/
- https://simplerqms.com/medical-device-complaint-handling/

AI / local models
- https://medtechintelligence.com/feature_article/ai-assisted-triage-accelerating-post-market-surveillance-while-eliminating-reporting-blind-spots/
- https://www.smarteeva.com/blog/ai-in-post-market-surveillance-what-actually-works
- https://blog.zenqms.com/zenqms-and-compliant-ai-features
- https://blog.zenqms.com/quality-management-industry-report-how-do-life-sciences-quality-teams-really-feel-about-ais-role-in-compliance
- https://www.technologynetworks.com/informatics/blog/the-adoption-of-ai-critical-concerns-in-the-life-sciences-389333
- https://intuitionlabs.ai/articles/ai-adoption-life-sciences-barriers
- https://www.dreamfactory.com/hub/on-premise-llm-deployment-statistics
- https://blog.premai.io/on-premise-llm-deployment-the-real-costs-trade-offs-decision-framework
- https://petronellatech.com/blog/how-to-run-a-private-llm-hipaa-compliant-complete-setup-guide
- https://bestllmfor.com/best/structured-data-extraction-json/
- https://www.iunera.com/kraken/enterprise-ai/best-qwen-model-for-receipt-extraction-0-8b-vs-3b/
- https://github.com/nandan2003/edge-cpu-inference
- https://www.generalcompute.com/blog/the-7-8b-battle-llama-3-1-8b-vs-mistral-7b-vs-qwen-2-5-7b-vs-gemma-2-9b?agent=true
- https://www.kunalganglani.com/blog/llama-3-8b-vs-qwen-3-7b.md
- https://llmcheck.net/models/qwen-3-4b-on-m2/
- https://willitrunai.com/can-run/hf-bartowski--llama-3-2-3b-instruct-gguf-on-m2-air-16gb
- https://www.wizwand.com/sota/long-context-on-niah
- https://arxiv.org/pdf/2603.19558

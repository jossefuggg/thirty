# openFDA finding: infusion pumps (FRN), field completeness

**Date:** 24 Oct 2026
**Source:** openFDA device event API (MAUDE). `meta.results.last_updated`: 2026-10-13.
**Scope:** product code `FRN` (Pump, Infusion), `date_received` 2023-01-01 to 2025-12-31.

## Counts

| Measure | Count |
| --- | ---: |
| (a) All reports | 277,055 |
| (b) Reports missing `device.lot_number` | 0 |
| (c) Reports missing `date_of_event` | 15,038 |

## Percentages

- Missing `device.lot_number`: 0 / 277,055 = **0.00%**
- Missing `date_of_event`: 15,038 / 277,055 = **5.43%**

## Exact query URLs

(a) All reports — read `meta.results.total`:

```
https://api.fda.gov/device/event.json?search=device.device_report_product_code:FRN+AND+date_received:[20230101+TO+20251231]&limit=1
```

(b) Missing `device.lot_number`:

```
https://api.fda.gov/device/event.json?search=device.device_report_product_code:FRN+AND+date_received:[20230101+TO+20251231]+AND+_missing_:device.lot_number&limit=1
```

(c) Missing `date_of_event`:

```
https://api.fda.gov/device/event.json?search=device.device_report_product_code:FRN+AND+date_received:[20230101+TO+20251231]+AND+_missing_:date_of_event&limit=1
```

## Notes

- openFDA returns HTTP 404 (`"No matches found!"`) when a search matches zero
  records. Query (b) returned 404, so the count is 0: within this slice, no FRN
  report has `device.lot_number` entirely absent. The field is almost always
  present but frequently carries placeholder values such as `"NA"` or an empty
  string, which `_missing_` counts as present, not missing.
- For comparison, `_missing_:device.lot_number` across the whole MAUDE dataset
  (no FRN or date filter) returns 13,558 reports, confirming the field name is
  valid and `_missing_` works — the 0 above is specific to the FRN + 2023–2025
  slice.
- Counts are unvalidated per the openFDA disclaimer and reflect the dataset as
  of its last update (2026-10-13).

## Placeholder lot numbers (value distribution)

The `_missing_` check above counts 0 because the `device.lot_number` field is
almost always *present* — it just carries a placeholder instead of a real lot.
A `count=device.lot_number.exact` aggregation over the same FRN + 2023–2025
slice shows how often the value is non-informative.

**Query URL** (openFDA caps the `count` aggregation at the top 1000 terms):

```
https://api.fda.gov/device/event.json?search=device.device_report_product_code:FRN+AND+date_received:[20230101+TO+20251231]&count=device.lot_number.exact
```

Placeholder / non-informative values counted (exact terms from the response):

| Term | Count |
| --- | ---: |
| `""` (empty) | 253,881 |
| `NA` | 11,508 |
| `N/A` | 4,147 |
| `NI` | 94 |
| `UNKNOWN` | 64 |
| `NOT PROVIDED` | 28 |
| `N/I` | 24 |
| `UNK` | 14 |
| **Sum** | **269,760** |

- Placeholder share: 269,760 / 277,055 = **97.37%**
- This is a **lower bound**: openFDA returns only the top 1000 distinct values
  for a `count` aggregation, so additional placeholder spellings in the long
  tail (e.g. other `UNKNOWN`/`UNAVAILABLE`/`NONE` variants) are not captured.
- Terms excluded as genuine lot numbers: alphanumeric serials such as
  `HG7J59S`, `2206213120`, `20140108-SH`, `4349110`, etc. No `ASKU`, `NONE`, or
  `UNAVAILABLE` terms appeared in the returned top-1000 set.
- Counts are unvalidated per the openFDA disclaimer; dataset last updated
  2026-10-13.

---

# Second device: IV administration sets (FPA)

**Date:** 24 Oct 2026
**Source:** openFDA device event API (MAUDE). `meta.results.last_updated`: 2026-10-13.
**Scope:** product code `FPA`, `date_received` 2023-01-01 to 2025-12-31.

## Product code confirmation

Fetched one FPA report and read `device.openfda.device_name`:

```
https://api.fda.gov/device/event.json?search=device.device_report_product_code:FPA&limit=1
```

- `device.openfda.device_name` = **"Set, Administration, Intravascular"**
  (regulation 880.5440, class 2). Confirmed as an intravascular administration
  set, so FPA is the correct code. No fallback `generic_name` search was needed.

For an IV administration set — a lot-controlled disposable — a missing or
placeholder lot number is a genuine traceability gap, unlike the durable pump
above.

## Counts

| Measure | Count |
| --- | ---: |
| Total reports | 93,174 |
| Reports missing `date_of_event` | 7,236 |

- Missing `date_of_event`: 7,236 / 93,174 = **7.77%**

## Placeholder lot numbers (value distribution)

```
https://api.fda.gov/device/event.json?search=device.device_report_product_code:FPA+AND+date_received:[20230101+TO+20251231]&count=device.lot_number.exact
```

Values counted as empty / placeholder (exact terms from the response):

| Term | Count |
| --- | ---: |
| `UNKNOWN` | 32,920 |
| `""` (empty) | 4,374 |
| `NI` | 867 |
| `ASKU` | 788 |
| `UNK` | 163 |
| `INFUSION DEVICES - UNKNOWN` | 130 |
| **Sum** | **39,242** |

- Placeholder share: 39,242 / 93,174 = **42.12%**
- This is a **lower bound**: openFDA returns only the top 1000 distinct values
  for a `count` aggregation, so placeholder spellings in the long tail are not
  captured.
- Ambiguous terms **not** included in the sum (listed for transparency):
  `SEE H10` (85), `SEE H.10` (61), `PLOT` (55), `PLOTS` (53). These look like
  narrative cross-references or typed noise rather than clear empty/unknown
  markers; counting them would raise the sum to 39,496 (**42.39%**).
- All other returned terms are real-looking lot numbers (e.g. `6005315`,
  `4334149`, `24025030`).
- Counts are unvalidated per the openFDA disclaimer; dataset last updated
  2026-10-13.

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

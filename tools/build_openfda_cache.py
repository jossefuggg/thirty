"""Build the device-readiness openFDA cache under data/openfda_cache/.

Pulls openFDA device adverse-event and recall data for every product code in
thirty/readiness_rules.json and writes the reduced JSON the Signals view reads,
so /readiness works offline and in the public demo. Each cache file records the
query URL and the fetch date.

Run:  .venv/bin/python tools/build_openfda_cache.py [--dir DATA_DIR]

The openFDA endpoints, product-code field (device.device_report_product_code),
and the count fields (product_problems.exact, patient.sequence_number_outcome.exact,
date_received) were confirmed against the live API via the fetch MCP tool before
this script was written. Only codes that return results are kept; a code that
returns nothing is reported and skipped. This mirrors thirty.readiness.openfda
.fetch_and_cache exactly, but runs over the whole product-code list at build time.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import requests  # noqa: E402

from thirty.readiness import engine, openfda  # noqa: E402


def _get(url):
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return {"results": []}  # openFDA: no matching records
    resp.raise_for_status()
    return resp.json()


def build(data_dir):
    os.environ["VIGIL_DIR"] = data_dir
    rules = engine.load_rules()
    codes = [c["code"] for c in rules.get("product_codes", [])]
    today = dt.date.today()
    start = today.replace(year=today.year - openfda._YEARS)
    window = f"[{start:%Y%m%d}+TO+{today:%Y%m%d}]"
    cache = openfda.cache_dir()
    kept, skipped = [], []

    for code in codes:
        dev_url = (f'{openfda.EVENT_API}?search=device.device_report_product_code:"{code}"'
                   f"+AND+date_received:{window}&count=product_problems.exact")
        pat_url = (f'{openfda.EVENT_API}?search=device.device_report_product_code:"{code}"'
                   f"+AND+date_received:{window}&count=patient.sequence_number_outcome.exact")
        year_url = (f'{openfda.EVENT_API}?search=device.device_report_product_code:"{code}"'
                    f"+AND+date_received:{window}&count=date_received")
        recall_url = (f'{openfda.RECALL_API}?search=product_code:"{code}"'
                      f"&limit={openfda._RECALL_N}&sort=event_date_posted:desc")

        dev = openfda._reduce_terms(_get(dev_url))
        pat = openfda._reduce_terms(_get(pat_url))
        years = openfda._reduce_years(_get(year_url))
        recalls = openfda._reduce_recalls(_get(recall_url))

        if not (dev or pat or years or recalls):
            skipped.append(code)
            print(f"  {code}: no results, skipped")
            continue

        openfda._atomic_write_json(os.path.join(cache, f"{code}_event.json"),
                                   {"url": dev_url, "fetched": today.isoformat(),
                                    "data": {"device_problems": dev, "patient_problems": pat,
                                             "reports_per_year": years}})
        openfda._atomic_write_json(os.path.join(cache, f"{code}_recall.json"),
                                   {"url": recall_url, "fetched": today.isoformat(),
                                    "data": {"recalls": recalls}})
        kept.append(code)
        print(f"  {code}: {len(dev)} problems, {len(pat)} patient outcomes, "
              f"{sum(y['count'] for y in years)} reports/3y, {len(recalls)} recalls")
        time.sleep(0.3)  # be gentle with the public API

    print(f"\nCache written to {cache}")
    print(f"Kept: {kept}")
    if skipped:
        print(f"Skipped (no data): {skipped}")
    return kept, skipped


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("VIGIL_DIR") or ROOT,
                    help="data folder (cache goes under <dir>/openfda_cache); defaults to repo root")
    args = ap.parse_args()
    build(os.path.abspath(args.dir))

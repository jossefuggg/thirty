"""openFDA signal cache: loader (pure, offline, empty-safe) and fetcher.

The "what goes wrong with devices like this" step reads cached openFDA JSON
from ``data/openfda_cache/`` so the page works offline and in the public demo
(Requirement 6.1). The network is touched only by :func:`fetch_and_cache`,
which the build-time cache population and the "Refresh from openFDA" route call
— never page rendering.

Cache layout (one file per product code per API), under ``config.data_dir()``::

    openfda_cache/
      BZD_event.json   = {"url": ..., "fetched": "YYYY-MM-DD", "data": {...}}
      BZD_recall.json  = {"url": ..., "fetched": "YYYY-MM-DD", "data": {...}}

The ``data`` payloads are pre-reduced to exactly what the Signals view shows, so
:func:`load_signals` does no heavy work on render:

- event ``data``: ``device_problems`` / ``patient_problems`` (``[{term,count}]``)
  and ``reports_per_year`` (``[{year,count}]``, last 3 years);
- recall ``data``: ``recalls`` (``[{reason,date,cfres_id,url}]``).

:func:`load_signals` is **empty-safe**: a missing file, an empty file, invalid
JSON, or zero records all yield a well-formed empty result rather than an error
(Requirement 6.7 / Property 6).
"""
import datetime as dt
import json
import os
import tempfile

from .engine import load_rules

# openFDA endpoints (no API key required). Verified at open.fda.gov.
EVENT_API = "https://api.fda.gov/device/event.json"
RECALL_API = "https://api.fda.gov/device/recall.json"

# A human FDA record page for a recall (cfres_id links to the CDRH recall DB UI).
_RECALL_RECORD = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id={cfres_id}"

# How many top problem terms and recalls to keep in the cache.
_TOP_N = 8
_RECALL_N = 10
_YEARS = 3


class RefreshError(Exception):
    """Raised by :func:`fetch_and_cache` when a live openFDA refresh fails.

    Callers keep the existing cache unchanged and report that the refresh did
    not complete (Requirement 6.6).
    """


def _shipped_cache_dir():
    """The committed cache that ships with the code: ``<CODE_DIR>/data/openfda_cache``.

    This is the offline/public-demo cache built at release time. It travels with
    the repo (and the frozen app via ``config.CODE_DIR``), so ``/readiness``
    renders signals with no network even on a fresh checkout or a locked demo.
    """
    from thirty import config  # lazy: keep this module import-light for tests
    return os.path.join(config.CODE_DIR, "data", "openfda_cache")


def _runtime_cache_dir():
    """The per-install cache under the data folder, where "Refresh" writes."""
    from thirty import config
    return os.path.join(config.data_dir(), "openfda_cache")


def cache_dir():
    """Where "Refresh from openFDA" writes and where the loader looks first.

    Resolution: use the runtime cache under the data folder (``VIGIL_DIR`` /
    app-data) so a refresh persists per install; the loader also falls back to
    the shipped cache (:func:`_shipped_cache_dir`). Created lazily. A test may
    point ``VIGIL_DIR`` at a temp folder to isolate the cache.
    """
    d = _runtime_cache_dir()
    os.makedirs(d, exist_ok=True)
    return d


def _empty_signals(code):
    """A well-formed empty Signals result for ``code`` (the empty state)."""
    return {
        "code": code,
        "device_problems": [],
        "patient_problems": [],
        "reports_per_year": [],
        "recalls": [],
        "fetched": {"event": None, "recall": None},
        "has_data": False,
    }


def _read_cache_file(path):
    """Read a cache file; return its dict or ``None`` on missing/empty/invalid.

    Never raises: a missing file, an empty file, or invalid JSON all return
    ``None`` so :func:`load_signals` can degrade to the empty state.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
        if not text:
            return None
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def load_signals(product_code):
    """Load the cached openFDA signals for ``product_code``. Empty-safe, offline.

    Reads ``<CODE>_event.json`` and ``<CODE>_recall.json`` from :func:`cache_dir`.
    Returns ``{"code", "device_problems", "patient_problems", "reports_per_year",
    "recalls", "fetched": {"event", "recall"}, "has_data"}``. Any missing,
    empty, invalid, or zero-record cache file degrades to an empty result
    without raising (Property 6). ``has_data`` is True only when at least one
    non-empty section was loaded.
    """
    code = (product_code or "").strip().upper()
    result = _empty_signals(code)
    if not code:
        return result

    # Look in the per-install runtime cache first (where Refresh writes), then
    # fall back to the shipped cache so a fresh checkout / public demo still
    # renders offline.
    def _find(name):
        for base in (_runtime_cache_dir(), _shipped_cache_dir()):
            obj = _read_cache_file(os.path.join(base, name))
            if obj:
                return obj
        return None

    def _clean_list(items):
        out = []
        for i in (items or []):
            term = _clean_term(i.get("term", "")) if isinstance(i, dict) else None
            if term:
                out.append({"term": term, "count": int(i.get("count") or 0)})
        return out

    event = _find(f"{code}_event.json")
    if event:
        data = event.get("data") or {}
        result["device_problems"] = _clean_list(data.get("device_problems"))
        result["patient_problems"] = _clean_list(data.get("patient_problems"))
        result["reports_per_year"] = list(data.get("reports_per_year") or [])
        result["fetched"]["event"] = event.get("fetched")

    recall = _find(f"{code}_recall.json")
    if recall:
        data = recall.get("data") or {}
        result["recalls"] = list(data.get("recalls") or [])
        result["fetched"]["recall"] = recall.get("fetched")

    result["has_data"] = bool(
        result["device_problems"] or result["patient_problems"]
        or result["reports_per_year"] or result["recalls"]
    )
    return result


# ---------------------------------------------------------------- where to look first
def _is_connected(answers):
    """Whether the feature is plausibly a connected device (app/wireless/software).

    Inferred from the answers: a feature that estimates a body measurement or
    flags a condition, used by consumers or both, is treated as connected (the
    typical wearable/app pattern). Kept simple and explainable — signals only
    raise attention, they never change the category.
    """
    if not isinstance(answers, dict):
        return False
    claims = answers.get("claims") or set()
    claims = set(claims) if not isinstance(claims, set) else claims
    users = answers.get("users")
    return bool(claims & {"measure", "flag"}) and users in ("consumers", "both")


def _matches(term, needles):
    t = (term or "").lower()
    return any(n in t for n in needles)


def where_to_look_first(signals, answers):
    """Map openFDA problem patterns to the Step 1 answers.

    Returns a list of ``{"label", "count", "source"}`` items — every item
    carries its count and its source (Requirement 5.5 / Property 7). For a
    ``measure`` feature, device problems matching accuracy / false-reading terms
    are surfaced; for a connected feature, software / connectivity problems are
    surfaced. Returns ``[]`` when there is no data (the view then shows the
    empty state). ``signals`` is a :func:`load_signals` result; ``answers`` is a
    normalized answers dict.
    """
    if not signals or not signals.get("has_data"):
        return []

    rules = load_rules()
    terms = rules.get("signal_terms", {})
    accuracy = [t.lower() for t in terms.get("accuracy_terms", [])]
    connectivity = [t.lower() for t in terms.get("connectivity_terms", [])]
    source = rules.get("citations", {}).get("openfda_event", {}).get("label", "openFDA device adverse-event API")

    claims = answers.get("claims") or set()
    claims = set(claims) if not isinstance(claims, set) else claims

    out = []
    seen = set()
    device_problems = signals.get("device_problems") or []

    def add(item, note):
        label = f"{item.get('term', '')} - {note}"
        key = item.get("term", "")
        if key and key not in seen:
            seen.add(key)
            out.append({"label": label, "count": int(item.get("count") or 0), "source": source})

    if "measure" in claims:
        for item in device_problems:
            if _matches(item.get("term"), accuracy):
                add(item, "accuracy / false-reading problem")

    if _is_connected(answers):
        for item in device_problems:
            if _matches(item.get("term"), connectivity):
                add(item, "software / connectivity problem")

    # Always show the single largest reported problem as a baseline, with its
    # count and source, so the panel is never empty when there is data.
    if not out and device_problems:
        top = max(device_problems, key=lambda i: int(i.get("count") or 0))
        add(top, "most-reported device problem")

    return out


# ---------------------------------------------------------------- fetcher (build/refresh only)
def _atomic_write_json(path, obj):
    """Write ``obj`` as JSON atomically (tmp + os.replace), the repo convention."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _count_url(api, product_code, count_field, years=_YEARS):
    """Build an openFDA count query URL for ``count_field`` over the last ``years``.

    The product code is matched on ``device.device_report_product_code`` — the
    field that is actually populated in MAUDE device events (the
    ``device.openfda.product_code`` field is frequently empty).
    """
    today = dt.date.today()
    start = today.replace(year=today.year - years)
    search = (f'device.device_report_product_code:"{product_code}"'
              f"+AND+date_received:[{start:%Y%m%d}+TO+{today:%Y%m%d}]")
    return f"{api}?search={search}&count={count_field}"


def _clean_term(term):
    """Keep only meaningful count terms; drop blanks and single-char code noise.

    openFDA exact counts sometimes split coded fields into single-letter noise
    (e.g. "", " H", " R") alongside the real labels. We drop any term that is
    blank or shorter than three characters so the view shows real problem names.
    """
    t = (term or "").strip()
    return t if len(t) >= 3 else None


def _reduce_terms(openfda_json, top_n=_TOP_N):
    """Reduce an openFDA count response to ``[{term, count}]`` (top N, cleaned)."""
    results = (openfda_json or {}).get("results") or []
    out = []
    for r in results:
        term = _clean_term(r.get("term", ""))
        if term:
            out.append({"term": term, "count": int(r.get("count") or 0)})
    out.sort(key=lambda x: -x["count"])
    return out[:top_n]


def _reduce_years(openfda_json, years=_YEARS):
    """Reduce a date_received year-count response to ``[{year, count}]`` (last ``years``)."""
    results = (openfda_json or {}).get("results") or []
    by_year = {}
    for r in results:
        # openFDA returns "time" as YYYYMMDD when counting a date field.
        t = str(r.get("time") or "")
        if len(t) >= 4 and t[:4].isdigit():
            by_year[int(t[:4])] = by_year.get(int(t[:4]), 0) + int(r.get("count") or 0)
    this_year = dt.date.today().year
    wanted = range(this_year - years + 1, this_year + 1)
    return [{"year": y, "count": by_year.get(y, 0)} for y in wanted]


def _reduce_recalls(openfda_json, top_n=_RECALL_N):
    """Reduce an openFDA recall response to ``[{reason, date, cfres_id, url}]``."""
    results = (openfda_json or {}).get("results") or []
    out = []
    for r in results[:top_n]:
        cfres_id = r.get("cfres_id") or r.get("product_res_number") or ""
        out.append({
            "reason": r.get("reason_for_recall") or r.get("root_cause_description") or "",
            "date": r.get("event_date_posted") or r.get("event_date_initiated_firm") or "",
            "cfres_id": cfres_id,
            "url": _RECALL_RECORD.format(cfres_id=cfres_id) if cfres_id else RECALL_API,
        })
    return out


def fetch_and_cache(product_code, *, timeout=20):
    """Fetch openFDA event + recall data for ``product_code`` and cache it. Build/refresh only.

    Performs the count/recall queries over ``requests`` (already a dependency),
    reduces them to the stored payload, and writes ``<CODE>_event.json`` and
    ``<CODE>_recall.json`` atomically — each recording the query URL and the
    fetch date (Requirement 6.2). Returns the fresh :func:`load_signals` result.

    Raises :class:`RefreshError` on any HTTP error, timeout, or parse failure so
    callers keep the existing cache unchanged (Requirement 6.6). Never called on
    page render.
    """
    import requests  # lazy: not needed for offline rendering

    code = (product_code or "").strip().upper()
    if not code:
        raise RefreshError("no product code")

    today = dt.date.today().isoformat()

    dev_url = _count_url(EVENT_API, code, "product_problems.exact")
    pat_url = _count_url(EVENT_API, code, "patient.sequence_number_outcome.exact")
    year_url = _count_url(EVENT_API, code, "date_received")
    recall_url = (f'{RECALL_API}?search=product_code:"{code}"'
                  f"&limit={_RECALL_N}&sort=event_date_posted:desc")

    def _get(url):
        try:
            resp = requests.get(url, timeout=timeout)
        except Exception as e:  # network error / timeout
            raise RefreshError(f"openFDA request failed: {type(e).__name__}") from e
        if resp.status_code == 404:
            # openFDA returns 404 with {"error": {"code": "NOT_FOUND"}} for no matches.
            return {"results": []}
        if resp.status_code != 200:
            raise RefreshError(f"openFDA returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise RefreshError("openFDA returned invalid JSON") from e

    event_data = {
        "device_problems": _reduce_terms(_get(dev_url)),
        "patient_problems": _reduce_terms(_get(pat_url)),
        "reports_per_year": _reduce_years(_get(year_url)),
    }
    recall_data = {"recalls": _reduce_recalls(_get(recall_url))}

    d = cache_dir()
    _atomic_write_json(os.path.join(d, f"{code}_event.json"),
                       {"url": dev_url, "fetched": today, "data": event_data})
    _atomic_write_json(os.path.join(d, f"{code}_recall.json"),
                       {"url": recall_url, "fetched": today, "data": recall_data})

    return load_signals(code)

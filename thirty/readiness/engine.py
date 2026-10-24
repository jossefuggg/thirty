"""The deterministic, data-driven category engine for device readiness.

Pure and import-light (no Flask, no network, no model). The single decision
function :func:`categorize` is **total** — for every possible combination of
answers it returns exactly one result from the fixed set of five categories
(Property 1). The thresholds, labels, driver phrasings, paths, citations and the
day-one checklist all come from ``thirty/readiness_rules.json`` (Requirement
11): this module holds the control flow, the rules file holds the policy.

No AI or model is involved in deciding a category.

Key invariants (asserted by ``tests/test_readiness_properties.py``):

- Property 1: every answer combination yields exactly one category.
- Property 2: any of ``diagnose`` / ``treat`` / ``replace`` / invasive / disease
  claim forecloses ``general_wellness``.
- Property 3: ``worst == "death"`` never yields ``class_i``.
- Property 4: every result carries the disclaimer and >= 1 catalogue citation.
- Property 5: the day-one checklist always includes the MDR item citing
  ``reg_803``.
"""
import json
import os

# ---------------------------------------------------------------- answer domain
CLAIM_OPTIONS = ("wellness", "measure", "flag", "diagnose", "treat", "replace")
WORST_OUTCOMES = ("none", "minor", "serious", "death")
USERS = ("consumers", "clinicians", "both")
PREDICATE = ("yes", "no", "unsure")
CATEGORIES = ("general_wellness", "borderline", "class_i", "class_ii", "class_iii")

# Claims that, on their own, make a feature a device (never general wellness).
# A `flag` claim (flag a possible disease/condition) is disease-flagging, which
# the rules treat as a device (Class II); diagnose/treat/replace are devices by
# their nature. `measure` alone is NOT here: a bare body-measurement estimate is
# borderline, not automatically a device (Requirement 3.6).
_DEVICE_CLAIMS = frozenset({"flag", "diagnose", "treat", "replace"})

# Path to the rules data file (sits next to the thirty package root).
_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "readiness_rules.json")

# The exact disclaimer sentence, resolved from the rules file on first load and
# cached here so callers can import DISCLAIMER as a constant.
DISCLAIMER = (
    "Decision support only, not regulatory advice. "
    "Confirm with a regulatory professional or ask FDA (513(g) request or Q-Submission)."
)

# mtime-keyed cache of the parsed rules file (mirrors history_context()/plugins).
_rules_cache = {"mtime": None, "data": None}


def load_rules():
    """Read and cache ``thirty/readiness_rules.json`` (re-read when the file changes).

    Returns the parsed rules dict. Caching is keyed on the file mtime so edits
    during development are picked up without a restart, the same pattern the
    console uses for ``history.csv``.
    """
    global DISCLAIMER
    try:
        mtime = os.path.getmtime(_RULES_PATH)
    except OSError:
        mtime = None
    if _rules_cache["data"] is None or _rules_cache["mtime"] != mtime:
        with open(_RULES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        _rules_cache["data"] = data
        _rules_cache["mtime"] = mtime
        # Keep the module constant in sync with the data file.
        DISCLAIMER = data.get("disclaimer") or DISCLAIMER
    return _rules_cache["data"]


# ---------------------------------------------------------------- normalize
def _as_bool(value):
    """Coerce an arbitrary value to a bool, treating common truthy strings as True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return bool(value)


def normalize(raw):
    """Coerce arbitrary input into the canonical ``Answers`` shape. Total: never raises.

    ``raw`` is any mapping (a parsed JSON body, a form dict, or junk). Unknown
    claims are dropped; a missing/invalid boolean becomes ``False``; an
    out-of-set scalar falls back to the safest value (``worst`` -> ``none``,
    ``users`` -> ``consumers``, ``predicate`` -> ``unsure``). This keeps
    :func:`categorize` total over every possible raw input (needed for Property
    1 and for the route's handling of malformed submissions).

    Returns ``{"claims": set[str], "invasive": bool, "disease_claim": bool,
    "worst": str, "users": str, "predicate": str}``.
    """
    raw = raw if isinstance(raw, dict) else {}

    raw_claims = raw.get("claims")
    if isinstance(raw_claims, (list, tuple, set)):
        claims = {c for c in raw_claims if c in CLAIM_OPTIONS}
    elif isinstance(raw_claims, str) and raw_claims in CLAIM_OPTIONS:
        claims = {raw_claims}
    else:
        claims = set()

    worst = raw.get("worst")
    worst = worst if worst in WORST_OUTCOMES else "none"

    users = raw.get("users")
    users = users if users in USERS else "consumers"

    predicate = raw.get("predicate")
    predicate = predicate if predicate in PREDICATE else "unsure"

    return {
        "claims": claims,
        "invasive": _as_bool(raw.get("invasive")),
        "disease_claim": _as_bool(raw.get("disease_claim")),
        "worst": worst,
        "users": users,
        "predicate": predicate,
    }


# ---------------------------------------------------------------- helpers
def _is_device_trigger(a):
    """Whether any answer makes the feature a device (never general wellness / borderline).

    True when a ``diagnose`` / ``treat`` / ``replace`` / ``flag`` claim is
    present, or the feature is invasive/implanted/energy/substance, or the
    marketing names a disease (Requirement 3.4 / Property 2).

    Also true for a **high-risk body-measurement** feature: general wellness and
    the borderline path only cover low-risk products, so a ``measure`` feature
    whose worst realistic outcome is ``serious`` injury or ``death`` is a device,
    not borderline or wellness. (A ``measure`` feature with worst harm
    ``none``/``minor`` is still low-risk and stays borderline.)
    """
    if bool(a["claims"] & _DEVICE_CLAIMS) or a["invasive"] or a["disease_claim"]:
        return True
    if "measure" in a["claims"] and a["worst"] in ("serious", "death"):
        return True
    return False


def _driver(rules, key):
    """Resolve a driver phrase from the rules ``driver_text`` table (key -> text)."""
    return rules.get("driver_text", {}).get(key, key)


def _citations(rules, keys):
    """Resolve a list of citation keys to full citation dicts from the catalogue.

    Each returned item is ``{"key", "label", "date", "url"}``. Unknown keys are
    skipped (the catalogue is the single source of truth; nothing is invented).
    """
    cat = rules.get("citations", {})
    out = []
    for key in keys:
        entry = cat.get(key)
        if entry:
            out.append({"key": key, "label": entry.get("label", key),
                        "date": entry.get("date"), "url": entry.get("url")})
    return out


def _path(rules, key):
    """Resolve a path entry (e.g. 510k / denovo / borderline_*) from the rules."""
    p = rules.get("paths", {}).get(key)
    if not p:
        return None
    return {"key": key, "name": p.get("name", key), "when": p.get("when", "")}


def _suggested_code(rules, a):
    """Suggest the closest product code for Step 3 from the Step 1 answers.

    Reads ``suggested_codes_by_claim`` from the rules; falls back to the first
    configured product code. May return ``None`` if no codes are configured.
    """
    by_claim = rules.get("suggested_codes_by_claim", {})
    # Prefer the most specific claim present, in rules-declared order.
    for claim in ("diagnose", "treat", "flag", "measure", "replace", "wellness"):
        if claim in a["claims"] and by_claim.get(claim):
            return by_claim[claim]
    codes = rules.get("product_codes", [])
    return codes[0]["code"] if codes else None


# ---------------------------------------------------------------- categorize
def categorize(answers):
    """Decide the likely category. Pure, total, deterministic — no AI.

    ``answers`` is the canonical shape from :func:`normalize` (callers should
    pass ``categorize(normalize(raw))``; a raw dict is normalized defensively
    here too). Returns exactly one ``Result`` (Property 1):

    ``{"category", "label", "headline", "drivers"[2..4], "paths"[],
    "citations"[>=1], "suggested_product_code", "disclaimer"}``.

    The decision is a first-match-wins ladder (strongest device signal first),
    so no weaker rule can override a stronger one and ``general_wellness`` is
    reachable only from its single explicit branch:

    1. Device? -> ``diagnose``/``treat``/``replace`` claim, invasive, or disease
       claim. If a device:
         - death, OR invasive + serious            -> class_iii (Property 3)
         - serious, OR a ``flag`` claim            -> class_ii (+ 510k/De Novo/both)
         - minor, non-invasive                     -> class_i (exemption note)
         - otherwise (device, none, non-invasive)  -> class_i
       A high-risk body-measurement feature is a device too: a ``measure``
       claim with worst harm ``serious`` -> class_ii, ``death`` -> class_iii
       (same predicate logic). Only low-risk measurement (worst none/minor)
       stays borderline.
    2. Not a device:
         - only ``wellness``, non-invasive, no disease, worst none/minor
                                                    -> general_wellness
         - ``measure`` present, worst none/minor, no flag/device claim,
           non-invasive, no disease                -> borderline (both paths)
         - anything else not a device              -> borderline
    """
    a = answers if (isinstance(answers, dict) and isinstance(answers.get("claims"), set)) else normalize(answers)
    rules = load_rules()
    cats = rules.get("categories", {})
    cat_cites = rules.get("category_citations", {})

    device = _is_device_trigger(a)
    drivers = []
    paths = []
    category = None

    if device:
        # Which trigger(s) made it a device -> drivers (2-4 most relevant).
        for claim in ("diagnose", "treat", "replace", "flag", "measure"):
            if claim in a["claims"]:
                drivers.append(_driver(rules, f"claim.{claim}"))
        if a["invasive"]:
            drivers.append(_driver(rules, "invasive"))
        if a["disease_claim"]:
            drivers.append(_driver(rules, "disease_claim"))

        if a["worst"] == "death" or (a["invasive"] and a["worst"] == "serious"):
            category = "class_iii"
            drivers.append(_driver(rules, f"worst.{a['worst']}"))
        elif a["worst"] == "serious" or "flag" in a["claims"]:
            category = "class_ii"
            if a["worst"] == "serious":
                drivers.append(_driver(rules, "worst.serious"))
            if a["predicate"] == "yes":
                paths.append(_path(rules, "510k"))
            elif a["predicate"] == "no":
                paths.append(_path(rules, "denovo"))
            else:  # unsure -> show both
                paths.append(_path(rules, "510k"))
                paths.append(_path(rules, "denovo"))
            drivers.append(_driver(rules, f"predicate.{a['predicate']}"))
        elif a["worst"] == "minor" and not a["invasive"]:
            # device, minor harm, non-invasive, no flag -> Class I (R3.9).
            category = "class_i"
            drivers.append(_driver(rules, "worst.minor"))
            paths.append(_path(rules, "class_i_note"))
        elif not a["invasive"]:
            # device, worst none, non-invasive, no flag/serious -> lowest class
            # (Class I). death/serious are handled above, so Class I is never
            # reached from death (Property 3).
            category = "class_i"
            drivers.append(_driver(rules, f"worst.{a['worst']}"))
            paths.append(_path(rules, "class_i_note"))
        else:
            # device + invasive but not death/serious (so worst none/minor):
            # invasive features are not Class I (R3.9 requires non-invasive).
            # Treat as Class II - the conservative non-I default for an invasive
            # device that did not meet the Class III threshold.
            category = "class_ii"
            drivers.append(_driver(rules, "invasive"))
            drivers.append(_driver(rules, f"worst.{a['worst']}"))
            if a["predicate"] == "yes":
                paths.append(_path(rules, "510k"))
            elif a["predicate"] == "no":
                paths.append(_path(rules, "denovo"))
            else:
                paths.append(_path(rules, "510k"))
                paths.append(_path(rules, "denovo"))
    else:
        only_wellness = a["claims"] == {"wellness"}
        if only_wellness and a["worst"] in ("none", "minor"):
            category = "general_wellness"
            drivers.append(_driver(rules, "claim.wellness"))
            drivers.append(_driver(rules, f"worst.{a['worst']}"))
            drivers.append(_driver(rules, "disease_claim") if a["disease_claim"] else _driver(rules, "users." + a["users"]))
        else:
            category = "borderline"
            if "measure" in a["claims"]:
                drivers.append(_driver(rules, "claim.measure"))
            elif "wellness" in a["claims"]:
                drivers.append(_driver(rules, "claim.wellness"))
            drivers.append(_driver(rules, f"worst.{a['worst']}"))
            drivers.append(_driver(rules, "users." + a["users"]))
            # Both wellness/device readings of a borderline feature.
            paths.append(_path(rules, "borderline_wellness"))
            paths.append(_path(rules, "borderline_device"))

    # Clamp drivers to the 2-4 that drove the result (Requirement 3.3). Keep the
    # first-seen order; dedupe; never fewer than 2 (pad from users/worst).
    seen, deduped = set(), []
    for d in drivers:
        if d and d not in seen:
            seen.add(d)
            deduped.append(d)
    if len(deduped) < 2:
        for extra in (_driver(rules, "users." + a["users"]), _driver(rules, f"worst.{a['worst']}")):
            if extra not in seen:
                seen.add(extra)
                deduped.append(extra)
            if len(deduped) >= 2:
                break
    drivers = deduped[:4]

    paths = [p for p in paths if p]

    cat_meta = cats.get(category, {})
    citations = _citations(rules, cat_cites.get(category, []))
    # Guarantee at least one citation (Property 4) even if the rules omit one.
    if not citations:
        citations = _citations(rules, ["gw_guidance"]) or [{"key": "gw_guidance", "label": "FDA guidance", "date": None, "url": None}]

    return {
        "category": category,
        "label": cat_meta.get("label", category),
        "headline": cat_meta.get("headline", "This is likely " + category + "."),
        "drivers": drivers,
        "paths": paths,
        "citations": citations,
        "suggested_product_code": _suggested_code(rules, a),
        "disclaimer": rules.get("disclaimer") or DISCLAIMER,
    }


# ---------------------------------------------------------------- day-one checklist
def day_one_checklist():
    """Return the day-one obligations checklist with resolved citations and tags.

    Each item is ``{"id", "text", "citations"[...], "thirty", "thirty_label"}``
    where ``thirty`` is ``"handles"`` / ``"flags"`` / ``None`` and
    ``thirty_label`` is the human tag (or ``None``). The list always contains the
    MDR item citing ``reg_803`` (Property 5) because the rules file always
    includes it; a test asserts this invariant.
    """
    rules = load_rules()
    tags = rules.get("thirty_tags", {})
    out = []
    for item in rules.get("day_one_checklist", []):
        thirty = item.get("thirty")
        out.append({
            "id": item.get("id"),
            "text": item.get("text", ""),
            "citations": _citations(rules, item.get("citations", [])),
            "thirty": thirty,
            "thirty_label": tags.get(thirty) if thirty else None,
        })
    return out

"""Example-based tests for device readiness: rules, engine, openFDA cache, routes, PDF."""
import contextlib
import json
import os

import pytest

from thirty.readiness import engine, openfda, pdf as rpdf


def _ans(**kw):
    base = {"claims": [], "invasive": False, "disease_claim": False,
            "worst": "none", "users": "consumers", "predicate": "unsure"}
    base.update(kw)
    return engine.normalize(base)


# ---------------------------------------------------------------- rules integrity
def test_rules_citation_keys_all_resolve():
    rules = engine.load_rules()
    cat = rules["citations"]
    # Every citation key referenced anywhere must exist in the catalogue.
    for item in rules["day_one_checklist"]:
        for key in item["citations"]:
            assert key in cat, f"checklist cites unknown {key}"
    for keys in rules["category_citations"].values():
        for key in keys:
            assert key in cat, f"category cites unknown {key}"


def test_checklist_tags_are_exactly_as_specified():
    cl = engine.day_one_checklist()
    by_id = {i["id"]: i for i in cl}
    assert by_id["complaints"]["thirty"] == "handles"
    assert by_id["mdr"]["thirty"] == "handles"
    assert by_id["audit"]["thirty"] == "handles"
    assert by_id["corrections"]["thirty"] == "flags"
    for other in ("registration", "qmsr", "udi", "cyber"):
        assert by_id[other]["thirty"] is None


def test_checklist_always_has_803():
    cl = engine.day_one_checklist()
    assert any(any(c["key"] == "reg_803" for c in i["citations"]) for i in cl)


def test_product_codes_non_empty_and_cached(data_dir):
    rules = engine.load_rules()
    codes = [c["code"] for c in rules["product_codes"]]
    assert codes
    # Every selectable code renders offline from the shipped cache.
    for code in codes:
        s = openfda.load_signals(code)
        assert s["has_data"], f"{code} has no cached data"


# ---------------------------------------------------------------- named category cases
def test_pure_wellness_is_general_wellness():
    assert engine.categorize(_ans(claims=["wellness"], worst="minor"))["category"] == "general_wellness"


def test_measure_only_is_borderline_with_both_paths():
    res = engine.categorize(_ans(claims=["measure"], worst="none"))
    assert res["category"] == "borderline"
    names = {p["key"] for p in res["paths"]}
    assert "borderline_wellness" in names and "borderline_device" in names


def test_device_death_is_class_iii():
    assert engine.categorize(_ans(claims=["diagnose"], worst="death"))["category"] == "class_iii"


def test_invasive_serious_is_class_iii():
    assert engine.categorize(_ans(claims=["treat"], invasive=True, worst="serious"))["category"] == "class_iii"


@pytest.mark.parametrize("predicate,expect_keys", [
    ("yes", {"510k"}),
    ("no", {"denovo"}),
    ("unsure", {"510k", "denovo"}),
])
def test_device_serious_is_class_ii_with_paths(predicate, expect_keys):
    res = engine.categorize(_ans(claims=["flag"], worst="serious", predicate=predicate))
    assert res["category"] == "class_ii"
    assert {p["key"] for p in res["paths"]} == expect_keys


def test_device_minor_noninvasive_is_class_i():
    res = engine.categorize(_ans(claims=["treat"], worst="minor", invasive=False))
    assert res["category"] == "class_i"
    assert any(p["key"] == "class_i_note" for p in res["paths"])


def test_drivers_count_between_2_and_4():
    for raw in ([("wellness",), "none"], [("diagnose",), "death"], [("measure",), "serious"]):
        claims, worst = raw
        res = engine.categorize(_ans(claims=list(claims), worst=worst))
        assert 2 <= len(res["drivers"]) <= 4


def test_every_result_has_likely_in_headline():
    res = engine.categorize(_ans(claims=["wellness"], worst="none"))
    assert "likely" in res["headline"].lower()


# ---------------------------------------------------------------- example preset
def test_example_preset_is_borderline_and_invented():
    rules = engine.load_rules()
    preset = rules["example_preset"]
    assert preset["name"] == "Stride Band"  # invented
    res = engine.categorize(engine.normalize(preset["answers"]))
    assert res["category"] == "borderline"


# ---------------------------------------------------------------- openFDA loader
def _seed_cache(tmp_path, code="ABC", event=True, recall=True, empty=False, missing=False):
    d = str(tmp_path)
    if missing:
        return d
    ev = {"url": "u", "fetched": "2026-01-01", "data": {
        "device_problems": [] if empty else [{"term": "Incorrect Measurement", "count": 50},
                                              {"term": "Wireless Communication Problem", "count": 30}],
        "patient_problems": [] if empty else [{"term": "Required Intervention", "count": 10}],
        "reports_per_year": [] if empty else [{"year": 2025, "count": 12}],
    }}
    rc = {"url": "u", "fetched": "2026-01-01", "data": {
        "recalls": [] if empty else [{"reason": "Firmware issue", "date": "2025-02-01", "cfres_id": "X1", "url": "http://x"}]}}
    if event:
        with open(os.path.join(d, f"{code}_event.json"), "w") as f:
            json.dump(ev, f)
    if recall:
        with open(os.path.join(d, f"{code}_recall.json"), "w") as f:
            json.dump(rc, f)
    return d


def test_load_signals_reads_cache(tmp_path, monkeypatch):
    d = _seed_cache(tmp_path, "ABC")
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    s = openfda.load_signals("ABC")
    assert s["has_data"]
    assert s["device_problems"][0]["term"] == "Incorrect Measurement"
    assert s["recalls"][0]["reason"] == "Firmware issue"


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_load_signals_empty_safe(kind, tmp_path, monkeypatch):
    d = _seed_cache(tmp_path, "ABC", empty=(kind == "empty"), missing=(kind == "missing"))
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    s = openfda.load_signals("ABC")
    assert s["has_data"] is False
    assert s["device_problems"] == [] and s["recalls"] == []


def test_load_signals_invalid_json_is_safe(tmp_path, monkeypatch):
    d = str(tmp_path)
    with open(os.path.join(d, "ABC_event.json"), "w") as f:
        f.write("{not json")
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    s = openfda.load_signals("ABC")
    assert s["has_data"] is False


def test_where_to_look_first_measure_surfaces_accuracy(tmp_path, monkeypatch):
    d = _seed_cache(tmp_path, "ABC")
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    s = openfda.load_signals("ABC")
    items = openfda.where_to_look_first(s, _ans(claims=["measure"], users="consumers"))
    assert items
    assert all(isinstance(i["count"], int) and i["source"] for i in items)
    assert any("accuracy" in i["label"].lower() or "Incorrect" in i["label"] for i in items)


def test_where_to_look_first_connected_surfaces_connectivity(tmp_path, monkeypatch):
    d = _seed_cache(tmp_path, "ABC")
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    s = openfda.load_signals("ABC")
    items = openfda.where_to_look_first(s, _ans(claims=["flag"], users="both"))
    assert any("Wireless" in i["label"] or "connectivity" in i["label"].lower() for i in items)


# ---------------------------------------------------------------- refresh (patched network)
@contextlib.contextmanager
def _patched_requests(payloads, raises=False):
    """Patch requests.get to return canned openFDA JSON (or raise)."""
    import requests

    class _Resp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return self._data

    def fake_get(url, timeout=None):
        if raises:
            raise requests.exceptions.ConnectionError("offline")
        # choose a payload by what the URL is counting
        if "product_problems" in url:
            return _Resp(payloads["dev"])
        if "sequence_number_outcome" in url:
            return _Resp(payloads["pat"])
        if "count=date_received" in url:
            return _Resp(payloads["years"])
        return _Resp(payloads["recalls"])

    orig = requests.get
    requests.get = fake_get
    try:
        yield
    finally:
        requests.get = orig


def test_fetch_and_cache_writes_atomic(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "cache_dir", lambda: d)
    payloads = {
        "dev": {"results": [{"term": "Low Readings", "count": 9}]},
        "pat": {"results": [{"term": "Hospitalization", "count": 3}]},
        "years": {"results": [{"time": "20250101", "count": 7}]},
        "recalls": {"results": [{"reason_for_recall": "r", "event_date_posted": "2025-01-01", "cfres_id": "C1"}]},
    }
    with _patched_requests(payloads):
        s = openfda.fetch_and_cache("ABC")
    assert s["has_data"]
    ev = json.load(open(os.path.join(d, "ABC_event.json")))
    assert ev["url"] and ev["fetched"]
    assert ev["data"]["device_problems"][0]["term"] == "Low Readings"


def test_fetch_and_cache_failure_raises_and_keeps_cache(tmp_path, monkeypatch):
    d = _seed_cache(tmp_path, "ABC")  # pre-existing cache
    monkeypatch.setattr(openfda, "_runtime_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "_shipped_cache_dir", lambda: d)
    monkeypatch.setattr(openfda, "cache_dir", lambda: d)
    before = open(os.path.join(d, "ABC_event.json")).read()
    with _patched_requests({}, raises=True):
        with pytest.raises(openfda.RefreshError):
            openfda.fetch_and_cache("ABC")
    assert open(os.path.join(d, "ABC_event.json")).read() == before  # untouched


# ---------------------------------------------------------------- PDF
def test_pdf_build_or_degrade():
    result = engine.categorize(_ans(claims=["measure"], worst="minor"))
    signals = openfda.load_signals("")
    checklist = engine.day_one_checklist()
    out = rpdf.build_pdf(result, signals, checklist, product_code=None)
    if rpdf.available():
        assert out and out[:4] == b"%PDF"
    else:
        assert out is None


def test_pdf_none_when_fpdf_missing(monkeypatch):
    monkeypatch.setattr(rpdf, "FPDF", None)
    assert rpdf.available() is False
    assert rpdf.build_pdf({}, {}, [], product_code=None) is None


# ---------------------------------------------------------------- routes (Flask client)
def test_readiness_page_renders_with_disclaimer_twice(client):
    r = client.get("/readiness")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    disclaimer = "Decision support only, not regulatory advice."
    assert body.count(disclaimer) >= 2  # top and bottom of the result
    assert "Device readiness" in body


def test_api_category_returns_expected(client):
    r = client.post("/api/readiness/category", json={"claims": ["wellness"], "worst": "none"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["result"]["category"] == "general_wellness"
    assert any(any(c["key"] == "reg_803" for c in i["citations"]) for i in data["checklist"])


def test_api_category_no_claim_still_returns_one_category(client):
    r = client.post("/api/readiness/category", json={})
    assert r.status_code == 200
    assert r.get_json()["result"]["category"] in engine.CATEGORIES


def test_api_signals_returns_seeded(client):
    r = client.get("/api/readiness/signals?code=QBJ&claim=measure&users=consumers")
    assert r.status_code == 200
    data = r.get_json()
    assert data["signals"]["code"] == "QBJ"
    assert data["signals"]["has_data"]
    assert data["notice"]
    for it in data["where_to_look_first"]:
        assert "count" in it and it["source"]


def test_api_signals_unknown_code_empty(client):
    r = client.get("/api/readiness/signals?code=ZZZ")
    assert r.status_code == 200
    assert r.get_json()["signals"]["has_data"] is False


def test_api_pdf_or_404(client):
    r = client.post("/api/readiness/pdf", json={"answers": {"claims": ["wellness"], "worst": "none"}, "code": "QBJ"})
    if rpdf.available():
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"
        assert r.get_data()[:4] == b"%PDF"
    else:
        assert r.status_code == 404


def test_refresh_locked_in_public_demo(data_dir, monkeypatch):
    """With THIRTY_PUBLIC_DEMO=1 the refresh endpoint is locked (403)."""
    import importlib.util
    import sys

    monkeypatch.setenv("THIRTY_PUBLIC_DEMO", "1")
    monkeypatch.setenv("VIGIL_DIR", data_dir)
    monkeypatch.setenv("THIRTY_SKIP_RUNTIME_INIT", "1")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("console_app_pd", os.path.join(root, "dashboard_v2", "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["console_app_pd"] = mod
    spec.loader.exec_module(mod)
    mod.app.config["TESTING"] = True
    c = mod.app.test_client()
    r = c.post("/api/readiness/refresh", json={"code": "QBJ"})
    assert r.status_code == 403
    # The read-only page and signals still work in the public demo.
    assert c.get("/readiness").status_code == 200
    assert c.get("/api/readiness/signals?code=QBJ").status_code == 200
    sys.modules.pop("console_app_pd", None)

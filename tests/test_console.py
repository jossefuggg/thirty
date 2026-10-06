"""Console pages, JSON API, review actions and brand rules (no model needed)."""
import os, re

import pytest

PAGES = ["/", "/complaints", "/clock", "/trends", "/audit", "/intake", "/integrations", "/demo"]
VIGIL_WORD = re.compile(r"\bVigil\b")  # internal identifiers stay lowercase (vigil:changed, vigil-reviewer, vigil.py)


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_as_thirty(client, path):
    r = client.get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<title>" in html and "· Thirty</title>" in html
    assert not VIGIL_WORD.search(html), "user-facing 'Vigil' left on " + path
    assert "/static/thirty/css/thirty.css" in html
    assert "0 bytes to cloud AI" in html
    assert 'class="sample"' in html and "Sample data" in html, "demo mode label missing on " + path


def test_detail_page_and_404(client, console):
    ids = [r["id"] for r in console.all_rows()]
    r = client.get(f"/complaint/{ids[0]}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Why Thirty decided this" in html and not VIGIL_WORD.search(html)
    assert client.get("/complaint/does-not-exist").status_code == 404


def test_static_brand_assets(client):
    for path in ("/static/thirty/css/thirty.css", "/static/thirty/fonts/manrope-500.woff2", "/static/thirty/fonts/instrument-serif-400.woff2",
                 "/static/thirty/logo/thirty-lockup.svg", "/static/thirty/logo/thirty-lockup-reverse.svg", "/static/thirty/logo/favicon.svg"):
        assert client.get(path).status_code == 200, path


def test_no_external_resources_in_templates():
    """No CDN, no Google Fonts, no analytics: everything the pages load is served from /static."""
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard_v2")
    bad = re.compile(r"https?://(?!localhost|127\.0\.0\.1|api\.telegram\.org)[^\s\"')]+")
    for root in (os.path.join(here, "templates"), os.path.join(here, "static", "thirty", "css")):
        for name in os.listdir(root):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                text = f.read()
            hits = [h for h in bad.findall(text) if "www.w3.org" not in h and "northwind-medical.example" not in h]
            assert not hits, f"{name}: {hits}"


def test_state_api_shape(client, console):
    j = client.get("/api/state").get_json()
    assert set(j) >= {"kpi", "feed", "queue", "alerts", "pipeline", "clock", "history", "demo"}
    assert j["kpi"]["reportable"]["value"] == sum(r["decision"] == "REPORTABLE" for r in console.all_rows())
    rows = console.all_rows()
    assert j["kpi"]["overdue"]["value"] == sum(1 for r in rows if console.is_open(r) and console.days_left(r) < 0) >= 2
    assert j["kpi"]["approved"]["value"] == sum(r["status"].startswith("APPROVED") for r in rows) >= 5
    assert j["demo"]["demo_mode"] is True and j["alerts"], "sample history should raise at least one pattern alert"
    assert all(r["status_kind"] == "pend" for r in j["queue"])
    assert [r["id"] for r in j["clock"]] == sorted((r["id"] for r in j["clock"]), key=lambda i: next(x["due_date"] for x in j["clock"] if x["id"] == i))


def test_complaints_list_filters_and_sort(client, console):
    total = len(console.all_rows())
    j = client.get("/api/complaints/list").get_json()
    assert j["total"] == total and len(j["rows"]) == total
    j = client.get("/api/complaints/list?decision=NOT_REPORTABLE").get_json()
    assert j["total"] == 10 and all(r["decision"] == "NOT_REPORTABLE" for r in j["rows"])
    j = client.get("/api/complaints/list?sort=due&dir=asc").get_json()
    dues = [r["due"] for r in j["rows"] if r["due"]]
    assert dues == sorted(dues)
    j = client.get("/api/complaints/list?q=steripak").get_json()
    assert j["total"] == 3


def test_other_json_endpoints(client):
    assert client.get("/api/health").status_code == 200
    t = client.get("/api/trends").get_json()
    assert t["live_rows"] == 40 and t["has_history"] and t["history_rows"] > 100
    assert len(client.get("/api/audit").get_json()["events"]) > 40
    ev = client.get("/api/audit").get_json()["events"]
    assert any(e["actor"] == "Thirty agent" for e in ev) and not any(VIGIL_WORD.search(e["actor"]) for e in ev)
    assert "thirty_audit_" in client.get("/audit.csv").headers["Content-Disposition"]
    assert client.get("/api/search?q=aeroflow").get_json()["total"] == 8
    assert client.get("/api/notifications").status_code == 200
    assert client.get("/api/intake").get_json()["counts"]["queued"] == 0


def test_review_actions_round_trip(client, console):
    cid = next(r["id"] for r in console.all_rows() if r["status"] == "PENDING_REVIEW" and r["decision"] == "REPORTABLE")
    assert client.post(f"/api/complaint/{cid}/action", json={"kind": "approve", "name": ""}).status_code == 400
    r = client.post(f"/api/complaint/{cid}/action", json={"kind": "approve", "name": "T. Reviewer"})
    assert r.status_code == 200 and r.get_json()["status"] == "APPROVED by T. Reviewer"
    assert client.get(f"/api/summary/{cid}").get_json()["status_kind"] == "appr"
    assert client.post(f"/api/complaint/{cid}/action", json={"kind": "info", "name": "T. Reviewer"}).status_code == 409  # never overrides an approval
    r = client.post(f"/api/complaint/{cid}/action", json={"kind": "undo", "name": "T. Reviewer"})
    assert r.status_code == 200
    assert client.get(f"/api/summary/{cid}").get_json()["status_kind"] == "pend"
    frag = client.get(f"/api/complaint/{cid}").get_json()
    assert "btn-accent" in frag["review"] and "Approve" in frag["review"]


def test_detail_fragments_use_brand_pills(client, console):
    five = next(r["id"] for r in console.all_rows() if str(r["deadline_days"]) == "5")
    html = client.get(f"/complaint/{five}").get_data(as_text=True)
    assert "pill-five-day" in html and 'data-five="1"' in html


def test_health_reports_sample_agent(client, console):
    console.HEALTH.update(model=console._check_model(), telegram=console._check_telegram())
    h = client.get("/api/health").get_json()
    assert h["demo_mode"] is True and h["agent"]["id"] == "sample"
    assert h["model"]["ok"] is True and "no model" in h["model"]["label"]
    assert h["telegram"]["off"] is True


def test_demo_replay_and_reset_in_process(client, console):
    """Demo mode runs the replay and the reset inside the console: no subprocess, no model."""
    import time
    before = len(console.all_rows())
    assert client.post("/api/demo/replay").status_code == 200
    for _ in range(200):
        d = client.get("/api/demo").get_json()
        if not d["running"]:
            break
        time.sleep(0.05)
    assert not d["running"] and d["rc"] == 0 and d["processed"] == d["total"] == len(console.sample_data.INCOMING)
    rows = console.all_rows()
    assert len(rows) == before + len(console.sample_data.INCOMING)
    new = {r["id"]: r for r in rows}["NW-24104"]
    assert new["decision"] == "REPORTABLE" and str(new["deadline_days"]) == "5"
    assert client.get(f"/complaint/NW-24104").status_code == 200
    assert client.post("/api/demo/reset").status_code == 200
    for _ in range(200):
        d = client.get("/api/demo").get_json()
        if not d["running"]:
            break
        time.sleep(0.05)
    assert d["rc"] == 0 and len(console.all_rows()) == before
    assert client.get("/demo").status_code == 200


def test_intake_runs_through_sample_agent(client, console):
    """A complaint posted to the REST intake is classified by the sample agent's fallback rules."""
    import time
    key = console.load_settings()["api_key"]
    r = client.post("/api/complaints", json={"id": "T-FIRE-1", "text": "The infusion pump started smoking and the patient was taken to hospital with a burn to the arm.",
                                             "device": "PulseGuard P1 infusion pump"}, headers={"X-API-Key": key})
    assert r.status_code == 202 and r.get_json()["accepted"] == 1
    for _ in range(200):
        items = client.get("/api/intake").get_json()["items"]
        it = next(i for i in items if i["cid"] == "T-FIRE-1")
        if it["status"] in ("processed", "error"):
            break
        time.sleep(0.05)
    assert it["status"] == "processed", it
    row = {r["id"]: r for r in console.all_rows()}["T-FIRE-1"]
    assert row["decision"] == "REPORTABLE" and str(row["deadline_days"]) == "5"

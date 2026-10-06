"""Decision records, jurisdiction clocks, the signed audit chain and the submission pack through the console API."""
import datetime as dt, io, json, zipfile


def _reportable(console):
    return next(r for r in console.all_rows() if r["status"] == "PENDING_REVIEW" and r["decision"] == "REPORTABLE" and r["category"] == "MALFUNCTION")


def test_detail_page_shows_decision_tree_and_clocks(client, console):
    assert client.post("/api/workspace", json={"org": "Northwind Medical", "unit": "Quality", "jurisdictions": ["US", "EU"]}).status_code == 200
    r = _reportable(console)
    html = client.get(f"/complaint/{r['id']}").get_data(as_text=True)
    assert "Reportability decision" in html and 'name="malfunction_likely" value="yes" checked' in html
    assert "Reporting clocks" in html and "US FDA" in html and "EU MDR" in html
    assert "Record decision" in html and "820.35" in html


def test_record_decision_validates_and_updates_the_row(client, console):
    r = _reportable(console)
    cid = r["id"]
    url = f"/api/complaint/{cid}/decision"
    assert client.post(url, json={"answers": {"death": "yes"}, "rationale": "x", "name": ""}).status_code == 400
    assert client.post(url, json={"answers": {"death": "yes"}, "rationale": "", "name": "A. Rivera"}).status_code == 400
    assert client.post("/api/complaint/nope/decision", json={"answers": {}, "rationale": "x", "name": "A"}).status_code == 404
    res = client.post(url, json={"answers": {"death": "no", "serious_injury": "yes", "malfunction_likely": "no", "remedial": "yes", "unanticipated": "yes"},
                                 "rationale": "Patient was admitted overnight with a burn.", "name": "A. Rivera", "aware": "2026-10-01",
                                 "fields": {"udi": "(01)00812345000012(21)SN4471"}})
    assert res.status_code == 200, res.get_json()
    rec = res.get_json()["record"]
    assert rec["outcome"]["category"] == "SERIOUS_INJURY" and rec["outcome"]["five_day"] and rec["fields"]["udi"].endswith("SN4471")
    assert [c["code"] for c in rec["clocks"]] == ["US", "EU"] and rec["clocks"][0]["due"] == "2026-10-08"
    row = next(x for x in console.all_rows() if x["id"] == cid)
    assert row["category"] == "SERIOUS_INJURY" and row["deadline_days"] == "5" and row["due_date"] == "2026-10-08" and row["status"] == "PENDING_REVIEW"
    assert client.get(f"/api/complaint/{cid}/decisions").get_json()["records"][-1]["by"] == "A. Rivera"
    html = client.get(f"/complaint/{cid}").get_data(as_text=True)
    assert "recorded by A. Rivera" in html and "Decision recorded" in html and "5-day" in html
    # not reportable: the row is logged, no clocks, rationale on file
    res = client.post(url, json={"answers": {"death": "no", "serious_injury": "no", "malfunction_likely": "no"},
                                 "rationale": "Follow-up showed the burn was unrelated to the device.", "name": "A. Rivera"})
    assert res.status_code == 200 and res.get_json()["record"]["clocks"] == []
    row = next(x for x in console.all_rows() if x["id"] == cid)
    assert row["decision"] == "NOT_REPORTABLE" and row["status"] == "LOGGED" and row["due_date"] == ""
    ev = client.get("/api/audit").get_json()["events"]
    mine = [e for e in ev if e["id"] == cid and e["action"] == "Decision recorded"]
    assert len(mine) == 2 and all(e["signed"] for e in mine) and any("NOT REPORTABLE" in e["detail"] for e in mine)
    # back to the agent's classification (the sample data set is shared with the other test modules)
    aware = (dt.date.fromisoformat(r["due_date"]) - dt.timedelta(days=30)).isoformat()
    res = client.post(url, json={"answers": {"death": "no", "serious_injury": "no", "malfunction_likely": "yes"}, "rationale": r["reason"], "name": "A. Rivera", "aware": aware})
    assert res.status_code == 200
    row = next(x for x in console.all_rows() if x["id"] == cid)
    assert row["decision"] == "REPORTABLE" and row["due_date"] == r["due_date"] and row["status"] == "PENDING_REVIEW" and row["deadline_days"] == "30"


def test_actions_are_signed_into_the_chain(client, console):
    cid = next(r["id"] for r in console.all_rows() if r["status"] == "PENDING_REVIEW" and r["decision"] == "REPORTABLE")
    before = client.get("/api/audit/verify").get_json()
    assert before["ok"]
    assert client.post(f"/api/complaint/{cid}/action", json={"kind": "approve", "name": "T. Reviewer", "meaning": "I approve this draft."}).status_code == 200
    after = client.get("/api/audit/verify").get_json()
    assert after["ok"] and after["count"] == before["count"] + 1
    chain = client.get("/audit.jsonl").get_data(as_text=True).strip().splitlines()
    last = json.loads(chain[-1])
    assert last["action"] == "Approved" and last["id"] == cid and last["meaning"] == "I approve this draft." and last["actor"] == "T. Reviewer"
    client.post(f"/api/complaint/{cid}/action", json={"kind": "undo", "name": "T. Reviewer"})


def test_submission_pack_zip(client, console):
    cid = next(r["id"] for r in console.all_rows() if r["decision"] == "REPORTABLE")
    res = client.get(f"/complaint/{cid}/pack.zip")
    assert res.status_code == 200 and res.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(res.data))
    names = z.namelist()
    assert "README.txt" in names and "complaint.json" in names and "decision-record.json" in names and "clocks.json" in names and "audit-entries.jsonl" in names
    assert f"MDR_{cid}.pdf" in names
    assert "Thirty drafts; a human files" in z.read("README.txt").decode()
    assert client.get("/complaint/nope/pack.zip").status_code == 404


def test_workspace_jurisdictions(client, console):
    res = client.post("/api/workspace", json={"org": "Northwind Medical", "unit": "Quality", "jurisdictions": ["EU", "CA", "zz"]})  # US is always on
    assert res.status_code == 200 and res.get_json()["jurisdictions"] == ["US", "EU", "CA"]
    cid = next(r["id"] for r in console.all_rows() if r["decision"] == "REPORTABLE" and r["status"] == "PENDING_REVIEW")
    html = client.get(f"/complaint/{cid}").get_data(as_text=True)
    assert "Health Canada" in html
    clock = client.get("/api/state").get_json()["clock"]
    assert any(c["code"] == "CA" for r in clock for r2 in [r] for c in r2["clocks"])
    client.post("/api/workspace", json={"org": "Northwind Medical", "unit": "Quality", "jurisdictions": ["US", "EU"]})
    html = client.get("/settings/licence").get_data(as_text=True)
    assert "Reporting clocks that apply" in html and 'value="EU" checked' in html

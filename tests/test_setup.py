"""First-run setup: gate, flow, choices applied."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty import plugins, sample_data, setup  # noqa: E402


def test_setup_gate_and_flow(client, console, data_dir):
    os.remove(setup.path())
    try:
        assert setup.required() and not setup.wants_sample_data(), "nothing is seeded before the user chooses"
        r = client.get("/"); assert r.status_code == 302 and r.headers["Location"].endswith("/setup")
        assert client.get("/api/state").status_code == 409
        html = client.get("/setup").get_data(as_text=True)
        assert "Explore with sample data" in html and "Start with my site" in html and "What the local model needs" in html
        assert client.get("/api/health").status_code == 200  # allowed during setup
        r = client.post("/api/setup", json={"mode": "site", "org": "Harbor Medical Devices", "unit": "Regulatory", "agent": "local",
                                            "local": {"base_url": "http://127.0.0.1:9/v1"}})
        assert r.status_code == 200 and not setup.required()
        st = setup.load()
        assert st["org"] == "Harbor Medical Devices" and st["mode"] == "site" and st["agent"] == "local"
        assert plugins.plugin_state("local")["settings"]["base_url"] == "http://127.0.0.1:9/v1"
        assert client.get("/").status_code == 200 and "Harbor Medical Devices" in client.get("/").get_data(as_text=True)
        assert client.get("/setup").status_code == 302 and client.get("/setup?again=1").status_code == 200
    finally:
        setup.complete("explore")
        assert "Northwind Medical" in client.get("/").get_data(as_text=True)


def test_site_mode_reset_does_not_seed_sample_data(client, console):
    import time
    os.remove(setup.path())
    try:
        client.post("/api/setup", json={"mode": "site", "org": "Harbor Medical Devices", "agent": "sample"})
        assert not setup.wants_sample_data() and console.sample_data_mode() is False
        assert client.post("/api/demo/reset").status_code == 200
        for _ in range(200):
            if not client.get("/api/demo").get_json()["running"]: break
            time.sleep(0.05)
        assert client.get("/api/complaints/list").get_json()["total"] == 0, "a site must start empty, never with sample complaints"
        assert "Sample agent" in client.get("/").get_data(as_text=True) and "Sample data" not in client.get("/").get_data(as_text=True)
    finally:
        setup.complete("explore"); sample_data.seed(console.VIGIL_DIR); console._cache.update(rows=[], mtime=None)

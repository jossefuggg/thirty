"""Plugin contract: discovery, manifests, state, status, switching, running with no agent."""
import json, os, shutil, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty import plugins, sample_data  # noqa: E402
from thirty.agents import get_agent, set_agent  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "plugins", "keyword-agent")


@pytest.fixture()
def pdir(tmp_path, monkeypatch):
    """A fresh data folder with no plugins.json and the env override removed."""
    monkeypatch.setenv("VIGIL_DIR", str(tmp_path)); monkeypatch.delenv("THIRTY_AGENT", raising=False)
    monkeypatch.delenv("VIGIL_LLM_BASE", raising=False); monkeypatch.delenv("VIGIL_LLM_MODEL", raising=False)
    monkeypatch.setenv("THIRTY_SAMPLE_DELAY", "0")
    plugins.discover(force=True); set_agent(None)
    yield tmp_path
    plugins.discover(force=True); set_agent(None)


def test_builtins_discovered_and_default_choice(pdir):
    found = plugins.discover(force=True)
    assert set(found) >= {"sample", "local"} and all(p.builtin for p in found.values())
    assert plugins.active_agent_id() == "sample" and get_agent().id == "sample"
    assert plugins.status("sample")["state"] == "ready"
    assert plugins.status("local")["state"] == "not-configured" and "Server URL" in plugins.status("local")["label"]


def test_settings_switching_and_no_agent(pdir):
    plugins.update_plugin("local", settings={"base_url": "http://127.0.0.1:9/v1", "timeout": "5", "api_key": "k"})
    st = plugins.plugin_state("local")
    assert st["settings"]["base_url"] == "http://127.0.0.1:9/v1" and st["settings"]["timeout"] == 5.0
    assert plugins.status("local", probe=False)["state"] == "ready"
    assert plugins.status("local")["state"] == "error"  # nothing listens on port 9
    ov = next(x for x in plugins.overview(probe=False)["plugins"] if x["id"] == "local")
    assert ov["settings"]["api_key"] == "" and ov["has_secret"]["api_key"]
    plugins.update_plugin("local", settings={"api_key": ""})  # blank keeps the secret
    assert plugins.plugin_state("local")["settings"]["api_key"] == "k"
    plugins.set_active("local"); assert get_agent().id == "local" and get_agent().base_url == "http://127.0.0.1:9/v1"
    plugins.set_active("none"); a = get_agent()
    assert a.id == "none" and a.classify({"text": "anything"})["decision"] == "NEEDS_INFO" and a.health()["ok"]
    with pytest.raises(plugins.PluginError):
        plugins.set_active("nope")
    plugins.update_plugin("sample", enabled=False)
    with pytest.raises(plugins.PluginError):
        plugins.set_active("sample")
    assert plugins.status("sample")["state"] == "disabled"
    plugins.set_active("local"); plugins.update_plugin("local", enabled=False)
    assert plugins.active_agent_id() == "none", "disabling the active agent falls back to manual review"
    assert json.load(open(pdir / "plugins.json"))["active_agent"] == "none"


def test_user_plugin_from_example(pdir):
    shutil.copytree(EXAMPLE, pdir / "plugins" / "keyword-agent")
    p = plugins.discover(force=True)["keyword-agent"]
    assert not p.builtin and p.version == "0.1.0" and plugins.status("keyword-agent")["state"] == "disabled"
    plugins.update_plugin("keyword-agent", enabled=True, settings={"words": "fire, death", "strict": "false"})
    assert plugins.status("keyword-agent")["state"] == "ready"
    plugins.set_active("keyword-agent")
    a = get_agent()
    assert a.classify({"text": "the unit caught fire"})["remedial_action_needed"] is True
    assert a.classify({"text": "fine"})["decision"] == "NOT_REPORTABLE"


def test_bad_plugins_are_listed_with_errors(pdir):
    bad = pdir / "plugins" / "broken"; bad.mkdir(parents=True)
    (bad / "plugin.json").write_text('{"id": "broken", "capabilities": ["agent"]}')  # no plugin.py
    (pdir / "plugins" / "wrong-id").mkdir(); (pdir / "plugins" / "wrong-id" / "plugin.json").write_text('{"id": "other", "capabilities": ["agent"]}')
    (pdir / "plugins" / "sample").mkdir(); (pdir / "plugins" / "sample" / "plugin.json").write_text('{"id": "sample", "capabilities": ["agent"]}')
    found = plugins.discover(force=True)
    assert found["broken"].error and "plugin.py" in found["broken"].error
    assert found["wrong-id"].error and "match the folder" in found["wrong-id"].error
    assert found["sample"].builtin, "a user plugin cannot shadow a built-in"
    assert plugins.status("broken")["state"] == "error"
    with pytest.raises(plugins.PluginError):
        plugins.set_active("broken")


def test_pipeline_runs_with_no_agent(pdir):
    import importlib.util
    plugins.set_active("none")
    spec = importlib.util.spec_from_file_location("vigil_noagent", os.path.join(ROOT, "vigil.py"))
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
    v.LOG, v.REPORTS, v.OUTBOX, v.HISTORY, v.SANDBOX = str(pdir / "d.csv"), str(pdir / "r"), str(pdir / "o.txt"), str(pdir / "h.csv"), ""
    row = v.process(sample_data.incoming_complaints()[0])
    assert row["decision"] == "NEEDS_INFO" and row["status"] == "PENDING_REVIEW" and row["due_date"]
    assert "No agent is active" in row["reason"]


def test_plugins_api(client, console):
    j = client.get("/api/plugins").get_json()
    assert {p["id"] for p in j["plugins"]} >= {"sample", "local"} and j["active_agent"] == "sample" and j["forced_by_env"]
    local = next(p for p in j["plugins"] if p["id"] == "local")
    assert [s["key"] for s in local["schema"]][:2] == ["base_url", "model"] and isinstance(local["settings"], dict)
    html = client.get("/settings/plugins").get_data(as_text=True)
    assert "Active agent" in html and "Install a plugin" in html
    r = client.post("/api/plugins/local", json={"settings": {"base_url": "http://127.0.0.1:9/v1"}})
    assert r.status_code == 200 and r.get_json()["status"]["state"] == "ready"
    assert client.post("/api/plugins/local/test").get_json()["status"]["state"] == "error"
    assert client.post("/api/plugins/nope", json={"enabled": True}).status_code == 400
    r = client.post("/api/plugins/active", json={"id": "none"})
    assert r.status_code == 200 and r.get_json()["active_agent"] == "sample", "THIRTY_AGENT env forces the agent in tests"

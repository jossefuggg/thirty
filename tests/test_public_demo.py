"""Public demo lock (THIRTY_PUBLIC_DEMO=1): settings routes refuse writes, no secrets rendered, banner shown.

The console reads THIRTY_PUBLIC_DEMO at import and caches it in a module global, so these tests import a
fresh copy of dashboard_v2/app.py with the public-demo environment set, pointed at its own data folder.
"""
import importlib.util, os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Write endpoints that must all refuse with 403 "Locked in the public demo".
LOCKED_POSTS = [
    ("/api/setup", {"mode": "explore"}),
    ("/api/settings/imap", {"host": "imap.example", "user": "x"}),
    ("/api/settings/connector/slack", {"config": {"Bot token": "x"}}),
    ("/api/settings/mapping", {"mapping": []}),
    ("/api/settings/api-key/rotate", {}),
    ("/api/licence", {"key": "thirty1.whatever"}),
    ("/api/licence/remove", {}),
    ("/api/desktop", {"auto_update": False}),
    ("/api/workspace", {"org": "Hijack Inc"}),
    ("/api/plugins/active", {"id": "none"}),
    ("/api/plugins/local", {"enabled": True}),
    ("/api/plugins/local/test", {}),
    ("/api/demo/replay", {}),
    ("/api/demo/reset", {}),
]


@pytest.fixture(scope="module")
def public_console(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("thirty-public-demo"))
    env = dict(os.environ)
    os.environ.update({
        "VIGIL_DIR": d,
        "VIGIL_CONSOLE_ACTIONS": os.path.join(d, "actions.csv"),
        "VIGIL_CONSOLE_SETTINGS": os.path.join(d, "settings.json"),
        "VIGIL_CONSOLE_INTAKE": os.path.join(d, "intake.json"),
        "THIRTY_AGENT": "sample",
        "THIRTY_PUBLIC_DEMO": "1",
        # let init run so the public demo seeds its own sample data and completes setup on start
        "THIRTY_SKIP_RUNTIME_INIT": "0",
    })
    spec = importlib.util.spec_from_file_location("console_app_public", os.path.join(ROOT, "dashboard_v2", "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["console_app_public"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(env)
    mod.app.config["TESTING"] = True
    return mod


@pytest.fixture()
def pclient(public_console):
    return public_console.app.test_client()


def test_public_demo_flag_is_on(public_console):
    assert public_console.PUBLIC_DEMO is True


def test_setup_is_skipped_and_data_seeded(public_console, pclient):
    # first-run setup never gates the public demo: the home page renders straight away
    assert pclient.get("/").status_code == 200
    assert len(public_console.all_rows()) > 0, "sample data should be seeded on start"


@pytest.mark.parametrize("path,body", LOCKED_POSTS)
def test_write_routes_refuse(pclient, path, body):
    r = pclient.post(path, json=body)
    assert r.status_code == 403, f"{path} should be locked"
    assert r.get_json()["error"] == "Locked in the public demo"


def test_banner_on_every_page(pclient):
    for path in ("/", "/complaints", "/integrations", "/settings/plugins", "/settings/licence", "/demo"):
        html = pclient.get(path).get_data(as_text=True)
        assert "Public demo: invented sample data, sample agent, nothing is sent to the FDA" in html, path


def test_no_secret_fields_rendered_on_integrations(public_console, pclient):
    # the real API key must never reach the page in the public demo
    key = public_console.load_settings()["api_key"]
    html = pclient.get("/integrations").get_data(as_text=True)
    assert key not in html
    assert 'id="key"' not in html and 'type="password"' not in html
    assert "Locked in the public demo" in html


def test_settings_pages_show_locked_notice(pclient):
    for path in ("/settings/plugins", "/settings/licence", "/integrations", "/demo"):
        html = pclient.get(path).get_data(as_text=True)
        assert "Locked in the public demo" in html, path


def test_read_only_apis_still_work(pclient):
    assert pclient.get("/api/plugins").status_code == 200
    assert pclient.get("/api/licence").status_code == 200
    assert pclient.get("/api/state").status_code == 200

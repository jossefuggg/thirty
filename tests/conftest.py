import importlib.util, os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("THIRTY_AGENT", "sample")      # tests never need a model
os.environ.setdefault("THIRTY_SAMPLE_DELAY", "0")    # no fake latency in tests
os.environ.setdefault("THIRTY_DEMO_DELAY", "0")
from thirty import sample_data  # noqa: E402


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("thirty-data"))
    sample_data.seed(d)
    return d


@pytest.fixture(scope="session")
def console(data_dir):
    """The console Flask app, pointed at the sample data folder (env must be set before app.py is imported)."""
    os.environ["VIGIL_DIR"] = data_dir
    os.environ["VIGIL_CONSOLE_ACTIONS"] = os.path.join(data_dir, "actions.csv")
    os.environ["VIGIL_CONSOLE_SETTINGS"] = os.path.join(data_dir, "settings.json")
    os.environ["VIGIL_CONSOLE_INTAKE"] = os.path.join(data_dir, "intake.json")
    spec = importlib.util.spec_from_file_location("console_app", os.path.join(ROOT, "dashboard_v2", "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["console_app"] = mod
    spec.loader.exec_module(mod)
    mod.app.config["TESTING"] = True
    return mod


@pytest.fixture()
def client(console):
    return console.app.test_client()

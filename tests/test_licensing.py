"""Licence check: Ed25519 key files verified offline, states over time, API and settings."""
import datetime as dt, os, secrets, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty import licensing  # noqa: E402


@pytest.fixture()
def keypair(monkeypatch):
    sk = secrets.token_bytes(32)
    pk = licensing.publickey(sk).hex()
    monkeypatch.setenv("THIRTY_LICENCE_PUBKEY", pk)
    return sk.hex(), pk


def issue(sk, days, site="Harbor Medical Devices"):
    today = dt.date.today()
    return licensing.make_key({"id": "LIC-TEST1", "site": site, "org": "Harbor Medical", "issued": today.isoformat(),
                               "expires": (today + dt.timedelta(days=days)).isoformat(), "seats": None, "notes": ""}, sk)


def test_sign_and_verify_roundtrip(keypair):
    sk, pk = keypair
    key = issue(sk, 365)
    payload, err = licensing.parse(key)
    assert err is None and payload["site"] == "Harbor Medical Devices"
    tampered = key[:-6] + ("AAAAAA" if not key.endswith("AAAAAA") else "BBBBBB")
    assert licensing.parse(tampered)[1] == "signature does not match"
    parts = key.split("."); parts[1] = licensing._b64e(licensing.canonical({"id": "X", "site": "Y", "expires": "2099-01-01"}))
    assert licensing.parse(".".join(parts))[1] == "signature does not match"
    assert licensing.parse("hello")[1] == "not a Thirty licence key"
    other = licensing.publickey(secrets.token_bytes(32)).hex()
    os.environ["THIRTY_LICENCE_PUBKEY"] = other
    assert licensing.parse(key)[1] == "signature does not match"


def test_states_over_time(tmp_path, keypair):
    sk, _ = keypair
    chk = licensing.OfflineKeyFile(str(tmp_path / "licence.key"))
    assert chk.status()["state"] == "evaluation"
    chk.install(issue(sk, 365)); st = chk.status()
    assert st["state"] == "licensed" and st["days_left"] == 365 and "Harbor" in st["label"]
    chk.install(issue(sk, 20)); assert chk.status()["state"] == "expiring"
    chk.install(issue(sk, -3)); assert chk.status()["state"] == "grace"
    chk.install(issue(sk, -40)); assert chk.status()["state"] == "expired"
    with pytest.raises(ValueError):
        chk.install("nonsense")
    chk.remove(); assert chk.status()["state"] == "evaluation"


def test_no_public_key_means_unverified(tmp_path, monkeypatch):
    monkeypatch.delenv("THIRTY_LICENCE_PUBKEY", raising=False); monkeypatch.setattr(licensing, "PUBLIC_KEY", "")
    key = issue(secrets.token_bytes(32).hex(), 100)
    chk = licensing.OfflineKeyFile(str(tmp_path / "l.key")); chk.install(key)
    st = chk.status()
    assert st["state"] == "invalid" and "no public key" in st["reason"]


def test_licence_api_and_desktop_settings(client, console, keypair):
    sk, _ = keypair
    html = client.get("/").get_data(as_text=True)
    assert "Evaluation" in html
    assert client.get("/settings/licence").status_code == 200
    assert client.post("/api/licence", json={"key": "bad"}).status_code == 400
    r = client.post("/api/licence", json={"key": issue(sk, 200)})
    assert r.status_code == 200 and r.get_json()["licence"]["state"] == "licensed"
    assert "Evaluation" not in client.get("/").get_data(as_text=True)
    assert client.get("/api/health").get_json()["licence"] == "licensed"
    assert client.post("/api/licence/remove").get_json()["licence"]["state"] == "evaluation"
    assert client.get("/api/licence").get_json()["desktop"]["auto_update"] is False
    assert client.post("/api/desktop", json={"auto_update": True}).get_json()["auto_update"] is True
    import json
    assert json.load(open(os.path.join(console.VIGIL_DIR, "desktop.json")))["auto_update"] is True
    client.post("/api/desktop", json={"auto_update": False})
    r = client.post("/api/workspace", json={"org": "Harbor Medical Devices", "unit": "RA"})
    assert r.status_code == 200 and "Harbor Medical Devices" in client.get("/").get_data(as_text=True)
    client.post("/api/workspace", json={"org": "Northwind Medical", "unit": "Quality"})

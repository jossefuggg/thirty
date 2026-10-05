#!/usr/bin/env python3
"""Screenshot every console screen with headless Chromium into docs/screenshots/.

Starts the console on a free port against a temporary data folder filled with the invented sample rows
(tests/sample_data.py), so the shots are reproducible and never contain real data.

    pip install -r requirements-dev.txt && playwright install chromium
    python3 tools/screenshots.py [--out docs/screenshots] [--keep]
"""
import argparse, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from thirty import sample_data  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def wait_for(url, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "screenshots"))
    ap.add_argument("--keep", action="store_true", help="keep the temporary data folder")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    data = tempfile.mkdtemp(prefix="thirty-shots-")
    ids = sample_data.seed(data)
    port = free_port()
    env = {**os.environ, "VIGIL_DIR": data, "VIGIL_CONSOLE_PORT": str(port),
           "VIGIL_CONSOLE_ACTIONS": os.path.join(data, "actions.csv"), "VIGIL_CONSOLE_SETTINGS": os.path.join(data, "settings.json"),
           "VIGIL_CONSOLE_INTAKE": os.path.join(data, "intake.json"), "THIRTY_AGENT": "sample", "THIRTY_SAMPLE_DELAY": "0.6", "THIRTY_DEMO_DELAY": "1.5"}
    env.pop("VIGIL_LLM_BASE", None)
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=os.path.join(ROOT, "dashboard_v2"), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        if not wait_for(base + "/api/health"):
            sys.exit("console did not start")
        os.makedirs(a.out, exist_ok=True)
        shots = [("01-command-center", "/"), ("02-complaints", "/complaints"), ("03-complaint-detail", f"/complaint/{ids[0]}"),
                 ("04-compliance-clock", "/clock"), ("05-trends", "/trends"), ("06-audit-log", "/audit"), ("07-intake-inbox", "/intake"),
                 ("08-integrations", "/integrations"), ("09-demo-control", "/demo"), ("10-not-found", "/complaint/missing-id"),
                 ("18-plugins", "/settings/plugins")]
        with sync_playwright() as p:
            exe = os.environ.get("THIRTY_CHROMIUM")  # optional: a Chromium build that differs from Playwright's own
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, reduced_motion="reduce")
            page = ctx.new_page()
            for name, path in shots:
                page.goto(base + path, wait_until="networkidle")
                page.wait_for_timeout(1200)  # pages poll their JSON once more after load
                page.screenshot(path=os.path.join(a.out, name + ".png"), full_page=True)
                print("wrote", name)
            # detail drawer open from the Command Center
            page.goto(base + "/", wait_until="networkidle"); page.wait_for_timeout(1000)
            page.click("#feed [data-open]"); page.wait_for_timeout(800)
            page.screenshot(path=os.path.join(a.out, "11-detail-drawer.png"), full_page=False); print("wrote 11-detail-drawer")
            # reviewer modal (the approve flow) from the queue
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
            page.click("#queue [data-q='approve']"); page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(a.out, "12-reviewer-modal.png"), full_page=False); print("wrote 12-reviewer-modal")
            page.keyboard.press("Escape")
            # dark mode
            page.click("#theme"); page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(a.out, "13-command-center-dark.png"), full_page=True); print("wrote 13-command-center-dark")
            page.goto(base + f"/complaint/{ids[1]}", wait_until="networkidle"); page.wait_for_timeout(1000)
            page.screenshot(path=os.path.join(a.out, "14-complaint-detail-dark.png"), full_page=True); print("wrote 14-complaint-detail-dark")
            page.click("#theme"); page.wait_for_timeout(300)
            # demo replay running: loading states on the Demo page and the Command Center feed
            page.goto(base + "/demo", wait_until="networkidle"); page.click("#b-replay"); page.wait_for_timeout(2500)
            page.screenshot(path=os.path.join(a.out, "15-demo-replay-running.png"), full_page=True); print("wrote 15-demo-replay-running")
            page.goto(base + "/", wait_until="networkidle"); page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(a.out, "16-command-center-replay.png"), full_page=False); print("wrote 16-command-center-replay")
            # error state: stop the console while the Command Center keeps polling
            proc.terminate(); proc.wait(5)
            page.wait_for_timeout(4500)
            page.screenshot(path=os.path.join(a.out, "17-command-center-offline.png"), full_page=False); print("wrote 17-command-center-offline")
            browser.close()
    finally:
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
        if a.keep: print("data kept in", data)
        else: shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Freeze the Thirty backend with PyInstaller into desktop/build/backend/ (what Electron spawns).

    pip install -r requirements.txt pyinstaller
    python3 tools/build_backend.py            # -> desktop/build/backend/thirty-backend[.exe]
    python3 tools/build_backend.py --check    # also start it and hit /api/health

Run on each target OS (PyInstaller does not cross-compile); the release workflow does this per runner."""
import argparse, os, shutil, socket, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = os.path.join(ROOT, "desktop")
OUT = os.path.join(DESKTOP, "build", "backend")


def build():
    shutil.rmtree(OUT, ignore_errors=True)
    work = os.path.join(DESKTOP, "build", "pyinstaller-work")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", os.path.join(DESKTOP, "build"),
           "--workpath", work, os.path.join(DESKTOP, "backend.spec")]
    print("$", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)
    shutil.rmtree(work, ignore_errors=True)
    exe = os.path.join(OUT, "thirty-backend" + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(exe):
        sys.exit(f"build failed: {exe} missing")
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs) / 1e6
    print(f"backend: {exe} ({size:.0f} MB)")
    return exe


def check(exe):
    """Boot the frozen backend on a fresh data folder, complete first-run setup through the API (explore mode),
    and confirm the console shows the sample data. Never reads the live process's stdout: that blocks."""
    import json
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    data = os.path.join(DESKTOP, "build", "check-data")
    shutil.rmtree(data, ignore_errors=True)
    env = {**os.environ, "VIGIL_DIR": data, "VIGIL_CONSOLE_PORT": str(port), "THIRTY_SAMPLE_DELAY": "0"}
    env.pop("VIGIL_LLM_BASE", None)
    log = open(os.path.join(DESKTOP, "build", "check.log"), "w+", encoding="utf-8", errors="replace")
    p = subprocess.Popen([exe], env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"

    def get(path, timeout=3):
        return urllib.request.urlopen(base + path, timeout=timeout).read().decode()

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=30).read().decode()

    try:
        end, health, setup_done = time.time() + 90, None, False
        while time.time() < end and p.poll() is None:
            try:
                health = get("/api/health", timeout=1)
                assert "Thirty" in get("/setup"), "setup page missing"
                if not setup_done:
                    post("/api/setup", {"mode": "explore", "agent": "sample"}); setup_done = True
                html = get("/")
                assert "Thirty" in html and "Sample data" in html, "console without sample data"
                pdfs = os.listdir(os.path.join(data, "reports"))
                assert pdfs, "no PDFs drafted"
                print(f"check ok: /api/health -> {health[:80]}… · {len(pdfs)} PDFs drafted · data in {data}", flush=True)
                return True
            except Exception:
                time.sleep(0.5)
        p.terminate()
        try: p.wait(5)
        except Exception: p.kill()
        log.seek(0); print(log.read()[-3000:], flush=True)
        sys.exit("check failed: backend did not answer or setup/console check failed")
    finally:
        p.terminate()
        try: p.wait(5)
        except Exception: p.kill()
        log.close()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); a = ap.parse_args()
    exe = build()
    if a.check:
        check(exe)

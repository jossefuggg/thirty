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
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    data = os.path.join(DESKTOP, "build", "check-data")
    shutil.rmtree(data, ignore_errors=True)
    env = {**os.environ, "VIGIL_DIR": data, "VIGIL_CONSOLE_PORT": str(port), "THIRTY_SAMPLE_DELAY": "0"}
    env.pop("VIGIL_LLM_BASE", None)
    p = subprocess.Popen([exe], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        end = time.time() + 60
        while time.time() < end:
            try:
                h = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read().decode()
                html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).read().decode()
                assert "Thirty" in html and "Sample data" in html
                pdfs = os.listdir(os.path.join(data, "reports"))
                print(f"check ok: /api/health -> {h[:80]}… · {len(pdfs)} PDFs drafted · data in {data}")
                return True
            except Exception:
                if p.poll() is not None:
                    break
                time.sleep(0.5)
        print(p.stdout.read()[-3000:])
        sys.exit("check failed: backend did not answer")
    finally:
        p.terminate()
        try: p.wait(5)
        except Exception: p.kill()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); a = ap.parse_args()
    exe = build()
    if a.check:
        check(exe)

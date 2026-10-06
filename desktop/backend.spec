# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Thirty backend (the Flask console + pipeline), built by tools/build_backend.py.

One-folder build: desktop/build/backend/thirty-backend[.exe] plus _internal/. Data files keep the
repository layout under _MEIPASS so dashboard_v2/app.py, vigil.py and the thirty package find each other
exactly as in development (see CODE_DIR in app.py and thirty/config.py)."""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "dashboard_v2", "templates"), os.path.join("dashboard_v2", "templates")),
    (os.path.join(ROOT, "dashboard_v2", "static"), os.path.join("dashboard_v2", "static")),
    (os.path.join(ROOT, "thirty", "plugins", "builtin"), os.path.join("thirty", "plugins", "builtin")),
    (os.path.join(ROOT, "thirty", "fonts"), os.path.join("thirty", "fonts")),
    (os.path.join(ROOT, "vigil.py"), "."),
    (os.path.join(ROOT, "intake.py"), "."),
    (os.path.join(ROOT, "demo_set.csv"), "."),
    (os.path.join(ROOT, "docs", "PLUGINS.md"), "docs"),
    (os.path.join(ROOT, "examples", "plugins"), os.path.join("examples", "plugins")),
]

a = Analysis(
    [os.path.join(ROOT, "dashboard_v2", "app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["thirty", "thirty.config", "thirty.sample_data", "thirty.plugins", "thirty.agents", "thirty.agents.base",
                   "thirty.agents.sample", "thirty.agents.local_model", "thirty.licensing", "thirty.setup", "flask", "jinja2", "fpdf", "requests",
                   "vaderSentiment", "vaderSentiment.vaderSentiment", "rapidfuzz"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "numpy", "PIL", "playwright", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="thirty-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # stdout/stderr go to the Electron log
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="backend")

// Thirty desktop: an Electron window around the Thirty console, which runs as a local Python backend.
// Nothing here talks to the network; the backend listens on 127.0.0.1 only and data lives in the OS
// app-data folder. Auto-update (Phase 7) is off unless the user switches it on in Settings.
"use strict";
const { app, BrowserWindow, Menu, dialog, shell, nativeImage } = require("electron");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

const PRODUCT = "Thirty";
const PACKAGED = app.isPackaged;
const REPO = path.resolve(__dirname, "..");
const DATA_DIR = process.env.VIGIL_DIR || path.join(app.getPath("userData"), "data");
const LOG_FILE = path.join(app.getPath("userData"), "thirty.log");

app.setName(PRODUCT);
let backend = null, win = null, port = 0, logStream = null, quitting = false;

function log(line) {
  const text = `[${new Date().toISOString()}] ${line}\n`;
  try { if (!logStream) logStream = fs.createWriteStream(LOG_FILE, { flags: "a" }); logStream.write(text); } catch (e) { /* ignore */ }
  if (!PACKAGED) process.stdout.write(text);
}

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer(); s.unref();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

function backendCommand() {
  if (PACKAGED) {
    const exe = path.join(process.resourcesPath, "backend", process.platform === "win32" ? "thirty-backend.exe" : "thirty-backend");
    return { cmd: exe, args: [], cwd: path.dirname(exe) };
  }
  // development: the console straight from the repository (python3, or python on Windows)
  const py = process.env.THIRTY_PYTHON || (process.platform === "win32" ? "python" : "python3");
  return { cmd: py, args: [path.join(REPO, "dashboard_v2", "app.py")], cwd: path.join(REPO, "dashboard_v2") };
}

function startBackend() {
  const { cmd, args, cwd } = backendCommand();
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const env = { ...process.env, VIGIL_DIR: DATA_DIR, VIGIL_CONSOLE_PORT: String(port), PYTHONUNBUFFERED: "1", PYTHONUTF8: "1", THIRTY_DESKTOP: "1",
                THIRTY_APP_VERSION: app.getVersion() };
  log(`starting backend: ${cmd} ${args.join(" ")} (port ${port}, data ${DATA_DIR})`);
  backend = spawn(cmd, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  backend.stdout.on("data", (d) => log(`backend: ${String(d).trimEnd()}`));
  backend.stderr.on("data", (d) => log(`backend! ${String(d).trimEnd()}`));
  backend.on("exit", (code, signal) => {
    log(`backend exited (${code ?? signal})`);
    backend = null;
    if (!quitting && win && !win.isDestroyed()) showError(`The Thirty backend stopped (exit ${code ?? signal}).`);
  });
}

function waitForBackend(timeoutMs) {
  const base = `http://127.0.0.1:${port}`;
  return new Promise((resolve, reject) => {
    const started = Date.now();
    (function poll() {
      const req = http.get(`${base}/api/health`, { timeout: 1000 }, (res) => { res.resume(); res.statusCode === 200 ? resolve(base) : retry(); });
      req.on("error", retry); req.on("timeout", () => { req.destroy(); retry(); });
      function retry() {
        if (!backend) return reject(new Error("backend process exited"));
        if (Date.now() - started > timeoutMs) return reject(new Error("backend did not answer in time"));
        setTimeout(poll, 300);
      }
    })();
  });
}

function stopBackend() {
  if (!backend) return;
  log("stopping backend");
  try { process.platform === "win32" ? spawnSync("taskkill", ["/pid", String(backend.pid), "/t", "/f"]) : backend.kill("SIGTERM"); } catch (e) { /* ignore */ }
  backend = null;
}

function tailLog(lines) {
  try { return fs.readFileSync(LOG_FILE, "utf8").trim().split("\n").slice(-lines).join("\n"); } catch (e) { return ""; }
}

function showError(message) {
  const html = fs.readFileSync(path.join(__dirname, "error.html"), "utf8")
    .replace("{{message}}", escapeHtml(message)).replace("{{log}}", escapeHtml(tailLog(40))).replace("{{logfile}}", escapeHtml(LOG_FILE));
  win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1024, minHeight: 640, title: PRODUCT, show: false,
    backgroundColor: "#F7F5F0",
    icon: process.platform === "linux" ? path.join(__dirname, "build", "icon.png") : undefined,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false },
  });
  win.once("ready-to-show", () => win.show());
  win.on("page-title-updated", (e) => e.preventDefault());  // always "Thirty"
  win.webContents.setWindowOpenHandler(({ url }) => {  // PDFs and docs open in the window; nothing else leaves it
    if (url.startsWith(`http://127.0.0.1:${port}/`)) return { action: "allow" };
    return { action: "deny" };
  });
  win.loadFile(path.join(__dirname, "loading.html"));
}

function about() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "build", "icon.png"));
  dialog.showMessageBox(win, {
    type: "none", icon: icon.isEmpty() ? undefined : icon.resize({ width: 64 }), title: `About ${PRODUCT}`, message: PRODUCT,
    detail: `Medical device complaint reporting. Thirty drafts; a human files.\n\n` +
      `Version ${app.getVersion()} · Electron ${process.versions.electron}\n` +
      `Data folder: ${DATA_DIR}\nLog: ${LOG_FILE}\n\n0 bytes to cloud AI: the agent runs on this machine.`,
    buttons: ["OK", "Open data folder"], defaultId: 0,
  }).then((r) => { if (r.response === 1) shell.openPath(DATA_DIR); });
}

function buildMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac ? [{ label: PRODUCT, submenu: [
      { label: `About ${PRODUCT}`, click: about }, { type: "separator" },
      { label: "Settings…", accelerator: "CmdOrCtrl+,", click: () => win && win.loadURL(`http://127.0.0.1:${port}/settings/plugins`) },
      { type: "separator" }, { role: "services" }, { type: "separator" }, { role: "hide" }, { role: "hideOthers" }, { role: "unhide" }, { type: "separator" }, { role: "quit" }] }] : []),
    { label: "File", submenu: [
      { label: "Command Center", accelerator: "CmdOrCtrl+1", click: () => win && win.loadURL(`http://127.0.0.1:${port}/`) },
      { label: "Complaints", accelerator: "CmdOrCtrl+2", click: () => win && win.loadURL(`http://127.0.0.1:${port}/complaints`) },
      { label: "Compliance Clock", accelerator: "CmdOrCtrl+3", click: () => win && win.loadURL(`http://127.0.0.1:${port}/clock`) },
      { type: "separator" },
      { label: "Open data folder", click: () => shell.openPath(DATA_DIR) },
      { label: "Open log file", click: () => shell.openPath(LOG_FILE) },
      { type: "separator" },
      ...(isMac ? [{ role: "close" }] : [{ label: "Settings…", accelerator: "CmdOrCtrl+,", click: () => win && win.loadURL(`http://127.0.0.1:${port}/settings/plugins`) }, { type: "separator" }, { role: "quit" }]),
    ] },
    { label: "Edit", submenu: [{ role: "undo" }, { role: "redo" }, { type: "separator" }, { role: "cut" }, { role: "copy" }, { role: "paste" }, { role: "selectAll" }] },
    { label: "View", submenu: [{ role: "reload" }, { type: "separator" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" }, { role: "togglefullscreen" },
      ...(PACKAGED ? [] : [{ type: "separator" }, { role: "toggleDevTools" }])] },
    { label: "Window", submenu: [{ role: "minimize" }, { role: "zoom" }, ...(isMac ? [{ type: "separator" }, { role: "front" }] : [{ role: "close" }])] },
    { label: "Help", submenu: [
      { label: "Documentation", click: () => shell.openPath(PACKAGED ? path.join(process.resourcesPath, "backend", "_internal", "docs") : path.join(REPO, "docs")) },
      { label: "Check for updates…", click: () => require("./updater").checkNow(win) },
      { type: "separator" }, ...(isMac ? [] : [{ label: `About ${PRODUCT}`, click: about }]),
    ] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    buildMenu();
    createWindow();
    try {
      port = await freePort();
      startBackend();
      const base = await waitForBackend(60000);
      log(`backend ready at ${base}`);
      await win.loadURL(base + "/");
      require("./updater").init({ win, dataDir: DATA_DIR, log });
      if (process.env.THIRTY_SCREENSHOT) {  // used by the repository's own smoke test under Xvfb
        setTimeout(async () => { const img = await win.webContents.capturePage(); fs.writeFileSync(process.env.THIRTY_SCREENSHOT, img.toPNG()); log("screenshot written"); app.quit(); }, 2500);
      }
    } catch (e) {
      log(`startup failed: ${e.message}`);
      showError(e.message);
    }
  });
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) { createWindow(); if (port && backend) win.loadURL(`http://127.0.0.1:${port}/`); } });
  app.on("before-quit", () => { quitting = true; stopBackend(); });
}

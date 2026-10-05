// Auto-update against GitHub Releases (electron-updater). OFF by default: it only runs when the user
// switches it on in Settings, which the backend records as {"auto_update": true} in <data>/desktop.json.
// Nothing is contacted until then. "Check for updates…" in the Help menu always asks first.
"use strict";
const fs = require("fs");
const path = require("path");
const { dialog } = require("electron");

let state = { win: null, dataDir: "", log: () => {}, timer: null, updater: null };

function settings() {
  try { return JSON.parse(fs.readFileSync(path.join(state.dataDir, "desktop.json"), "utf8")); } catch (e) { return {}; }
}

function loadUpdater() {
  if (state.updater) return state.updater;
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.logger = { info: (m) => state.log(`updater: ${m}`), warn: (m) => state.log(`updater: ${m}`), error: (m) => state.log(`updater! ${m}`), debug: () => {} };
    autoUpdater.on("update-available", (info) => {
      dialog.showMessageBox(state.win, { type: "info", title: "Update available", message: `Thirty ${info.version} is available.`,
        detail: "Download it now? It installs the next time Thirty quits.", buttons: ["Download", "Not now"], defaultId: 0 })
        .then((r) => { if (r.response === 0) autoUpdater.downloadUpdate(); });
    });
    autoUpdater.on("update-downloaded", () => {
      dialog.showMessageBox(state.win, { type: "info", title: "Update ready", message: "The update will install when Thirty quits.", buttons: ["OK"] });
    });
    autoUpdater.on("error", (e) => state.log(`updater! ${e && e.message}`));
    state.updater = autoUpdater;
  } catch (e) {
    state.log(`updater unavailable: ${e.message}`);
  }
  return state.updater;
}

function check(interactive) {
  const u = loadUpdater();
  if (!u) { if (interactive) dialog.showMessageBox(state.win, { type: "info", message: "Updates are not available in this build." }); return; }
  if (!require("electron").app.isPackaged) { if (interactive) dialog.showMessageBox(state.win, { type: "info", message: "Updates only work in the installed app." }); return; }
  u.checkForUpdates().then((r) => {
    if (interactive && r && r.updateInfo && !r.isUpdateAvailable) dialog.showMessageBox(state.win, { type: "info", message: "Thirty is up to date." });
  }).catch((e) => { state.log(`updater! ${e.message}`); if (interactive) dialog.showMessageBox(state.win, { type: "warning", message: "Could not check for updates.", detail: e.message }); });
}

function tick() {
  const s = settings();
  if (s.auto_update === true) { state.log("auto-update is on: checking GitHub Releases"); check(false); }
}

module.exports = {
  init(opts) {
    state = { ...state, ...opts };
    // first check 2 minutes after start, then every 6 hours; each tick re-reads the setting, so switching it
    // off in Settings stops the checks without a restart.
    state.timer = setInterval(tick, 6 * 60 * 60 * 1000);
    setTimeout(tick, 2 * 60 * 1000);
  },
  checkNow(win) { state.win = win || state.win; check(true); },
};

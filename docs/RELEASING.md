# Releasing Thirty

How installers are built, what you need to add for signing, how updates and licences work.

## 1. Cut a release

```bash
python3 tools/set_version.py 1.2.0        # thirty/__init__.py, pyproject.toml, desktop/package.json
git commit -am "Thirty 1.2.0" && git tag v1.2.0 && git push && git push --tags
```

Pushing a `v*` tag runs `.github/workflows/release.yml`: three runners (macOS 14, Windows 2022,
Ubuntu 22.04) each run the tests, freeze the backend with PyInstaller, build the Electron app with
`electron-builder`, and upload to a **draft GitHub Release** for that tag. Review the draft, then publish
it. The CI workflow (`ci.yml`) runs the tests and a backend boot on every push.

Artifacts per platform:

| OS | files |
|---|---|
| macOS | `Thirty-1.2.0-mac-x64.dmg`, `…-arm64.dmg`, the `.zip` pairs (used by the updater), `latest-mac.yml` |
| Windows | `Thirty-1.2.0-win-x64.exe` (NSIS installer), `latest.yml`, `.blockmap` |
| Linux | `Thirty-1.2.0-linux-x64.AppImage`, `.deb`, `latest-linux.yml` |

Unsigned builds work but users see OS warnings: macOS Gatekeeper ("cannot be opened because the
developer cannot be verified" → right-click → Open), Windows SmartScreen ("More info → Run anyway").
Auto-update on macOS **requires a signed app**; unsigned macOS builds cannot self-update.

Build locally (one OS at a time; PyInstaller does not cross-compile):

```bash
pip install -r requirements.txt pyinstaller
cd desktop && npm ci && npm run dist          # -> desktop/dist/
```

## 2. Signing: what to add as repository secrets

All optional. Missing secrets = unsigned build (the workflow says so in its log and carries on).

### macOS (Developer ID + notarisation)
You need an Apple Developer Program membership ($99/year).

| secret | value |
|---|---|
| `MAC_CSC_LINK` | the **Developer ID Application** certificate exported from Keychain as `.p12`, base64-encoded (`base64 -i cert.p12 | pbcopy`) |
| `MAC_CSC_KEY_PASSWORD` | the password you set when exporting the `.p12` |
| `APPLE_ID` | the Apple ID email of the developer account |
| `APPLE_APP_SPECIFIC_PASSWORD` | an app-specific password generated at appleid.apple.com |
| `APPLE_TEAM_ID` | the 10-character Team ID from the developer account |

With the first two, the app is signed; with all five, it is also notarised (required for a quiet first
launch on macOS 10.15+). `desktop/build/entitlements.mac.plist` already allows the backend sidecar.

### Windows (Authenticode)
| secret | value |
|---|---|
| `WIN_CSC_LINK` | a code-signing certificate (`.pfx`), base64-encoded |
| `WIN_CSC_KEY_PASSWORD` | its password |

An OV certificate removes most SmartScreen warnings after reputation builds; an EV certificate removes
them immediately. (EV certificates on hardware tokens cannot be used from GitHub-hosted runners; use
a cloud signing service such as Azure Trusted Signing and swap the `win` section of
`desktop/electron-builder.yml` for its `azureSignOptions`.)

### Linux
Nothing to sign. Optionally publish a GPG-signed checksum file.

### GitHub
`GITHUB_TOKEN` is provided automatically; the workflow has `contents: write` to create the release.
`publish.owner/repo` in `desktop/electron-builder.yml` must point at the repository that hosts the
releases (currently `jossefuggg/vigil`; change it if the repo is renamed).

## 3. Auto-update (Phase 7 scaffold)

* Implemented with `electron-updater` in `desktop/updater.js`, reading the `latest*.yml` files that
  `electron-builder --publish always` uploads to each GitHub Release.
* **Off by default.** The user switches it on under **Settings → Licence & updates → Updates**. The
  console writes `<data>/desktop.json` `{"auto_update": true}`; the Electron shell re-reads it on each
  check (two minutes after start, then every six hours), so switching off needs no restart.
* When on, Thirty asks before downloading; the update installs when the app quits. **Help → Check for
  updates…** always asks first and works regardless of the setting.
* Only the GitHub Releases API is contacted, and only when the setting is on or the menu item is used.
* To test: publish a release with a higher version than the installed app, switch the setting on, use
  Help → Check for updates…

## 4. Licences (Phase 7 scaffold)

Per-site annual licences, verified offline with an Ed25519 signature. No payment provider.

One-time setup (you, not CI):

```bash
python3 tools/make_licence.py keygen          # writes ~/.thirty/licence-secret.key (keep it private, back it up)
# prints:  PUBLIC_KEY = '…'   -> paste into thirty/licensing.py (PUBLIC_KEY = "…") and commit
```

Until `PUBLIC_KEY` is set, Thirty accepts no key ("cannot verify: no public key configured") and runs in
**Evaluation**. Builds made before the key is set cannot verify keys issued later.

Issue a key for a customer:

```bash
python3 tools/make_licence.py issue --site "Harbor Medical Devices" --org "Harbor Medical" --days 365 --out harbor.key
python3 tools/make_licence.py verify harbor.key
```

The customer pastes the key (or chooses the file) under **Settings → Licence & updates**. It is stored
as `<data>/licence.key` and never leaves the machine. States: **Licensed**, **Renews soon** (≤ 30 days),
**Grace period** (14 days after expiry), **Expired**, **Evaluation** (no key), **Invalid key**.

What the scaffold does *not* do yet (decisions for you): enforce anything beyond the "Evaluation"
label (e.g. block approvals after expiry), tie keys to a machine, count seats, or collect payment.
The `thirty.licensing.LicenseCheck` interface is the seam for a different implementation (online
check, licence server) later.

## 5. Secrets hygiene

Never commit: the licence secret key, certificates, `.p12`/`.pfx` files, app-specific passwords,
`secrets.env`. The repository `.gitignore` covers `*.env` and build output; keep certificates outside
the repository entirely and only in GitHub secrets.

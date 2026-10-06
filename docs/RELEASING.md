# Releasing Thirty

How installers are built, what you need to add for signing, how updates and licences work.

## 1. Cut a release

```bash
python3 tools/set_version.py 1.2.0        # thirty/__init__.py, pyproject.toml, desktop/package.json
git commit -am "Thirty 1.2.0" && git tag v1.2.0 && git push && git push --tags
```

Pushing a `v*` tag runs `.github/workflows/release.yml`: three runners (macOS 14, Windows 2022,
Ubuntu 22.04) each run the tests, freeze the backend with PyInstaller, build the Electron app with
`electron-builder`, and attach the files to the GitHub Release `v<version>`: created as a draft when it
does not exist yet, reused when you created it first (draft, pre-release or published). Review, then
publish. The workflow can also be started by hand (Actions → Release → Run workflow) on `main`; it then
builds the version stamped in the repository. The CI workflow (`ci.yml`) runs the tests and a backend
boot on every push.

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
releases (`jossefuggg/thirty`; change it if the repo moves).

## 3. Auto-update (Phase 7 scaffold)

* Implemented with `electron-updater` in `desktop/updater.js`, reading the `latest*.yml` files that
  `electron-builder --publish always` uploads to each GitHub Release.
* **On by default.** The app asks GitHub Releases for a newer version two minutes after start and every
  six hours, and asks the user before downloading. Switching it off under **Settings → Licence & updates →
  Updates** writes `<data>/desktop.json` `{"auto_update": false}`; the Electron shell re-reads it on each
  tick. Unsigned macOS builds cannot replace themselves (macOS requires a code-signed app), so on macOS the
  dialog opens the download page until `MAC_CSC_LINK` and notarisation are set up.
* When on, Thirty asks before downloading; the update installs when the app quits. **Help → Check for
  updates…** always asks first and works regardless of the setting.
* Only the GitHub Releases API is contacted (the `latest*.yml` manifest), and only while the setting is on or when the menu item is used.
* To test: publish a release with a higher version than the installed app, switch the setting on, use
  Help → Check for updates…

## 4. Licences (Phase 7 scaffold)

Per-site annual licences, verified offline with an Ed25519 signature. No payment provider.

The keypair exists: the public key is in `thirty/licensing.py` (`PUBLIC_KEY`), the **secret key is the
file `thirty-licence-secret.key` handed to the owner outside the repository**. Store it in a password
manager and at `~/.thirty/licence-secret.key` (mode 0600) on the machine that issues keys. If it is ever
lost or leaked, run `python3 tools/make_licence.py keygen` again, replace `PUBLIC_KEY`, ship a new
release, and reissue every customer key (old keys stop verifying).

Issue keys (any length; `--days N` or a fixed `--expires YYYY-MM-DD`):

```bash
python3 tools/make_licence.py issue --site "Harbor Medical Devices" --org "Harbor Medical" --days 365 --out harbor.key
python3 tools/make_licence.py issue --site "Harbor Medical Devices" --demo --days 14 --out harbor-demo.key   # demo
python3 tools/make_licence.py issue --site "Harbor Medical Devices" --expires 2027-03-31                     # end date
python3 tools/make_licence.py verify harbor.key
```

Demo keys (`--demo`) show as "Demo for <site> · N days left", turn to "renews soon" at 7 days, and have
**no grace period**: the day after they end, reviews are read-only. Site licences get 14 days of grace.

The customer pastes the key (or chooses the file) under **Settings → Licence & updates**. It is stored
as `<data>/licence.key` and never leaves the machine. States: **Licensed**, **Renews soon** (≤ 30 days),
**Grace period** (14 days after expiry), **Expired**, **Evaluation** (no key), **Invalid key**.

Policy (decided): **Evaluation runs fully** (demos and trials need every screen). After expiry there are
14 days of grace with a banner; past that, reviews are **read-only** (approve / request info / undo
answer 403 with a message pointing at the licence screen) until a renewed key is installed. Everything
else keeps working so nothing is lost. Not done: machine binding, seat counting, payment.
The `thirty.licensing.LicenseCheck` interface is the seam for a different implementation (online
check, licence server) later.

## 5. Secrets hygiene

Never commit: the licence secret key, certificates, `.p12`/`.pfx` files, app-specific passwords,
`secrets.env`. The repository `.gitignore` covers `*.env` and build output; keep certificates outside
the repository entirely and only in GitHub secrets.

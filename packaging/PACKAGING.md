# Making the installers

You get:

| Computer | What you build | File |
|---|---|---|
| Windows 10/11 (64-bit) | a normal setup wizard | `dist/installer/EKsImageWise-Setup-1.0.0.exe` |
| Mac with Apple silicon (M1 or newer) | a disk image: drag the app onto Applications | `dist/EKsImageWise-1.0.0-arm64.dmg` |
| Mac with an Intel chip | the same, built for Intel | `dist/EKsImageWise-1.0.0-x64.dmg` |

An installer can only be built **on its own kind of computer** (a Windows installer on Windows,
a Mac one on a Mac). There are two ways to get all three:

## Way 1 (easiest): let GitHub build them in the cloud

1. Put this project folder in a GitHub repository (a free account is enough; public repositories get
   free build time, private ones use your monthly allowance and Mac minutes count extra).
2. Open the repository's **Actions** tab, choose **Build installers**, press **Run workflow**.
3. After roughly 15 to 30 minutes the three installers appear on the run page under **Artifacts**.
4. To publish a release, push a tag such as `v1.0.0`; the workflow then attaches the installers to a
   GitHub release you can share a link to.

The recipe is `.github/workflows/build-installers.yml`. It uses Python 3.12 and the runners
`windows-latest`, `macos-15` (Apple silicon) and `macos-15-intel` (Intel). GitHub renames runners from
time to time; if a Mac job says its runner doesn't exist, update the `runner:` name from GitHub's list.

## Way 2: build on your own computers

**Windows** (your PC): install Python 3.12 from python.org (tick *Add Python to PATH*) and
[Inno Setup 6](https://jrsoftware.org/isdl.php), then double-click `packaging\build_windows.bat`.
The installer appears in `dist\installer`.

**Mac** (for example your daughter's): install Python 3.12 (python.org, or `brew install python@3.12`),
open Terminal in the project folder and run `./packaging/build_mac.sh`. The `.dmg` appears in `dist`.
(Optional: `brew install create-dmg` gives a nicer disk-image window.)

Both scripts create a private build folder (`.venv-build`), install what is needed, and call
`python packaging/build.py --models`. Useful options (add after the script name):

* `--models` is already on: it puts the background-removal models inside the installer, so the app
  works offline from the first run. It makes the installer about 200 MB bigger; remove it from the
  script to keep the installer smaller (the app then downloads a model the first time it is used).
* `--all-models` also includes the "general purpose" model.
* `--no-installer` stops after the app itself (`dist/EKsImageWise/` or `dist/EKsImageWise.app`).
* `--dry-run` shows what would happen without doing it.

Expect the first build to take 10 to 20 minutes and the installers to be roughly 400 to 600 MB.

## Your icon and splash screen

Put `Icon_1.png` (a square PNG with a transparent background, 512 x 512 or bigger) and `splash.png` in the
project folder next to `main.py`. The build turns `Icon_1.png` into the Windows `.ico` and the Mac `.icns`
automatically (installer icon, app icon, taskbar / Dock icon), and includes both files in the installed app.
Without them the app uses a built-in icon and starts without a splash screen.

## Version number

Edit `VERSION` in `imagewise/version.py`. The installers, the window "About" box and the
file names all follow it.

## Where things go on the customer's computer

* The app: `C:\Users\<name>\AppData\Local\Programs\EK Image Wise` (or Program Files if the installer
  is run for all users) / `Applications` on a Mac.
* The built-in plugins (Alpha Overlays, Background Removal, Pattern / Poster, Crop Shapes, Filters, Text, Colour & Brightness) are inside the app. Customers add their own to `<home folder>/EKImageWise/plugins`
  (Plugins > Open plugins folder). The log file `EKImageWise/logs/ekiw.log` is there too: ask customers
  to send it if something goes wrong (Help > About shows its location). Uninstalling keeps these.

## The warnings customers will see if the app is NOT signed

Unsigned apps work, but the operating systems warn people:

* **Windows SmartScreen**: "Windows protected your PC". Click **More info**, then **Run anyway**.
* **macOS Gatekeeper**: the app may be refused with "can't be opened" or "is damaged". Tell the customer to
  open **System Settings > Privacy & Security** and press **Open Anyway** after the first attempt, or run
  `xattr -dr com.apple.quarantine /Applications/EKsImageWise.app` in Terminal once.

For anything you sell, signing is strongly recommended.

## Signing (removes the warnings)

Add these as **repository secrets** in GitHub (Settings > Secrets and variables > Actions), or as
environment variables when building locally. The build uses them automatically when they exist.

**Windows** (a code-signing certificate from a certificate authority; roughly 100 to 400 USD a year):

| Secret | What it is |
|---|---|
| `WIN_CERT_PFX_BASE64` | your `.pfx` certificate file, converted to text (PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`) |
| `WIN_CERT_PASSWORD` | the certificate's password |

Locally, set `WIN_CERT_FILE` (path to the `.pfx`) and `WIN_CERT_PASSWORD` instead. A brand-new certificate
may still trigger SmartScreen until the app has built up some reputation; newer "extended validation"
certificates avoid that.

**macOS** (an Apple Developer account, 99 USD a year, and a *Developer ID Application* certificate):

| Secret | What it is |
|---|---|
| `MAC_CERT_P12_BASE64` | the certificate exported from Keychain Access as `.p12`, converted with `base64 -i cert.p12` |
| `MAC_CERT_PASSWORD` | the password you chose when exporting it |
| `MAC_CODESIGN_IDENTITY` | the certificate's full name, e.g. `Developer ID Application: Your Name (ABCDE12345)` |
| `APPLE_ID` | your Apple ID e-mail |
| `APPLE_TEAM_ID` | your 10-character team ID |
| `APPLE_APP_PASSWORD` | an *app-specific password* made at appleid.apple.com |

With the first three the app is signed; with all six it is also *notarized* (Apple scans it) and stapled,
so it opens with no warning at all. Locally, set `CODESIGN_IDENTITY` and the three `APPLE_*` variables.

## If a build fails

* **"No module named ..." when the built app starts**: add the module name to `hiddenimports` in
  `packaging/ek_image_wise.spec` and rebuild. A *plugin* that imports a library the app itself doesn't
  use needs that library listed there too (installed apps only contain what was packaged).
* **Background removal says rembg is missing in the installed app**: build again after
  `pip install -r requirements.txt` (the build must be able to import `rembg`); check the build log for
  `[spec] note:` lines saying which part wasn't found.
* **Antivirus flags the Windows installer**: this happens with unsigned PyInstaller apps; signing fixes it,
  and you can submit the file to the antivirus vendor as a false positive.
* **Mac job: "create-dmg" hangs or fails**: the build falls back to a plain disk image automatically.
* **Something else**: run the build locally; the full messages are shown, and `build/` holds PyInstaller's
  warnings (`build/ek_image_wise/warn-ek_image_wise.txt`).

## Before you sell it

* Test each installer on a clean computer (a Mac and a PC that have never had Python on them): install,
  open a picture, crop, remove a background, add a shape, text and a filter, export, uninstall.
* Read `THIRD_PARTY_NOTICES.md`, check the licences it lists are still correct for the versions you ship
  (Qt/PySide6 is LGPL; the packaged app keeps the Qt libraries as separate files so they can be replaced),
  and keep that file with the app. If you are unsure, ask someone who can give proper legal advice.

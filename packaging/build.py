#!/usr/bin/env python3
"""Builds the installer for the computer you are on.

    python packaging/build.py                  # Windows: setup .exe   |  macOS: .dmg disk image
    python packaging/build.py --models         # include the background-removal models (works offline)
    python packaging/build.py --models --all-models
    python packaging/build.py --no-installer   # just the app folder (Windows) / .app (macOS)
    python packaging/build.py --dry-run        # show what would happen, change nothing

Optional signing (see packaging/PACKAGING.md):
    Windows:  WIN_CERT_FILE, WIN_CERT_PASSWORD  (and optionally WIN_TIMESTAMP_URL)
    macOS:    CODESIGN_IDENTITY  (+ APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD to notarize)
"""
from __future__ import annotations

import argparse
import glob
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from imagewise.version import APP_FILE, APP_NAME, VERSION  # noqa: E402

DIST = ROOT / "dist"
DRY = False


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    if DRY:
        return None
    return subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, **kw)


def note(msg: str):
    print(f"\n=== {msg}", flush=True)


# ----------------------------------------------------------------------------- common steps
def step_icons():
    note("Icons")
    ico = ROOT / "imagewise" / "assets" / "ekiw.ico"
    source = ROOT / "Icon_1.png"  # your own icon, if you put one in the project folder
    if not ico.is_file() or (source.is_file() and source.stat().st_mtime > ico.stat().st_mtime):
        run([sys.executable, "packaging/make_icons.py"])
    else:
        print("icons already present")


def step_models(all_models: bool):
    note("Background-removal models")
    run([sys.executable, "packaging/download_models.py"] + (["--all"] if all_models else []))


def step_pyinstaller():
    note("Packaging the app with PyInstaller")
    for old in (DIST / APP_FILE, DIST / f"{APP_FILE}.app"):
        if old.exists() and not DRY:
            shutil.rmtree(old)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", DIST, "--workpath", ROOT / "build", "packaging/ek_image_wise.spec"])


# ----------------------------------------------------------------------------- Windows
def find_first(candidates):
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


def find_iscc():
    return find_first([
        shutil.which("ISCC"), shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    ])


def find_signtool():
    found = shutil.which("signtool")
    if found:
        return found
    hits = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe"))
    return hits[-1] if hits else None


def sign_windows(path: Path):
    cert, pwd = os.environ.get("WIN_CERT_FILE"), os.environ.get("WIN_CERT_PASSWORD")
    if not cert:
        return
    tool = find_signtool()
    if not tool:
        print("WARNING: WIN_CERT_FILE is set but signtool.exe was not found; not signing", path.name)
        return
    stamp = os.environ.get("WIN_TIMESTAMP_URL", "http://timestamp.digicert.com")
    run([tool, "sign", "/fd", "SHA256", "/tr", stamp, "/td", "SHA256", "/f", cert, "/p", pwd or "", path])


def windows_installer():
    note("Windows installer (Inno Setup)")
    app_dir = DIST / APP_FILE
    sign_windows(app_dir / f"{APP_FILE}.exe")
    iscc = find_iscc()
    if not iscc and not DRY:
        sys.exit("Inno Setup was not found. Install it from https://jrsoftware.org/isdl.php "
                 "(or: choco install innosetup) and run this again, or use --no-installer.")
    out_dir = DIST / "installer"
    run([iscc or "ISCC.exe", f"/DMyAppVersion={VERSION}", f"/DSourceDir={app_dir}", f"/DOutDir={out_dir}",
         "packaging/installer_windows.iss"])
    setup = out_dir / f"EKsImageWise-Setup-{VERSION}.exe"
    sign_windows(setup)
    return setup


# ----------------------------------------------------------------------------- macOS
def mac_arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def mac_dmg():
    note("macOS disk image (.dmg)")
    app = DIST / f"{APP_FILE}.app"
    identity = os.environ.get("CODESIGN_IDENTITY")
    if identity:
        run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    dmg = DIST / f"{APP_FILE}-{VERSION}-{mac_arch()}.dmg"
    stage = DIST / "dmg-staging"
    if not DRY:
        if dmg.exists():
            dmg.unlink()
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        shutil.copytree(app, stage / app.name, symlinks=True)
    made = False
    if shutil.which("create-dmg"):
        try:  # prettier window with an Applications shortcut; can hang on machines with no screen, so time-box it
            cmd = ["create-dmg", "--volname", APP_NAME, "--volicon", ROOT / "imagewise/assets/ekiw.icns",
                   "--window-size", "620", "380", "--icon-size", "110", "--icon", app.name, "160", "180",
                   "--app-drop-link", "460", "180", dmg, stage]
            run(cmd, timeout=180)
            made = True
        except (subprocess.SubprocessError, OSError) as exc:
            print("create-dmg did not finish (", exc, ") - using the plain method instead")
            if dmg.exists() and not DRY:
                dmg.unlink()
    if not made:
        if not DRY:
            link = stage / "Applications"
            if not link.exists():
                link.symlink_to("/Applications")
        run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
    if identity:
        run(["codesign", "--force", "--sign", identity, dmg])
    if all(os.environ.get(k) for k in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_PASSWORD")):
        note("Apple notarization (this can take several minutes)")
        run(["xcrun", "notarytool", "submit", dmg, "--apple-id", os.environ["APPLE_ID"],
             "--team-id", os.environ["APPLE_TEAM_ID"], "--password", os.environ["APPLE_APP_PASSWORD"], "--wait"])
        run(["xcrun", "stapler", "staple", dmg])
    elif identity:
        print("NOTE: signed but not notarized (set APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD to notarize).")
    else:
        print("NOTE: not signed. Macs will warn when opening it; see packaging/PACKAGING.md.")
    if not DRY and stage.exists():
        shutil.rmtree(stage)
    return dmg


# ----------------------------------------------------------------------------- main
def main() -> int:
    global DRY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", action="store_true", help="bundle the background-removal models (u2net, u2netp)")
    ap.add_argument("--all-models", action="store_true", help="also bundle isnet-general-use (implies --models)")
    ap.add_argument("--no-installer", action="store_true", help="stop after building the app itself")
    ap.add_argument("--dry-run", action="store_true", help="print the steps without running them")
    args = ap.parse_args()
    DRY = args.dry_run

    print(f"{APP_NAME} {VERSION} on {platform.system()} {platform.machine()}")
    step_icons()
    if args.models or args.all_models:
        step_models(args.all_models)
    step_pyinstaller()

    result = None
    if not args.no_installer:
        if sys.platform == "win32":
            result = windows_installer()
        elif sys.platform == "darwin":
            result = mac_dmg()
        else:
            print("Installers are built for Windows and macOS only; the app folder is in dist/.")
    note("Finished")
    print("Result:", result or DIST / (f"{APP_FILE}.app" if sys.platform == "darwin" else APP_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())

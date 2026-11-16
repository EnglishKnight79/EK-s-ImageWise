# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for EK's Image Wise (Windows and macOS).

Run from the project folder (packaging/build.py does this for you):
    python -m PyInstaller --noconfirm --clean packaging/ek_image_wise.spec
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = the folder holding this file
sys.path.insert(0, str(ROOT))
from imagewise.version import APP_FILE, APP_ID, APP_NAME, VERSION  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

datas, binaries = [], []
hiddenimports = collect_submodules("imagewise") + [
    # Pillow modules that only the plugins use (PyInstaller can't see plugin files)
    "PIL.ImageFont", "PIL.ImageEnhance", "PIL.ImageFilter", "PIL.ImageOps", "PIL.ImageChops",
    "PIL.ImageDraw", "PIL.ImageStat", "PIL.ImageColor", "PIL.ImageMath", "PIL.ImageSequence",
]

# --- things shipped inside the app ---
datas.append((str(ROOT / "plugins"), "plugins"))  # built-in plugins (users add their own in ~/EKImageWise/plugins)
datas.append((str(ROOT / "imagewise" / "assets"), "imagewise/assets"))  # icons
for name in ("splash.png", "Icon_1.png"):  # your splash screen and icon, if they are in the project folder
    if (ROOT / name).is_file():
        datas.append((str(ROOT / name), "."))
if (ROOT / "models").is_dir():  # background-removal models, when built with --models
    datas.append((str(ROOT / "models"), "models"))
if (ROOT / "THIRD_PARTY_NOTICES.md").is_file():
    datas.append((str(ROOT / "THIRD_PARTY_NOTICES.md"), "."))

# --- background removal (rembg and everything it needs). Optional: the app still runs without it. ---
for pkg in ("rembg", "onnxruntime", "pymatting", "numba", "llvmlite"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # package not installed
        print(f"[spec] note: {pkg} not collected ({exc})")
for pkg in ("skimage", "scipy"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception as exc:
        print(f"[spec] note: {pkg} not collected ({exc})")
for dist_name in ("rembg", "pymatting", "numba", "scikit-image", "scipy", "onnxruntime", "pooch", "tqdm",
                  "numpy", "pillow", "filetype", "jsonschema"):
    try:
        datas += copy_metadata(dist_name)  # some libraries read their own version at start-up
    except Exception:
        pass

icon_file = ROOT / "imagewise" / "assets" / ("ekiw.ico" if IS_WIN else "ekiw.icns")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_FILE,
    console=False,  # no black console window
    icon=str(icon_file) if icon_file.is_file() else None,
    upx=False,
    # macOS signing (only when you provide a Developer ID certificate; see PACKAGING.md)
    codesign_identity=(os.environ.get("CODESIGN_IDENTITY") or None) if IS_MAC else None,
    entitlements_file=str(ROOT / "packaging" / "entitlements.plist") if IS_MAC else None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_FILE)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_FILE}.app",
        icon=str(icon_file) if icon_file.is_file() else None,
        bundle_identifier=APP_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "Copyright EK",
            # lets "Open With" and dropping pictures on the Dock icon open them in the app
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Image",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.image"],
            }],
        },
    )

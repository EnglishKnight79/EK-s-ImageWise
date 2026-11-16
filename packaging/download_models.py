"""Download the background-removal models into ./models so the installer can include them
(the app then works offline, with no first-run download).

    python packaging/download_models.py              # u2net + u2netp  (about 180 MB)
    python packaging/download_models.py --all        # also isnet-general-use (about 170 MB more)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


def main() -> int:
    names = ["u2net", "u2netp"] + (["isnet-general-use"] if "--all" in sys.argv else [])
    MODELS.mkdir(exist_ok=True)
    os.environ["U2NET_HOME"] = str(MODELS)
    try:
        from rembg import new_session
    except Exception as exc:
        print(f"rembg is not installed ({exc}). Run: pip install -r requirements.txt")
        return 1
    for name in names:
        print(f"Downloading {name} ...")
        new_session(name)  # rembg downloads and checks the model file
    print("Models in", MODELS)
    for f in sorted(MODELS.glob("*.onnx")):
        print(f"  {f.name}  {f.stat().st_size / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

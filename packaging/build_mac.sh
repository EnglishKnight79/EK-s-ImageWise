#!/usr/bin/env bash
# Builds the macOS disk image (.dmg) for the kind of Mac you run it on
# (Apple-silicon Macs make an arm64 build, Intel Macs an x64 build).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null || { echo "Python 3.10 - 3.12 is needed (python.org, or: brew install python@3.12)"; exit 1; }
[ -d .venv-build ] || python3 -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r packaging/requirements-build.txt
command -v create-dmg >/dev/null || echo "(optional) 'brew install create-dmg' gives a nicer disk-image window"

# --models puts the background-removal models inside the app so it works offline
python packaging/build.py --models "$@"

echo
echo "Done. Your disk image is in the dist folder."

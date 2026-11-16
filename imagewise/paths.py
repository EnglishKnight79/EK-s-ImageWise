"""Where things live, both when run from source and when packaged (PyInstaller)."""
from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    """True when running as the installed / packaged app."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Folder that holds the plugins/ folder, imagewise/assets and any bundled models/."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]  # the project folder (next to main.py)


def user_dir() -> Path:
    """The user's own folder: plugins, logs, data. Lives in the home folder, survives updates."""
    return Path.home() / "EKImageWise"


def log_dir() -> Path:
    return user_dir() / "logs"


def root_file(name: str) -> Path:
    """A file that sits next to main.py in the project folder (splash.png, Icon_1.png), or in the
    installed app's main folder."""
    return app_root() / name


def asset(name: str) -> Path:
    return app_root() / "imagewise" / "assets" / name


def bundled_models_dir() -> Path | None:
    """Background-removal models shipped inside the app (installer builds), if any."""
    folder = app_root() / "models"
    return folder if folder.is_dir() else None

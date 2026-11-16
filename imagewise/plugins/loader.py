"""Finds and loads plugins. No UI code; a broken plugin never stops the app."""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from imagewise.plugins.api import API_VERSION, Plugin

log = logging.getLogger("imagewise")
MODULE_PREFIX = "ekiw_plugin_"


@dataclass
class PluginRecord:
    name: str
    path: Path
    plugin: Plugin | None = None
    error: str | None = None


def user_plugin_dir() -> Path:
    return Path.home() / "EKImageWise" / "plugins"


def plugin_dirs(app_root: Path) -> list[Path]:
    """Plugins that ship with the app, then the user's own folder."""
    return [Path(app_root) / "plugins", user_plugin_dir()]


def discover(dirs: list[Path]) -> list[Path]:
    """Entry files: every plugin .py, and every sub-folder containing __init__.py.
    Names starting with _ or . are ignored (handy for templates and disabled plugins)."""
    found: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
            if p.name.startswith(("_", ".")):
                continue
            if p.is_file() and p.suffix == ".py":
                found.append(p)
            elif p.is_dir() and (p / "__init__.py").is_file():
                found.append(p / "__init__.py")
    return found


def _module_name(entry: Path) -> str:
    base = entry.parent.name if entry.name == "__init__.py" else entry.stem
    return MODULE_PREFIX + re.sub(r"\W+", "_", base)


def _find_class(module) -> type[Plugin]:
    cls = getattr(module, "PLUGIN", None)
    if cls is None:
        candidates = [v for v in vars(module).values()
                      if isinstance(v, type) and issubclass(v, Plugin) and v is not Plugin
                      and v.__module__ == module.__name__]
        if not candidates:
            raise ImportError("No Plugin subclass found (define one, or set PLUGIN = YourClass)")
        cls = candidates[0]
    if not (isinstance(cls, type) and issubclass(cls, Plugin)):
        raise TypeError("PLUGIN must be a subclass of imagewise.plugins.api.Plugin")
    return cls


def load_one(entry: Path, host) -> Plugin:
    mod_name = _module_name(entry)
    if entry.name == "__init__.py":
        spec = importlib.util.spec_from_file_location(
            mod_name, entry, submodule_search_locations=[str(entry.parent)])
    else:
        spec = importlib.util.spec_from_file_location(mod_name, entry)
    if spec is None or spec.loader is None:
        raise ImportError("Could not read the plugin file")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        cls = _find_class(module)
        if getattr(cls, "api_version", 1) > API_VERSION:
            raise RuntimeError(f"needs a newer version of EK's Image Wise (plugin API {cls.api_version})")
        return cls(host)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise


def unload_all() -> None:
    for name in [n for n in sys.modules if n.startswith(MODULE_PREFIX)]:
        del sys.modules[name]


def load_all(host, dirs: list[Path]) -> list[PluginRecord]:
    unload_all()
    records: list[PluginRecord] = []
    seen: set[str] = set()
    for entry in discover(dirs):
        label = entry.parent.name if entry.name == "__init__.py" else entry.stem
        try:
            plugin = load_one(entry, host)
            name = str(plugin.name)
            n, unique = 2, name
            while unique in seen:  # two plugins with the same name
                unique = f"{name} ({n})"
                n += 1
            if unique != name:
                plugin.name = unique
            seen.add(unique)
            records.append(PluginRecord(unique, entry, plugin))
        except Exception as exc:
            log.exception("Plugin %s failed to load", entry)
            records.append(PluginRecord(label, entry, None, f"{type(exc).__name__}: {exc}"))
    return records

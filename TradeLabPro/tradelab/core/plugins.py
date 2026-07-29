"""Plugin SDK (Phase 6): drop-in custom indicators, auto-discovered.

A plugin is a single .py file in the top-level ``plugins/`` folder that
defines:

    PLUGIN_NAME = "My Indicator"        # required, shown in the UI
    def compute(df):                    # required, returns a pandas Series
        return df["Close"].rolling(10).mean()

On discovery each valid plugin is registered as a field in
tradelab.core.filters.FIELD_SPECS (keyed "plugin:<name>"), so it becomes
usable in the Scanner's custom filters and the no-code Strategy Builder
with no other wiring. Bad plugins (import error, missing PLUGIN_NAME or
compute) are skipped with the error recorded, never crashing the app.
"""
from __future__ import annotations

import importlib.util
import traceback
from pathlib import Path

from tradelab.core.config import ROOT_DIR
from tradelab.core import filters

PLUGINS_DIR = ROOT_DIR / "plugins"

_loaded: dict = {}   # name -> module
_errors: dict = {}   # filename -> short error string


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name).upper()


def loaded_plugins() -> dict:
    return dict(_loaded)


def plugin_errors() -> dict:
    return dict(_errors)


def discover_plugins(directory=None) -> dict:
    """(Re)scan the plugins folder, import valid plugins, and register them
    as indicator fields. Returns {"loaded": [names], "errors": {file: msg}}."""
    directory = Path(directory) if directory else PLUGINS_DIR
    _unregister_fields()
    _loaded.clear()
    _errors.clear()
    if directory.exists():
        for path in sorted(directory.glob("*.py")):
            if path.name == "__init__.py":
                continue
            _load_one(path)
    _register_fields()
    return {"loaded": list(_loaded), "errors": dict(_errors)}


def _load_one(path: Path):
    try:
        spec = importlib.util.spec_from_file_location(f"tlp_plugin_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        _errors[path.name] = traceback.format_exc().strip().splitlines()[-1]
        return
    name = getattr(mod, "PLUGIN_NAME", None)
    if not name or not callable(getattr(mod, "compute", None)):
        _errors[path.name] = "missing PLUGIN_NAME or compute(df)"
        return
    _loaded[str(name)] = mod


def _plugin_key(name: str) -> str:
    return f"plugin:{name}"


def _unregister_fields():
    for key in [k for k in filters.FIELD_SPECS if k.startswith("plugin:")]:
        del filters.FIELD_SPECS[key]


def _register_fields():
    for name, mod in _loaded.items():
        col = f"PLUGIN_{_safe(name)}"
        # Default args capture the per-plugin column name and module.
        filters.FIELD_SPECS[_plugin_key(name)] = filters._spec(
            f"{name} (plugin)", None,
            (lambda p, c=col: c),
            (lambda df, p, m=mod: m.compute(df)),
        )

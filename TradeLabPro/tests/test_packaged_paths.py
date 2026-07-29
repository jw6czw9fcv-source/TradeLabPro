"""Where a packaged build reads and writes.

Once frozen into an .exe there are two different roots, and conflating them
loses data: the bundle is read-only (and, for a one-file build, a temp folder
Windows deletes on exit), so anything the app writes has to live outside it.
"""
import importlib
import sys
from pathlib import Path

import pytest


def _reload_config(monkeypatch, frozen: bool, meipass: str = None,
                   localappdata: str = None):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if meipass is not None:
        monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)
    elif hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    if localappdata is not None:
        monkeypatch.setenv("LOCALAPPDATA", localappdata)
    import tradelab.core.config as config
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def _restore_config():
    """These tests reload config with a faked frozen state; put the real paths
    back afterwards, including in the modules that captured them at import."""
    yield
    import tradelab.core.config as config
    import tradelab.core.logging_config as logging_config
    import tradelab.core.plugins as plugins
    importlib.reload(config)
    importlib.reload(logging_config)
    importlib.reload(plugins)


def test_running_from_source_uses_the_repo(monkeypatch):
    cfg = _reload_config(monkeypatch, frozen=False)
    assert cfg.FROZEN is False
    assert cfg.DATA_DIR == cfg.ROOT_DIR / "data"
    assert cfg.LOG_DIR == cfg.ROOT_DIR / "logs"
    assert (cfg.ROOT_DIR / "tradelab").is_dir()      # really is the source tree


def test_packaged_writes_outside_the_bundle(tmp_path, monkeypatch):
    bundle, appdata = tmp_path / "_MEI12345", tmp_path / "AppData"
    cfg = _reload_config(monkeypatch, frozen=True, meipass=str(bundle),
                         localappdata=str(appdata))
    assert cfg.FROZEN is True
    # The manual and other shipped files come out of the bundle...
    assert cfg.ROOT_DIR == bundle
    # ...but nothing writable may live there, or it is gone when the app exits.
    for writable in (cfg.DATA_DIR, cfg.DB_PATH, cfg.LOG_DIR, cfg.PLUGINS_DIR):
        assert bundle not in Path(writable).parents, f"{writable} is inside the bundle"
    assert cfg.DATA_DIR == appdata / cfg.APP_NAME
    assert cfg.DB_PATH == appdata / cfg.APP_NAME / "tradelab.db"


def test_packaged_falls_back_to_home_without_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    cfg = _reload_config(monkeypatch, frozen=True, meipass=str(tmp_path / "bundle"))
    assert cfg.DATA_DIR == tmp_path / cfg.APP_NAME


def test_logging_and_plugins_follow_the_writable_root(tmp_path, monkeypatch):
    cfg = _reload_config(monkeypatch, frozen=True, meipass=str(tmp_path / "b"),
                         localappdata=str(tmp_path / "AppData"))
    import tradelab.core.logging_config as lc
    import tradelab.core.plugins as pl
    importlib.reload(lc)
    importlib.reload(pl)
    assert lc.LOG_FILE.parent == cfg.LOG_DIR == cfg.DATA_DIR / "logs"
    assert pl.PLUGINS_DIR == cfg.DATA_DIR / "plugins"

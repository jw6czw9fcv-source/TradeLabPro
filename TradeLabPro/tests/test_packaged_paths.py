"""Where the app reads and writes, from source and from a packaged .exe.

Two rules are being pinned here:

1. **One data folder, however the app was started.** The .exe and a run from
   source must open the same portfolio, journal and alerts — otherwise the two
   drift apart and a trade logged in one is invisible in the other.
2. **Nothing writable inside the bundle.** A one-file build unpacks to a temp
   folder Windows deletes on exit, so a database written there would take the
   whole portfolio with it every time the app closed.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest


def _reload(monkeypatch, frozen: bool, meipass: str = None,
            localappdata: str = None, data_dir: str = None):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if meipass is not None:
        monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)
    elif hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    if localappdata is not None:
        monkeypatch.setenv("LOCALAPPDATA", localappdata)
    # The suite normally forces this at the temp dir set in conftest; drop it so
    # these tests can exercise the real resolution rules.
    monkeypatch.delenv("TRADELAB_DATA_DIR", raising=False)
    if data_dir is not None:
        monkeypatch.setenv("TRADELAB_DATA_DIR", data_dir)
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


def test_source_and_packaged_share_one_data_folder(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData"
    from_source = _reload(monkeypatch, frozen=False, localappdata=str(appdata))
    source_data, source_db = from_source.DATA_DIR, from_source.DB_PATH

    packaged = _reload(monkeypatch, frozen=True, meipass=str(tmp_path / "_MEI1"),
                       localappdata=str(appdata))
    assert packaged.DATA_DIR == source_data, "the .exe and source must not diverge"
    assert packaged.DB_PATH == source_db
    assert source_data == appdata / packaged.APP_NAME


def test_data_never_lands_in_the_source_tree(tmp_path, monkeypatch):
    cfg = _reload(monkeypatch, frozen=False, localappdata=str(tmp_path / "AppData"))
    # Real positions do not belong inside a git checkout.
    assert cfg.ROOT_DIR not in cfg.DATA_DIR.parents
    assert (cfg.ROOT_DIR / "tradelab").is_dir()      # really is the source tree


def test_packaged_writes_outside_the_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "_MEI12345"
    cfg = _reload(monkeypatch, frozen=True, meipass=str(bundle),
                  localappdata=str(tmp_path / "AppData"))
    assert cfg.FROZEN is True
    assert cfg.ROOT_DIR == bundle                    # the manual ships in here
    for writable in (cfg.DATA_DIR, cfg.DB_PATH, cfg.LOG_DIR):
        assert bundle not in Path(writable).parents, f"{writable} is inside the bundle"


def test_the_data_dir_can_be_overridden(tmp_path, monkeypatch):
    cfg = _reload(monkeypatch, frozen=False, data_dir=str(tmp_path / "elsewhere"))
    assert cfg.DATA_DIR == tmp_path / "elsewhere"
    assert cfg.DB_PATH == tmp_path / "elsewhere" / "tradelab.db"


def test_falls_back_to_home_without_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    cfg = _reload(monkeypatch, frozen=True, meipass=str(tmp_path / "bundle"))
    assert cfg.DATA_DIR == tmp_path / cfg.APP_NAME


def test_logs_follow_the_data_and_plugins_follow_the_install(tmp_path, monkeypatch):
    cfg = _reload(monkeypatch, frozen=True, meipass=str(tmp_path / "b"),
                  localappdata=str(tmp_path / "AppData"))
    import tradelab.core.logging_config as lc
    import tradelab.core.plugins as pl
    importlib.reload(lc)
    importlib.reload(pl)
    assert lc.LOG_FILE.parent == cfg.LOG_DIR == cfg.DATA_DIR / "logs"
    # Plugins are code that ships with the app, not data you accumulate.
    assert pl.PLUGINS_DIR == cfg.ROOT_DIR / "plugins"


def test_the_suite_cannot_touch_the_real_portfolio():
    # conftest redirects the whole run; without it a bare Database() would open
    # the portfolio actually being traded.
    from tradelab.core import config
    assert os.environ.get(config.DATA_DIR_ENV), "conftest should set the override"
    real = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / config.APP_NAME
    assert config.DATA_DIR.resolve() != real.resolve()

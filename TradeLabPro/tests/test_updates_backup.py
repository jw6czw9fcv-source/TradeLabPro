"""Update check (installer folder + GitHub tags) and the weekly data backup."""
import datetime as dt
import json
import sqlite3
import zipfile

import pytest

from tradelab.core import backup, updates


# --- updates (Qt-free) -----------------------------------------------------------

def test_versions_are_read_from_any_label():
    assert updates.parse_version("2.53.0 Waiting for a pension, counted") == (2, 53, 0)
    assert updates.parse_version("v2.9.1") == (2, 9, 1)
    assert updates.parse_version("") == ()
    assert (2, 10, 0) > (2, 9, 9)   # compared as numbers, not text


def _installers(folder, *versions):
    for v in versions:
        (folder / f"TradeLabPro-Setup-{v}.exe").write_bytes(b"x")


def test_the_newest_installer_newer_than_the_running_one_is_offered(tmp_path):
    _installers(tmp_path, "2.52.0", "2.54.0", "2.53.0")
    (tmp_path / "notes.txt").write_text("not an installer")
    version, path = updates.newer_installer(tmp_path, "2.53.0 Something")
    assert version == (2, 54, 0) and path.name == "TradeLabPro-Setup-2.54.0.exe"


def test_no_offer_when_the_folder_holds_nothing_newer(tmp_path):
    _installers(tmp_path, "2.52.0", "2.53.0")
    assert updates.newer_installer(tmp_path, "2.53.0") is None
    assert updates.newer_installer(tmp_path / "missing", "2.53.0") is None
    assert updates.newer_installer("", "2.53.0") is None


def test_the_latest_published_version_comes_from_the_tags():
    tags = [{"name": "v2.52.0"}, {"name": "v2.53.0"}, {"name": "v2.9.0"}, {"name": "misc"}]
    assert updates.latest_published(lambda url: json.dumps(tags).encode()) == (2, 53, 0)


def test_an_unreachable_github_is_none_not_an_error():
    def offline(url):
        raise OSError("no network")
    assert updates.latest_published(offline) is None


# --- backups (Qt-free) -------------------------------------------------------------

def _data(folder):
    db = sqlite3.connect(folder / "tradelab.db")
    db.execute("create table t (x)")
    db.execute("insert into t values (42)")
    db.commit()
    db.close()
    (folder / "links.json").write_text('{"links": []}')
    (folder / "notes.txt").write_text("hello")
    (folder / "universe_cache.json").write_text("{}")
    (folder / "logs").mkdir()
    (folder / "logs" / "tradelab.log").write_text("log")


def test_a_backup_holds_the_database_and_the_small_files(tmp_path):
    _data(tmp_path)
    path = backup.make_backup(tmp_path, now=dt.datetime(2026, 10, 13, 9, 30))
    assert path.parent == tmp_path / "backups"
    assert path.name == "TradeLab-backup-2026-10-13_093000.zip"
    with zipfile.ZipFile(path) as zf:
        assert sorted(zf.namelist()) == ["links.json", "notes.txt", "tradelab.db"]
        zf.extract("tradelab.db", tmp_path / "restored")
    copy = sqlite3.connect(tmp_path / "restored" / "tradelab.db")
    assert copy.execute("select x from t").fetchone() == (42,)
    copy.close()


def test_a_backup_is_due_weekly(tmp_path):
    _data(tmp_path)
    dest = backup.backup_dir(tmp_path)
    assert backup.due(dest)
    backup.make_backup(tmp_path, now=dt.datetime(2026, 10, 1, 8, 0))
    assert not backup.due(dest, now=dt.datetime(2026, 10, 7, 8, 0))
    assert backup.due(dest, now=dt.datetime(2026, 10, 8, 8, 0))


def test_only_the_newest_backups_are_kept(tmp_path):
    _data(tmp_path)
    for day in range(1, 12):
        backup.make_backup(tmp_path, now=dt.datetime(2026, 9, day, 8, 0), keep=8)
    kept = backup.backups(backup.backup_dir(tmp_path))
    assert len(kept) == 8
    assert kept[0][0] == dt.datetime(2026, 9, 11, 8, 0)
    assert kept[-1][0] == dt.datetime(2026, 9, 4, 8, 0)


# --- the Settings panel ---------------------------------------------------------------

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _panel(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from tradelab.data.database import Database
    from tradelab.ui.app import SettingsPanel
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    panel = SettingsPanel(Database(tmp_path / "t.db"), settings=settings)
    panel.data_dir = tmp_path
    return panel


def test_a_newer_installer_is_offered_and_run(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    folder = tmp_path / "out"
    folder.mkdir()
    _installers(folder, "99.0.0")
    asked, opened = [], []
    monkeypatch.setattr(appmod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[2]) or appmod.QMessageBox.Yes))
    monkeypatch.setattr("tradelab.ui.panels.settings.open_external", lambda url: opened.append(url.toLocalFile()))
    panel = _panel(qapp, tmp_path)
    panel.update_folder.setText(str(folder))
    panel.check_updates()
    assert "99.0.0" in asked[0]
    assert len(opened) == 1 and opened[0].endswith("TradeLabPro-Setup-99.0.0.exe")


def test_github_news_is_told_once_at_startup(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    told = []
    monkeypatch.setattr(appmod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: told.append(a[2])))
    panel = _panel(qapp, tmp_path)
    panel._on_published((99, 0, 0), quiet=True)
    panel._on_published((99, 0, 0), quiet=True)
    assert len(told) == 1 and "99.0.0" in told[0]
    assert "installer is not in the installer folder" in panel.update_status.text()
    panel._on_published((1, 0, 0), quiet=True)
    assert "the latest version" in panel.update_status.text()


def test_an_unreachable_github_pops_up_only_when_asked(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    panel = _panel(qapp, tmp_path)
    panel._on_published(None, quiet=True)
    assert shown == []
    panel._on_published(None, quiet=False)
    assert len(shown) == 1 and "GitHub could not be reached" in shown[0]


def test_backup_now_from_settings(qapp, tmp_path):
    _data(tmp_path)
    panel = _panel(qapp, tmp_path)
    assert panel.backup_status.text() == "No backup yet."
    panel.backup_now()
    panel._backup_worker.wait(10000)
    qapp.processEvents()
    assert panel.backup_status.text().startswith("Backed up to ")
    assert len(backup.backups(backup.backup_dir(tmp_path))) == 1


def test_a_failed_backup_pops_up(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    shown = []
    monkeypatch.setattr("tradelab.ui.common.show_problem", lambda text, parent=None: shown.append(text))
    panel = _panel(qapp, tmp_path)
    panel._on_backup_done("", "disk full", quiet=True)
    assert shown == ["Backup failed: disk full"]


def test_startup_backs_up_when_due_and_checks_updates_only_when_installed(qapp, tmp_path, monkeypatch):
    from tradelab.core import config
    _data(tmp_path)
    panel = _panel(qapp, tmp_path)
    calls = []
    monkeypatch.setattr(panel, "backup_now", lambda quiet=False: calls.append(("backup", quiet)))
    monkeypatch.setattr(panel, "check_updates", lambda quiet=False: calls.append(("update", quiet)))
    monkeypatch.setattr(config, "FROZEN", False)
    panel.startup_checks()
    assert calls == [("backup", True)]
    calls.clear()
    monkeypatch.setattr(config, "FROZEN", True)
    panel.startup_checks()
    assert calls == [("backup", True), ("update", True)]


# --- restoring -------------------------------------------------------------------

def test_a_restore_is_staged_then_applied_after_backing_up_the_current_data(tmp_path):
    _data(tmp_path)
    old = backup.make_backup(tmp_path, now=dt.datetime(2026, 10, 1, 8, 0))
    # Things change after that backup...
    db = sqlite3.connect(tmp_path / "tradelab.db")
    db.execute("update t set x = 7")
    db.commit()
    db.close()
    (tmp_path / "notes.txt").write_text("changed")
    assert backup.stage_restore(old, tmp_path) == ["links.json", "notes.txt", "tradelab.db"]
    assert backup.restore_pending(tmp_path)
    restored = backup.apply_pending_restore(tmp_path, now=dt.datetime(2026, 10, 14, 9, 0))
    assert restored == ["links.json", "notes.txt", "tradelab.db"]
    assert not backup.restore_pending(tmp_path)
    assert (tmp_path / "notes.txt").read_text() == "hello"
    db = sqlite3.connect(tmp_path / "tradelab.db")
    assert db.execute("select x from t").fetchone() == (42,)
    db.close()
    # ...and what was replaced was kept, so the restore can be undone.
    safety = backup.backups(backup.backup_dir(tmp_path))[0][1]
    with zipfile.ZipFile(safety) as zf:
        assert zf.read("notes.txt") == b"changed"


def test_nothing_staged_means_nothing_restored(tmp_path):
    assert backup.apply_pending_restore(tmp_path) == []


def test_a_zip_without_a_database_is_refused(tmp_path):
    bad = tmp_path / "other.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("readme.txt", "hi")
    with pytest.raises(ValueError):
        backup.stage_restore(bad, tmp_path)
    assert not backup.restore_pending(tmp_path)


def test_a_zip_cannot_write_outside_the_data_folder(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("tradelab.db", "x")
        zf.writestr("../outside.txt", "nope")
    (tmp_path / "data").mkdir()
    assert backup.stage_restore(evil, tmp_path / "data") == ["tradelab.db"]
    assert not (tmp_path / "outside.txt").exists()


def test_restore_from_settings_stages_and_restarts(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    _data(tmp_path)
    zip_path = backup.make_backup(tmp_path, now=dt.datetime(2026, 10, 1, 8, 0))
    restarted = []
    monkeypatch.setattr(appmod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: appmod.QMessageBox.Yes))
    monkeypatch.setattr("tradelab.ui.panels.settings.restart_app", lambda: restarted.append(True))
    panel = _panel(qapp, tmp_path)
    panel.restore(str(zip_path))
    assert restarted == [True] and backup.restore_pending(tmp_path)


def test_a_declined_restore_changes_nothing(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    _data(tmp_path)
    zip_path = backup.make_backup(tmp_path, now=dt.datetime(2026, 10, 1, 8, 0))
    monkeypatch.setattr(appmod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: appmod.QMessageBox.No))
    monkeypatch.setattr("tradelab.ui.panels.settings.restart_app", lambda: pytest.fail("restarted"))
    _panel(qapp, tmp_path).restore(str(zip_path))
    assert not backup.restore_pending(tmp_path)

"""Headless smoke tests for the Help menu (User Manual viewer + Version dialog)."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _help_menu(win):
    return win.help_menu


def _main_window(qapp):
    from tradelab.ui.app import MainWindow
    return MainWindow()


def test_help_menu_has_user_manual_and_version(qapp):
    win = _main_window(qapp)
    menu = _help_menu(win)
    assert menu is not None
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "User Manual" in labels
    assert "Version" in labels


def test_user_manual_action_opens_a_viewer_with_the_manual(qapp, monkeypatch):
    from tradelab.ui import app as appmod
    captured = {}

    # Don't block on a modal dialog - capture it and return immediately.
    def fake_exec(self):
        captured["dialog"] = self
        return 0
    monkeypatch.setattr(appmod.QDialog, "exec", fake_exec)

    win = _main_window(qapp)
    win.show_user_manual()
    dlg = captured.get("dialog")
    assert dlg is not None
    from PySide6.QtWidgets import QTextBrowser
    viewer = dlg.findChild(QTextBrowser)
    assert viewer is not None
    # The rendered manual should carry recognizable content, not the error text.
    text = viewer.toPlainText()
    assert "TradeLab Pro" in text
    assert "Could not load" not in text


def test_version_action_shows_about_with_version(qapp, monkeypatch):
    from tradelab.ui import app as appmod
    from tradelab.core.config import APP_VERSION
    shown = {}
    monkeypatch.setattr(appmod.QMessageBox, "about",
                        lambda parent, title, text: shown.update(title=title, text=text))
    win = _main_window(qapp)
    win.show_version()
    assert "About" in shown["title"]
    assert APP_VERSION in shown["text"]

"""Simple and Advanced mode: which tabs show, the switch, and the first-run
default."""
import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _visible(win):
    return [win.tabs.tabText(i) for i in range(win.tabs.count()) if win.tabs.isTabVisible(i)]


def test_a_first_run_is_simple_and_a_used_install_advanced(tmp_path):
    from PySide6.QtCore import QSettings
    from tradelab.data.database import Database
    from tradelab.ui.app import UI_MODE_KEY, ui_mode
    s = QSettings(str(tmp_path / "m.ini"), QSettings.IniFormat)
    db = Database(path=tmp_path / "m.db")
    assert ui_mode(db, s) == "simple"
    db.add_portfolio("REER A")
    assert ui_mode(db, s) == "advanced"
    s.setValue(UI_MODE_KEY, "simple")
    assert ui_mode(db, s) == "simple"                 # the last choice wins
    db.conn.close()


def test_the_switch_shows_and_hides_tabs(qapp):
    from tradelab.settings import app_settings
    from tradelab.ui.app import SIMPLE_TABS, UI_MODE_KEY, MainWindow
    win = MainWindow()
    try:
        win.apply_mode("simple")
        assert _visible(win) == [t for t in [win.tabs.tabText(i) for i in range(win.tabs.count())]
                                 if t in SIMPLE_TABS]
        assert "Scanner" not in _visible(win) and "Guide" in _visible(win)
        assert "show all tabs" in win.mode_button.text()
        assert not win.advanced_action.isChecked()
        assert app_settings().value(UI_MODE_KEY) == "simple"

        # A hidden tab that was showing gives way to the first tab.
        win.apply_mode("advanced")
        win.tabs.setCurrentWidget(win.tabs.widget(
            [win.tabs.tabText(i) for i in range(win.tabs.count())].index("Scanner")))
        win.toggle_mode()
        assert win.mode == "simple" and win.tabs.currentIndex() == 0

        win.advanced_action.trigger()                  # the View menu
        assert win.mode == "advanced" and len(_visible(win)) == win.tabs.count()
    finally:
        win.close()

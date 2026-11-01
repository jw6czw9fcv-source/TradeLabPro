"""French on screen: the dictionary, the swap, and the logic left in English."""
import pytest

from tradelab import i18n


@pytest.fixture
def french():
    i18n.set_current("fr")
    yield
    i18n.set_current("en")


def test_tr_only_in_french(french):
    assert i18n.tr("Refresh") == "Actualiser"
    assert i18n.tr("Not in the dictionary") == "Not in the dictionary"
    i18n.set_current("en")
    assert i18n.tr("Refresh") == "Refresh"


def test_the_templates_keep_their_fields():
    import string
    for key, value in i18n.FR.items():
        fields = {f for _t, f, _s, _c in string.Formatter().parse(key) if f}
        assert fields == {f for _t, f, _s, _c in string.Formatter().parse(value) if f}, key


def test_the_language_setting(tmp_path):
    from PySide6.QtCore import QSettings
    s = QSettings(str(tmp_path / "l.ini"), QSettings.IniFormat)
    assert i18n.language(s) == "en"
    s.setValue(i18n.LANG_KEY, "fr")
    assert i18n.language(s) == "fr"
    s.setValue(i18n.LANG_KEY, "de")
    assert i18n.language(s) == "en"


pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_window_in_french_keeps_its_logic(qapp, french):
    from tradelab.ui.app import MainWindow
    win = MainWindow()
    try:
        assert win.tabs.tabText(1) == "Home"                                # logic: English
        assert win.tabs._buttons[1].text() == "Accueil"                     # screen: French
        assert win.view_menu.title() == "&Affichage"
        guide = win.guide_panel
        assert guide.horizon.itemText(0) == "Moins de 2 ans"
        guide.accounts.setCurrentIndex(3)
        guide.emergency.setCurrentIndex(1)
        a = guide.answers()
        assert a["accounts"] == "Neither yet" and a["emergency"] == "No"   # stored in English
        assert win.plan_panel.flow_kind.itemText(0) == "Dépôt"
        win.apply_mode("simple")
        assert "Mode simple" in win.mode_button.text()
        # Unmarked lists the code reads by text stay English.
        assert win.plan_panel.trading.findText("(none)") >= 0
    finally:
        win.close()


def test_english_is_untouched(qapp):
    from tradelab.ui.app import MainWindow
    win = MainWindow()
    try:
        assert win.tabs._buttons[1].text() == "Home"
        assert "Language" in [a.text() for a in win.view_menu.actions()]
    finally:
        win.close()

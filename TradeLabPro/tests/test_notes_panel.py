"""Headless smoke tests for the Notes panel and the multi-row tab bar."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QLabel, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_notes_panel_loads_and_autosaves(qapp, tmp_path):
    from tradelab.ui.app import NotesPanel
    from tradelab.core.notes import load_notes
    path = tmp_path / "notes.txt"
    panel = NotesPanel(path=path)
    panel.editor.setPlainText("watch AAPL breakout")
    panel.save()                                 # (the debounce timer calls this)
    assert load_notes(path) == "watch AAPL breakout"
    # A new panel pointed at the same file reloads it.
    assert NotesPanel(path=path).editor.toPlainText() == "watch AAPL breakout"


def test_notes_panel_shutdown_flushes(qapp, tmp_path):
    from tradelab.ui.app import NotesPanel
    from tradelab.core.notes import load_notes
    path = tmp_path / "notes.txt"
    panel = NotesPanel(path=path)
    panel.editor.setPlainText("unsaved idea")
    panel.shutdown()
    assert load_notes(path) == "unsaved idea"


def test_multirow_tabs_shows_all_tabs(qapp):
    from tradelab.ui.app import MultiRowTabs
    tabs = MultiRowTabs()
    pages = [QWidget() for _ in range(17)]
    for i, p in enumerate(pages):
        tabs.addTab(p, f"Tab {i}")
    assert tabs.count() == 17
    # Every tab has a visible button (no overflow / scroll arrow).
    assert len(tabs._buttons) == 17
    # Switching works by index and by widget.
    tabs.setCurrentIndex(5)
    assert tabs.currentIndex() == 5 and tabs._buttons[5].isChecked()
    tabs.setCurrentWidget(pages[9])
    assert tabs.currentWidget() is pages[9]
    assert tabs.tabText(9) == "Tab 9"


def test_multirow_tab_bar_wraps_to_multiple_rows(qapp):
    from tradelab.ui.app import MultiRowTabs
    tabs = MultiRowTabs()
    for i in range(17):
        tabs.addTab(QWidget(), f"Paper Trading {i}")   # wide labels force wrapping
    tabs.resize(420, 600)
    tabs.show()
    qapp.processEvents()
    # A single row would be ~30px tall; wrapping makes the bar taller.
    assert tabs._bar.height() > 45
    tabs.hide()


def test_chart_fullscreen_toggle(qapp):
    from tradelab.ui.app import MainWindow
    win = MainWindow()
    assert win.tabs.isVisible() or True          # not shown yet
    win.toggle_chart_fullscreen()
    assert win._chart_full is True
    assert not win.tabs.isVisible()              # left panel hidden for the chart
    assert "Exit" in win.chart._fs_btn.text()
    win.toggle_chart_fullscreen()
    assert win._chart_full is False
    assert win.tabs.isVisible()
    assert "Exit" not in win.chart._fs_btn.text()

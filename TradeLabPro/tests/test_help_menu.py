"""Headless smoke tests for the Help menu (User Manual viewer + Version dialog)."""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

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


def test_manual_window_has_open_as_pdf_button(qapp, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from tradelab.ui import app as appmod
    captured = {}
    monkeypatch.setattr(appmod.QDialog, "exec",
                        lambda self: captured.update(dialog=self) or 0)
    win = _main_window(qapp)
    win.show_user_manual()
    buttons = [b.text() for b in captured["dialog"].findChildren(QPushButton)]
    assert any("PDF" in t for t in buttons)


def test_export_manual_pdf_writes_a_valid_pdf(qapp, monkeypatch):
    import PySide6.QtGui as QtGui
    from tradelab.core.config import ROOT_DIR
    opened = {}
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.update(path=url.toLocalFile()) or True))
    win = _main_window(qapp)
    win._export_manual_pdf(ROOT_DIR / "docs" / "USER_MANUAL.md")
    path = opened.get("path")
    assert path and os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read(5) == b"%PDF-"
    assert os.path.getsize(path) > 10_000  # non-trivial (embeds screenshots)


def test_manual_window_has_minimize_and_maximize_buttons(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from tradelab.ui import app as appmod
    captured = {}
    monkeypatch.setattr(appmod.QDialog, "exec",
                        lambda self: captured.update(dialog=self) or 0)
    win = _main_window(qapp)
    win.show_user_manual()
    flags = captured["dialog"].windowFlags()
    assert flags & Qt.WindowMaximizeButtonHint
    assert flags & Qt.WindowMinimizeButtonHint


def test_manual_screenshots_scale_to_the_window_width(qapp):
    from tradelab.ui.app import ManualBrowser
    from tradelab.core.config import ROOT_DIR
    docs = ROOT_DIR / "docs"
    browser = ManualBrowser(docs)
    browser.load_markdown((docs / "USER_MANUAL.md").read_text(encoding="utf-8"))
    browser.resize(700, 500)
    browser.show()
    qapp.processEvents()
    browser._rescale_images()

    # Walk the document for the first embedded image and confirm it was scaled
    # to (roughly) the viewport width, not left at its ~1000px native size.
    doc = browser.document()
    widths = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                widths.append(frag.charFormat().toImageFormat().width())
            it += 1
        block = block.next()
    browser.hide()
    assert widths, "no embedded images found in the manual"
    avail = browser.viewport().width() - 24
    assert abs(widths[0] - avail) < 2  # scaled to the content width


def test_recolor_doc_links_helper_makes_links_black(qapp):
    # The PDF export recolours links to black via this helper (the on-screen
    # viewer keeps Qt's default link colour), so test the helper directly.
    from PySide6.QtGui import QTextDocument
    from tradelab.ui.app import _recolor_doc_links
    doc = QTextDocument()
    doc.setMarkdown("See [the scanner](#scanner) and [charts](#charts).")
    _recolor_doc_links(doc)
    found = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isAnchor():
                c = frag.charFormat().foreground().color()
                found.append((c.red(), c.green(), c.blue()))
            it += 1
        block = block.next()
    assert found and all(rgb == (0, 0, 0) for rgb in found)


def _first_image_width(browser):
    doc = browser.document()
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                return frag.charFormat().toImageFormat().width()
            it += 1
        block = block.next()
    return None


def test_manual_screenshots_follow_ctrl_wheel_zoom(qapp):
    from tradelab.ui.app import ManualBrowser
    from tradelab.core.config import ROOT_DIR
    docs = ROOT_DIR / "docs"
    browser = ManualBrowser(docs)
    browser.load_markdown((docs / "USER_MANUAL.md").read_text(encoding="utf-8"))
    browser.resize(700, 500)
    browser.show()
    qapp.processEvents()
    browser._rescale_images()
    base = _first_image_width(browser)

    # Zoom the text in; images should grow with it (browser-style page zoom).
    browser.zoomIn(6)
    browser._rescale_images()
    zoomed = _first_image_width(browser)
    browser.hide()

    assert base and zoomed
    assert browser._zoom_factor() > 1.0
    assert zoomed > base * 1.1


def test_window_min_height_fits_a_normal_screen(qapp):
    # Regression: a QTabWidget adopts its tallest page as the whole stack's
    # minimum height, so the tall Scanner tab used to force the window past a
    # 1080p screen and clip the bottom. Each tab page is now wrapped in a
    # scroll area, so the window minimum must stay well under a typical screen.
    win = _main_window(qapp)
    assert win.centralWidget().minimumSizeHint().height() < 700
    assert win.minimumSizeHint().height() < 720


def test_tab_panels_are_still_accessible_after_scroll_wrap(qapp):
    # Wrapping tab pages in scroll areas must not break the panel attributes
    # the rest of the app (and tests) rely on.
    win = _main_window(qapp)
    assert win.scanner_panel.__class__.__name__ == "ScannerPanel"
    assert win.heatmap_panel.__class__.__name__ == "HeatmapPanel"
    assert win.alerts_panel.__class__.__name__ == "AlertsPanel"


def test_scanner_results_map_into_the_heatmap(qapp):
    import pandas as pd
    win = _main_window(qapp)
    # Keep the heatmap's background load offline + instant.
    win.heatmap_panel._quote_provider = lambda symbols, period=None, progress=None: {}
    # Simulate a completed scan (skip the ERROR row).
    win.scanner_panel.results = pd.DataFrame([
        {"Symbol": "AAPL", "Signal": "BUY"},
        {"Symbol": "MSFT", "Signal": "BUY"},
        {"Symbol": "BADX", "Signal": "ERROR"},
    ])
    assert win.scanner_panel.result_symbols() == ["AAPL", "MSFT"]   # ERROR filtered
    win.scanner_panel.show_results_in_heatmap()
    # Heatmap now sourced from the scan results, and that tab is fronted.
    assert win.heatmap_panel.market.currentText() == "Scanner results"
    assert win.heatmap_panel._symbols_for_market() == ["AAPL", "MSFT"]
    assert win.tabs.currentWidget() is win._heatmap_page
    win.heatmap_panel.shutdown()                    # join the background load


def test_map_results_with_no_scan_is_safe(qapp):
    import pandas as pd
    win = _main_window(qapp)
    win.scanner_panel.results = pd.DataFrame()
    win.scanner_panel.show_results_in_heatmap()   # must not raise
    assert "no results" in win.scanner_panel.status.text().lower()


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


def test_help_menu_has_a_revision_history_entry(qapp):
    win = _main_window(qapp)
    labels = [a.text() for a in win.help_menu.actions() if a.text()]
    assert "Revision history" in labels


def test_revision_history_shows_the_release_index_and_the_changelog(qapp, monkeypatch):
    from tradelab.ui import app as appmod
    from tradelab.core.config import APP_VERSION
    opened = {}

    def fake_exec(self):
        tabs = self.findChild(appmod.QTabWidget)
        opened["titles"] = [tabs.tabText(i) for i in range(tabs.count())]
        opened["text"] = "\n".join(
            tabs.widget(i).toPlainText() for i in range(tabs.count()))
        opened["window"] = self.windowTitle()
        opened["labels"] = [w.text() for w in self.findChildren(appmod.QLabel)]
        return 0

    monkeypatch.setattr(appmod.QDialog, "exec", fake_exec)
    win = _main_window(qapp)
    win.show_revision_history()

    assert opened["titles"] == ["Releases", "Full changelog"]
    assert "Revision history" in opened["window"]
    # The index really loaded, rather than the "not found" fallback.
    assert "2.41.0" in opened["text"]
    assert "no release index" not in opened["text"].lower()
    assert any(APP_VERSION in label for label in opened["labels"])


def test_packaged_build_ships_what_the_history_viewer_reads():
    """Help -> Revision history reads these at runtime, so a build that
    doesn't bundle them shows an empty viewer on a machine with no source."""
    spec = (ROOT / "TradeLabPro.spec").read_text(encoding="utf-8")
    assert '"docs/VERSIONS.md"' in spec
    assert '"CHANGELOG.md"' in spec


def test_table_fullscreen_hides_the_chart_and_restores_it(qapp):
    """The mirror of the chart's own full screen: the ETF Screener is 31
    columns wide and shares its width with a chart."""
    win = _main_window(qapp)

    win.toggle_panel_fullscreen()
    assert win._panel_full is True
    assert not win.chart.isVisible()
    assert win.tabs.isVisible()                       # the tabs keep the window
    assert win.etf_screener_panel.fullscreen_btn.text().startswith("⤢")

    win.toggle_panel_fullscreen()
    assert win._panel_full is False
    assert win.chart.isVisible()
    # Both panes are back; exact pixel sizes are Qt's to decide once the
    # window changes state, so don't assert them on a never-shown window.
    assert all(size > 0 for size in win.splitter.sizes())
    assert win.etf_screener_panel.fullscreen_btn.text().startswith("⛶")


def test_the_screener_button_is_wired_to_the_window(qapp):
    win = _main_window(qapp)
    assert win.etf_screener_panel.on_toggle_fullscreen == win.toggle_panel_fullscreen


def test_the_way_back_is_the_first_control_on_the_bar(qapp):
    win = _main_window(qapp)
    panel = win.etf_screener_panel
    bar = panel.fullscreen_btn.parentWidget()
    assert bar.layout().itemAt(0).widget() is panel.fullscreen_btn


def test_full_screen_brings_the_toolbar_back_into_view(qapp):
    """Every tab page is in a scroll area. Scrolled down to the table, the
    toolbar — and the only way out of full screen — is off the top."""
    from PySide6.QtWidgets import QScrollArea
    win = _main_window(qapp)
    panel = win.etf_screener_panel
    area = panel.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    assert area is not None, "the panel should sit in a scroll area"

    area.verticalScrollBar().setRange(0, 500)
    area.verticalScrollBar().setValue(500)      # scrolled down to the table
    win.toggle_panel_fullscreen()
    assert area.verticalScrollBar().value() == 0
    assert win.etf_screener_panel.fullscreen_btn.text().startswith("⤢")
    win.toggle_panel_fullscreen()


def test_panel_status_messages_reach_the_window_status_bar(qapp):
    """The per-panel line sits mid-page and is easy to look straight past;
    the status bar is where people expect "what just happened"."""
    win = _main_window(qapp)
    win.etf_screener_panel.status.setText("Column widths saved (31 columns).")
    assert "Column widths saved" in win.statusBar().currentMessage()

    win.watch_panel.status.setText("Watchlist: 4 symbols")
    assert "Watchlist: 4 symbols" in win.statusBar().currentMessage()


def test_every_panel_with_a_status_line_is_routed(qapp):
    from tradelab.ui.app import StatusLabel
    win = _main_window(qapp)
    routed = [name for name in dir(win)
              if name.endswith("_panel")
              and isinstance(getattr(getattr(win, name, None), "status", None), StatusLabel)]
    assert len(routed) >= 10, routed
    for name in routed:
        getattr(win, name).status.setText(f"probe from {name}")
        assert f"probe from {name}" in win.statusBar().currentMessage()


def test_an_empty_status_does_not_wipe_the_bar(qapp):
    win = _main_window(qapp)
    win.etf_screener_panel.status.setText("something happened")
    win.etf_screener_panel.status.setText("")        # panels clear their line
    assert "something happened" in win.statusBar().currentMessage()

"""Headless smoke tests for the Help menu (User Manual viewer + Version dialog)."""
import os
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

"""Problems are pop-ups, and links open in front: show_problem, flag_problem,
the error-log handler, and the link opener's second try and browser lookup."""
import logging
import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def popups(monkeypatch):
    """Real pop-ups for this test (the suite turns them off), closed after."""
    from tradelab.ui import common as appmod
    monkeypatch.delenv(appmod.NO_POPUPS_ENV, raising=False)
    yield appmod
    if appmod._problem_box is not None:
        appmod._problem_box.done(0)


def _visible_boxes():
    return [w for w in QApplication.topLevelWidgets()
            if isinstance(w, QMessageBox) and w.isVisible()]


def test_a_problem_is_a_popup(qapp, popups):
    popups.show_problem("Could not chart XYZ: no data")
    box = popups._problem_box
    assert box is not None and box.isVisible()
    assert box.text() == "Could not chart XYZ: no data"
    assert box.icon() == QMessageBox.Warning


def test_problems_arriving_together_share_one_popup(qapp, popups):
    for i in range(9):
        popups.show_problem(f"problem {i}")
    box = popups._problem_box
    assert _visible_boxes() == [box]
    assert "problem 0" in box.text() and "problem 5" in box.text()
    assert "problem 6" not in box.text() and "3 more" in box.text()


def test_a_closed_popup_makes_way_for_the_next(qapp, popups):
    popups.show_problem("first")
    popups._problem_box.done(0)
    assert popups._problem_box is None
    popups.show_problem("second")
    assert popups._problem_box.text() == "second"


def test_flag_problem_says_it_on_the_status_line_too(qapp, monkeypatch):
    from tradelab.ui import common as appmod
    shown = []
    monkeypatch.setattr(appmod, "show_problem", lambda text, parent=None: shown.append(text))
    label = appmod.StatusLabel("")
    appmod.flag_problem(label, "Import failed: bad file", "more detail")
    assert label.text() == "Import failed: bad file"
    assert shown == ["Import failed: bad file\n\nmore detail"]


def test_failure_messages_on_status_lines_pop_up(qapp, tmp_path, monkeypatch):
    # One of the converted call sites, end to end: an unreadable links CSV.
    from tradelab.core.links import LinkStore
    from tradelab.ui import common as appmod
    shown = []
    monkeypatch.setattr(appmod, "show_problem", lambda text, parent=None: shown.append(text))

    def unreadable(path):
        raise ValueError("not a CSV")

    monkeypatch.setattr(appmod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "bad.csv"), "")))
    monkeypatch.setattr(appmod.pd, "read_csv", unreadable)
    from tradelab.ui.app import LinksPanel
    panel = LinksPanel(store=LinkStore(tmp_path / "links.json"))
    panel.import_csv()
    assert shown == ["Import failed: not a CSV"]


def test_logged_errors_become_popups(qapp, monkeypatch):
    from tradelab.ui import common as appmod
    reported = []
    monkeypatch.setattr(appmod, "report_problem", reported.append)
    logger = logging.getLogger("tradelab.test_problem_popups")
    handler = appmod.ProblemPopupHandler()
    logger.addHandler(handler)
    try:
        logger.warning("only a warning")
        logger.error("shown already", extra={"popup": False})
        try:
            raise ValueError("no network")
        except ValueError:
            logger.exception("Auto-refresh of HomePanel failed")
    finally:
        logger.removeHandler(handler)
    assert reported == ["Auto-refresh of HomePanel failed: no network"]


def test_a_problem_from_a_worker_thread_is_shown_on_the_gui_thread(qapp, monkeypatch):
    from tradelab.ui import common as appmod
    shown = []
    monkeypatch.setattr(appmod, "show_problem", lambda text, parent=None: shown.append(
        (text, QThread.currentThread() == qapp.thread())))
    monkeypatch.setattr(appmod, "_problem_bridge", appmod._ProblemBridge())
    worker = threading.Thread(target=appmod.report_problem, args=("from a worker",))
    worker.start()
    worker.join()
    qapp.processEvents()
    assert shown == [("from a worker", True)]


# --- opening links ------------------------------------------------------------

def _opener(monkeypatch, qt_result, shell_result=None):
    from tradelab.ui import common as appmod
    calls = []
    monkeypatch.setattr(appmod.QDesktopServices, "openUrl",
                        staticmethod(lambda url: calls.append(("qt", url.toString())) or qt_result))
    monkeypatch.setattr(appmod, "_shell_open",
                        lambda text: calls.append(("shell", text)) or shell_result)
    monkeypatch.setattr(appmod, "_allow_foreground", lambda: calls.append(("allow",)))
    monkeypatch.setattr(appmod, "_bring_browser_forward_soon",
                        lambda scheme="https": calls.append(("forward", scheme)))
    return appmod, calls


def test_a_link_opens_with_the_browser_brought_forward(qapp, monkeypatch):
    appmod, calls = _opener(monkeypatch, qt_result=True)
    assert appmod.open_external("https://example.com/a") is None
    assert calls == [("allow",), ("qt", "https://example.com/a"), ("forward", "https")]


def test_a_link_qt_refuses_is_tried_through_the_shell(qapp, monkeypatch):
    appmod, calls = _opener(monkeypatch, qt_result=False, shell_result=None)
    assert appmod.open_external("https://example.com/a") is None
    assert ("shell", "https://example.com/a") in calls
    assert calls[-1] == ("forward", "https")


def test_a_link_nothing_opens_says_why(qapp, monkeypatch):
    appmod, calls = _opener(monkeypatch, qt_result=False, shell_result="Access is denied.")
    assert appmod.open_external("https://example.com/a") == "Access is denied."
    assert ("forward", "https") not in calls


def test_a_file_opens_without_moving_any_browser(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QUrl
    appmod, calls = _opener(monkeypatch, qt_result=True)
    assert appmod.open_external(QUrl.fromLocalFile(str(tmp_path / "manual.pdf"))) is None
    assert [c[0] for c in calls] == ["qt"]


def test_the_headless_test_platform_never_launches_anything(qapp, monkeypatch):
    from tradelab.ui import common as appmod
    monkeypatch.setattr(appmod.os, "startfile", lambda *a: pytest.fail("launched"), raising=False)
    assert appmod._shell_open("https://example.com") == "there is no desktop to open it on"


def test_the_browser_program_is_read_from_its_open_command():
    from tradelab.ui.app import browser_exe_from_command as exe
    assert exe(r'"C:\Users\x\AppData\Local\Programs\Opera\opera.exe" -noautoupdate -- "%1"') == "opera.exe"
    assert exe(r'"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --single-argument %1') == "msedge.exe"
    assert exe(r'C:\Program Files\Mozilla Firefox\firefox.exe -osint -url "%1"') == "firefox.exe"
    assert exe("") is None

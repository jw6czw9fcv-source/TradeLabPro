"""Closing the window while a thread is still working.

A QThread destroyed while it is still running ends the process abnormally.
Sixteen panels that start threads stop them on close; two did not — the
Scanner, whose scan can run for minutes, and AI Assist, whose request can
take a minute — and closing the app mid-scan exited with code 127 where a
clean close exits 0. These tests hold the line for every panel, including
the ones written after them.
"""
import inspect
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _main_window(qapp):
    from tradelab.ui.app import MainWindow
    return MainWindow()


def _slow_scan(symbols, cfg):
    """A scan that takes seconds and, like the real one, checks its stop flag
    between symbols."""
    from tradelab.ui.app import ScanWorker

    class SlowScan(ScanWorker):
        def run(self):
            for _ in range(200):
                if self._stop:
                    return
                time.sleep(0.02)
    return SlowScan(symbols, cfg)


def test_closing_mid_scan_stops_the_scan(qapp):
    win = _main_window(qapp)
    panel = win.scanner_panel
    worker = _slow_scan([], panel.cfg)
    panel.scan_worker = worker
    worker.start()
    time.sleep(0.05)
    assert worker.isRunning()

    win.close()
    assert not worker.isRunning(), "the scan outlived the window"
    assert panel.scan_worker is None


def test_the_scanner_can_be_shut_down_with_nothing_running(qapp):
    win = _main_window(qapp)
    win.scanner_panel.shutdown()          # must not raise
    win.scanner_panel.shutdown()          # nor the second time


def test_closing_mid_answer_lets_the_ai_request_finish_quietly(qapp):
    """A half-sent request cannot be cancelled; it is disconnected, so a late
    reply cannot write into a widget that no longer exists, and waited for."""
    from tradelab.ui.app import _AIWorker

    class SlowAnswer(_AIWorker):
        def run(self):
            time.sleep(0.3)
            self.done.emit("too late")

    win = _main_window(qapp)
    panel = win.ai_panel
    received = []
    worker = SlowAnswer([], "key", "model", "")
    worker.done.connect(received.append)
    panel._worker = worker
    worker.start()

    win.close()
    assert not worker.isRunning()
    assert panel._worker is None
    qapp.processEvents()
    assert received == [], "a reply arrived after the panel had shut down"


# -- the rule, for every panel ---------------------------------------------------

def _panels_that_start_threads():
    import tradelab.ui.app as app
    from PySide6.QtWidgets import QWidget
    found = []
    for name, cls in vars(app).items():
        if not (inspect.isclass(cls) and issubclass(cls, QWidget)) or cls.__module__ != app.__name__:
            continue
        source = inspect.getsource(cls)
        if "Worker(" in source and ".start()" in source:
            found.append(cls)
    return found


def test_every_panel_that_starts_a_thread_can_stop_it():
    """How both misses would have been caught. A panel that starts a worker
    thread must be able to stop it, or the window cannot close cleanly while
    it runs."""
    panels = _panels_that_start_threads()
    assert len(panels) >= 16, "the scan for thread-starting panels found too few"
    missing = [cls.__name__ for cls in panels if not hasattr(cls, "shutdown")]
    assert not missing, f"start threads but have no shutdown(): {missing}"


def test_the_window_stops_every_panel_that_can_be_stopped(qapp, monkeypatch):
    """Having shutdown() is half of it; closeEvent has to call it."""
    win = _main_window(qapp)
    called, expected = [], []
    for attr, panel in vars(win).items():
        if attr.endswith("_panel") and hasattr(panel, "shutdown"):
            expected.append(attr)
            monkeypatch.setattr(panel, "shutdown",
                                lambda a=attr: called.append(a))
    win.close()
    assert sorted(called) == sorted(expected), (
        f"never stopped on close: {sorted(set(expected) - set(called))}")

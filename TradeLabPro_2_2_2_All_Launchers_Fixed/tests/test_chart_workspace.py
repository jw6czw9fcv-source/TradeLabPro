"""Regression tests for ChartWorkspace's multi-tab dock handling.

Covers a real bug: opening a second chart tab immediately made the
workspace forget the first tab ever existed (visibilityChanged fires on
every tab-switch hide, not just real closes), and the newly opened tab
never actually became the visible/active one (dock.raise_() called before
Qt finishes processing tabifyDockWidget() is a no-op).
"""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QTabBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def test_opening_second_chart_keeps_both_tracked(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)

    ws.add_chart("MSFT")
    _pump(qapp)

    assert len(ws._docks) == 2
    assert len(ws._panels) == 2
    assert [d.windowTitle() for d in ws._docks] == ["AAPL", "MSFT"]


def test_opening_second_chart_raises_it_to_front(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)

    ws.add_chart("MSFT")
    _pump(qapp)

    tabbars = ws._dock_host.findChildren(QTabBar)
    assert len(tabbars) == 1
    tabbar = tabbars[0]
    assert tabbar.tabText(tabbar.currentIndex()) == "MSFT"
    assert ws.current_chart().symbol == "MSFT"


def test_actually_closing_a_tab_still_prunes_it(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)
    ws.add_chart("MSFT")
    _pump(qapp)
    assert len(ws._docks) == 2

    msft_dock = ws._docks[1]
    msft_dock.close()
    _pump(qapp)

    assert len(ws._docks) == 1
    assert ws._docks[0].windowTitle() == "AAPL"


def _tab_buttons(ws):
    # Close ("x") buttons share the row now - filter to the checkable
    # switcher buttons specifically, since close buttons aren't checkable.
    layout = ws._chart_tabs_layout
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    return [(w.text(), w.isChecked()) for w in widgets if w.isCheckable()]


def test_chart_switcher_row_shows_one_button_per_open_chart(qapp):
    """Explicit switcher row - regression coverage for "how do I switch
    chart, I don't see the second one" - the native QDockWidget tab bar is
    easy to miss, so this row exists as a guaranteed-visible alternative.
    """
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)
    assert _tab_buttons(ws) == [("AAPL", True)]

    ws.add_chart("MSFT")
    _pump(qapp)
    assert _tab_buttons(ws) == [("AAPL", False), ("MSFT", True)]


def test_clicking_a_switcher_button_activates_that_chart(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)
    ws.add_chart("MSFT")
    _pump(qapp)
    assert ws.current_chart().symbol == "MSFT"

    aapl_button = ws._chart_tabs_layout.itemAt(0).widget()
    aapl_button.click()
    _pump(qapp)

    assert ws.current_chart().symbol == "AAPL"
    assert _tab_buttons(ws) == [("AAPL", True), ("MSFT", False)]


def test_reset_charts_collapses_back_to_a_single_clean_chart(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)
    ws.add_chart("MSFT")
    ws.add_chart("GOOG")
    _pump(qapp)
    assert len(ws._docks) == 3

    ws.reset_charts()
    _pump(qapp)

    assert len(ws._docks) == 1
    assert len(ws._panels) == 1
    assert ws._docks[0].windowTitle() == "AAPL"
    assert _tab_buttons(ws) == [("AAPL", True)]


def test_dock_native_title_bar_is_hidden(qapp):
    """The dock's native title bar just repeated the symbol the switcher
    row and the chart's own search box already show, right above each
    other - regression test for that duplication being removed.
    """
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)

    # QDockWidget.titleBarWidget() returns None unless you've explicitly
    # replaced it - a non-None (empty) widget is how the native title bar,
    # and the symbol text on it, gets hidden.
    assert ws._docks[0].titleBarWidget() is not None


def test_close_button_only_appears_with_more_than_one_chart_open(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)
    layout = ws._chart_tabs_layout
    assert all(w.isCheckable() for w in (layout.itemAt(i).widget() for i in range(layout.count())))  # no close btn yet

    ws.add_chart("MSFT")
    _pump(qapp)
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    close_buttons = [w for w in widgets if not w.isCheckable()]
    assert len(close_buttons) == 2  # one per chart, now that there are 2


def test_close_button_closes_only_that_chart(qapp):
    from tradelab.ui.workspace.chart_workspace import ChartWorkspace

    ws = ChartWorkspace()
    ws.show()
    _pump(qapp)
    ws.add_chart("MSFT")
    _pump(qapp)
    assert len(ws._docks) == 2

    layout = ws._chart_tabs_layout
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    # Layout order per dock is [switcher_button, close_button] - the close
    # button for AAPL (the first dock) is right after its switcher button.
    aapl_close_button = widgets[1]
    assert not aapl_close_button.isCheckable()
    aapl_close_button.click()
    _pump(qapp)

    assert len(ws._docks) == 1
    assert ws._docks[0].windowTitle() == "MSFT"

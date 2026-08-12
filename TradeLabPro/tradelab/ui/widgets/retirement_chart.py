"""The retirement projection, drawn — with a saved run kept beside it.

A projection is only useful against something. Change the spending by five
thousand and the table of numbers changes everywhere at once, which is hard
to read; two lines on one chart answer "better or worse, and from when" at a
glance.

So this holds two series. The **saved** one stays until it is explicitly
replaced — closing the app does not clear it — and the **current** one
redraws on every run. That asymmetry is the whole point: a baseline that
moved every time you experimented would not be a baseline.

Like the other chart widgets here, this one holds no projection maths. It
draws series someone else computed.
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tradelab.ui import theme
from tradelab.ui.widgets.equity_curve import MoneyAxis
from tradelab.ui.widgets.pg_chart_widget import GRID_ALPHA

SAVED_COLOUR = theme.MUTED
CURRENT_COLOUR = theme.UP


class RetirementChartWidget(QWidget):
    """Public API:
        show_projection(years, balances, label, band=None)
        show_saved(saved)     # {"years", "balances", "label"} or None
        clear(message)
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.title = QLabel("Retirement projection")
        self.title.setStyleSheet(
            "color: " + theme.TEXT + "; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.title)

        self.plot = pg.PlotWidget(axisItems={"left": MoneyAxis(orientation="left")})
        self.plot.setBackground(None)
        self.plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self.plot.setLabel("bottom", "Year")
        self.plot.getPlotItem().getViewBox().setDefaultPadding(0.05)
        layout.addWidget(self.plot, 1)

        self.footnote = QLabel("")
        self.footnote.setWordWrap(True)
        self.footnote.setStyleSheet("color: " + theme.MUTED + "; font-size: 11px;")
        layout.addWidget(self.footnote)

        self._saved = None
        self._current = None
        self._legend = None
        self.clear("Run a projection to draw it here.")

    # -- drawing -------------------------------------------------------------
    def clear(self, message: str = ""):
        self.plot.clear()
        self._legend = None
        if message:
            self.footnote.setText(message)

    def show_saved(self, saved):
        """The kept run. None removes it."""
        self._saved = saved or None
        self._redraw()

    def show_projection(self, years, balances, label="Current", band=None):
        """`band` is an optional (low, high) pair of series — the percentile
        spread from a many-path run. Drawn as a shaded region, because a
        single median line from hundreds of paths would claim more precision
        than the run supports."""
        self._current = {"years": list(years), "balances": list(balances),
                         "label": label, "band": band}
        self._redraw()

    def _redraw(self):
        self.plot.clear()
        self._legend = self.plot.addLegend(offset=(10, 10),
                                           labelTextColor=theme.TEXT,
                                           brush=pg.mkBrush(17, 21, 28, 200))
        drawn = []

        if self._current and self._current.get("band"):
            low, high = self._current["band"]
            years = self._current["years"]
            lower = self.plot.plot(years, list(low), pen=pg.mkPen(CURRENT_COLOUR, width=1))
            upper = self.plot.plot(years, list(high), pen=pg.mkPen(CURRENT_COLOUR, width=1))
            fill = pg.FillBetweenItem(lower, upper, brush=pg.mkBrush(63, 185, 80, 40))
            self.plot.addItem(fill)

        if self._saved:
            # Dashed and muted: it is a reference, and it should not compete
            # with the run being looked at.
            self.plot.plot(self._saved["years"], self._saved["balances"],
                           pen=pg.mkPen(SAVED_COLOUR, width=2, style=Qt.DashLine),
                           name=self._saved.get("label") or "Saved")
            drawn.append("saved")

        if self._current:
            self.plot.plot(self._current["years"], self._current["balances"],
                           pen=pg.mkPen(CURRENT_COLOUR, width=2),
                           name=self._current.get("label") or "Current")
            drawn.append("current")

        # A projection crossing zero is the whole question, so the line is
        # always in view rather than left off the bottom of the axis.
        self.plot.addLine(y=0, pen=pg.mkPen(theme.MUTED, width=1, style=Qt.DotLine))

        if not drawn:
            self.footnote.setText("Run a projection to draw it here.")
        elif "saved" in drawn and "current" in drawn:
            self.footnote.setText(
                "Dashed is the run you saved; solid is the current one. The saved line "
                "changes only when you press Save sim — a baseline that moved with every "
                "experiment would not be one. Today's dollars.")
        elif "saved" in drawn:
            self.footnote.setText("Your saved run. Today's dollars.")
        else:
            self.footnote.setText(
                "Press Save sim to keep this as the line to compare against. "
                "Today's dollars.")

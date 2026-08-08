"""A compact equity-curve plot for the Home tab.

The book's value over a window, drawn the way a broker draws an account chart:
one line, an area under it tinted by the direction of the period, a dashed line
at the value it started from, and a readout that follows the cursor. It renders
a series someone else computed — this file contains no portfolio maths, so the
chart can never disagree with the figures beside it.

Bars are plotted at their index (0, 1, 2 …) rather than at a timestamp, the same
as the main chart: weekends and holidays would otherwise leave dead space in a
year-long line. `BarDateAxis` maps those positions back to real dates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from tradelab.ui import theme
from tradelab.ui.widgets.pg_chart_widget import BarDateAxis, GRID_ALPHA


def _small_font() -> QFont:
    font = QFont()
    font.setPointSize(8)
    return font


def _money(value: float, decimals: int = 0) -> str:
    """A dollar figure short enough for an axis tick: 1.24M / 412k / 950."""
    v = float(value)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.2f}M"
    if abs(v) >= 10_000:
        return f"${v / 1_000:,.0f}k"
    return f"${v:,.{decimals}f}"


class MoneyAxis(pg.AxisItem):
    """Left axis in short dollars. A book worth 412,300 needs '$412k' on the
    axis; the exact figure belongs in the tile above the chart, not repeated
    six times down the side of it."""

    def tickStrings(self, values, scale, spacing):
        return [_money(v) for v in values]


class EquityCurveWidget(QWidget):
    """Plots a value series with a title, a hover readout and a footnote.

    Public API:
        show_curve(data, title=..., footnote=...)  — draw a core.home ytd_curve
        clear_curve(message)                       — say why there's no chart
    """

    def __init__(self, height: int = 210, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        self.title = QLabel("This year")
        self.title.setStyleSheet("font-weight:bold;")
        head.addWidget(self.title)
        head.addStretch()
        # Follows the cursor across the line; falls back to the period summary
        # when the mouse is elsewhere, so the space is never blank.
        self.readout = QLabel("")
        self.readout.setStyleSheet(f"color:{theme.MUTED};")
        head.addWidget(self.readout)
        layout.addLayout(head)

        self.plot = pg.PlotWidget(axisItems={"bottom": BarDateAxis(orientation="bottom"),
                                             "left": MoneyAxis(orientation="left")})
        # Capped as well as floored: a PlotWidget expands by default, and on
        # Home that pushed "Needs attention" and the day's movers off the
        # bottom of the tab. The chart is one section of the screen, not the
        # screen.
        self.plot.setMinimumHeight(height)
        self.plot.setMaximumHeight(int(height * 1.4))
        self.plot.showGrid(x=False, y=True, alpha=GRID_ALPHA)
        # A glance chart, not a workspace: dragging it around would only leave
        # the user with a view they have to reset. The Chart tab is for that.
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.getPlotItem().setContentsMargins(0, 6, 8, 0)
        layout.addWidget(self.plot)

        self.footnote = QLabel("")
        self.footnote.setWordWrap(True)
        self.footnote.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(self.footnote)

        self._curve = self.plot.plot([], [], pen=pg.mkPen(theme.UP, width=2))
        self._fill = None
        self._baseline = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen(theme.MUTED, width=1,
                                                      style=Qt.DashLine))
        self._baseline.setVisible(False)
        self.plot.addItem(self._baseline, ignoreBounds=True)
        # A dashed line with no explanation is decoration; this says what it is.
        # Filled, because a flat year runs the curve straight through the label.
        self._baseline_label = pg.InfLineLabel(self._baseline, text="", position=0.03,
                                               color=theme.MUTED, anchors=[(0, 1), (0, 1)],
                                               fill=pg.mkBrush(17, 21, 28, 210))
        self._baseline_label.setFont(_small_font())
        self._crosshair = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen("#666f78", width=1))
        self._crosshair.setVisible(False)
        self.plot.addItem(self._crosshair, ignoreBounds=True)
        self._dot = pg.ScatterPlotItem(size=7, brush=pg.mkBrush(theme.TEXT),
                                       pen=pg.mkPen("#11151c", width=1))
        self._dot.setVisible(False)
        self.plot.addItem(self._dot)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self._values = np.array([], dtype=float)
        self._dates = []
        self._start = None
        self._summary = ""
        self._currency = None

    # --- drawing ------------------------------------------------------------

    def show_curve(self, data: dict, title: str = None, footnote: str = ""):
        """Draw a `core.home.ytd_curve` result (or any dict with `series` and
        `start_value`). A falsy `data` clears the chart instead."""
        if not data or data.get("series") is None or len(data["series"]) < 2:
            self.clear_curve()
            return
        series = data["series"]
        values = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
        if values.shape[0] < 2:
            self.clear_curve()
            return

        self._values = values.to_numpy(dtype=float)
        self._dates = list(pd.to_datetime(values.index))
        self._start = float(data.get("start_value") or self._values[0])
        self._currency = data.get("currency")
        self._summary = data.get("text") or ""
        if title:
            self.title.setText(title)
        self.footnote.setText(footnote)

        x = np.arange(len(self._values), dtype=float)
        # Green for a year that's up, red for one that's down — the same pair
        # every P&L figure in the app uses.
        colour = theme.pnl_color(self._values[-1] - self._start)
        self._curve.setData(x, self._values, pen=pg.mkPen(colour, width=2))

        # The area under the line, tinted the same way but faintly, so the
        # chart reads as a balance rather than as a price.
        if self._fill is not None:
            self.plot.removeItem(self._fill)
        floor = float(self._values.min())
        pad = (float(self._values.max()) - floor) * 0.12 or max(abs(floor) * 0.01, 1.0)
        tint = pg.mkColor(colour)
        tint.setAlpha(38)
        self._fill = pg.PlotCurveItem(x, self._values, fillLevel=floor - pad,
                                      brush=pg.mkBrush(tint), pen=pg.mkPen(None))
        self.plot.addItem(self._fill)

        self._baseline.setPos(self._start)
        self._baseline.setVisible(True)
        anchor = ("last year's close" if data.get("from_last_year")
                  else f"{self._dates[0]:%d %b}")
        self._baseline_label.setFormat(f"{anchor}  {_money(self._start)}")
        self.plot.getAxis("bottom").set_index(values.index)
        self.plot.setXRange(0, len(x) - 1, padding=0.01)
        low = min(floor, self._start)
        high = max(float(self._values.max()), self._start)
        margin = (high - low) * 0.12 or max(abs(high) * 0.01, 1.0)
        self.plot.setYRange(low - margin, high + margin, padding=0)
        self.readout.setText(self._summary)

    def clear_curve(self, message: str = "Not enough of this year priced yet to draw a curve."):
        self._values = np.array([], dtype=float)
        self._dates = []
        self._start = None
        self._summary = ""
        self._curve.setData([], [])
        if self._fill is not None:
            self.plot.removeItem(self._fill)
            self._fill = None
        self._baseline.setVisible(False)
        self._baseline_label.setFormat("")
        self._crosshair.setVisible(False)
        self._dot.setVisible(False)
        self.plot.getAxis("bottom").set_index([])
        self.readout.setText(message)
        self.footnote.setText("")

    # --- cursor readout -----------------------------------------------------

    def _on_mouse_moved(self, pos):
        if self._values.size == 0:
            return
        vb = self.plot.getPlotItem().vb
        if not self.plot.sceneBoundingRect().contains(pos):
            self._crosshair.setVisible(False)
            self._dot.setVisible(False)
            self.readout.setText(self._summary)
            return
        i = int(round(vb.mapSceneToView(pos).x()))
        i = max(0, min(len(self._values) - 1, i))
        value = float(self._values[i])
        self._crosshair.setPos(i)
        self._crosshair.setVisible(True)
        self._dot.setData([i], [value])
        self._dot.setVisible(True)
        self.readout.setText(self._point_text(i, value))

    def _point_text(self, i: int, value: float) -> str:
        ccy = f" {self._currency}" if self._currency else ""
        stamp = self._dates[i].strftime("%d %b") if i < len(self._dates) else ""
        text = f"{stamp}  ${value:,.0f}{ccy}"
        if self._start:
            pct = (value / self._start - 1.0) * 100.0
            text += f"  ({pct:+.1f}%)"
        return text

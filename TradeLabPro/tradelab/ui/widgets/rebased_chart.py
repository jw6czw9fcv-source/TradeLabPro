"""Several funds on one chart, all starting from the same line.

A plan's funds are priced at whatever level history left them at — one unit of
Indiciel équilibré is $504.68, one unit of Act. Américaines is $84.53. Plotted
raw, that is seven lines at seven altitudes and no comparison at all. Rebased to
100 at the first statement they share a starting point, and the only thing left
on screen is relative performance: the laggard is the line at the bottom.

Points are plotted at real timestamps rather than at bar indices (the main chart's
convention) because statements are sparse and irregular — two dots eight months
apart have to sit eight months apart, or the slope lies.

Like the equity curve beside it, this file holds no maths: it draws a
`core.retirement.rebased()` result and nothing else.
"""
from __future__ import annotations

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from tradelab.ui import theme
# The categorical palette: these colours separate one fund from another and
# carry no good/bad meaning, which is exactly why they live with the chart
# overlays rather than in theme.py's semantic set.
from tradelab.ui.widgets.pg_chart_widget import _OVERLAY_COLORS as SERIES_COLORS
from tradelab.ui.widgets.pg_chart_widget import GRID_ALPHA

BASE = 100.0


class RebasedChartWidget(QWidget):
    """Plots {fund name: {"dates": [...], "values": [...]}} rebased to 100.

    Public API:
        show_funds(rebased, title=..., footnote=...)
        clear(message)
    """

    def __init__(self, height: int = 260, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        self.title = QLabel("Each fund since your first statement (rebased to 100)")
        self.title.setStyleSheet("font-weight:bold;")
        head.addWidget(self.title)
        head.addStretch()
        self.readout = QLabel("")
        self.readout.setStyleSheet(f"color:{theme.MUTED};")
        head.addWidget(self.readout)
        layout.addLayout(head)

        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.plot.setMinimumHeight(height)
        self.plot.setMaximumHeight(int(height * 1.6))
        self.plot.showGrid(x=False, y=True, alpha=GRID_ALPHA)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.getPlotItem().setContentsMargins(0, 6, 8, 0)
        layout.addWidget(self.plot)

        self.footnote = QLabel("")
        self.footnote.setWordWrap(True)
        self.footnote.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(self.footnote)

        self._legend = None
        self._curves: list = []
        # 100 is where every fund started; without the line, a chart of seven
        # rising curves looks like seven winners.
        self._baseline = pg.InfiniteLine(angle=0, movable=False, pos=BASE,
                                         pen=pg.mkPen(theme.MUTED, width=1,
                                                      style=Qt.DashLine))
        self._baseline.setVisible(False)
        self.plot.addItem(self._baseline, ignoreBounds=True)

    # --- drawing ------------------------------------------------------------

    def show_funds(self, rebased: dict, title: str = None, footnote: str = ""):
        """Draw one line per fund. A falsy `rebased` clears the chart."""
        self._clear_items()
        if not rebased:
            self.clear()
            return
        if title:
            self.title.setText(title)
        self.footnote.setText(footnote)

        self._legend = self.plot.addLegend(offset=(10, 10),
                                           labelTextColor=theme.TEXT,
                                           brush=pg.mkBrush(17, 21, 28, 200),
                                           pen=pg.mkPen("#2a2f38"))
        lows, highs = [], []
        # Worst-to-best so the winning line is drawn last and sits on top where
        # two funds overlap.
        ordered = sorted(rebased.items(), key=lambda kv: kv[1]["values"][-1])
        for i, (name, series) in enumerate(ordered):
            values = [float(v) for v in series["values"]]
            stamps = [pd.Timestamp(d).timestamp() for d in series["dates"]]
            if len(values) < 2:
                continue
            colour = SERIES_COLORS[i % len(SERIES_COLORS)]
            pen = pg.mkPen(colour, width=2)
            curve = self.plot.plot(stamps, values, pen=pen,
                                   name=f"{name}  {values[-1] - BASE:+.1f}%",
                                   symbol="o", symbolSize=5,
                                   symbolBrush=pg.mkBrush(colour),
                                   symbolPen=pg.mkPen(None))
            self._curves.append(curve)
            lows.append(min(values))
            highs.append(max(values))

        if not self._curves:
            self.clear()
            return
        self._baseline.setVisible(True)
        low, high = min(lows + [BASE]), max(highs + [BASE])
        margin = (high - low) * 0.12 or 1.0
        self.plot.setYRange(low - margin, high + margin, padding=0)
        self.plot.enableAutoRange(axis="x")
        self.readout.setText(f"{len(self._curves)} funds")

    def clear(self, message: str = "Two statement dates are needed before funds "
                                   "can be compared."):
        self._clear_items()
        self._baseline.setVisible(False)
        self.readout.setText(message)
        self.footnote.setText("")

    def _clear_items(self):
        for curve in self._curves:
            self.plot.removeItem(curve)
        self._curves = []
        if self._legend is not None:
            try:
                self._legend.scene().removeItem(self._legend)
            except (AttributeError, RuntimeError):
                pass
            self._legend = None

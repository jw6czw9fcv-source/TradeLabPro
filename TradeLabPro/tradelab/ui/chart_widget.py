"""Compatibility shim.

Chart Engine Phase 1 replaced the matplotlib-based chart core with a
PyQtGraph-based one (dockable panels, drawing tools, more overlays - see
tradelab/ui/widgets/pg_chart_widget.py and tradelab/ui/workspace/chart_workspace.py).

app.py imports `ChartWorkspace` and `ChartWidget` from this module, so this
file re-exports the new implementations under the old names rather than
requiring changes throughout app.py. The previous matplotlib implementation
lives in git history; it was removed together with matplotlib, which
nothing else in the app used.
"""
from tradelab.ui.workspace.chart_workspace import ChartWorkspace
from tradelab.ui.widgets.pg_chart_widget import PGChartWidget as ChartWidget

__all__ = ["ChartWorkspace", "ChartWidget"]

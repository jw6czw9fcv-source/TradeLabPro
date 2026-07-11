# TradeLab Pro Project Status

Current version: 2.2.0
Current phase: Phase 1 - Chart Engine (complete)

## Completed in 2.2.0 (Chart Engine Phase 1)
- Dockable, resizable, floatable chart workspace (QDockWidget-based), replacing fixed tabs.
- Chart rendering rewritten from matplotlib to PyQtGraph for responsive pan/zoom/crosshair.
- Drawing tools: trendline, H-line, V-line, rectangle, Fibonacci retracement, text notes. Persisted per symbol/timeframe.
- Chart types: Candlestick, Heikin-Ashi, Line, Area.
- New overlays: VWAP, Pivot Points, SuperTrend, Ichimoku Cloud, Volume Profile.
- Synced crosshair across price/volume/MACD/RSI panes.
- Saved/loadable named chart layouts.
- Centralized rotating-file logging.
- Versioned database migrations.
- BUG-003 (crosshair label stabilization) resolved.
- BUG-009 (open chart in new tab) superseded by dockable panels.
- pytest regression suite established: 47 tests, all passing. This is now mandatory to keep passing before any release closes.
- Found and fixed a real bug in the offline synthetic-data fallback (array length could mismatch date index depending on pandas version).

## Open / Watch
- BUG-005 Stop Scanner remains under user validation.
- BUG-006 Canadian ticker coverage remains under user validation.
- SCN-026 IBKR-style Technical Filter Builder planned.
- `app.py` (76KB) is still a UI monolith. Splitting it into `tradelab/ui/panels/` and `tradelab/ui/widgets/` is planned to start alongside Phase 2 (Scanner Pro), not yet done.
- Strategy/plugin interface unification (formal `Strategy` base class + auto-discovery) not yet done — planned for Phase 2/5.
- Dependency versions pinned in 2.2.0; re-verify against your actual installed environment (`pip freeze`) before your next release, since exact patch versions may need adjustment for your machine.

## Next
- Phase 2: Scanner Professional (multi-strategy, sector/market-cap breakdown, preset manager - SCN-029).

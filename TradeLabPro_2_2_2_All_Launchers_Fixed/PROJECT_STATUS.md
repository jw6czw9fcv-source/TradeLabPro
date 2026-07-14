# TradeLab Pro Project Status

Current version: 2.10.1
Current phase: Phase 6 - Plugin SDK (done)

## Completed in 2.10.1 (Company name on chart + sub-pane safeguard)
- Price pane now shows the full company name above the indicator legend (`AAPL — Apple Inc.`), via `get_quote_meta`; falls back to the ticker.
- Indicators dialog sub-pane safeguard: "Show Volume/RSI/MACD" toggles separated from their period fields, plus a "Show all sub-panes" one-click restore, so panes can't be lost by accident.
- pytest regression suite now 280 tests, all passing.

## Completed in 2.10.0 (Plugin SDK, Phase 6)
- `tradelab/core/plugins.py`: auto-discovers `.py` files in `plugins/` that define `PLUGIN_NAME` + `compute(df)`, registering each as an indicator field (`plugin:<name>`) usable in Scanner filters and the Strategy Builder. Errors are surfaced, never fatal. Runs at startup and via the Plugins tab's Reload.
- Bundled `plugins/sample_hl_range.py` template; Plugins tab rebuilt to show loaded/errored plugins.
- pytest regression suite now 278 tests, all passing.

## Completed in 2.9.0 (No-code Strategy Builder + configurable indicators, Phase 5)
- No-code Strategy Builder: BUY/SELL condition blocks -> saveable custom strategies (`tradelab/strategies/custom.py`, persisted in data/strategies/) that run in the Scanner and Backtest like built-ins.
- Expanded indicator library (Stochastic, Williams %R, CCI, ROC, OBV, MFI, VWAP).
- Field-vs-field comparison operators ("Above/Below field") for crossover-style conditions.
- Period-parameterized fields everywhere with standard defaults + on-demand computation (`ensure_columns`); legacy keys auto-migrate.
- Chart indicator manager (add/remove overlays with tunable periods), configurable MACD/RSI sub-pane periods, and a clickable on-chart legend that opens the editor.
- pytest regression suite now 269 tests, all passing.
- data/setups/ and data/strategies/ added to .gitignore (runtime user data).

## Completed in 2.8.0 (Backtesting Lab, Phase 4)
- `tradelab/core/backtest.py`: strategy-agnostic engine - single-symbol simulation, multi-symbol aggregation, single-parameter optimization, and walk-forward analysis with a consistency score. Adds Max drawdown %. Qt-free, offline-testable.
- Backtest tab rebuilt from dead code into 4 sub-tabs (Single / Multi-Symbol / Optimize / Walk-Forward) and registered as a tab. Includes plain-language hints + colour-coded verdicts that interpret the numbers for the user (backtesting is abstract; the tab now explains itself).
- Fixed a real bug: backtest prep did a blanket dropna() that threw away ~199 bars just for SMA200 warmup no signal uses; now drops only actual signal-input warmup (~35 bars).
- pytest regression suite now 225 tests, all passing.

## Completed in 2.7.0 (Market Dashboard, Phase 3)
- `tradelab/core/market.py`: Qt-free dashboard logic - 11 SPDR sector ETFs, per-symbol trend analysis (last / % change / above 50- & 200-day SMA), sector-breadth counts, and a transparent `market_condition()` "is it a good day to trade" 0-100 read with reasons.
- Market tab UI rebuilt from a placeholder into: a colour-coded macro read headline + reasons, a sector-breadth table across all 11 sector ETFs, and a breadth summary line, on top of the existing regime-symbol table (which now feeds the read).
- pytest regression suite now 201 tests, all passing.

## Completed in 2.6.1 (Junk-symbol filter fix)
- Fixed non-ticker junk (e.g. "41") appearing in scan results: `is_tradeable_symbol()` now requires at least one letter, rejecting purely-numeric strings from bad feed lines while keeping every real ticker. 26-case regression test in `tests/test_universe.py`.
- pytest regression suite now 187 tests, all passing.

## Completed in 2.6.0 (Sector/market-cap context, multi-strategy scanning, confidence scoring, SCN-030)
Completes the last roadmap bullet for Phase 2 - all three pieces in one release:
- Fixed a real bug: `get_quote_meta()` was a complete stub returning a fake market cap seeded from `hash(symbol)` - never real data. Now fetches real market cap + sector + industry via yfinance, cached in-process.
- Sector/market-cap context: new "Cap" (Mega/Large/Mid/Small/Micro) and "Sector" scan result columns, plus a sector breakdown in the results status line.
- Multi-strategy scanning: added RSI Mean-Reversion (`tradelab/strategies/rsi_reversion.py`) alongside the original EMA/MACD Trend strategy, with a registry (`tradelab/strategies/__init__.py`) and a Scanner "Strategy" dropdown to pick between them. Persists through Setup save/load.
- Confidence scoring tied to backtest stats (`tradelab/core/confidence.py`): "Conf%"/"Sample" columns showing what fraction of the selected strategy's historical BUY signals on this symbol were profitable 10 bars later - reuses the already-computed indicators, no separate backtest pass, deliberately distinct from the existing heuristic Score.
- Found and fixed a real bug while writing tests: a `Confidence %` column mixing numbers and `None` gets coerced to `NaN` by pandas, which an `is not None` check doesn't catch - rendered `"nan%"` instead of `"—"`.
- pytest regression suite now 161 tests, all passing.

## Completed in 2.5.0 (Custom Technical Filter Builder, SCN-026)
- `tradelab/core/filters.py`: IBKR-style arbitrary filter conditions across 16 technical fields (price, volume, relative volume, RSI, ATR%, ADX, MACD family, EMA fast/slow, SMA20/50/200, Bollinger bands, price-vs-SMA20%), each with Above/Below/Between + a value. ANDs with the existing fixed filters rather than replacing them.
- Scanner UI: "Custom Filters" section with dynamic add/remove rows, wired through `ScannerConfig.custom_filters`, `scan_symbols()`, and the Setup save/load system.
- Also verified BUG-005 (Stop Scanner) and BUG-006 (Canadian ticker coverage) live before starting this - both confirmed working, closed off the watch list (see below).
- pytest regression suite now 114 tests, all passing.

## Completed in 2.4.1 (Chart workspace multi-tab UX)
- Explicit chart switcher row (own row below the toolbar, one button per open chart) - fixes real confusion ("I don't see the second added chart") caused by the native QDockWidget tab bar being easy to miss.
- "Reset charts" button to collapse back to a single clean chart.
- Removed each dock's native title bar (was repeating the same symbol name the switcher row and the chart's own search box already show); added a small per-chart close (x) button in the switcher row to replace the title bar's close button, shown only once more than one chart is open.
- pytest regression suite now 92 tests, all passing.

## Completed in 2.4.0 (Scanner Preset Manager upgrade, SCN-029)
- Setup name field is now an editable combo box ("Preset:") listing every saved preset from `data/setups/` - pick one to switch instantly instead of using an Open file dialog. Stays in sync automatically after Save/Save As/Delete. "Open" button kept for loading a file from elsewhere on disk.
- `load_setup()` and the new `load_setup_by_name()` now share one `_apply_setup_data()` implementation instead of duplicating the field-by-field restore logic.
- Fixed a real bug found while doing this: `new_setup()` set the name to "New Setup" then called `default_setup()`, which itself unconditionally reset the name back to "Default Setup" - the New button never actually worked as intended.
- pytest regression suite now 86 tests, all passing.

## Completed in 2.3.2 (Chart Engine rendering fixes, part 2)
Continued first manual pass over Phase 1. All silent bugs - no exception, no error log:
- BUY/SELL signal triangles and the price pane's own crosshair lines never appeared: `show_empty_placeholder()`'s `price_plot.clear()` silently orphaned both, added at construction but never re-added. Also sized signal markers up (14 to 36) and gave them a white outline - they were technically rendering but invisible next to same-colored candles.
- Crosshair froze outside the price pane: each pane (price/volume/MACD/RSI) has its own `QGraphicsScene`, but only price_plot's mouse-move signal was connected. Now all four are wired in.
- MACD/RSI crosshair lines specifically still didn't render even after that fix - `_plot_macd()`/`_plot_rsi()` call `.clear()` on their own pane on every replot, wiping their crosshair line every time. This is why a test checking only position values (not scene attachment) didn't catch it; two rounds of fixing were needed here.
- Opening a second chart tab silently made the workspace forget the first tab existed (`visibilityChanged` fires on tab-switch hides, not just real closes) and never actually raised the new tab to front (`dock.raise_()` called before Qt processes `tabifyDockWidget()` is a no-op).
- MACD/RSI sub-panels now visible by default. Crosshair readout moved to a bottom status bar (date+time, full OHLCV, visible indicator values) instead of a floating label that could obscure the candle it described.
- pytest regression suite now 80 tests, all passing.

## Completed in 2.3.1 (Chart Engine rendering fixes)
Phase 1 (Chart Engine) had only ever been verified by automated tests and headless launches. This release is the first time it was actually clicked through by hand, which surfaced three real bugs invisible to the test suite (none of them raise an exception):
- Candle bodies visually fused with no visible wicks: the outline pen width was set in the same data-space coordinate system as the candle body width, so the stroke bridged the gap into neighboring candles regardless of zoom. Fixed with a cosmetic (pixel-width) wick pen and no outline on the body (fill only).
- Price pane Y-axis permanently stuck at a placeholder `[-1, 1]` range from construction-time `show_empty_placeholder()`, which disables pyqtgraph's Y auto-range until explicitly re-enabled - nothing ever did. Fixed by setting Y range explicitly from visible High/Low on every replot, same as X range already was.
- Bar-duration (Interval) selector was missing from the Chart tab entirely - Phase 1's PyQtGraph rewrite only carried over the Period dropdown. Added `interval_combo`, wired to `cfg.interval`, synced correctly when a chart is loaded from a Scanner result.
- pytest regression suite now 71 tests, all passing.

## Completed in 2.3.0 (Scanner Professional Phase 2, kickoff)
- SCN-027 Scanner result color standard: `tradelab/ui/colors.py` centralizes score-tier row backgrounds, Signal/EMA/MACD Bull-Bear foreground colors, and RSI overbought/oversold highlighting, replacing inline magic-number `QColor` values.
- Fixed a real bug: scan-error rows (Score 0) were visually indistinguishable from genuinely weak low-score results. Errors now render as a distinct gray, and the previously-hidden error message is surfaced as a Symbol-cell tooltip.
- pytest regression suite now 70 tests, all passing.

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
- `app.py` (76KB) is still a UI monolith. Splitting it into `tradelab/ui/panels/` and `tradelab/ui/widgets/` is planned to start alongside Phase 2 (Scanner Pro), not yet done.
- Strategy/plugin interface unification (formal `Strategy` base class + auto-discovery) not yet done — planned for Phase 2/5.
- Dependency versions in requirements.txt were relaxed to `>=` floors in 2.2.2/2.2.3 after exact pins broke on Python 3.14 (no prebuilt wheels for pandas 2.2.3/numpy 1.26.4/matplotlib 3.9.2). Re-verify against your actual installed environment (`pip freeze`) before your next release regardless, since floors can still drift.

## Next
- Everything on the Phase 2 - Scanner Professional roadmap bullet is now done (SCN-026, SCN-027, SCN-029, SCN-030). Worth deciding whether to keep pushing deeper here (e.g. a formal Strategy plugin interface, more strategies, richer backtest-derived confidence) or move to Phase 3 (Market Dashboard).

# Changelog

## 2.10.0 - Plugin SDK (Phase 6)

The Plugins tab was dead code (it only listed filenames and wasn't even registered as a tab). Turned it into a real, formal plugin system with auto-discovery.

### Added
- `tradelab/core/plugins.py`: drop a `.py` file in the top-level `plugins/` folder defining `PLUGIN_NAME` and `compute(df) -> Series`, and it's auto-discovered and registered as an indicator field (keyed `plugin:<name>`) in `filters.FIELD_SPECS` - so it's immediately usable in the Scanner's Custom Filters and the no-code Strategy Builder with no other wiring. Bad plugins (import error, missing `PLUGIN_NAME`/`compute`) are recorded and shown, never crashing the app. Discovery runs at startup (before panels build) and on demand.
- `plugins/sample_hl_range.py`: a working template plugin ("High-Low Range %") users can copy.
- Plugins tab rebuilt: lists loaded (✓) and errored (✗ + reason) plugins with a Reload button; reloading refreshes the condition-field dropdowns.

### Verified
- 278/278 pytest regression tests pass (9 new: `tests/test_plugins.py` covering discovery, field registration, condition evaluation with a plugin field, error handling, re-discovery, and the panel).
- Manually tested: the sample plugin loads and appears as a selectable field in Custom Filters.

## 2.9.0 - No-code Strategy Builder + configurable indicators (Phase 5)

Phase 5, plus a major push toward TradingView/IBKR-level flexibility: indicators are now parameterized and editable everywhere from the UI, with no code.

### Added
- **No-code Strategy Builder**: build a strategy from BUY/SELL condition blocks, save/load/delete it, and it becomes a real runnable strategy in the Scanner and Backtest dropdowns (keyed `custom:<name>`) via the registry. New `tradelab/strategies/custom.py` (CustomStrategy: signal_series on rising-edge of the condition blocks + score_symbol), persisted as JSON in `data/strategies/`.
- **Expanded indicator library**: Stochastic %K/%D, Williams %R, CCI, Rate of Change, OBV, Money Flow Index, and VWAP added to `add_indicators` and exposed as condition/overlay fields.
- **Field-vs-field comparisons**: new "Above field"/"Below field" operators compare one indicator to another (e.g. EMA 9 above EMA 30, Price above VWAP, MACD above Signal) - so crossover strategies are expressible in the no-code builder.
- **Tunable periods everywhere, with standard defaults**: `filters.py` fields became period-parameterized (`FIELD_SPECS` + `ensure_columns` computes any period on demand). Every condition row (Scanner filters and Strategy Builder) has an inline period spinbox pre-filled with the standard value (RSI 14, EMA 20, SMA 50, CCI 20, ROC 12, ATR 14, ADX 14, MFI 14, Bollinger 20). Legacy field keys (`rsi14`, `ema_fast`, ...) auto-migrate so saved presets/strategies keep working.
- **Chart indicator manager**: the fixed "Overlays" menu became an "Indicators…" dialog to add/remove any number of price overlays (EMA, SMA, VWAP, Bollinger, SuperTrend, Ichimoku, Pivots) each with a tunable period, plus toggles and periods for the oscillator sub-panes.
- **Configurable MACD/RSI sub-panes**: RSI period and MACD fast/slow/signal are now editable (were hardcoded 14 and 12/26/9).
- **Clickable on-chart legend**: each pane shows a colour-coded legend of its indicators in the top-left; clicking any entry opens the Indicators editor - the legend is the primary editing entry point, TradingView-style.

### Verified
- 269/269 pytest regression tests pass (new suites for custom strategies, the strategy-builder panel, chart indicators, plus extended filter/indicator coverage).
- Manually tested in the real app: building an EMA-crossover custom strategy, scanning/backtesting with it, adding multi-period overlays, editing MACD/RSI periods, and editing via the legend.

## 2.8.0 - Backtesting Lab (Phase 4)

The Backtest panel existed but wasn't even registered as a tab (dead code) and was single-symbol, single-strategy (hardcoded EMA/MACD). Rebuilt into a proper lab and wired in as a "Backtest" tab.

### Added
- `tradelab/core/backtest.py`: strategy-agnostic engine (works with any strategy in the SCN-030 registry via its signal_series). Single-symbol simulation plus the three things the roadmap calls for: multi-symbol aggregation, single-parameter optimization (sweep + rank), and walk-forward (sequential out-of-sample windows + a consistency score). Qt-free and network-optional, unit-testable offline. Adds a Max drawdown % metric throughout.
- Backtest tab UI with 4 sub-tabs (Single / Multi-Symbol / Optimize / Walk-Forward), a shared Strategy/Period/Interval row, and — because backtesting is an abstract concept — **plain-language self-explanation**: an italic hint under each sub-tab describing what it does, and a bold colour-coded verdict after each run that interprets the raw numbers ("this strategy made money (+45%)…", "made money in 3 of 4 time periods (75%) — reliable", etc.).

### Fixed
- Backtest data prep did a blanket `dropna()`, discarding the first ~199 bars purely for SMA200's warmup even though no strategy signal uses SMA200 - crippling shorter backtests and walk-forward windows. Now drops only rows where the actual signal inputs (EMA/MACD/RSI, ~35 bars) are still warming up.

### Verified
- 225/225 pytest regression tests pass (32 new: `tests/test_backtest.py` for the engine incl. drawdown/optimize/walk-forward, `tests/test_backtest_panel.py` for the 4 sub-tabs and plain-language verdicts).

## 2.7.0 - Market Dashboard (Phase 3)

Starts Phase 3. The Market tab was a placeholder (a regime-symbol table whose own status line said "breadth is planned in the next phase"); this fills it in.

### Added
- `tradelab/core/market.py`: Qt-free, offline-testable dashboard logic - the 11 SPDR sector ETFs, per-symbol trend analysis (last / % change / above 50- & 200-day SMA), sector-breadth counts, and a transparent `market_condition()` "is it a good day to trade" read.
- Market tab UI:
  - **"Is it a good day to trade?"** macro read - a colour-coded headline (green Favorable / amber Neutral / red Caution) with a 0-100 score and the plain-English list of reasons that produced it (SPY vs its 50/200-day averages, VIX level, sector participation). Same no-black-box philosophy as the scanner's confidence score.
  - **Sector breadth** table across all 11 SPDR sector ETFs (daily % change + above/below 50-day average).
  - Breadth summary in the status line (e.g. "8/11 sectors up today, 9/11 above their 50-day average").
- The existing regime-symbol table (VIX/SPY/QQQ/…) now also feeds the macro read.

### Verified
- 201/201 pytest regression tests pass (14 new: `tests/test_market.py` for the logic, `tests/test_market_panel.py` for the UI incl. graceful handling of a failing symbol).
- Rendered the panel offscreen to confirm layout; refresh runs end-to-end.

## 2.6.1 - Junk-symbol filter fix

### Fixed
- Non-ticker junk like "41" could appear as a scan result row. `is_tradeable_symbol()` accepted any `[A-Z0-9.-]+` string, so a purely-numeric value from a bad exchange-feed line passed as a valid ticker. Now requires at least one letter (a real ticker always has one), which rejects `41`/`123`/`0` while keeping every real symbol including dotted Canadian tickers (`RY.TO`), class shares (`BRK.B`), and letter+digit tickers. Re-run "Refresh exchanges" to re-pull the lists through the corrected filter.

### Verified
- 187/187 pytest regression tests pass (26 new: `tests/test_universe.py`).

## 2.6.0 - Sector/market-cap context, multi-strategy scanning, confidence scoring (SCN-030)

Completes the last roadmap bullet for Phase 2 - "multi-strategy scanning, sector/market-cap context, transparent confidence scoring tied to backtest stats" - all three pieces in one release.

### Fixed
- `get_quote_meta()` was a complete stub returning a fake market cap seeded from `hash(symbol)` - the "Minimum market cap" filter has never actually filtered on real data since Phase 1. Now fetches real market cap + sector + industry via yfinance, cached in-process per symbol.

### Added
- **Sector/market-cap context**: new "Cap" (Mega/Large/Mid/Small/Micro bucket) and "Sector" scan result columns, plus a sector breakdown in the results status line (e.g. `Results: 12 — Technology: 5 | Healthcare: 3 | ...`).
- **Multi-strategy scanning**: a second real strategy, RSI Mean-Reversion (`tradelab/strategies/rsi_reversion.py`) - BUY on a bounce out of oversold, SELL on a rollover out of overbought, as opposed to EMA/MACD's trend-following logic. A small registry (`tradelab/strategies/__init__.py`) lets the Scanner's new "Strategy" dropdown pick between them; persists through Setup save/load like everything else.
- **Confidence scoring tied to backtest stats** (`tradelab/core/confidence.py`): new "Conf%"/"Sample" columns - of the selected strategy's historical BUY signals on this symbol's already-fetched price window, what fraction were profitable 10 bars later. Reuses the indicators DataFrame scan_symbols() already computed, so it stays fast enough to run inline during a scan instead of requiring a separate backtest pass. This is deliberately a different, more transparent number than the existing heuristic point-based Score.

### Verified
- 161/161 pytest regression tests pass (29 new, across indicators/strategies/confidence/scanner/UI wiring).
- Live end-to-end: real market caps and sectors confirmed (AAPL/MSFT→Technology, XOM→Energy, JNJ→Healthcare); both strategies produce different signals/scores/confidence on the same symbols; full path verified through the actual ScannerPanel UI, not just the core engine.
- Found and fixed a real bug during test-writing: a `Confidence %` column mixing real numbers and `None` across rows gets coerced to `NaN` by pandas (not `None`), which an `is not None` check doesn't catch - rendered as `"nan%"` in the table instead of `"—"`.

## 2.5.0 - Custom Technical Filter Builder (SCN-026)

### Added
- `tradelab/core/filters.py`: IBKR-style arbitrary filter conditions - pick any of 16 technical fields (price, volume, relative volume, RSI, ATR%, ADX, MACD/signal/histogram, fast/slow EMA, SMA20/50/200, Bollinger bands, price-vs-SMA20%), an operator (Above/Below/Between), and a value. Conditions AND together with each other and with the existing fixed Price/Volume/Technical/Signal filters - this is an additive layer, not a replacement.
- `ScannerConfig.custom_filters`: list of serialized conditions, wired through `scan_symbols()`, the Setup save/load system (`current_setup_dict`/`_apply_setup_data`), and `current_config()`.
- Scanner UI: a "Custom Filters" section with "+ Add Filter" - each row is a field dropdown, operator dropdown, value spinbox(es) (a second spinbox appears only for "Between"), and a remove button.

### Verified
- BUG-005 (Stop Scanner) and BUG-006 (Canadian ticker coverage) re-verified live before starting this work: `scan_symbols` stops exactly where `should_stop()` says to, and `refresh_exchange_cache()` pulled 1087 real Canadian symbols with zero source errors. Both closed off the watch list.
- 114/114 pytest regression tests pass (22 new: `tests/test_filters.py` for the field/operator evaluation logic, `tests/test_scanner_filter_builder.py` for the row widgets and persistence round-trip).
- End-to-end live scan test: an impossible custom condition (RSI < 1) correctly excluded every symbol; a trivial one (RSI < 100) let real scores through.

## 2.4.1 - Chart workspace multi-tab UX

### Added
- Explicit, always-visible chart switcher row (its own row below the toolbar) - one button per open chart, click to bring it to front. The native QDockWidget tab bar this sits alongside is easy to miss, which is exactly the confusion this fixes ("I don't see the second added chart" / "how do I switch chart").
- "Reset charts" toolbar button - closes every open chart tab and starts over with a single clean chart, for when multi-tab state gets confusing.
- A small close (x) button next to each chart in the switcher row, appearing only once more than one chart is open (same rule the old QTabWidget-based workspace used: never let you close your last tab).

### Changed
- Removed each dock's native title bar. It repeated the same symbol name the new switcher row and the chart's own search box already show, directly above each other. Trade-off: dragging a dock by its title bar to float/split it is no longer available - the switcher row and Reset button cover the everyday cases.

### Verified
- 92/92 pytest regression tests pass (12 new across the switcher row, reset, title bar removal, and per-chart close button).
- Manually tested in the real running app after each step of this round.

## 2.4.0 - Scanner Preset Manager upgrade (SCN-029)

### Changed
- The Setup name field is now an editable combo box (`Preset:`) listing every saved preset from `data/setups/`, instead of a plain text field paired with an Open file dialog. Picking a preset from the dropdown loads it instantly; typing a new name and hitting Save/Save As still works exactly as before. The dropdown stays in sync automatically after Save, Save As, and Delete. The existing "Open" button is kept for loading a setup file from elsewhere on disk (outside `data/setups/`), which the dropdown doesn't cover.
- `load_setup()` (file-dialog path) and the new `load_setup_by_name()` (dropdown path) now share one `_apply_setup_data()` implementation instead of duplicating the whole field-by-field restore logic.

### Fixed
- `new_setup()` set the name to "New Setup" and then immediately called `default_setup()`, which itself unconditionally reset the name back to "Default Setup" - the New button never actually showed "New Setup". Reordered so the name is set after the reset, not before.

### Verified
- 86/86 pytest regression tests pass (6 new: `tests/test_scanner_presets.py`, covering dropdown sync on save/save-as/delete, preset switching restoring saved values, and the New Setup naming fix).
- Manually tested in the real running app.

## 2.3.2 - Chart Engine rendering fixes, part 2 (BUY/SELL, crosshair, multi-tab)

Continued first manual pass over Phase 1 (Chart Engine). All of these were silent - no exception, no error log - which is exactly the class of bug automated tests miss unless they specifically check scene/tracking state rather than just "did this raise."

### Fixed
- **BUY/SELL signal triangles and the price pane's own crosshair lines never appeared.** `show_empty_placeholder()` (called once at construction) does `price_plot.clear()`, which silently orphaned every item added to price_plot before that point - `signal_scatter` and the price pane's own `InfiniteLine`s were removed and never re-added. Fixed by re-adding them in `show_empty_placeholder()`.
- **Signal markers, once actually rendering, were nearly invisible** - `size=14` with no outline, using the same green/red as the candles right next to them. Sized up (14 to 20, then to 36 per follow-up feedback) and given a white outline for contrast.
- **Crosshair froze the instant the mouse left the price pane.** Each chart pane (price/volume/MACD/RSI) is a separate `PlotWidget` with its own independent `QGraphicsScene`, but only price_plot's `sigMouseMoved` was ever connected. Wired all four panes into the same handler, mapping through whichever pane's own ViewBox the mouse is actually over (panes are on very different value scales, so this matters).
- **MACD/RSI crosshair lines specifically still didn't render even after the above fix** - `_plot_macd()`/`_plot_rsi()` each call `.clear()` on their own pane on *every* replot (symbol change, overlay toggle, anything), which wiped that pane's own crosshair line every time, never re-added. `setPos()` on the orphaned line succeeded silently, which is why a test that only checked position values (not scene attachment) didn't catch it. Fixed by re-adding each pane's line right after its own `.clear()`.
- **Opening a second chart tab made the workspace forget the first one existed.** `ChartWorkspace` tracked dock lifecycle via `visibilityChanged`, which fires both on a real close AND whenever a dock is hidden for merely not being the active tab in a tabified group - the latter happens to every dock the instant a second one is tabified onto it. The new tab was also never actually brought to front (`dock.raise_()` called before Qt finishes processing `tabifyDockWidget()` is a no-op). Fixed with a proper close-only signal (`QDockWidget` subclass overriding `closeEvent`) and a deferred `QTimer.singleShot(0, dock.raise_)`.

### Changed
- MACD and RSI sub-panels now visible by default (were off, requiring a manual toggle every session).
- Crosshair readout moved from a floating label that could obscure the very candle it described to a status bar fixed at the bottom of the chart, showing date+time (with time-of-day on intraday intervals), full OHLCV, and visible EMA/RSI/MACD values.

### Verified
- 80/80 pytest regression tests pass (9 new, covering scene attachment after a real replot - not just position values - plus the multi-tab dock lifecycle).
- Manually tested in the real running app after each fix; two of these bugs (BUY/SELL markers, MACD/RSI crosshair) only surfaced because a first "fix" that passed automated + offscreen verification still didn't work when actually clicked through, which is why several fixes above needed a second pass.

## 2.3.1 - Chart Engine rendering fixes (found during first manual test of Phase 1)

Phase 1 (Chart Engine) had only ever been verified by automated tests and headless launches - this is the first release where it was actually clicked through by hand, which surfaced three real bugs the test suite couldn't catch because none of them raise an exception:

### Fixed
- **Candle bodies visually fused into a solid ribbon with no visible wicks.** Root cause: the candle outline pen width (`1.0`) was set in the same data-space coordinate system as the candle body width (`0.4`), not screen pixels - the stroke extended half a data-unit past every edge, comfortably bridging the gap to the next candle and fusing outlines together regardless of how much fill-gap was configured. Fixed by using a cosmetic (constant-pixel-width) pen for the wick and dropping the outline on the body entirely (fill only), so a stroke can never bridge into a neighboring candle.
- **Price pane Y-axis permanently stuck at a placeholder `[-1, 1]` range.** `show_empty_placeholder()` (shown once at widget construction) pins the Y-axis with `setYRange`, which disables pyqtgraph's Y auto-range until explicitly re-enabled - nothing ever did, so every chart's price pane stayed locked to that placeholder range instead of fitting the real price data. A leftover placeholder text item (never removed once real data loaded) compounded this by also pulling the auto-range toward zero. Fixed by removing the placeholder item on first real plot and setting the Y range explicitly from the visible candles' High/Low (matching how X range was already handled), instead of relying on auto-range's deferred, paint-cycle-dependent recompute.
- **Bar-duration (Interval) selector missing from the Chart tab.** The PyQtGraph rewrite (Phase 1) only carried over a Period dropdown (3mo-max); the Interval control (1m/5m/.../1d/1wk/1mo) that the Scanner tab has always had was never wired into the standalone chart toolbar, even though the data layer already supported it. Added `interval_combo` next to Period, and `plot()` now syncs both combos when a cfg with a different period/interval is loaded externally (e.g. from a Scanner result), instead of leaving the toolbar showing stale values.
- Default visible window on chart load reduced from 180 to 100 bars, and candle/volume/MACD-histogram bar width tightened, so bars have a real, visible gap at typical panel widths instead of compressing to sub-pixel spacing.

### Verified
- 71/71 pytest regression tests pass (1 new: a Y-axis-fit regression test in `test_chart_engine_ui.py`).
- Manually tested by launching the real (non-offscreen) app after each fix.

## 2.3.0 - Scanner result color standard (Phase 2 kickoff, SCN-027)

### Added
- `tradelab/ui/colors.py`: single source of truth for Scanner result table colors - score tiers (background), Signal/EMA/MACD Bull-Bear state (foreground), and RSI overbought/oversold zones (foreground). Previously the score-tier row tint was the only coloring, defined as unlabeled magic `QColor` values inline in `populate_table`.

### Fixed
- Scan errors (`Signal == "ERROR"`) previously fell into the same "poor score" red tint as a genuinely weak but valid result (both had `Score == 0`), making a scan failure indistinguishable from a real low-scoring symbol at a glance. Errors now render as a distinct neutral gray, and the error message (previously computed but never shown anywhere) is now surfaced as a tooltip on the Symbol cell.

### Verified
- 70/70 pytest regression tests pass (16 new: `tests/test_scanner_colors.py`), including an integration test that drives `ScannerPanel.populate_table()` end-to-end and checks table cell colors/tooltip.

## 2.2.2 - Installer fix, part 2 (all launchers protected)

### Fixed
- The 2.2.1 fix only lived in `run_tradelab.bat`. This project has four separate launchers (`run_tradelab.bat`, `run_tradelab_console.bat`, `run_tradelab_no_venv.bat`/`run_tradelab.sh` via `main.py`, and the VBS shortcut which just calls `run_tradelab.bat`) — `run_tradelab_console.bat` called `launch_tradelab.py` directly and skipped the check entirely, so the same `ModuleNotFoundError: No module named 'pyqtgraph'` crash still reached the user.
- **Moved the dependency check into `launch_tradelab.py` itself** (`ensure_dependencies()` / `missing_modules()`), the single file every launcher eventually runs. It now auto-installs any missing packages via pip on first detection and retries, instead of surfacing a raw traceback.
- `main.py` (used by `run_tradelab_no_venv.bat` / `run_tradelab.sh`) now also runs the same preflight before importing the app, instead of crashing at import time.
- `run_tradelab_console.bat` now creates the venv via `install_requirements.bat` if it doesn't exist yet, instead of assuming it's already there.
- Simplified `run_tradelab.bat`: dependency verification logic now lives only in `launch_tradelab.py`, not duplicated across every `.bat` file.

### Added
- `tests/test_launch_dependency_preflight.py`: regression tests for the preflight logic itself, plus a check that `launch_tradelab.py`'s `REQUIRED_MODULES` stays in sync with `requirements.txt` (mirrors `test_installer_consistency.py`, applied to this second location).

### Verified
- 54/54 pytest regression tests pass.
- Directly simulated a missing `pyqtgraph` module and confirmed `main.py` and `launch_tradelab.py` no longer crash at import time — the preflight check runs first and would auto-install before the app loads.
- Confirmed a healthy environment still boots MainWindow end-to-end with no regressions.

## 2.2.1 - Installer fix

### Fixed
- **`check_install.py` didn't check for `pyqtgraph`**, so it could report "All dependencies are installed" on an environment that was actually missing it — surfacing instead as a `ModuleNotFoundError` crash on launch. Reported by a real install on an existing (pre-2.2.0) virtual environment.
- **`run_tradelab.bat` only ran the installer when the venv folder was completely missing**, so an existing venv from a prior release never picked up new dependencies added later (`pyqtgraph` in this case). It now verifies dependencies via `check_install.py` on every launch and self-heals by re-running the installer if anything is missing.

### Added
- Regression test (`tests/test_installer_consistency.py`) that fails the build if any runtime package in `requirements.txt` isn't also verified by `check_install.py` — this exact class of bug can't silently ship again.

### Verified
- 49/49 pytest regression tests pass.

## 2.2.0 - Chart Engine Phase 1 (PyQtGraph rewrite)

### Added
- **Dockable, resizable, floatable chart workspace** replacing the fixed tab bar (`tradelab/ui/workspace/chart_workspace.py`). Panels can be dragged into tabs, split, or floated to a second monitor.
- **PyQtGraph-based chart rendering** (`tradelab/ui/widgets/pg_chart_widget.py`), replacing matplotlib for interactive charts. Matplotlib is kept only as an unused legacy reference (`chart_widget_legacy_matplotlib.py`).
- **Drawing tools**: trendlines, horizontal/vertical lines, rectangles, Fibonacci retracement, text notes — all persisted per symbol/timeframe (SQLite) and reloaded automatically.
- **Chart types**: Candlestick, Heikin-Ashi, Line, Area.
- **New indicator overlays**: VWAP, Pivot Points, SuperTrend, Ichimoku Cloud, Volume Profile (all in `tradelab/core/indicators.py` as pure, independently-tested functions).
- **Synced crosshair** across price/volume/MACD/RSI panes — resolves BUG-003.
- **Saved chart layouts** (name, save, load) persisted to a new `chart_layouts` table.
- Centralized logging (`tradelab/core/logging_config.py`), writing rotating logs to `logs/tradelab.log`.
- Versioned database migrations (`schema_version` table) replacing ad hoc `CREATE TABLE IF NOT EXISTS` sprawl.
- Full pytest regression suite: 47 tests covering indicators, drawings, database migrations/persistence, market data fallback, and headless Qt smoke tests for the chart engine. **All 47 pass.**

### Fixed
- **BUG-003** chart crosshair bottom date/time label stabilization — resolved by the new synced-crosshair implementation.
- **BUG-009** Open Chart in New Tab — superseded by "add dockable chart panel," which is strictly more flexible.
- A real (previously undetected) bug in `synthetic_ohlcv()`'s offline fallback data generator: array lengths assumed `date_range(periods=N, freq="B")` always returns exactly N rows, which isn't guaranteed across pandas versions and could throw `ValueError: Length of values (260) does not match length of index (259)`. Now sized off the actual generated date index. Covered by a dedicated regression test.

### Changed
- Dependency versions in `requirements.txt` are now pinned exactly (was `>=`), added `pyqtgraph` and `pytest`.
- `app.py` continues to import `ChartWorkspace`/`ChartWidget` from `tradelab.ui.chart_widget` unchanged — that module is now a thin compatibility shim re-exporting the new implementations, so no call sites elsewhere needed to change.

### Verified
- 47/47 pytest regression tests pass (`pytest tests/ -q`).
- Full MainWindow construction + chart workspace interaction (add panel, plot, switch all 4 chart types, add/persist/reload drawings, save/list layouts) exercised end-to-end with no exceptions.
- Python compile passed.
- No .pyc or __pycache__ included.

## 2.1.11 - Exchange UI Cleanup

### Added
- UI-008 compact exchange shortcut buttons: USA, Canada, All, None.

### Changed
- SCN-034 removed ETF from the Exchanges section.
- SCN-035 moved ETFs into My Lists as a scan list/category.
- SCN-036 removed the confusing Custom Selection preset. Manual checkboxes are now the custom selection.
- UI-006/UI-007 improved setup toolbar sizing and kept the setup name visible.

### Verified
- Python compile passed.
- No .pyc or __pycache__ included.

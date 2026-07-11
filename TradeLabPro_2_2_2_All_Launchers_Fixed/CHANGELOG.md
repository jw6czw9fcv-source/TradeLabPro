# Changelog

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

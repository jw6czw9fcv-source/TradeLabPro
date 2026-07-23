# TradeLab Pro Project Status

Current version: 2.29.0
Current phase: Country-first Market tab + chart Measure tool (done)

## Completed in 2.29.0 (Country-first Market tab; Measure tool; Esc-to-cursor)
- Fix: `analyze_trend`/`realized_vol` crashed (`TypeError: float() ... not 'Series'`) when yfinance returned a frame with duplicate `Close` columns; new `_close_series()` collapses a 2-D Close to its first column.
- `core/market.py`: `sector_instruments(region)` sources the 11 sectors from `core.sectors` so Market and Scanner share one taxonomy (ETF where a fund exists, else equal-weighted constituents via `aggregate_trend()`); `regime_rows(region)` (Canada gets TSX/XIC/ZEB/USD-CAD/oil/gold); `SECTOR_REGIONS` no longer holds sector lists.
- Market tab: `country_combo` at top drives the whole tab (one read card, regime rows, sectors); both markets cached and the non-visible one prefetched, so switching country is instant. Sector cells carry a chartable symbol in `Qt.UserRole` (basket rows show "6 stocks").
- Scanner: single top selector (…/Sectors — US/Sectors — Canada); the separate sector-market dropdown removed.
- Chart: restored the legacy **Measure** tool (two-click ruler: price, %, bars, dated span) as a `measure` drawing kind; **Esc** returns any drawing tool to Cursor (event filter on the panes); full screen now uses a **⤢ retract icon** button, not Esc; date X-axis retained.
- pytest regression suite now 613 tests, all passing.

## Completed in 2.28.0 (Scanner sectors separated by market)
- `core/sectors.py` restructured by region, mirroring the Market tab: `US_SECTORS` + **new `CANADA_SECTORS`** (all 11 GICS sectors on the TSX — Technology CSU/SHOP/OTEX, Financials the Big Six + insurers, Materials ABX/AEM/K/FNV/WPM, etc.), `INDUSTRIES` kept as one mixed source and **split by suffix at read time**, `ETF_BASKETS` keyed by region.
- API: `REGIONS`, `is_canadian()`, `region_baskets(region)`, `basket_choices(region)`, `basket_symbols(name, region)`, `universe_name(region, basket)`, `split_universe_name()`, `scanner_universes()`. Universe keys carry the region (`Sector - Canada - Banks`); Canada drops baskets with no domestic names (no TSX Semiconductors/Social Media). 43 US + 30 Canada = 73 baskets.
- Scanner: new **Sector market** dropdown (US/Canada) above the universe checkboxes; only the selected market's baskets are listed, labels drop the redundant region. No basket mixes markets (test-enforced).
- pytest regression suite now 596 tests, all passing.

## Completed in 2.27.0 (Chart date axis + Scanner sector baskets)
- `pg_chart_widget.BarDateAxis`: bottom axis maps bar index -> the bar's real timestamp (candles plot at index so weekends/holidays leave no gap, which had left the axis labelling `0, 50, 100`). Format adapts to span (intraday `%H:%M` / `%d %b %H:%M`, daily `%d %b`, multi-year `%b %Y`); out-of-range ticks blank. `_date_axes`/`_set_date_index()`/`_sync_date_axes()` feed all four panes and show values only on the lowest showing pane (driven by `_sub_panel_flags`, not `isVisible()`).
- `core/sectors.py` (Qt-free): `SECTORS` (11 GICS), `INDUSTRIES` (sub-sectors incl. Gold & Precious Metals, Banks, Uranium, Oil & Gas, REITs... + `heatmap.THEMES` merged in, shared not duplicated), `ETF_BASKETS`; `all_baskets()`/`basket_choices()`/`basket_symbols()`/`scanner_universes()` with `BASKET_PREFIX = "Sector - "`. 43 baskets.
- Scanner: baskets registered via `available_universes()`, grouped as "Sectors" (checked before the ETF rule), new "Sectors / Industries" exchange preset + "Sectors" shortcut button. `list_symbols()` resolves basket country **per symbol** (`.TO/.V/.CN/.NE` -> Canada) so a mixed basket survives a country filter.
- pytest regression suite now 588 tests, all passing.

## Completed in 2.26.0 (Market favorability: global indices + US/Canada sectors)
- `core/market.py`: `GLOBAL_INDICES` (8 majors in **session-open order**, each carrying UTC open minutes + local open label), `CANADA_SECTOR_ETFS` (7 liquid iShares TSX capped sectors) + `SECTOR_REGIONS`/`sector_region()` (US→SPDRs vs SPY, Canada→TSX sectors vs XIC.TO), `market_read()` (per-index Favorable/Neutral/Caution vs 50/200-day), `sector_favorability()`/`rank_sectors()` (transparent 0–100 score: trend, RS vs benchmark, momentum, day move) + `sector_score_criteria()`, `realized_vol()` (VIX substitute outside the US), `analyze_trend` gained `mom_pct`, `sector_breadth` gained 200-day counts, `market_condition` gained momentum, 200-day breadth, a realised-vol fallback and a plain-English `summary`.
- `MarketPanel`: global-indices table in market-open order; sector table ranked best→worst with a **US/Canada dropdown**; **two read cards** (US + Canada) both scored every refresh; collapsible "how this is scored" panel + header/score tooltips; **click any row to chart it**.
- Threading: `_MarketRefreshWorker` (batch download + progress) and `_HistoryWorker` (click-to-chart) moved every network call off the UI thread — the tab no longer freezes. Fetch and render are separated; render is network-free. `shutdown()` wired into `closeEvent`.
- pytest regression suite now 565 tests, all passing.

## Completed in 2.25.0 (Stop/bracket orders + News feed)
- Paper broker (`core/broker.py`): added STOP, STOP_LIMIT, TRAILING_STOP order types (+ trail_amount/trail_pct, live stop_price), and bracket/OCO (`place_bracket`, parent_id/oco_group/active plumbing; `_after_fill` activates children + cancels OCO siblings). `poll()`/`_should_trigger()`/`_trail_level()` handle triggering; `_new_order()` factored out. PaperTradingPanel: type dropdown (5 types) with dynamic Limit/Stop/Trail fields, a Bracket row (take-profit/stop-loss), Cancel-selected, Stop column.
- News: `core/news.py` (`fetch_news(symbols, fetcher=, macro_only=)`, `NewsItem`, `is_macro`, `MACRO_KEYWORDS`, `MARKET_SYMBOLS`; parses old flat + new nested Yahoo shapes, dedupe/sort). New "News" tab (`NewsPanel` + `NewsWorker`): Symbol vs Market&macro source, macro-only filter, macro headlines flagged ⚑, double-click opens the article. Read-only.
- pytest regression suite now 525 tests, all passing.

## Completed in 2.24.0 (Notes tab, multi-row tabs, chart full screen)
- New "Notes" tab: `tradelab/core/notes.py` (`load_notes`/`save_notes` -> `data/notes.txt`, gitignored) + `NotesPanel` (plain-text QTextEdit, debounced autosave via QTimer, `shutdown()` flush wired into closeEvent).
- `MultiRowTabs` (+ `FlowLayout`) replaces `QTabWidget` for the left panel so all ~17 tabs wrap to multiple rows and stay visible (no overflow arrow); implements the QTabWidget subset the app uses (addTab/currentWidget/setCurrentWidget/count/widget/tabText). Compact buttons with a checked highlight.
- Chart full-screen: `ChartWorkspace.fullscreenRequested` signal + "⛶ Full screen" toolbar button; `MainWindow.toggle_chart_fullscreen()` hides the left panel and `showFullScreen()` (Esc/`keyPressEvent` also exits), `set_fullscreen_label()` updates the button. `self.splitter` stored to restore sizes.
- pytest regression suite now 501 tests, all passing.

## Completed in 2.23.0 (Links page, Phase 16)
- `tradelab/core/links.py` (Qt-free): `normalize_url` (defaults https://), `Link` dataclass, `LinkStore` -> `data/links.json` (gitignored) with add/update/remove/persist.
- New "Links" tab (`LinksPanel`, before Settings): add/edit-in-place form (name/URL/group), table sorted by group+name, double-click / Open selected -> `QDesktopServices.openUrl`, Remove, Import/Export CSV. Opens links only; sends nothing.
- pytest regression suite now 493 tests, all passing.

## Completed in 2.22.0 (Data-source abstraction, Phase 15)
- `tradelab/data/providers.py`: `DataProvider` ABC + `YahooProvider` (delegates to `market_data._yahoo_history`/`_yahoo_quote_meta`) + `SyntheticProvider` (offline deterministic); registry (`register`/`active`/`set_active`/`provider_names`), default Yahoo. `market_data.get_history`/`get_quote_meta` now delegate to `providers.active()` (cache stays in the wrapper; switch clears it). All existing market_data tests unchanged.
- New Settings tab (`SettingsPanel`, replaces the plain text tab): Data-source dropdown persisted to QSettings `data/provider`, applied at MainWindow startup before panels fetch. Injectable `settings=` for tests. conftest autouse resets the active provider around every test.
- pytest regression suite now 481 tests, all passing.

## Completed in 2.21.0 (Heatmap <-> Scanner link, Phase 14)
- Scanner: added `on_show_heatmap` callback + "Map results" button + `result_symbols()`/`show_results_in_heatmap()` (drops ERROR rows). MainWindow `_show_scan_in_heatmap()` sets the heatmap source and fronts the tab (`self.tabs`/`self._heatmap_page`).
- HeatmapPanel: `set_external_symbols(symbols, label)` adds/selects a "Scanner results" source (clears theme) and loads; `_symbols_for_market` handles it. `HeatmapView` now emits `context_requested` on right-click (left-click still charts); `_on_tile_menu` offers Open chart / Add to watchlist.
- Heatmap zoom re-lays the treemap out into a larger scene (`_zoom`/`_zoom_at`/`_fit_zoom`, clamp 1x-12x, cursor-anchored) instead of scaling the view transform — so tiles grow, label text stays normal size, and previously-hidden tickers appear. `HeatmapView` emits `zoom_requested`/`fit_requested`; drag-to-pan with click-vs-drag detection; double-click empty = fit; `load()` resets zoom.
- Heatmap tile labels now auto-fit the tile (`HeatmapPanel._fit_pt`) and are clipped to it (`ItemClipsChildrenToShape`), so small tiles show tickers too.
- pytest regression suite now 471 tests, all passing.

## Completed in 2.20.0 (Chart Replay, Phase 13)
- Rebuilt the dead `ReplayPanel` (was an unregistered "Next candle" stub) into a full bar-by-bar replay and registered it as the "Replay" tab. Play/Pause via `QTimer`, step +/-, reset/to-end, speed 0.5x-8x, a scrub `QSlider`, and a "Start at bar N" spin. `_plot()` charts `data.iloc[:index]` so indicators use only revealed bars (no look-ahead). `set_data()` hook makes it testable without network; `shutdown()` stops the timer (wired into closeEvent).
- pytest regression suite now 463 tests, all passing.

## Completed in 2.19.0 (Risk & Position Sizing, Phase 12)
- `tradelab/core/risk.py` (Qt-free): `size_position()` returns a `SizeResult` (shares floored to risk, position value/%, actual risk $/%, stop %, capped_by), supporting fixed-$ risk and max-position-%/buying-power caps; `r_targets()` gives 1R/2R/3R target prices + $ P&L (long up, short down); `sector_exposure(positions, sector_of=)` buckets positions by sector with % of book.
- New "Risk" tab: live position-sizing calculator, R-target table, and portfolio sector-exposure table (loaded via `SectorExposureWorker` off the UI thread; flags ≥40% concentration). "Use paper account equity" convenience. No orders placed.
- pytest regression suite now 457 tests, all passing.

## Completed in 2.18.4 (Journal column sorting)
- Enabled click-to-sort headers on the Journal trades table and breakdown table (`setSortingEnabled`), with numeric cells using `SortableTableWidgetItem` sort_values so they order by value. `refresh()`/`_refresh_breakdown()` disable sorting while repopulating then restore the user's sort indicator (default: Entry date descending / P&L descending).
- pytest regression suite now 437 tests, all passing.

## Completed in 2.18.3 (Journal shows trade dates)
- Journal table gained Entry date / Exit date / Days columns (dates were imported correctly but never displayed) and now sorts newest-first.
- pytest regression suite now 435 tests, all passing.

## Completed in 2.18.2 (IBKR import "no trades" fixes)
- `fetch_ibkr_flex`: max_wait 20s → 90s and now RAISES "still generating, try again" past the deadline instead of returning IBKR's in-progress body (which has no trades and read as "no trades found") — the likely cause on large accounts.
- Removed the stocks-only (`assetCategory=STK`) filter from both the XML and CSV importers; all asset classes import, with the contract `multiplier` folded into quantity so option/future P&L is in real dollars.
- `parse_ibkr_flex_xml` now also reads `<TradeConfirm>` rows (Trade Confirmation queries) and de-duplicates multi-level-of-detail reports (prefers EXECUTION rows).
- Added `flex_trade_row_count()`; the UI now reports how many trade rows the report held, what to check, and saves the raw report to `logs/ibkr_flex_last.xml`.
- Added `flex_missing_fields()`: when trade rows lack a required field (e.g. Trade Price, the real cause of a user's 61-row report importing nothing), the UI names the missing field and where to enable it.
- pytest regression suite now 433 tests, all passing.

## Completed in 2.18.1 (IBKR Flex credential persistence)
- IBKR Flex dialog: added a "Save" button (store token+query id without fetching) and a "Show token" toggle. Credentials persist in QSettings (`ibkr/*`, OS store — survives app updates). Extracted `_save_flex_credentials(token, query, settings=)` (injectable) + `_start_flex_fetch()`; dialog uses a custom result code (`_FLEX_SAVE`) to distinguish Save vs Fetch&import.
- pytest regression suite now 427 tests, all passing.

## Completed in 2.18.0 (Trade Journal, Phase 11)
- `tradelab/core/journal.py` (Qt-free): `JournalEntry` (side/qty/entry/stop/exit/strategy/tags/notes) with derived P&L, P&L%, R-multiple (vs stop), holding days; `summarize()` (win rate, expectancy, profit factor, avg R, totals) and `group_stats(key)` by strategy/tag/symbol; `extract_trades_from_fills()` pairs fills into position-level round-trips; `parse_ibkr_trades_csv()` reads IBKR Flex-Query/Activity CSVs; `fetch_ibkr_flex(token, query_id, transport=)` runs the Flex Web Service two-step SendRequest/GetStatement (retry while generating) and `parse_ibkr_flex_xml()` parses the report; `Journal` store → `data/journal.json` (gitignored) with idempotent `import_fills()`/`import_ibkr_csv()`/`import_ibkr_flex()`.
- New "Journal" tab: log-a-trade form, trades table (P&L/R coloured), Close/Edit note/Delete, Import from Paper Trading, **Import from IBKR (CSV)** and **Import from IBKR (Flex Web Service)** (both read-only; Flex fetch runs in `IbkrFlexWorker` QThread, token+query id stored masked in QSettings under `ibkr/*`), Export CSV, double-click to chart, live stats + Strategy/Tag/Symbol breakdown.
- pytest regression suite now 426 tests, all passing (network-free).

## Completed in 2.17.0 (Heatmap: Industry/Country grouping, Themes, World map)
- Group-by is now Sector/Industry/Country/None (was a sector checkbox). `heatmap.group_tiles(tiles, key)` generalizes grouping; `layout_heatmap(..., group_by=<attr>|None)`; `HeatmapTile` gains `industry`/`country`; `get_quote_meta` returns `country`.
- Theme dropdown maps curated `heatmap.THEMES` baskets (AI, Semis, EV, Cloud, Cybersecurity, Biotech, Renewables, Fintech, E-commerce, Defense, Gaming, Social) and overrides the Market while set. `theme_choices()`.
- "World - Large caps" market (global ADRs) auto-groups by Country. Tooltips show industry + country.
- pytest regression suite now 389 tests, all passing.

## Completed in 2.16.0 (Heatmap Portfolio + performance periods)
- Heatmap: added "Portfolio" as a market source (maps `db.positions()` symbols) and a Finviz-style Period dropdown (1 Day/1 Week/1 Month/3 Month/6 Month/1 Year/3 Year/5 Year/10 Year/YTD; long look-backs use bounded ≤10y spans, never `max`, so the update stays ~0.5s). Core `heatmap.py` now has `HEATMAP_PERIODS`/`period_choices`/`_spec_for`/`_reference_close`/`_stats_from_df`; `default_quote_provider(symbols, period=..., progress=...)` and `_batch_prices(symbols, spec)` measure % change over the chosen window (N trading days back, or prior-year last close for YTD). `HeatmapWorker` takes a period; changing the period re-fetches once a map is loaded and relabels the legend.
- pytest regression suite now 382 tests, all passing.

## Completed in 2.15.0 (ETF/Index heatmaps)
- Added ETF/index presets to the Heatmap: US Sector ETFs (SPDR), US Index & asset ETFs, US ETFs (all = US_AMEX), Canada ETFs. `get_quote_meta` now falls back to AUM (totalAssets/netAssets) for size and fund `category` for the sector grouping when marketCap/sector are absent, plus a `quote_type` field. Hardened `_company_name_from_info` to reject filler summary starts ("In seeking to track…") via a content-word check.
- pytest regression suite now 376 tests, all passing.

## Completed in 2.14.3 (Company names on chart)
- Fixed many tickers (KO, CAT, MO, JPM, XOM...) showing only the symbol, no company name. Yahoo stopped returning longName/shortName for these; `get_quote_meta` now resolves via longName → shortName → legal name derived from `longBusinessSummary` (`_name_from_summary`, handles `&`/`of` connectors) → `displayName` → ticker. Chart header, heatmap tooltips, and Scanner name/sector all benefit.
- pytest regression suite now 373 tests, all passing.

## Completed in 2.14.2 (Heatmap auto-refresh)
- Added an auto-refresh timer to the Heatmap tab: an "Auto-refresh every N s" checkbox + interval spin (15–3600s) drives a `QTimer` that re-runs `load()`. Toggling on refreshes immediately; interval changes apply live; a refresh that overruns is skipped (load() no-ops while a worker is in flight); timer stops in `shutdown()`. Status line shows last-update time + "auto-refresh on".
- pytest regression suite now 363 tests, all passing.

## Completed in 2.14.1 (Window-fit layout fix)
- Fixed the window bottom being clipped/unreachable on ~1080p screens. A `QTabWidget` adopts its tallest page as the tab stack's minimum height, so the Scanner tab (~1330px) forced the whole window taller than the screen. Each tab page is now wrapped in a widget-resizable `QScrollArea` (`_scroll_tab`), dropping the window minimum height from ~1360px to ~380px; tall tabs scroll internally instead of overflowing.
- pytest regression suite now 360 tests, all passing.

## Completed in 2.14.0 (Market Heatmap, Phase 10)
- `tradelab/core/heatmap.py`: Qt-free, offline-testable market-map engine. Iterative **squarified treemap** (`squarify`, no recursion limit) + `layout_heatmap` (sector blocks with header bands), a green→red `color_for_change` scale, `build_tiles`/`group_tiles_by_sector`, and an injectable `default_quote_provider` (one batched yfinance download for price/%-change/dollar-volume + cached `get_quote_meta` for cap/sector; falls back to synthetic history offline).
- New "Heatmap" tab: `HeatmapView` (QGraphicsScene) renders tiles sized by market cap (or dollar volume), coloured by day % change, grouped by sector; tooltips + click-to-chart. US/Canada presets (NASDAQ/NYSE/TSX large caps, expanded TSX) + Watchlist; size-by and group-by toggles; max-tiles cap; loads in a background `HeatmapWorker` with progress; re-lays out on resize; clean shutdown on close.
- pytest regression suite now 358 tests, all passing (network-free).

## Completed in 2.13.0 (Alerts Engine, Phase 9)
- `tradelab/core/alerts.py`: Qt-free, offline-testable alerts engine. An `Alert` watches one symbol for one `FilterCondition` (reuses the Scanner/Strategy-Builder condition system). Firing is edge-triggered (false->true crossing), with "once" (disarm after firing) and "recurring" (re-arm when the condition releases) modes. `AlertStore` persists to `data/alerts.json` (gitignored). `evaluate_alerts()` takes an injectable history provider so it runs network-free in tests.
- New "Alerts" tab: symbol + single-condition builder (shared `_build_condition_row`, now with a non-removable variant), alert table with live status colouring, enable/disable + remove + "Check now", a configurable auto-check interval, an in-panel triggered-alerts log, and desktop notifications via `QSystemTrayIcon`. Checks run in a background `AlertCheckWorker` (QThread) so the UI never blocks; the poller stops cleanly on close.
- Alerts are analysis-only and never place orders (simulated-only safety model preserved).
- pytest regression suite now 339 tests, all passing (network-free).

## Completed in 2.12.5 (Manual: Open as PDF)
- "Open as PDF" button at the top of Help > User Manual: renders the manual (text + screenshots) to an A4 PDF and opens it in the system viewer.
- PDF links (incl. TOC) render black; on-screen viewer keeps default link colour.
- pytest regression suite now 322 tests, all passing.

## Completed in 2.12.4 (Manual zoom follows screenshots)
- Help > User Manual: Ctrl+wheel now zooms text and embedded screenshots together (was text-only).
- pytest regression suite now 319 tests, all passing.

## Completed in 2.12.3 (Manual window polish)
- Help > User Manual window: standard minimize + maximize/restore title-bar buttons.
- Manual screenshots scale to the window width and re-scale on resize (ManualBrowser).
- pytest regression suite now 318 tests, all passing.

## Completed in 2.12.2 (User manual screenshots)
- 7 real screenshots (captured via Qt widget.grab(), against a throwaway temp DB) embedded in docs/USER_MANUAL.md.
- In-app Help > User Manual viewer resolves relative image paths so screenshots render in-app too.
- Shareable HTML manual (Artifact) embeds the same screenshots as base64 data URIs.

## Completed in 2.12.1 (Help menu)
- Help menu with an in-app User Manual viewer (renders docs/USER_MANUAL.md, F1) and a Version/About dialog.
- pytest regression suite now 316 tests, all passing.

## Completed in 2.12.0 (Paper Trading, Phase 8)
- `tradelab/core/broker.py`: Qt-free broker abstraction + `PaperBroker` simulator — cash, long/short positions with weighted-average cost, realized/unrealized P&L, market + resting-limit order book, commission, JSON persistence (`data/paper_account.json`, gitignored). Price source is injectable (offline-testable).
- New "Paper Trading" tab: simulated-account banner, order entry, live account summary, positions/orders tables, mark-to-market refresh, reset.
- AI Assist tab: added a persistent "no live market data" disclaimer.
- Live trading intentionally out of scope — simulation only; no orders routed, no funds moved.
- pytest regression suite now 312 tests, all passing (network-free).

## Completed in 2.11.0 (AI Assistant, Phase 7 - option b: LLM-backed)
- `tradelab/core/ai_assistant.py`: Qt-free, transport-injectable client for Anthropic's Messages API. Builds an indicator-snapshot context per symbol, sends chat turns, parses replies. Default model `claude-sonnet-5` (Opus 4.8 / Haiku 4.5 selectable).
- New "AI Assist" tab: chat UI, masked API-key field + model picker (saved in QSettings), symbol-context loader, threaded worker so the UI never freezes.
- No key set -> falls back to the offline rules-based Trade Coach (zero cost, always usable).
- Safety: system prompt forbids buy/sell/hold advice and recommendation-style targets; educational only; user brings their own paid API key. In-UI disclaimer.
- pytest regression suite now 295 tests, all passing (network-free via injected fake transport).

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

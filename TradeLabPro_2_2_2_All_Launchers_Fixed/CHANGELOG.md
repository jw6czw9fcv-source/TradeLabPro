# Changelog

## 2.21.0 - Heatmap ↔ Scanner link (Phase 14)

### Added
- **Map your scan results.** A new **🗺 Map results** button on the Scanner sends the current results into the **Heatmap** as a "Scanner results" source (sized by cap, coloured by % change, grouped by sector) and switches to that tab — instantly see which of your hits are green/red and where the strength is.
- **Right-click a heatmap tile** for a context menu: **Open chart** or **Add to watchlist**. (Left-click still opens the chart.)
- **Zoom & pan the heatmap (Finviz-style).** Scroll to **zoom** toward the cursor on dense maps, **drag** to pan, **double-click** empty space to fit. Zoom enlarges the *tiles* while the **label text stays a normal, readable size** — and tickers that were too small to show simply **appear** once their tile is big enough. Left-click still charts a tile; right-click still opens the menu.
- **More tickers labelled on the heatmap.** Tile labels now **auto-fit** their font to the tile and are **clipped** to it, so far smaller tiles show their symbol (and % change where there's room) instead of only the big ones — handy on dense maps like mapped scan results.

### Verified
- 471/471 pytest tests pass (new: Scanner `result_symbols()` filters error rows, `show_results_in_heatmap()` end-to-end sets the heatmap source and fronts the tab; heatmap `set_external_symbols()` adds/selects the source and clears any theme).

## 2.20.0 - Chart Replay (Phase 13)

### Added
- **New "Replay" tab.** Practice reading a chart bar-by-bar with the future hidden:
  - **Play / Pause**, step **forward** / **back**, jump to **start** or **end**, and a **speed** control (0.5×–8×).
  - Choose where to start (**Start at bar N**) and **scrub** anywhere with the slider.
  - Indicators recompute **only on revealed bars**, so there's genuinely no look-ahead.
- (This replaces a dead, never-wired-in "Next candle" stub with a full transport.)

### Verified
- 463/463 pytest tests pass (new: reveals only the start bars, step/scrub stay in bounds, auto-play pauses at the end, reset returns to the start, controls disabled until loaded).

## 2.19.0 - Risk & Position Sizing (Phase 12)

### Added
- **New "Risk" tab.** Size trades by risk instead of by gut:
  - **Position sizing** — account equity + risk % (or a fixed $) + entry + stop → the **share count** that risks exactly that, live as you type. Long or short, with optional caps by **max position %** and it flags when a cap kicks in. Shows position value, % of account, actual $ and % at risk, stop distance, and $/share risked. "Use paper account equity" fills equity from your paper account.
  - **R-multiple targets** — a table of 1R / 2R / 3R target prices and the dollar gain for the sized position (1R = your stop distance; longs aim up, shorts down).
  - **Portfolio sector exposure** — loads your Portfolio-tab positions and breaks them down by sector with % of book, flagging heavy concentration (≥40% in one sector).
- Planning tool only — it places no orders.

### Verified
- 457/457 pytest tests pass (new: `tests/test_risk.py` — share-count math, floor rounding, fixed-$ risk, short side, max-position/buying-power caps, invalid inputs, R-target prices for long/short, sector-exposure grouping; `tests/test_risk_panel.py` — headless UI incl. live recompute and exposure handler).

## 2.18.4 - Journal: click a header to sort

### Added
- **Click any column header in the Journal to sort** (click again to reverse) — trades table and the breakdown table. Numeric columns (Qty, Entry, P&L, P&L %, R, Days, Win %) sort by **value, not text**, so 100 doesn't land between 10 and 2. Dates sort chronologically.
- Your chosen sort **survives a refresh/import**, so re-importing doesn't throw you back to the default. Default remains Entry date, newest first.

### Verified
- 437/437 pytest tests pass (new: numeric column sorts by value both directions, chosen sort persists across refresh).

## 2.18.3 - Journal: show trade dates

### Fixed
- **Imported trades appeared to have no date.** The dates were parsed correctly all along (IBKR's `20260126;123300` -> `2026-01-26`), but the journal table had no date columns to show them. Added **Entry date**, **Exit date** and **Days** (holding period) columns.

### Changed
- The trades table now lists **newest first**, so a freshly imported year of history opens on your most recent trades.

### Verified
- 435/435 pytest tests pass (new: date/Days columns populate, newest-first ordering).

## 2.18.2 - Fix "no trades found" on IBKR import

### Fixed
- **Big accounts reported "no trades" when the report was simply still generating.** IBKR returns a "statement generation in progress" response while it builds the report; after our 20 s wait we returned *that* body, which contains no trades. We now wait up to **90 s** and, if it's still generating, say so ("wait a few seconds and Fetch again") instead of pretending the report was empty.
- **Non-stock trades were silently dropped.** The importers filtered to `assetCategory = STK`, so options / futures / forex activity vanished. **All asset classes** now import (CSV and XML). For derivatives the contract **multiplier** is applied so P&L is real dollars (1 option contract $2 → $5 = **+$300**, not +$3).
- **Trade Confirmation reports are now readable** — a query producing `<TradeConfirm>` rows (instead of Activity's `<Trade>`) previously parsed to nothing.
- **No more double counting** when a query emits the same trade at several levels of detail (execution + order/closed-lot) — execution rows win.

### Changed
- If your Flex Query omits a required field (most commonly **Trade Price**), the error now **names the missing field** and tells you where to tick it, instead of a vague "none could be read".
- When an import returns nothing, the message now says *why*: it reports how many trade rows the report actually contained and what to check (Trades section enabled, date period, Activity vs Trade Confirmation query), and saves the raw report to `logs/ibkr_flex_last.xml` for inspection.

### Verified
- 433/433 pytest tests pass (new: still-generating timeout raises instead of returning an empty body, all-asset-class import, option multiplier P&L, `<TradeConfirm>` parsing, level-of-detail de-duplication, row-count diagnostic).

## 2.18.1 - IBKR Flex credentials: save & keep

### Changed
- The **IBKR Flex** dialog now has a **Save** button that stores your token + Query ID **without** fetching — so when the token changes you can just update it in the app. Credentials are kept in the OS settings store (independent of the app folder), so they **persist across app updates/reinstalls**; you only enter them once. Added a **Show token** toggle for entry.

### Verified
- 427/427 pytest tests pass (new: credentials save via an injected settings store, so the real saved token is never touched).

## 2.18.0 - Trade Journal (Phase 11)

### Added
- **New "Journal" tab.** Log trades (symbol, side, qty, entry, optional **stop**, strategy, tags, notes) and review what actually works:
  - Per-trade **P&L, P&L %, R-multiple** (vs. your stop), and status.
  - Aggregate stats: **win rate, W/L, expectancy per trade, profit factor, average R, total P&L**.
  - **Breakdown by Strategy / Tag / Symbol** — see which setups make money.
- **Import from Paper Trading** — pairs your paper account's fills into position-level round-trip trades (size-weighted entry/exit), idempotently (no duplicates on re-import).
- **Import from IBKR (CSV)** — load a real Interactive Brokers trades export (both the **Flex Query** trades format and the **Activity Statement** format), auto-detecting columns and asset class (stocks only); fills are paired into round-trips and de-duplicated like paper imports. Read-only import of your own history — no brokerage connection, no orders.
- **Import from IBKR (Flex Web Service)** — a direct pull: paste your read-only **Flex token + Query ID** (stored locally, token masked) and the app fetches the report over HTTPS (two-step SendRequest/GetStatement with automatic retry while the statement generates), off the UI thread. Parses the Flex XML report (falls back to CSV) and imports it. Still read-only — no login, no order routing, no funds.
- **Close** open trades (enter an exit price), **edit notes**, **export to CSV**, and double-click a row to chart the symbol.
- Journal persists to `data/journal.json` (gitignored). Analysis/practice only — nothing here places orders.

### Verified
- 426/426 pytest tests pass (new: `tests/test_journal.py` — P&L/R/expectancy/profit-factor math, strategy/tag breakdowns, FIFO position-level fill pairing incl. scale-outs/shorts/opens, IBKR Flex/Activity CSV parsing, Flex Web Service two-step fetch with retry + error handling and XML report parsing, store persistence; `tests/test_journal_panel.py` — headless UI incl. paper, IBKR CSV, and Flex import paths).

## 2.17.0 - Heatmap: group by Industry/Country, Theme baskets, World map

### Added
- **Group by Sector / Industry / Country / None.** The old "Group by sector" checkbox is now a **Group** dropdown. `get_quote_meta` now also returns `country`, so tiles can block by industry or country.
- **Theme dropdown (thematic baskets).** A **Theme** selector maps curated baskets — AI & Big Data, Semiconductors, EV & Battery, Cloud & SaaS, Cybersecurity, Biotech, Renewable Energy, Fintech & Payments, E-commerce & Internet, Defense & Aerospace, Gaming & Esports, Social Media. A theme overrides the Market while set; picking a Market clears it.
- **World map (Finviz-style).** New **World – Large caps** market of major global companies (mostly US-listed ADRs), which auto-selects **Group by Country** — Taiwan, China, Japan, UK, Germany, India, Brazil, Canada, and more.
- Tile tooltips now show Industry and Country too.

### Verified
- 389/389 pytest tests pass (new: industry/country grouping, theme baskets/choices, tiles carry industry+country, panel group-by options, theme override, World→Country default).

## 2.16.0 - Heatmap: Portfolio map + performance periods

### Added
- **Portfolio map.** "Portfolio" is now a Market source on the Heatmap — it maps your Portfolio-tab holdings, just like Watchlist.
- **Performance-period dropdown (Finviz-style).** A **Period** selector — **1 Day / 1 Week / 1 Month / 3 Month / 6 Month / 1 Year / 3 Year / 5 Year / 10 Year / YTD** — chooses the window the tile colour represents. The reference close is the price N trading days back (or the prior year's last close for YTD). Long look-backs use bounded fetch spans (≤10y, never `max`) so the update stays fast (~0.5s regardless of period). Changing the period re-fetches automatically once a map is loaded, and the colour legend relabels (e.g. "1 Month change:").

### Verified
- 382/382 pytest tests pass (new: 1-Day/1-Week/YTD change math, period choices, Portfolio source, period dropdown updates the legend).

## 2.15.0 - ETF / Index heatmaps

### Added
- **ETF and index maps on the Heatmap tab.** New presets: **US – Sector ETFs (SPDR)** (XLF, XLK, XLE, …), **US – Index & asset ETFs** (SPY, QQQ, DIA, IWM, GLD, SLV, TLT, HYG, LQD, ARKK), **US – ETFs (all)**, and **Canada – ETFs** (XIU, XIC, ZSP, VFV, …).
- Funds have no market cap or sector, so `get_quote_meta` now falls back to **AUM** (`totalAssets`/`netAssets`) for tile size and the fund **category** (e.g. "Large Blend", "Financial", "Long Government") for the sector grouping — so ETF maps size and group meaningfully. The market-cap filter and Scanner get real AUM for funds too.

### Fixed
- Hardened company-name resolution so a rate-limited fund whose summary starts with filler ("In seeking to track …") no longer shows a garbage name — it falls back to the display name or ticker.

### Verified
- 376/376 pytest tests pass (new: ETF AUM/category resolution, filler-summary guard, ETF/index presets present).

## 2.14.3 - Company names on the chart (KO, CAT, JPM…)

### Fixed
- **Many stocks showed only their ticker, not the company name** (KO, CAT, MO, JPM, XOM, …). Yahoo has become inconsistent about which name field it returns — these blue-chips come back **without** `longName`/`shortName`, so the lookup fell back to the ticker. Name resolution now also uses `displayName` and derives the full legal name from the business summary, so the chart header (and heatmap tooltips) show e.g. **"KO — The Coca-Cola Company"**, **"JPM — JPMorgan Chase & Co."**, **"BAC — Bank of America Corporation"**. Affects `get_quote_meta`, so the Scanner "Sector"/name columns benefit too.

### Verified
- 373/373 pytest tests pass (new: legal-name extraction from a business summary incl. `&`/`of` connectors, and the full longName → shortName → summary → displayName → ticker fallback chain).

## 2.14.2 - Heatmap auto-refresh

### Added
- **Auto-refresh timer on the Heatmap.** Tick "Auto-refresh every N s" (15 s–1 h) and the map reloads on a timer so it tracks the market through the day. Toggling it on refreshes immediately; the status line shows the last update time and an "auto-refresh on" marker. A refresh that overruns its interval is skipped rather than stacked (the loader no-ops while a fetch is in flight). The timer stops cleanly on app close.

### Verified
- 363/363 pytest tests pass (new: timer starts/stops with the toggle, interval changes apply live, shutdown stops the timer).

## 2.14.1 - Window fits the screen (layout fix)

### Fixed
- **The bottom of the window could be cut off / unreachable** (reported when clicking a stock in the Heatmap). Root cause: a `QTabWidget` adopts its **tallest** page as the whole tab stack's minimum height, so the tall **Scanner** tab (~1330px, its parameters + results table) forced the entire window taller than a 1080p screen — clipping the bottom of every tab and the charts. Each tab page is now wrapped in a **scroll area**, so a page still fills a tall pane but scrolls internally instead of overflowing a short one. The window's minimum height dropped from ~1360px to ~380px, so it fits any screen.

### Verified
- 360/360 pytest tests pass (new: window minimum height stays under a normal screen; tab panels remain accessible after the scroll-area wrap).

## 2.14.0 - Market Heatmap

### Added
- **New "Heatmap" tab** — a Finviz-style market map. Each stock is a tile **sized by market cap** (or dollar volume) and **coloured green→red by the day's % change**, grouped into **sector blocks** via a squarified treemap. See a whole market's health at a glance.
- **US and Canadian presets** built in: US Mega/Large caps (NASDAQ+NYSE), NASDAQ-only, NYSE-only, Canada TSX large caps, Canada TSX (expanded), plus your **Watchlist**.
- **Click any tile to open its chart.** Hover for a tooltip (name, sector, price, % change, size). Toggle sector grouping, choose the sizing metric, and cap the tile count for speed/readability.
- Loads off the UI thread with a progress bar; prices come from a single batched download and cap/sector from cached metadata, so it stays responsive and still renders offline.

### Verified
- 358/358 pytest tests pass (new: `tests/test_heatmap.py` — squarified-treemap layout tiles the area proportionally & in-bounds, colour scale, tile/sector building, offline provider; `tests/test_heatmap_panel.py` — headless UI smoke via an injected provider).

## 2.13.0 - Alerts Engine

### Added
- **New "Alerts" tab.** Watch any symbol for any condition (the same field/operator/value builder the Scanner and Strategy Builder use — price, RSI, MACD, EMA/SMA crossovers, VWAP, and every other indicator, incl. plugins) and get a **desktop notification** the moment it triggers.
- **Edge-triggered** firing: "RSI Below 30" fires once as it drops through 30, not on every check while it stays below. Two modes — **recurring** (re-arms and can fire again on the next crossing) and **once** (fires a single time, then disarms).
- **Background poller** with a configurable **Auto-check** interval (15 s – 1 h) plus a manual **Check now**; a running check never freezes the UI (evaluation runs off the UI thread). Firings are shown in an in-panel log and sent to the system tray.
- Alerts persist to `data/alerts.json` (gitignored per-user state), surviving restarts without immediately re-firing already-true conditions.
- Quick-add a symbol from your watchlist.

### Notes
- Analysis/practice tool only — alerts never place orders (consistent with the simulated-only safety model).

### Verified
- 339/339 pytest tests pass (new: `tests/test_alerts.py` core engine — edge-trigger/once/recurring/persistence/offline-provider; `tests/test_alerts_panel.py` headless UI smoke).

## 2.12.5 - Manual: Open as PDF

### Added
- **📄 Open as PDF** button at the top of the in-app **Help → User Manual** window. It renders the manual (text + all screenshots) to an A4 PDF and opens it in the system's default viewer. Images are embedded as document resources and scaled to the page width.

### Changed
- Links in the exported **PDF** (including the Table of Contents) render in **black**. The on-screen viewer keeps Qt's default link colour.

### Verified
- 322/322 pytest tests pass (new: PDF button present, PDF export writes a valid `%PDF`, shared link-recolor helper).

## 2.12.4 - Manual zoom follows screenshots

### Fixed
- In the in-app **Help → User Manual** viewer, **Ctrl + mouse wheel** now zooms the text *and* the embedded screenshots together (browser-style page zoom). Previously only the text zoomed and the images stayed at a fixed size. Window resize/maximize scaling (added in 2.12.3) is unchanged.

### Verified
- 319/319 pytest tests pass (1 new in `tests/test_help_menu.py`: images grow with Ctrl+wheel zoom).

## 2.12.3 - Manual window polish

### Changed
- The in-app **Help → User Manual** window now has standard title-bar controls — **minimize** and **maximize/restore** next to the close [X] — like a normal window (was a plain dialog with only a close button).
- Embedded screenshots in the manual viewer now **scale to the window width** and re-scale on resize/maximize (new `ManualBrowser`), instead of staying at their fixed native size.

### Verified
- 318/318 pytest tests pass (2 new in `tests/test_help_menu.py`: window buttons present, images scale to width).

## 2.12.2 - User manual screenshots

### Added
- Seven real screenshots (captured via Qt `widget.grab()`) embedded in `docs/USER_MANUAL.md`: Scanner, Charts, Backtest, Strategy builder, Plugins, Paper Trading, and AI Assist.
- The in-app **Help → User Manual** viewer now resolves the manual's relative image paths (`setSearchPaths`), so the screenshots render inside the app as well as on GitHub.

### Notes
- Screenshots were captured against a throwaway temporary database, so no real user data appears in them.
- The shareable HTML manual (Artifact) embeds the same screenshots as base64 data URIs.

## 2.12.1 - Help menu

### Added
- **Help** menu in the menu bar with two items:
  - **User Manual** (F1) — opens an in-app viewer that renders `docs/USER_MANUAL.md` in a scrollable window, so the full manual is readable without leaving the app.
  - **Version** — an About dialog showing the app name, version, a one-line description, and the analysis/practice-only disclaimer.
- Menu/action references are held on the window so PySide6 doesn't garbage-collect the underlying C++ objects.

### Verified
- 316/316 pytest tests pass (3 new in `tests/test_help_menu.py`).

## 2.12.0 - Paper Trading (Phase 8)

Phase 8 delivers the safe, genuinely useful half of "IBKR-grade" connectivity: a broker abstraction plus a fully-simulated paper-trading account. **No real money moves and no live orders are ever routed** — everything fills against a local ledger. The abstraction is built so a real broker *paper-account* adapter can drop in later behind the same API.

### Added
- `tradelab/core/broker.py`: a Qt-free, price-source-injectable broker layer. `Broker` abstract interface + `PaperBroker` — a self-contained simulator with cash, long/short positions (weighted-average cost, realized + unrealized P&L), a market/limit order book (limits rest until a crossing price), commission support, and JSON persistence (`data/paper_account.json`, gitignored).
- New **Paper Trading** tab: a prominent simulated-account banner, order entry (symbol / side / qty / market-or-limit), a live account summary (cash, equity, realized/unrealized/total P&L), positions and orders tables, mark-to-market refresh, and account reset.
- AI Assist tab now carries a persistent "no live market data" disclaimer clarifying it reasons over TradeLabPro's indicator snapshot plus training knowledge, not real-time prices/news.

### Safety
- Live trading is intentionally out of scope: this layer simulates only. It never sends orders to a broker or moves funds.

### Verified
- 312/312 pytest regression tests pass (16 new across `tests/test_broker.py` and `tests/test_paper_trading_panel.py`), all network-free via injected prices.

## 2.11.0 - AI Assistant (Phase 7, option b: LLM-backed)

The roadmap's Phase 7 "AI Assistant" shipped as a real natural-language assistant (not just the offline rules-based coach). It explains scans, charts and setups in plain English by calling Anthropic's Messages API with the user's own key.

### Added
- `tradelab/core/ai_assistant.py`: a Qt-free, transport-injectable LLM client. Builds a compact indicator-snapshot context from a symbol (reusing the offline coach's scoring), sends chat turns to the Claude Messages API, and parses the reply. Model is configurable (default `claude-sonnet-5`; Opus 4.8 and Haiku 4.5 also selectable).
- New **AI Assist** tab: chat UI with a masked API-key field + model picker (saved locally in QSettings), a "Load symbol context" button, and a threaded worker (`QThread`) so the window never freezes during a call.
- **Graceful degradation**: with no API key set, the assistant answers from the offline rules-based Trade Coach — the feature is always usable at zero cost.

### Safety
- The system prompt hard-constrains the model to educational/explanatory output only: no buy/sell/hold calls, no recommendation-style price targets, honest about uncertainty, and it must not invent data. This is reinforced by an in-UI disclaimer. The user supplies (and pays for) their own API key; no credentials ship with the app.

### Verified
- 295/295 pytest regression tests pass (15 new across `tests/test_ai_assistant.py` and `tests/test_ai_assistant_panel.py`), all with an injected fake transport — no network access in tests.

## 2.10.1 - Company name on chart + sub-pane safeguard

### Added
- The full company name is now shown above the indicator legend in the price pane (e.g. `AAPL — Apple Inc.`), fetched via `get_quote_meta` on plot. Falls back to just the ticker when the name is unavailable.
- Sub-pane safeguard in the Indicators dialog: the on/off toggles are relabelled "Show Volume / Show RSI / Show MACD" and visually separated (a stretch) from their period fields so a pane can't be turned off by accident while adjusting a period. A new "Show all sub-panes" button restores every hidden pane in one click.

### Verified
- 280/280 pytest regression tests pass (new: company-name header test and the "Show all sub-panes" safeguard test).

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

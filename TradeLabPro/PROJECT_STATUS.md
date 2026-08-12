# TradeLab Pro Project Status

Current version: 2.43.0
Current phase: ETF comparison & allocation building (done)

## Completed in 2.43.0 (Fill an allocation by a rule)
- **`etf_metrics.build_allocation(funds, bands, method, cap, drop_duplicates)`** -> `{"weights", "excluded"}`. Eligibility by **published CSA band**, `EQUAL` or `INVERSE_VOL` weighting, an iterative cap that redistributes the excess (and stops when every fund is capped rather than looping), and duplicate removal via `overlaps(..., weight_key=None)` keeping the **lower MER** with the ticker as tie-break so it's repeatable. It selects nothing on its own - every input is the user's.
- **Cap bug found by using it:** the redistribution fed the excess back to funds already at the cap, oscillating instead of converging and returning a weight *above* the cap (VAB at 40% under a 30% cap). Capped funds are now fixed and only uncapped ones absorb the excess. An **infeasible** cap (`cap * n < 1`) is refused with the lowest workable cap named — a test had previously enshrined the broken outcome (three funds at 20% summing to 60%).
- `_BuildAllocationDialog.LAST` remembers the rule for the session; reopening at the defaults read as the form resetting itself.
- **Sectors column** from `get_fund_composition`'s `sectors` (same fetch, no extra request; covers the whole fund unlike the top-ten holdings), sorted desc and run through `market_data.canonical_sector` so `financial_services` and `Financial Services` are one sector. `_weighted_html()` renders name/weight pairs with the weights in `theme.MUTED` - a `QTableWidgetItem` is one colour throughout, so those cells are `QLabel` widgets carrying `{"html", "sort"}`.
- `_FULLSCREEN_ENTER`/`_FULLSCREEN_EXIT` module constants shared by the chart, the Screener and both report dialogs, which now toggle full screen themselves.
- **`holdings_summary()`** folds it to one row per fund (the shipped view; `holdings_rows()` keeps the per-holding form). `published` is `None` for a silent fund, never 0 - unknown is not empty. `_EtfReportDialog` word-wraps and caps a runaway column at 520px so the holdings cell shows in full.
- **`holdings_rows(funds, compositions)`** + `show_fund_holdings()` / `_render_fund_holdings()`: one row per (fund, holding), each fund's unpublished remainder as its own row, a fund publishing nothing kept with `weight=None` (unknown != empty). Shares the look-through's two-stage fetch through a `self._lt_render` hook rather than a second copy of it.
- **Editing gotcha worth remembering:** a scripted `str.replace` on `def shutdown(self):` hit **eight** panels at once. Anchor on a docstring line unique to the panel, and assert `count(old) == 1` before replacing.
- `overlaps()` gained `weight_key=None` ("compare every fund", for building from scratch) and `keep`/`drop` per pair.
- `_BuildAllocationDialog` previews the result live and disables Apply when nothing matches. Bands are pre-ticked by **name** correspondence to the target column, labelled in the code as such. Writing **replaces** the whole column (a stale weight must not survive into a mix the rule no longer includes) and leaves the other two allocations alone.
- **Full-screen fix:** tab pages live in a `QScrollArea`; scrolled down to the table, the toolbar and the only exit button were off the top. `toggle_panel_fullscreen` now scrolls the panel to the top, and the button is first on the bar. **Esc was tried and removed** - the user wants the button, matching the chart.

## Completed in 2.42.0 (One risk rating, the published one)
- **`csa_volatility()` / `csa_level()` in `core/etf_metrics.py`** — NI 81-102 Appendix F: annualized standard deviation of **month-end** returns over **10 years** (monthly sd x sqrt(12)), banded 0-6 Low / 6-11 Low to medium / 11-16 Medium / 16-20 Medium to high / 20+ High. Bands verified against the AIMA Canada & CAIA guidelines quoting Appendix F, not written from memory. Returns `(stdev, months)`: **the window is reported with the figure**, because a level standing on 4 years is not the regulator's 10-year level. `CSA_MIN_MONTHS = 36` — under three years nothing is rated. The regulation fills a short history with a reference index; **we do not**, and the tooltip says so, so a young fund can differ from its own Fund Facts.
- **Deliberately a second measurement, not a replacement for `risk_metrics()`**: that one is daily x sqrt(252) over available history (for comparing funds inside the app), this one is monthly over a fixed decade (for matching a published document). Confusing them is the whole trap.
- `dividend_yield()` reuses `core.dividends.ttm_per_share` so the Screener and the Dividends tab cannot report different yields; `compute_metrics(symbol, prices, dividends)` fetches dividends itself when not supplied.
- **Schema v5**: `pct_gold` -> `pct_alt` (gold was one commodity in a column built for index funds; the rule is *metal in a vault has no geography, miners are equities and go in the regional columns*), plus `csa_stdev` / `csa_level` / `csa_months` / `dividend_yield`. **Nothing dropped** - `risk`, `sharpe` and `my_mix` stay in the table and merely leave the screen, so no judgement anyone typed is destroyed.
- **Columns removed from the view**, on the user's "enlever le superflu": hand-typed `risk` 1-5 (disagreed with the app's own volatility: ZLU rated 2 at 13.9%, MNT rated 3 at 19.6%), `sharpe` (a performance measure, incomparable across funds with different histories), `my_mix` (**verified identical to `mid_risk` on all 31 rows**), and the `low_vol` flag from 2.41.0 (the Risk column answers it against a published standard).
- **Totals row** is a separate 1-row table under the main one (a total row *inside* it would sort with the funds and vanish under a filter), tracking the table's column widths and horizontal scroll. **`MainWindow.toggle_panel_fullscreen()`** mirrors `toggle_chart_fullscreen` - hides the chart instead of the tabs, reusing the window-level mechanism rather than reparenting the table, which would break the pinned column and the totals row. **Frozen-column fix:** both views forced to `ScrollPerPixel` - a QTableView scrolls per item until row heights differ, so forwarding a scrollbar value between two views in different modes parked the pinned column half a row off.
- Summary rows reworked: "Average risk" dropped with its input column, "Weighted dividend yield" added. Filter gains a `Risk: <band>` group.

## Completed in 2.41.0 (The ETF workbook, in the app) — pushed + tagged v2.41.0 (b6cdb78)
- **Schema v3** (`SCHEMA_V3` in `data/database.py`): one `etf_screener` row per fund, mirroring the columns of the `Portefeuille_FNB.xlsx` workbook it replaces. Percentages stored as fractions, as the workbook stored them.
- **Typed columns and computed columns never cross.** `etf_upsert` touches only the keys it is given (so editing one cell can't blank the row) and ignores unknown ones; `etf_update_metrics` is restricted to `ETF_METRIC_COLUMNS` and **drops `None`** — a fund with eight years of history keeps the ten-year figure already on file instead of having a refresh erase it.
- New `core/etf_metrics.py` (Qt-free, offline-testable): `trailing_return`, `risk_metrics`, `get_prices`, `compute_metrics` — the maths of `tools/maj_rendements.py`, unchanged, ported off the spreadsheet. Returns >= 1 year annualized, adjusted close (dividends reinvested), 3% risk-free rate for Sharpe. **A column with too little history is not written**, never estimated.
- `composition_summary(funds, weight_key)` replaces the workbook's SUMPRODUCT block, and adds what the spreadsheet could not say: `covered` per row, so a weighted 10-year return standing on half the allocation is reported as half, not as the whole.
- New **ETF Screener** tab (`EtfScreenerPanel`, **between Scanner and Watchlists** — the fund decision falls before the shortlist): 31-column editable table, add/remove tickers, percent-in / percent-out editing (type `20`, `20%` or `62.5 %`), and **four** weight columns — `low_risk` / `mid_risk` / `high_risk` / `my_mix` — totalled side by side with an OK/adjust check. Tab is **English like the rest of the app**, guarded by a test that rejects French letters in any string the panel owns. Foot of the tab carries the workbook's CAD ↔ US equivalence notes (`EtfScreenerPanel.EQUIVALENTS`). **`_FrozenFirstColumn`** pins the Ticker column (a second `QTableView` over the *same* model + selection model, columns 1..n hidden, stacked over the host viewport - only geometry, row heights and the two vertical scrollbars need syncing; its header click is forwarded to `sortItems` since it covers the host's own). Double-click on column 0 charts the **Yahoo** symbol via `_HistoryWorker`; other columns are left to the cell editor. Toolbar is a `FlowLayout` in a `heightForWidth` widget - a fixed `QHBoxLayout` clipped Refresh/Stop when the chart splitter was dragged right. `shutdown()` wired into `closeEvent`.
- **Schema v4** renames `reco_star`/`spec_star`/`ma_compo` → `mid_risk`/`high_risk`/`my_mix` and adds `low_risk`. `ALTER TABLE ... RENAME COLUMN`, not a re-create: those columns hold real allocations. Verified against the live 31-fund database.
- **Acting on an allocation, not just describing it:** `etf_metrics.rebalance(funds, holdings_rows, weight_key)` (matches on the **Yahoo** symbol, percentages of the **whole book**, `covered` + `unmatched` so a half-covered plan can't read as on-plan), `overlaps()` (same-mix-or-category pairs that both carry weight, `OVERLAP_TOLERANCE = 0.10` keeps VCN/XIC together without merging VFV/VGT; runs on every edit, not behind a button), `rebased_series()` (**common** start date - rebasing each fund from its own first bar compares different periods). UI: `_EtfReportDialog` / `_EtfCompareDialog`, reusing `_MarketRefreshWorker`, `_FundCompositionWorker`, `pa.holdings`, `pa.look_through` and `RebasedChartWidget` rather than growing new maths. Same synthetic-data refusal as Analytics. Plus filter box, CSV export (stored fractions), Watchlist/Portfolio buttons (0 shares, like the Scanner), green/red on measured columns only.
- **Help → Revision history** (`show_revision_history`): `docs/VERSIONS.md` + `CHANGELOG.md` in a two-tab `ManualBrowser`, both added to `TradeLabPro.spec` datas (a viewer reading files the build doesn't ship is empty on a clean machine).
- **Filter dropdown**: values built from the table's own contents, plus `EXPOSURE_CHOICES` reading the `pct_*` columns via the item's `sort_value` — region is a *label* (XAW says "Global" and is 60% US), so filtering on it alone misses funds. Combo item data is a **string** (`keyvalue`): Qt's `findData()` compares QVariants and silently fails to match a Python tuple.
- **Three defects found by using it (2026-08-10), none reachable from the test suite:** (0) `add_fund` on an existing ticker with an empty Yahoo box overwrote `yahoo` with the bare ticker (VFV.TO -> VFV): the DB layer's "only touch what you were given" rule, broken one level up in the UI. Cost: the fund silently became "held directly" in the look-through. (1) `self._analysis_worker = worker` *inside the first worker's signal handler* freed a still-running QThread -> native crash, no traceback (same family as the 2.37.0 Analytics crash). `_track()`/`_forget()` keep every live worker in `self._workers` until `finished`; `shutdown()` joins them all. (2) `market_data._fund_holding_symbol` appends `.TO` to a bare ticker inside a `.TO` fund - correct for RY in XIC.TO, **wrong for VOO in VFV.TO**, and VOO.TO is not a quote. `alternate_listing()` + `fold_alternate_listings()` ask for both and keep whichever answered.
- **Two-level look-through:** `pass_through_symbols(comps, min_weight=PASS_THROUGH_WEIGHT=0.9)` finds a fund held ~whole inside another (VFV.TO -> VOO.TO at 100%) and the panel fetches those in a **second** `_FundCompositionWorker` pass before rendering; `expand_compositions()` folds them down, **keeping the nested fund's unpublished remainder attributed to that fund** so every company weight stays a floor. Threshold is deliberately 0.9: 60% in one name is a concentrated fund, not a wrapper. A failed second pass degrades to one level rather than reporting nothing.
- **`low_vol` computed column** (`etf_metrics.is_low_volatility`, `LOW_VOL_THRESHOLD = 0.12`): **True/False/None**, where None = never refreshed and is deliberately *not* False. Not a DB column - computed in `_decorated_funds()` on every render, so a stale answer can't survive a threshold change. Threshold spinbox persists via `QSettings("TradeLabPro", "TradeLabPro")` - **a bare `QSettings()` has no organization and silently persists nothing**, which is how the first version failed. Filter gains a "Passes low vol" entry; CSV exports yes/no/blank.
- **Bug found in the wild:** `look_through()` returns `exposures`, not `rows` — the panel read a key that has never existed, so "What this mix holds" was always empty. `funds_no_data` is also computed panel-side: a source answering with an empty record is as much "nothing published" as one that doesn't answer, and `look_through` only counts the latter.
- `docs/VERSIONS.md` + `tools/build_version_index.py`: generated release index (61 releases), CHANGELOG for the titles + git tags for the dates, distinguishing *unreleased* (newer than every tag) from *no tag of its own* (folded into a later release). `tests/test_version_index.py` fails if the committed file drifts.
- Scanner: dropped the redundant "Load selected chart" button (double-click has done it for releases; the right-click menu keeps the explicit path).
- `EtfMetricsWorker` (QThread, `ScanWorker` pattern) refreshes returns/risk with a progress bar and a Stop button — one 11-year download per fund, spaced 0.6 s, so a thirty-fund refresh cannot freeze the UI. A dead symbol is skipped and counted, not fatal.
- `tools/import_etf_screener.py` — one-off, idempotent Excel import (31 funds). Blank cells are omitted rather than written as zero. `tools/maj_rendements.py` kept alongside it as the original script; the workbook itself is gitignored (personal allocations, public repo).
- Tests: `tests/test_etf_metrics.py`, `tests/test_etf_screener_panel.py`, `tests/test_etf_import.py`, plus the ETF block in `tests/test_database.py`. Full suite 1081 passing.

## Completed in 2.40.0 (The plan you can't import)
- New `core/retirement.py` (Qt-free, offline-testable). Model: `Account` -> `Fund` -> `Snapshot` (units / unit_value / value) + `Flow` (contribution / employer / withdrawal) + `Published` (a fact sheet's figure for one horizon, with the fund's own index).
- **Two returns, never conflated.** `fund_return` prefers unit values (exact — a unit price cannot be moved by buying more units) and falls back to chain-linked `modified_dietz` over dollar balances, reporting `method` either way. `personal_return` is an `xirr` (bisection, not Newton: irregular contributions hand Newton a near-zero derivative) treating the **first snapshot as the opening stake**, so no history is required — flows dated on or before it are already inside that balance and are ignored.
- **`parse_published`** reads a fund fact sheet's compound-returns block. Column headings are *read, never assumed* — a fund too young for a 10-year column would otherwise have its 5-year figure reported as a decade's. French worded dates ("au 31 mars 2026") parse.
- **The fee is modelled, not footnoted.** Sheet returns are struck before the plan's investment management fee; `published_rows` reports `excess_pct` as published and `net_excess_pct` after the fee. On the real plan this is decisive: the index fund's +0.03 pp one-year edge becomes roughly -1.5 pp after a 1.5% fee. An annual fee is not applied to the 3-month row.
- `plan_published` weights by holdings (not a plain average) and reports `covered_pct` + `missing` so a figure speaking for 60% of the money reads differently from one speaking for all of it.
- `parse_statement` handles the real Canada Life layout: category headings skipped, `12 049,25 $` and `1,234.56` both parsed (last separator wins), re-pasting a date corrects that statement instead of doubling it. `unrecorded_units` flags a unit jump with no contribution on file rather than absorbing it into performance.
- New `ui/widgets/rebased_chart.py` — every fund restated to 100 at its first statement. **Unit values only**: a dollar balance rises when you contribute, and charting that as performance would mislead.
- New **Retirement** tab (`RetirementPanel`, after Dividends): statement paste with **preview before write**, fact-sheet paste per fund, plan fee input, horizon picker, funds table (index column editable, everything else output), published-returns table, rebased chart, contributions table, and a "needs" list naming what is missing. Refuses synthetic index data like Analytics and Dividends. `shutdown()` wired into `closeEvent`.
- Tests: `tests/test_retirement.py`, `tests/test_retirement_panel.py`. Full suite 911 passing.

## Completed in 2.39.0 (The book's year, charted on Home)
- New `core/home.ytd_curve(positions, histories, target, fx, today)` (Qt-free): slices `portfolio_analytics.portfolio_equity` at the calendar year and **anchors it to last year's final close** when the history reaches back that far (`from_last_year`), returning the series plus start/last/change/change_pct, high/low, `max_drawdown_pct`, `limited_by` and a one-line `text`. `YTD_MIN_POINTS = 3` (two dots in January is not a year); `YTD_LATE_START_DAYS = 7` decides when a late start is a holding's fault rather than the calendar's.
- `_ytd_limited_by` names the holding whose short history cut the year short — the equity curve spans only dates every priced holding shares, so one recently-listed name silently moves "the start of the year" to March.
- New `ui/widgets/equity_curve.py` — `EquityCurveWidget` (pyqtgraph): direction-coloured line + tinted area, dashed baseline with a labelled anchor, `MoneyAxis` short-dollar ticks (`$412k`), bars plotted at index with the chart's own `BarDateAxis` so weekends leave no gaps, and a cursor readout (date, value, % from start) that falls back to the period summary. **No portfolio maths in the widget** — it renders a series someone else computed.
- `HomePanel.ytd_chart` + `_render_ytd` sit under the tiles; `home.summarize` exposes `ytd`. The footnote states the caveat every time: today's share counts valued backwards, **not an account statement** (no contributions, withdrawals, intra-year trades or dividends received) — an imported IBKR position has no trade date, so nothing better exists in the data.
- Suite 819 passing.

## Completed in 2.38.0 (Coming up: scheduled dates)
- New `core/events.py` (Qt-free, offline-testable): `upcoming(calendars, today, horizon_days, symbols)` -> sorted `{symbol, kind, date, days_away, text}`; `EARNINGS`/`EX_DIVIDEND`; `HORIZON_DAYS = 45`; `describe_when` (today/tomorrow/in N days); `next_for`; `summarize` (events + `no_data` + one-line `text`); `text_for` (caps at 3, "+N more").
- **Rules, all deliberate:** past dates dropped (a done ex-div is history); beyond the 45-day horizon dropped (estimates that far out move); **nothing inferred** — a date is published or absent. Module docstring records why the **economic calendar (CPI/PPI/FOMC/BoC) and analyst actions are excluded**: no reliable wired-in source, and a hardcoded table goes stale silently.
- Data layer: `market_data.get_calendar` (cached) + `_yahoo_calendar` (yfinance `Ticker().calendar`, no synthetic fallback) + `_first_date` (earnings arrive as a list — a confirmed date or a low/high estimate range — while ex-dividend is a bare date); `DataProvider.get_calendar` on the ABC (synthetic returns both None).
- UI: `HomePanel.upcoming_line` + `_render_upcoming` — amber when the soonest event is <=3 days, and **names holdings with no calendar** so a quiet line reads as "funds have none", not "the lookup broke". `_HomeWorker` now fetches calendars too (`done` signal gained an argument); `home.summarize(..., calendars=...)` exposes `events`.
- Verified on the real book: POW.TO reports in 3 days, KTOS in 8, RY.TO in 31, IBKR ex-div in 35; VTI/XDIV.TO/XIC.TO publish nothing; POW's and RY's already-past ex-div dates correctly excluded. Suite 799 passing.

## Completed in 2.37.0 (Look-through exposure)
- `core/portfolio_analytics.py`: `look_through(rows, compositions)` — the book restated by company (direct + fund-borne, `via` names the funds), with each fund's unreported remainder kept separate in `unallocated` (**never scaled up**, so every exposure is a floor); `funds_opened`/`funds_no_data` make gaps visible. `look_through_sectors(rows, compositions, stock_sectors)` blends fund sector weights with individual holdings' sectors, keeping the unpublished part as "Unclassified".
- Data layer: `market_data.get_fund_composition` (cached per symbol) + `_yahoo_fund_composition` (yfinance `funds_data.top_holdings` / `sector_weightings`, **no synthetic fallback**), `DataProvider.get_fund_composition` on the ABC (synthetic returns empty).
- **`_fund_holding_symbol`** — Yahoo lists a TSX fund's holdings as a mix of `RY`, `TD`, `MFC.TO`; a bare ticker inside a `.TO/.V/.CN/.NE` fund means the Toronto listing. Taken literally `RY` is the NYSE line (different security/price/currency) and would have split the largest exposure in two.
- **`canonical_sector`** — funds say `financial_services`, stock profiles say `Financial Services`; unnormalised, the real book reported the same sector twice (45% + 25%). One mapping now merges them (70%).
- UI: `_FundCompositionWorker` (per-symbol fetch + `get_quote_meta` sector for non-funds, off-thread); Analytics gains the look-through table (Company / Exposure / % of book / Held directly / Also inside, click-to-chart) + summary line naming the unallocated floor + a book-wide sector line. **Both fetches start from `analyze()` and run in parallel** — starting the composition fetch from the render path let a worker outlive its panel and crashed the test process.
- `core/home.py`: `CONCENTRATION_PCT = 40.0` shared by the position-level and look-through checks; `summarize(..., compositions=...)` exposes `look_through`; `attention(..., look_through)` adds the "once funds are opened up" item only when funds actually contribute. `_HomeWorker` now also fetches compositions (`done` signal gained an argument).
- Verified on the real book: RY.TO 33.4% look-through vs 28.5% direct, via XDIV.TO + XIC.TO; 18% unallocated below the published top ten. Suite 774 passing.

## Completed in 2.36.0 (Home dashboard)
- New `core/home.py` (Qt-free, offline-testable, **assembly-only**): `movers` (per-holding day move — % native, $ converted), `day_move`, `next_payment` (nearest paying month, wrapping into next year), `attention` (>5% drop, `no_data`, `fx_missing`, >40% concentration), `summarize` (delegates to `portfolio_analytics.summarize` and `dividends.summarize` so Home can never disagree with those tabs), `_headline`.
- Market context on Home, also assembly-only: `STRIP_INDICES`/`index_strip` (world board, TSX first) and `MACRO_ROW`/`macro_row` (USD/CAD 4dp, commodities in dollars, ^TNX as a yield with a basis-point move and `directional=False` so it is never coloured green-for-up).
- New **Home** tab (`HomePanel`), placed first: four metric tiles, Needs attention + Today's movers in a 150px height-capped split (the container is what keeps headings tight to their boxes without stranding the lines below), income line, market read line, world line, macro line. Click-to-chart on movers; refuses synthetic price data; `shutdown()` wired into `closeEvent`.
- `MarketPanel` now publishes what it computed: `marketRefreshed` signal, `_last_refresh`, `_global_indices`, and `market_summary()` returning per-region read/breadth/sectors/VIX plus `indices` and `macro` (regime instruments merged across scored regions). Home renders that read rather than computing a cheaper second one.
- `MainWindow.refresh_on_startup()` — Home first (400ms after paint), then `_warm_market` 3s later, each in its own try so startup can never be taken down by a refresh failure.
- New `ui/theme.py`: one semantic palette (UP/DOWN/NEUTRAL/MUTED/TEXT/WARN, `pnl_color`, `pct_color`, and the NOT_ADVICE/EDUCATIONAL_ONLY/ANALYSIS_ONLY strings). `ui/colors.py` and `pg_chart_widget.py` now derive from it instead of re-picking their own greens and reds.
- Fixed: `log` was local to `main()`, so the startup-refresh error handlers would themselves raise `NameError` — now a module-level logger. Added `if __name__ == "__main__"` to `ui/app.py` (`python -m tradelab.ui.app` previously exited 0 with no window).
- Tests: `tests/test_home.py`, `tests/test_home_panel.py`. Full suite 759 passing.

## Completed in 2.35.0 (Dividend tracker)
- New `core/dividends.py` (Qt-free, offline-testable): `detect_frequency` (median payment spacing -> monthly/quarterly/semi/annual), `ttm_per_share` (historical fact) vs `forward_per_share` (latest payment x frequency — the projection, so a raise counts immediately), `growth_pct`, `payment_months`, `holding_income` (income, current yield, yield on cost), `payment_calendar`, `summarize`. Currency follows the v2.34.1 model: per-share amounts native, income totals in the target currency.
- Data layer: `market_data.get_dividends` + `_yahoo_dividends` (tz-naive), `DataProvider.get_dividends` on the ABC (synthetic provider returns empty — income is never fabricated).
- New **Dividends** tab (`DividendsPanel`, after Analytics): income tiles, per-holding table (frequency, div/share, income, yield, yield on cost, growth), and a shaded 12-month payment calendar. Click-to-chart; refuses synthetic price data.
- **Chart dividend markers restored** (lost when the chart engine moved from matplotlib to PyQtGraph): `_DividendFetchWorker` (off-thread, cached per symbol), `dividend_scatter` markers under each bar with amount tooltips, trailing yield in the price header, and a toggle in the Indicators dialog.
- Fixed: growth compared window *sums*, so an uneven payment count (3 vs 4 in a window) reported a raising dividend as a ~19% cut — now compares average payment size. Chart header and Dividends tab now share one yield calculation so they can't disagree.
- Tests: `tests/test_dividends.py`, `tests/test_dividends_panel.py`, `tests/test_chart_dividends.py`. Full suite 728 passing.

## Completed in 2.34.1 (Analytics matches IBKR)
- `holdings()` reworked to the IBKR display model: `last`/`avg_entry` native currency, `market_value`/`cost_basis`/`unrealized` in the target currency (both sides converted at the current FX rate, so unrealized % equals the native price move). Verified line-for-line vs the user's IBKR CAD statement.
- Fixed test-suite data leak: `tests/test_heatmap_panel.py` built its panel on the real `data/tradelab.db` and inserted a demo NVDA position every run; tests now use a throwaway temp DB.
- `market_data.synthetic_ohlcv` frames carry `attrs["synthetic"]=True`; new `is_synthetic()`. `PortfolioAnalyticsPanel._on_loaded` filters synthetic frames so Analytics never renders fabricated prices (stock, benchmark, or FX) — missing data shows "—" plus a named status note.
- `summarize()`: unrealized P&L excludes unpriced holdings' cost (`no_data` list reported); `window_limited_by` names a holding whose short history shrinks the common window >10%.
- Holdings table: new per-holding "Return" column (window return in display currency); benchmark named in the return tile; click-to-chart wired on Portfolio and Analytics tables (`_HistoryWorker`).
- Tests: suite at 700 passing; regression coverage for all of the above.

## Completed in 2.34.0 (Portfolio analytics + IBKR position import)
- New `core/portfolio_analytics.py` (Qt-free): `holdings` (per-position valuation, weights, unrealized P&L), `portfolio_equity` (Σ shares×close on common dates = real equity curve), `beta`/`annualized_vol`/`max_drawdown`/`total_return`/`cagr`, `concentration` (largest, top-3, HHI effective-N), `correlation` (holdings only, avg pairwise), `summarize`. Multi-currency: `currency_of` (suffix→ccy), `fx_pair_symbol`, and conversion so **live prices convert to a target currency (default CAD) while the imported cost basis is left as-is** (an IBKR CAD account's costs stay CAD; only Yahoo prices are converted). Benchmark converted too.
- New `core/portfolio_import.py` (Qt-free): parse open positions from IBKR Flex XML (`<OpenPosition>`) / Activity CSV / flat Flex CSV; lot-merge; keep short signs. `_to_yahoo_symbol` (exchange/currency → Yahoo suffix, class-share dash) and `choose_symbol`/`resolve_positions` (cost-basis-proximity probe to disambiguate homonyms like US XDIV vs XDIV.TO, and the US-stock-vs-Canadian-CDR trap for NVDA). `fetch_ibkr_positions` reuses the Journal's read-only Flex fetch.
- `Database.set_portfolio_positions(portfolio, positions)` — replace-in-place sync (no duplicate re-imports).
- UI: new **Analytics** tab (`PortfolioAnalyticsPanel`, after Portfolio): benchmark + history + **Currency selector (default CAD)**, metric tiles, holdings table with native-currency column, concentration line, correlation matrix, off-thread fetch (`_MarketRefreshWorker`) including FX pairs. **Portfolio** tab gains "Import from IBKR" (CSV/XML file + Flex fetch, `_IbkrPositionsWorker`/`_ResolveSymbolsWorker`, replaces the 'IBKR' group). Both new panels' `shutdown()` wired into `closeEvent`.
- Tests: `tests/test_portfolio_analytics.py`, `tests/test_portfolio_import.py`, `tests/test_portfolio_analytics_panel.py`. Full suite 695 passing.

## Completed in 2.33.0 (Seasonality analysis)
- New `core/seasonality.py` (Qt-free, offline-testable): `monthly_return_series` (month-end resample → month-over-month %), `monthly_stats` (12 rows: avg/median/win-rate/best/worst/count across years), `weekday_stats` (Mon–Fri daily-return seasonality), `annual_returns` (intra-year first→last-close % per year), `years_covered`, `month_context` (per-month strong/weak/mixed read), and `summarize` (headline text + best/worst month + current-month context). Shares the `_close` guard pattern (collapse duplicated 2-D Close, coerce a DatetimeIndex).
- New **Seasonality** tab (`SeasonalityPanel` in `ui/app.py`, after Replay): symbol + history selector, `_SeasonalityWorker` fetches off-thread; renders a By-month table with a green→red heatmap avg column (reuses `heatmap.color_for_change`) and bolded strongest/weakest months, plus By-weekday and By-year tables and a plain-English headline. `shutdown()` wired into `MainWindow.closeEvent`.
- Descriptive/backward-looking only — labelled not a forecast, not advice.
- Tests: `tests/test_seasonality.py` (10) + `tests/test_seasonality_panel.py` (2). Full suite 662 passing.

## Completed in 2.32.0 (AI Trading Coach)
- New `core/coach.py` (Qt-free, offline-testable): `grade_trade(entry)` — additive, transparent PROCESS rubric (base 50; stop present +20 / absent −28; stop honored +5 / broken −15; reward-to-risk tiers by R; documented +8 / −6; clamped 0–100 → A/B/C/D/F). Grades execution, not outcome: a lucky no-stop win grades F, a disciplined −1R loss grades B. `coach_report(entries)` — process metrics (no-stop %, stop-honored %, documented %, avg win/loss ratio, holding winners vs losers, grade distribution, best/worst strategy by expectancy) + ranked `suggestions` (warn/good/info, each citing its number). `build_coach_context()` / `offline_coach_report()` / `COACH_SYSTEM_PROMPT` / `coach_answer()` for the LLM path (reuses `ai_assistant.ask`, transport-injectable).
- New **Coach** tab (`CoachPanel` in `ui/app.py`, after Journal): graded-trades table (colour-coded grade, R, P&L; click a row for the point-by-point breakdown), live offline process report, and an AI chat over the journal (shares the AI-Assist API key via QSettings `AIAssistant/*`; offline fallback with no key). `_CoachWorker` runs the LLM call off the UI thread; auto-refreshes from the Journal on show; `shutdown()` wired into `MainWindow.closeEvent`.
- Educational/retrospective only — reviews past trades, never recommends or predicts. Offline-first; the LLM only narrates the locally-computed numbers.
- Tests: `tests/test_coach.py` (18) + `tests/test_coach_panel.py` (3). Full suite 650 passing.

## Completed in 2.31.0 (Faster Market refresh: batched downloads, both markets cached)
- Fix: the US Market refresh no longer stalls. `_MarketRefreshWorker` used to fetch ~90 symbols serially (one `get_history` each), tripping Yahoo's rate limit. New `market_data.get_histories()` / `_yahoo_histories()` / `_yahoo_download_chunk()` batch up to 40 tickers per `yf.download(list, group_by="ticker")` call; the provider abstraction gained `DataProvider.get_histories()` (default serial loop, Yahoo overrides with the real batch). Failed/empty symbols fall back to synthetic per-symbol, same as before.
- Change: one refresh now downloads and scores **both** markets in the same batched pass (~167 symbols, ~5 requests) via `required_symbols()`; `_render()` caches every region. Switching country is always an instant re-render — the racy background prefetch (`_prefetch_other_region`) is gone.
- Fix: the global-indices table no longer blanks on a country switch. `_populate_global_scaffold()` builds it once at construction; `populate_static()` now rebuilds only the region tables, so the global values persist across switches.
- pytest regression suite passing, incl. new batched-download tests and a global-indices-survive-a-switch regression test.

## Completed in 2.30.0 (Advance/decline breadth on the Market tab)
- `core/market.py`: `breadth_universe(region, per_sector=6)` (the 6 largest names per GICS sector from `core.sectors`, deduped: ~66 US / ~64 CA) and `advance_decline(trends)` (advancers/decliners, A/D ratio, net, % above 50/200-day). `market_condition` gained `breadth_unit` and now weights the 200-day breadth share heavily (±12), naming the % in a reason and the summary.
- Market tab: new **_MarketBreadthCard** under the read card — big highlighted **% above 200-day** (green>60/amber/red<40), advancers vs decliners with A/D ratio, % above 50-day, sample size. Follows the country selector; both markets cached + prefetched. The read's breadth component now comes from stock-level participation (`stock_breadth`) rather than the 11-sector count.
- Refresh grew ~45→~86 symbols per market (still off-thread, progress bar, background prefetch of the other market).
- pytest regression suite now 623 tests, all passing.

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

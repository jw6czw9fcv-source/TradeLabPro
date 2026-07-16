# TradeLab Pro — User Manual

**Version 2.12.0**

TradeLab Pro is a desktop trading **workstation** for the stock market: scan the
market for setups, chart and analyze symbols, keep watchlists and a portfolio,
backtest strategies, build your own strategies and indicators without code,
practice with a simulated paper-trading account, and ask a built-in AI assistant
to explain what you're looking at.

> **Important — what this app is and isn't.** TradeLab Pro is an **analysis and
> practice** tool. It does **not** place real orders, connect to a live
> brokerage, or move real money. Everything about trading in this app is
> **simulated**. Nothing in it is financial advice. Always do your own research
> and consult a licensed professional before risking real capital.

---

## Table of Contents

1. [Installation & launching](#1-installation--launching)
2. [The main window](#2-the-main-window)
3. [A five-minute tour](#3-a-five-minute-tour)
4. [Scanner](#4-scanner)
5. [Charts](#5-charts)
6. [Watchlists](#6-watchlists)
7. [Portfolio](#7-portfolio)
8. [Market dashboard](#8-market-dashboard)
9. [Backtest lab](#9-backtest-lab)
10. [Strategy builder](#10-strategy-builder)
11. [Plugins](#11-plugins)
12. [Paper trading](#12-paper-trading)
13. [AI assist](#13-ai-assist)
14. [Settings & your data](#14-settings--your-data)
15. [Tips & FAQ](#15-tips--faq)
16. [Glossary](#16-glossary)

---

## 1. Installation & launching

**Requirements:** Windows, Python 3.11+ (tested through 3.14).

**First-time setup:**
1. Run `install_requirements.bat` to install the Python dependencies.
2. Launch with `run_tradelab.bat` **or** double-click `START_TradeLabPro.vbs`.

The app opens maximized and remembers its window size and position between runs.

**Online vs. offline.** TradeLab Pro pulls market data from Yahoo Finance
(`yfinance`) when you're connected. With no internet, it falls back to
**deterministic synthetic data** so every screen stays usable for practice and
demos — the numbers are fake but consistent, so nothing crashes or blanks out.

---

## 2. The main window

The window is split into two halves:

- **Left — the tabbed control panel.** Ten tabs: Scanner, Watchlists, Portfolio,
  Market, Backtest, Strategies, Plugins, Paper Trading, AI Assist, Settings.
- **Right — the chart workspace.** Always visible. Charts you open from the
  Scanner (or type in directly) appear here as dockable panels.

Drag the divider between the two halves to rebalance the space. The left panel
won't collapse below a readable width.

---

## 3. A five-minute tour

1. **Scan.** Open the **Scanner** tab, pick an exchange/list (e.g. USA), and click
   **Scan**. A ranked table of matching symbols appears.
2. **Chart.** Double-click any result row — it loads on the chart at right, with
   the company name and **live price** at the top-left, candlesticks, moving
   averages, and Volume/MACD/RSI sub-panes.
3. **Save it.** Right-click a result (or use the buttons) to add a symbol to a
   **Watchlist** or **Portfolio**.
4. **Check the market.** Open the **Market** tab for a one-glance read on whether
   conditions favor trading today.
5. **Practice.** Open **Paper Trading**, buy a few simulated shares, and watch
   your P&L update. No real money involved.
6. **Ask.** Open **AI Assist**, load a symbol's context, and ask "what is this
   setup telling me?" in plain English.

---

## 4. Scanner

The Scanner filters the market down to symbols matching your criteria and ranks
them by a 0–100 **Score**.

### Running a scan
1. Choose which symbols to scan using the **exchange / list** selectors
   (shortcuts: USA, Canada, All, None; your own lists live under **My Lists**;
   ETFs are under My Lists, not Exchanges).
2. Set your filters (below).
3. Click **Scan**. Use **Stop** to interrupt a long scan.

### Filters
- **Price / Volume / Market cap** — minimum and maximum bounds.
- **Relative volume, RSI range, ATR% range** — momentum and volatility gates.
- **EMA trend / positive MACD** — require a trend condition.
- **Custom filters** — add your own conditions across 16+ technical fields
  (price, volume, RSI, ATR%, ADX, MACD family, EMAs, SMAs, Bollinger bands,
  price-vs-SMA20%, and any indicator plugins you've added). Each is
  Above / Below / Between a value, and all are AND-ed with the fixed filters.
- **Strategy** — the dropdown chooses which strategy scores and signals each
  symbol (e.g. EMA/MACD Trend, RSI Mean-Reversion, or any custom strategy you
  built). This drives the Signal and Score columns.

### Reading the results
Columns: **Symbol, Signal, Score, Conf%, Sample, Price, Volume, RelVol,
Market Cap, Cap, Sector, RSI, ATR%, EMA, MACD**.

- **Score (0–100)** — the strategy's overall read; rows are color-tiered by score.
- **Signal** — BUY / SELL / neutral per the selected strategy.
- **Conf% / Sample** — of the strategy's past BUY signals on this symbol, the
  fraction that were profitable 10 bars later, and how many signals that's based
  on. A high Conf% on a large Sample is more trustworthy than one on a tiny
  sample. A dash (—) means not enough history.
- **Cap** — Mega / Large / Mid / Small / Micro bucket.
- Error rows (Score 0) render in gray, with the error message on the Symbol
  cell's tooltip — so a scan failure never masquerades as a weak result.

Double-click a row to chart it. The status line summarizes counts and a sector
breakdown.

### Presets
Use the **Preset** combo to save, switch, and delete named scan setups (stored in
`data/setups/`). "Save As" creates a new one; the list stays in sync
automatically. **Open** loads a setup file from elsewhere on disk. You can also
**export** scan results.

---

## 5. Charts

The chart workspace on the right renders responsive, zoomable charts (built on
PyQtGraph).

### Loading & navigating
- Load a symbol by double-clicking a Scanner result, or type a ticker into the
  chart's own search box.
- **Period** and **Interval** selectors set the history length and bar size.
- **Pan** by dragging, **zoom** with the scroll wheel, and read exact values from
  the **crosshair** — a synced readout across the price, Volume, MACD, and RSI
  panes shows date/time and full OHLCV plus indicator values in the bottom status
  bar.

### The price header
Top-left of the price pane shows:
```
AAPL — Apple Inc.
$212.45   +1.32 (+0.63%)
```
The company name, then the **latest price** and its **day-over-day change**
(green when up, red when down). This is the last close of the loaded history, not
a live streaming tick.

### Chart types
**Candlestick, Heikin-Ashi, Line, Area.**

### Indicators
Click any entry in the on-chart **legend** (top-left) to open the **Indicators**
dialog — the legend *is* the editing entry point. From there you can:
- Add / remove **overlays** with tunable periods: EMA, SMA, Bollinger, VWAP,
  Pivot Points, SuperTrend, Ichimoku Cloud, Volume Profile, and any plugin
  indicators.
- Toggle the **Volume / MACD / RSI** sub-panes and tune their periods. A
  "Show all sub-panes" button restores any you turned off by accident.
- Toggle **BUY/SELL signal** markers (EMA-crossover confirmed by MACD).

### Drawing tools
Trendline, horizontal line, vertical line, rectangle, **Fibonacci retracement**,
and text notes. Drawings are **saved per symbol and timeframe**, so they're still
there when you come back.

### Multiple charts & layouts
Open several charts side by side as dockable panels; a switcher row (below the
toolbar) has one button per open chart, plus a small close (×) on each and a
**Reset charts** button to collapse back to one. You can save and reload named
chart **layouts**.

---

## 6. Watchlists

Track symbols you care about. The table shows **Item, Symbol, Last, Change %,
Purpose**. You can import and export watchlists. Add symbols directly from Scanner
results. Selecting an entry can load it on the chart.

---

## 7. Portfolio

A simple holdings record: **ID, Portfolio, Symbol, Shares, Entry**. Add positions
(e.g. from a Scanner result), group them by portfolio name, and export. This is a
**record-keeping** ledger for positions you hold elsewhere — it does not place or
track live orders. For simulated order entry and P&L, use **Paper Trading**
(section 12).

---

## 8. Market dashboard

A one-glance read on overall conditions:
- A color-coded **macro headline** with a 0–100 "is it a good day to trade" read
  and the reasons behind it.
- A **sector-breadth table** across 11 SPDR sector ETFs: **Sector, ETF, Change %,
  vs 50-day**, plus a breadth summary line (how many sectors are above/below
  their moving averages).
- A regime-symbol table that feeds the read.

Use this before scanning to gauge whether the broad market is with you or against
you.

---

## 9. Backtest lab

Test a strategy against historical data. Four sub-tabs:

- **Single** — run one strategy on one symbol; see metrics (win rate, total
  return, profit factor, **max drawdown %**) and the full trade list (Entry Date,
  Exit Date, Entry, Exit, Return %).
- **Multi-Symbol** — the same strategy across many symbols, aggregated:
  Symbol, Trades, Win rate %, Total return %, Profit factor, Max drawdown %.
- **Optimize** — sweep a single parameter to see which value performed best.
- **Walk-Forward** — test across rolling time windows (Window, From, To, Trades,
  Win rate %, Total return %) with a consistency score, to check a strategy isn't
  just curve-fit to one period.

Each tab includes plain-language hints and color-coded verdicts that interpret
the numbers for you.

> **Backtests describe the past, not the future.** Good historical numbers are
> necessary but not sufficient. Watch the sample size, the max drawdown, and
> whether results hold up across walk-forward windows.

---

## 10. Strategy builder

Build your own BUY/SELL strategies **without code**:
1. Add **condition blocks** for entry (BUY) and exit (SELL) — e.g. "RSI Below 30",
   "EMA 9 Above EMA 21", "Price Above SMA 200".
2. Conditions support **field-vs-value** and **field-vs-field** comparisons (for
   crossover-style rules).
3. **Save** the strategy — it's stored in `data/strategies/` and immediately
   appears in the Scanner and Backtest **Strategy** dropdowns, running exactly
   like the built-in strategies.

The available fields include the full indicator library (Stochastic, Williams %R,
CCI, ROC, OBV, MFI, VWAP, and more), each period-parameterized with sensible
defaults.

---

## 11. Plugins

Extend TradeLab Pro with **custom indicators** written in Python:
- Drop a `.py` file in the `plugins/` folder that defines `PLUGIN_NAME` and a
  `compute(df)` function returning an indicator series.
- It's auto-discovered at startup (and via the **Reload** button on this tab) and
  registered as an indicator field (`plugin:<name>`) usable in Scanner custom
  filters, the Strategy Builder, and chart overlays.
- The Plugins tab lists every plugin as loaded-OK or errored (errors are shown,
  never fatal). A bundled `sample_hl_range.py` is included as a template.

---

## 12. Paper trading

A fully **simulated brokerage account** for practice — the safe way to rehearse
order entry and watch P&L behave.

> **Simulated only.** No real money moves and no live orders are ever placed.
> Everything fills against a local ledger inside the app. A prominent amber banner
> on the tab is your reminder.

**Starting out:** the account begins with **$100,000** in simulated cash. It
persists between runs (in `data/paper_account.json`).

**Placing an order:**
1. Enter a **Symbol**, choose **BUY** or **SELL**, set the **Qty**, and pick
   **MARKET** or **LIMIT**.
2. **Market** orders fill immediately at the latest price. **Limit** orders rest
   until the price crosses your limit — click **Refresh** to fill any that have.
3. The order appears in the **Orders** table (with status and fill price).

**Watching your account:** the summary line shows **Cash, Positions value,
Equity, Realized P&L, Unrealized P&L, Total P&L**. The **Positions** table marks
each holding to market (Symbol, Qty, Avg price, Last, Market value, Unrealized
P&L). Both long and short positions are supported with proper average-cost and
realized-P&L accounting.

**Refresh** re-marks positions to the current price and fills any crossed limit
orders. **Reset account** wipes everything back to the starting cash (with a
confirmation).

---

## 13. AI assist

A natural-language assistant that **explains** indicators, scores, and setups in
plain English.

> ⚠ **No live market data.** It reasons over the indicator snapshot TradeLab Pro
> computes for the loaded symbol plus the model's general knowledge — not
> real-time prices, today's news, or earnings dates. **Educational only — not
> financial advice.** By design it won't tell you to buy, sell, or hold.

**Two modes:**
- **Offline Trade Coach (default, free).** With no API key set, you get a
  rules-based explainer at zero cost — always available.
- **LLM-backed (bring your own key).** Paste an **Anthropic API key** and pick a
  model to get richer, conversational answers. Per-use cost is billed to *your*
  Anthropic account.

**Setting up the LLM mode:**
1. Create a key at **console.anthropic.com** → API Keys, and add a little billing
   credit (the key won't work without it).
2. Paste it into the **API key** field and choose a **model**:
   - **Sonnet 5** *(default)* — the best balance; near-Opus quality for
     technical-analysis explanations at a fraction of the cost (~½–1¢ per
     question).
   - **Haiku 4.5** — cheapest (~⅓¢), great for simple "what is X?" lookups.
   - **Opus 4.8** — the richest multi-indicator reasoning (~1.3¢), when you want
     the most careful answer.
3. Click **Save**. The key is stored on your PC (Windows registry, under
   `TradeLabPro`) — treat it like a password; on a shared machine prefer an
   `ANTHROPIC_API_KEY` environment variable, or clear the field when done.

**Using it:** load a symbol's context, then ask questions like "Is this an uptrend
and why?" or "What does the RSI reading here mean?" Follow-ups in the same chat
cost a bit more (the whole conversation is re-sent each turn); use **Clear** to
reset. It's great at *"what does this setup mean"* and useless for *"what's the
price right now"* — that's the data limitation, not the model.

---

## 14. Settings & your data

The **Settings** tab shows where your data lives: the database path, the data
folder, and scan-history counts.

**Where things are stored** (all under the app's `data/` folder unless noted):
- `data/tradelab.db` — the SQLite database (watchlists, portfolio, scan history).
- `data/setups/` — saved Scanner presets.
- `data/strategies/` — your custom strategies.
- `data/paper_account.json` — your simulated paper-trading account.
- `logs/` — rotating application logs (useful if something misbehaves).
- Your **API key** and window layout — in the Windows registry under
  `TradeLabPro`, not in a file.

The database uses versioned migrations, so it upgrades cleanly across releases.

---

## 15. Tips & FAQ

**Where is my API key stored?** In the Windows registry at
`HKEY_CURRENT_USER\Software\TradeLabPro\TradeLabPro\AIAssistant`, or in an
`ANTHROPIC_API_KEY` environment variable if you set one. It's plain text — guard
it like a password.

**Why does the AI say it can't give me the current price?** Because it has no live
market feed — it only sees the indicator snapshot the app computes plus its
training knowledge. That's a deliberate limitation, not a bug.

**Can this place real trades?** No. Order entry exists only in **Paper Trading**
and is entirely simulated. There is no live brokerage connection.

**A scan row is gray — what happened?** That's a scan error for that symbol (data
fetch failed, etc.), shown distinctly from genuinely weak results. Hover the
Symbol cell for the error message.

**Nothing loads / I'm offline.** The app falls back to deterministic synthetic
data so screens stay usable. Reconnect for real Yahoo Finance data.

**My chart drawings disappeared.** Drawings are saved per symbol *and* timeframe —
switch back to the same interval to see them.

---

## 16. Glossary

- **EMA / SMA** — Exponential / Simple Moving Average.
- **MACD** — Moving Average Convergence Divergence (trend/momentum).
- **RSI** — Relative Strength Index (0–100 momentum oscillator; >70 often
  "overbought", <30 "oversold").
- **ATR%** — Average True Range as a percent of price (volatility).
- **Relative volume (RelVol)** — today's volume vs. its typical level.
- **Bollinger Bands** — a moving average with volatility bands above and below.
- **VWAP** — Volume-Weighted Average Price.
- **Score** — TradeLab Pro's 0–100 ranking of a setup for the selected strategy.
- **Conf%** — the historical hit-rate of the selected strategy's past BUY signals
  on that symbol.
- **Max drawdown** — the largest peak-to-trough drop in a backtest's equity.
- **Profit factor** — gross profit ÷ gross loss in a backtest (>1 is profitable).
- **Paper trading** — simulated trading with fake money, for practice.
- **Realized / Unrealized P&L** — profit/loss on closed positions / on open
  positions at the current price.
- **Long / Short** — a position that profits when price rises / falls.

---

*TradeLab Pro is an educational analysis and practice tool. It is not a brokerage,
does not execute trades, and does not provide financial advice.*

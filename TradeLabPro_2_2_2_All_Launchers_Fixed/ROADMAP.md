# Roadmap

## Complete: Phase 1 - Chart Engine
Dockable/resizable panels, PyQtGraph rendering, drawing tools, new overlays, saved layouts, synced crosshair.

## Current / Next: Phase 2 - Scanner Professional
- SCN-026 Professional Technical Filter Builder.
- SCN-027 Scanner result color standard.
- SCN-029 Professional Scanner Preset Manager.
- Multi-strategy scanning, sector/market-cap context, transparent confidence scoring tied to backtest stats.

## Later
- Phase 3: Market Dashboard (sector/breadth, "is it a good day to trade" macro read)
- Phase 4: Backtesting Lab (multi-symbol, optimization, walk-forward)
- Phase 5: Strategy Builder (visual, no-code)
- Phase 6: Plugin SDK (formal interface + auto-discovery)
- Phase 7: AI Assistant (explanatory coaching beyond the current heuristic ranker)
- Phase 8: IBKR Trade Connectivity (paper trading first, live only on explicit go-ahead)
- Phase 9: Alerts Engine (condition-based price/indicator alerts + desktop notifications) — DONE 2.13.0
- Phase 10: Market Heatmap (Finviz-style sector treemap for US & Canada) — DONE 2.14.0

- Phase 11: Trade Journal (tag/note trades, win-rate/R-multiple/expectancy review, import paper fills) — DONE 2.18.0

- Phase 12: Risk & position-sizing (risk %/stop -> shares, R-targets, sector exposure) — DONE 2.19.0

## Candidate next
- Phase 13: Chart replay / bar-by-bar practice mode — DONE 2.20.0
- Data-source abstraction (Alpaca/Polygon/IBKR) to harden the yfinance dependency
- Heatmap follow-ups: auto-refresh timer (DONE 2.14.2), index/ETF maps (DONE 2.15.0), click-through from Scanner results

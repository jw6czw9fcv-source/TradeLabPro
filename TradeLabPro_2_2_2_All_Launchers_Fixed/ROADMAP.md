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

## Candidate next
- Trade journal on top of paper trading (tag/note fills, win-rate & R-multiple review)
- Risk & position-sizing panel (risk % + stop -> shares, sector exposure)
- Chart replay / bar-by-bar practice mode
- Data-source abstraction (Alpaca/Polygon/IBKR) to harden the yfinance dependency
- Heatmap follow-ups: auto-refresh timer (DONE 2.14.2), index/ETF maps, click-through from Scanner results

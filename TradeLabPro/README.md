# TradeLab Pro

TradeLab Pro is a Qt desktop trading workstation for scanning, charting, watchlists, portfolios, and strategy development.

## Version
2.47.0 - Fresh when you open it - the tabs showing market data bring themselves up to date when opened (prices after 15 minutes, dividends and sectors once a day) and say how old their figures are; plus six fixes from a full review, and an installer 9.4 MiB lighter

2.46.1 - One rule for a bad download - a frame that came back with two 'Close' columns crashed a backtest optimisation, and would have taken the scanner, the alerts poller and the chart with it; the rule that prevents it now lives in one place instead of two

2.46.0 - What inflation is actually for - the projection runs in the dollars of the year each thing happens, with inflation projected explicitly over the indexed benefits, the spending and the tax brackets; tick Today's $ to read it back in today's purchasing power

## Run
1. Run `install_requirements.bat` if needed.
2. Run `run_tradelab.bat` or `START_TradeLabPro.vbs`.

## Build the executable and installer
```
pip install pyinstaller
winget install JRSoftware.InnoSetup
python tools/build_release.py
```

That produces three things:

| Output | What it is |
| --- | --- |
| `resources/tradelab.ico` | The app icon, redrawn from `tools/make_icon.py` |
| `dist/TradeLabPro.exe` | Standalone app, ~130 MB, runs with no Python installed |
| `installer/Output/TradeLabPro-Setup-<version>.exe` | Normal Windows installer |

The executable takes a few seconds to start, since a one-file build unpacks
itself each time. `--exe` skips the installer step.

**The installer** puts the app in `%LOCALAPPDATA%\Programs\TradeLab Pro` — the
per-user location VS Code and Teams use, so there is no admin prompt — adds it to
Settings > Apps so it uninstalls normally, and offers Start Menu and desktop
shortcuts. Its version number is read from `VERSION`, so it cannot claim a
different version from the app inside it.

**Taskbar pinning is a manual step.** Windows 10/11 removed the API that let
installers pin to the taskbar, so no installer can do it. Open the app, then
right-click its taskbar button and choose *Pin to taskbar*. The installer's final
page says the same thing.

## Where your data lives
In `%LOCALAPPDATA%\TradeLab Pro\` — whichever way you start the app. The .exe and
a run from source open the **same** portfolio, journal and alerts, so a trade
logged in one is never invisible in the other.

It sits outside both the source tree (real positions do not belong in a git
checkout) and the executable (a one-file build unpacks to a temp folder Windows
deletes on exit, which would throw the database away on every close).

Set `TRADELAB_DATA_DIR` to run against a different set of data. The test suite
uses it so a run can never touch your real portfolio.

## Connect Claude (MCP server)
`tradelab_mcp.py` lets Claude Desktop or Claude Code read TradeLab's figures and run
its calculations — retirement projection, Quebec + federal tax, look-through,
dividends, the ETF comparison and the journal. Pair it with IBKR's own connector and
one conversation holds the live account and TradeLab's maths on top of it.

Read-only by construction: the database is opened in SQLite's read-only mode, and it
runs locally over stdio with no network port.

```
pip install -r requirements-mcp.txt
claude mcp add tradelab --scope user -- python "C:\path\to\TradeLabPro\tradelab_mcp.py"
```

Claude Desktop setup and the tool list: manual, section 21.

## Notes
- ETFs are now located under My Lists, not Exchanges.
- Exchange shortcuts: USA, Canada, All, None.

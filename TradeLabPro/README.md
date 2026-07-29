# TradeLab Pro

TradeLab Pro is a Qt desktop trading workstation for scanning, charting, watchlists, portfolios, and strategy development.

## Version
2.38.0 - Coming up: the dates your holdings have scheduled - when each next reports earnings and next trades ex-dividend, on the Home tab

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

## Notes
- ETFs are now located under My Lists, not Exchanges.
- Exchange shortcuts: USA, Canada, All, None.

# TradeLab Pro

TradeLab Pro is a Qt desktop trading workstation for scanning, charting, watchlists, portfolios, and strategy development.

## Version
2.38.0 - Coming up: the dates your holdings have scheduled - when each next reports earnings and next trades ex-dividend, on the Home tab

## Run
1. Run `install_requirements.bat` if needed.
2. Run `run_tradelab.bat` or `START_TradeLabPro.vbs`.

## Build a standalone .exe
Produces `dist/TradeLabPro.exe`, which runs on a Windows machine with no Python
installed:

```
pip install pyinstaller
pyinstaller TradeLabPro.spec --noconfirm
```

The executable is around 130 MB (most of it Qt) and takes a few seconds to start,
since a one-file build unpacks itself each time.

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

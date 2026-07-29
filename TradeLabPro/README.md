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

**Where a packaged build keeps your data.** Not inside the .exe: it unpacks to a
temporary folder that Windows deletes on exit, so anything written there would be
lost when you close the app. The database, journal, alerts, notes, logs and
plugins all live in `%LOCALAPPDATA%\TradeLab Pro\` instead. Running from source
is unchanged — data stays in `data/` next to the code. That means the packaged
app starts with an empty portfolio; copy `data\tradelab.db` across if you want
your existing positions in it.

## Notes
- ETFs are now located under My Lists, not Exchanges.
- Exchange shortcuts: USA, Canada, All, None.

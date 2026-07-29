# PyInstaller build spec — produces a single TradeLabPro.exe.
#
#   pip install pyinstaller
#   pyinstaller TradeLabPro.spec --noconfirm
#
# The result lands in dist/TradeLabPro.exe and needs no Python installed on the
# machine that runs it.
#
# Note what does NOT ship inside it: your database, journal, alerts, notes and
# logs. A one-file build unpacks itself into a temp folder that Windows deletes
# on exit, so anything written there would be lost every time you closed the
# app. config.py sends all of that to %LOCALAPPDATA%\TradeLab Pro instead (see
# tests/test_packaged_paths.py).
from PyInstaller.utils.hooks import collect_submodules

datas = [
    # The in-app Help viewer reads the manual at runtime, so it has to travel
    # with the executable — along with the screenshots it references.
    ("docs/USER_MANUAL.md", "docs"),
    ("docs/images", "docs/images"),
    # Shipped sample plugins, so the Plugins tab isn't empty on a fresh machine.
    ("plugins", "plugins"),
    # The window/taskbar icon is loaded at runtime, so it has to ship too - the
    # `icon=` argument below only sets the icon on the .exe file itself.
    ("resources/tradelab.ico", "resources"),
]

hiddenimports = [
    # yfinance and pandas reach for these lazily, so the analyser can miss them.
    "yfinance",
    "pandas._libs.tslibs.base",
    *collect_submodules("pyqtgraph"),
]

excludes = [
    # Qt ships several large subsystems this app never touches; leaving them in
    # roughly doubles the download for no benefit.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtBluetooth", "PySide6.QtDesigner",
    "tkinter", "pytest", "PyInstaller",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TradeLabPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A desktop app, not a console tool: no black terminal window behind it.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Sets the icon on the .exe file itself, as Explorer shows it. Regenerate
    # with: python tools/make_icon.py
    icon="resources/tradelab.ico",
)

"""Helpers every tab shares: the status line, problem pop-ups, opening links
in front, the auto-refresh mixin and small table helpers."""
import os
import sys
import json
import logging
import re
import traceback
import time
from pathlib import Path
import pandas as pd
from PySide6.QtCore import (Qt, QThread, Signal, QSettings, QTimer, QUrl, QSize, QRect,
                            QPoint, QEvent, QObject, Slot)
from PySide6.QtGui import QAction, QImage, QTextCursor, QColor, QIcon, QPainter, QFont, QPen, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QSpinBox, QDoubleSpinBox, QComboBox,
    QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QSplitter, QFormLayout, QGroupBox, QCheckBox,
    QAbstractItemView, QTextEdit, QFileDialog, QProgressBar, QScrollArea, QHeaderView,
    QMenu, QToolButton, QSizePolicy, QDialog, QTextBrowser, QSystemTrayIcon, QStyle,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsSimpleTextItem, QFrame,
    QInputDialog, QSlider, QGraphicsItem, QLayout, QStackedWidget, QButtonGroup,
    QTableView
)
from tradelab.core.config import (APP_NAME, APP_VERSION, ScannerConfig, DATA_DIR,
                                  ROOT_DIR, LOG_DIR)
from tradelab.data.database import Database
from tradelab.data.universe import list_symbols, available_universes, refresh_exchange_cache, import_universe_file, universe_metadata
from tradelab.data.market_data import get_history, get_histories
from tradelab.core.scanner import scan_symbols
from tradelab.core.alerts import Alert, AlertStore
from tradelab.core.filters import FilterCondition
from tradelab.core.journal import Journal, JournalEntry, summarize, group_stats
from tradelab.core.risk import size_position, r_targets
from tradelab.core.links import Link, LinkStore
from tradelab.core.notes import load_notes, save_notes
from tradelab.core.news import fetch_news, MARKET_SYMBOLS, GEO_SYMBOLS, SECTOR_ETFS
from tradelab.core import heatmap as hm
from tradelab.core import freshness
from tradelab.core import backup, updates
from tradelab.core.updates import parse_version, version_text
from tradelab.data.universe import US_NASDAQ, US_NYSE, US_AMEX, CAN_TSX, CAN_TSX_EXPANDED
from tradelab.strategies import strategy_choices
from tradelab.ui.chart_widget import ChartWorkspace, ChartWidget
from tradelab.ui.widgets.equity_curve import EquityCurveWidget
from tradelab.ui.widgets.rebased_chart import RebasedChartWidget
from tradelab.ui.widgets.retirement_chart import RetirementChartWidget
from tradelab.ui import colors, theme
from tradelab.core.backtester import backtest_ema_macd
from tradelab.core.ai_ranker import explain_symbol
from tradelab.core.logging_config import get_logger
from tradelab.settings import SETTINGS_FILE_ENV, app_settings  # noqa: E402,F401

log = get_logger(__name__)


class StatusLabel(QLabel):
    """A panel's status line that also announces itself.

    Every panel keeps its own status label next to the controls it describes,
    which is the right place to read it while working — but it is easy to miss
    mid-page, and the window already has a status bar people look at. This
    emits what it was told to say so MainWindow can mirror it there; the two
    then cannot disagree, because there is one setText and one signal.
    """
    messageChanged = Signal(str)

    def setText(self, text):
        super().setText(text)
        if text:
            self.messageChanged.emit(text)


# --- problems: never silent --------------------------------------------------
# Set by the test suite, so a failure path under test does not leave a pop-up
# over every later test.
NO_POPUPS_ENV = "TRADELAB_NO_POPUPS"


_PROBLEMS_LISTED = 6     # problems one pop-up lists before "...and N more"


_problem_box = None      # the pop-up on screen, if any


_problem_lines = []      # what it lists, oldest first


def show_problem(text, parent=None):
    """Show a problem in a Windows pop-up, so nothing goes wrong silently.

    One pop-up at a time: problems arriving while it is open (a refresh failing
    in several tabs at once) are added to it instead of piling up behind it.
    Modal but not blocking - it returns at once, so a failure inside a worker's
    callback does not stall the window. GUI thread only; report_problem() is
    the way in from anywhere else."""
    global _problem_box
    log.warning("Problem shown: %s", text)
    if os.environ.get(NO_POPUPS_ENV) or QApplication.instance() is None:
        return
    if _problem_box is not None:
        _problem_lines.append(text)
        listed = _problem_lines[:_PROBLEMS_LISTED]
        body = "\n\n".join(listed)
        if len(_problem_lines) > len(listed):
            body += f"\n\n...and {len(_problem_lines) - len(listed)} more (see the log)."
        _problem_box.setText(body)
        return
    box = QMessageBox(QMessageBox.Warning, f"{APP_NAME} - problem", text,
                      QMessageBox.Ok, parent)
    box.setWindowModality(Qt.ApplicationModal)
    box.setAttribute(Qt.WA_DeleteOnClose)
    box.finished.connect(_problem_closed)
    _problem_lines[:] = [text]
    _problem_box = box
    box.show()
    box.raise_()
    box.activateWindow()


def _problem_closed(*_):
    global _problem_box
    _problem_box = None
    _problem_lines.clear()


def flag_problem(label, text, details=""):
    """A failure: say it on the panel's status line and in a pop-up. details,
    when given, goes in the pop-up only - too long for a status line."""
    label.setText(text)
    show_problem(f"{text}\n\n{details}" if details else text, label.window())


class _ProblemBridge(QObject):
    """Carries a problem from any thread to the pop-up on the GUI thread."""
    raised = Signal(str)

    def __init__(self):
        super().__init__()
        self.raised.connect(self._show)

    @Slot(str)
    def _show(self, text):
        show_problem(text, QApplication.activeWindow())


_problem_bridge = None


def report_problem(text):
    """show_problem() from any thread."""
    if _problem_bridge is not None:
        _problem_bridge.raised.emit(text)
        return
    app = QApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        show_problem(text, QApplication.activeWindow())
    else:
        log.warning("Problem with no window to show it: %s", text)


class ProblemPopupHandler(logging.Handler):
    """The app's own logged errors, as pop-ups: a refresh or a worker failing in
    the background logs it, and nobody reads the log while it happens. A record
    logged with extra={"popup": False} has shown its own pop-up already."""

    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        if getattr(record, "popup", True) is False:
            return
        try:
            text = (record.getMessage().splitlines() or [""])[0]
            exc = record.exc_info[1] if record.exc_info else None
            if exc is not None:
                text = f"{text}: {exc}"
            report_problem(text)
        except Exception:
            self.handleError(record)


def install_problem_popups():
    """Route problems from every thread, and the app's logged errors, to the
    pop-up. Once, on the GUI thread, after the QApplication exists."""
    global _problem_bridge
    if _problem_bridge is None:
        _problem_bridge = _ProblemBridge()
        logging.getLogger("tradelab").addHandler(ProblemPopupHandler())


# --- opening links: in front, and never silently -----------------------------
_ASFW_ANY = 0xFFFFFFFF


def open_external(target):
    """Open a web address (or a file) with its Windows program, in front.

    Returns None when it went, else the reason it did not. Two ways this used
    to look like a dead button: QDesktopServices.openUrl reports a refusal only
    through its return value, which was dropped; and a browser already running
    took the link in a tab behind this maximised window, because Windows does
    not let a background program jump in front. Now a refusal gets a second try
    through the shell, and the browser is brought to the front."""
    url = target if isinstance(target, QUrl) else QUrl(str(target))
    if url.isEmpty() or not url.isValid():
        return f"'{url.toString()}' is not an address that can be opened."
    text = url.toLocalFile() if url.isLocalFile() else url.toString(QUrl.FullyEncoded)
    web = not url.isLocalFile()
    if web:
        _allow_foreground()
    if QDesktopServices.openUrl(url):
        log.info("Opened %s", text)
    else:
        log.warning("Qt could not open %s; asking the shell directly", text)
        reason = _shell_open(text)
        if reason is not None:
            log.warning("The shell could not open %s either: %s", text, reason)
            return reason
        log.info("Opened %s through the shell", text)
    if web:
        _bring_browser_forward_soon(url.scheme())
    return None


def _shell_open(text):
    """A second try outside Qt: None when it went, else the reason. Never on the
    headless (offscreen) platform the tests run on, where Qt refuses every
    link: there is no desktop there, and a test must not launch the browser."""
    if QApplication.platformName() == "offscreen":
        return "there is no desktop to open it on"
    if sys.platform == "win32":
        try:
            os.startfile(text)
            return None
        except OSError as exc:
            return exc.strerror or str(exc)
    import webbrowser
    return None if webbrowser.open(text) else "no web browser is set up"


def _allow_foreground():
    """Let whichever process takes the link (the browser) come to the front.
    Only the program in front may grant that - which, right after a click on a
    link, this one is."""
    if sys.platform != "win32" or QApplication.platformName() == "offscreen":
        return
    try:
        import ctypes
        from ctypes import wintypes
        ctypes.WinDLL("user32").AllowSetForegroundWindow(wintypes.DWORD(_ASFW_ANY))
    except Exception:
        log.debug("AllowSetForegroundWindow failed", exc_info=True)


def browser_exe_from_command(command):
    """The program's file name in a Windows open command:
    '"C:\\...\\opera.exe" -noautoupdate -- "%1"' -> 'opera.exe'."""
    m = re.search(r'([^"\\/]+\.exe)', os.path.expandvars(command or ""), re.IGNORECASE)
    return m.group(1).strip().lower() if m else None


def _default_browser_exe(scheme="https"):
    """The program Windows opens web links with (opera.exe), from the registry."""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        key = rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            prog_id = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as k:
            command = winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None
    return browser_exe_from_command(command)


def _bring_browser_forward_soon(scheme="https"):
    """Put the browser in front once it has had a moment to take the link - two
    tries, since a browser that was closed takes longer to show a window. Each
    acts only while this program is still the one in front, so it never pulls
    focus from wherever the person has gone since."""
    if sys.platform != "win32" or QApplication.platformName() == "offscreen":
        return
    exe = _default_browser_exe(scheme)
    if not exe:
        return
    for delay in (400, 1500):
        QTimer.singleShot(delay, lambda: _bring_forward(exe))


def _bring_forward(exe):
    """Put the front-most window of program exe in front, if this program's
    window is still the foreground one. True when it moved."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        def pid_of(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value

        def exe_of(pid):
            handle = kernel32.OpenProcess(0x1000, False, pid)  # query limited information
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return Path(buf.value).name.lower()
                return ""
            finally:
                kernel32.CloseHandle(handle)

        if pid_of(user32.GetForegroundWindow()) != os.getpid():
            return False
        found = []

        def visit(hwnd, _):
            # Visible, not owned by another window, the browser's, titled: a
            # browser window rather than one of its pop-ups. EnumWindows goes
            # front to back, so the first match is the one used last.
            if (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4)  # GW_OWNER
                    and exe_of(pid_of(hwnd)) == exe and user32.GetWindowTextLengthW(hwnd)):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(enum_proc(visit), 0)
        if not found:
            return False
        if user32.IsIconic(found[0]):
            user32.ShowWindow(found[0], 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(found[0]))
    except Exception:
        log.debug("Could not bring the browser forward", exc_info=True)
        return False


AUTO_REFRESH_KEY = "AutoRefresh/enabled"


AUTO_REFRESH_MINUTES_KEY = "AutoRefresh/minutes"


def auto_refresh_settings(settings) -> tuple:
    """(enabled, minutes) as set in Settings: on, 15 minutes, unless changed."""
    enabled = str(settings.value(AUTO_REFRESH_KEY, "true")).lower() in ("true", "1")
    try:
        minutes = int(float(settings.value(AUTO_REFRESH_MINUTES_KEY,
                                           freshness.DEFAULT_MAX_AGE_MINUTES)))
    except (TypeError, ValueError):
        minutes = freshness.DEFAULT_MAX_AGE_MINUTES
    return enabled, max(1, minutes)


class AutoRefresh:
    """A tab whose data can go stale, and how to bring it back.

    Mixed into a panel (before QWidget) to declare the method its own Refresh
    button calls, the workers that mean a refresh is already running, and how
    fast its data goes stale (core.freshness). The window does the rest when
    the tab is opened.

    Two timestamps, because they answer different questions. When a refresh
    *started* decides whether to start another - set by the button and by the
    window alike, and set even if the fetch then fails, so a dead network is
    not retried on every tab switch. When one *succeeded* is what the label
    shows, because "updated 14:32" has to mean the figures are from 14:32.
    """
    REFRESH_METHOD = "refresh"
    REFRESH_WORKERS = ("_worker",)
    REFRESH_POLICY = freshness.INTRADAY
    _refresh_started_at = None
    _refreshed_at = None
    freshness_label = None

    def note_refresh_started(self):
        self._refresh_started_at = time.time()

    def make_freshness_label(self):
        label = QLabel("")
        label.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px;")
        self.freshness_label = label
        return label

    def mark_refreshed(self):
        self._refreshed_at = time.time()
        self.update_freshness_label()

    def update_freshness_label(self, now=None):
        if self.freshness_label is not None and self._refreshed_at is not None:
            self.freshness_label.setText(
                freshness.stamp(self._refreshed_at, time.time() if now is None else now))

    def refresh_running(self) -> bool:
        for attr in self.REFRESH_WORKERS:
            worker = getattr(self, attr, None)
            try:
                if worker is not None and worker.isRunning():
                    return True
            except RuntimeError:            # the C++ side is already gone
                continue
        return False

    def refresh_if_stale(self, max_age_minutes=freshness.DEFAULT_MAX_AGE_MINUTES, now=None) -> bool:
        """Refresh if the data is stale and nothing is already fetching it.
        Returns whether a refresh was started."""
        now = time.time() if now is None else now
        self.update_freshness_label(now)
        if self.refresh_running():
            return False
        if not freshness.is_stale(self._refresh_started_at, now,
                                  self.REFRESH_POLICY, max_age_minutes):
            return False
        getattr(self, self.REFRESH_METHOD)()
        return True


def fmt_large(v):
    try:
        v=float(v)
        if abs(v)>=1_000_000_000: return f"{v/1_000_000_000:.2f}B"
        if abs(v)>=1_000_000: return f"{v/1_000_000:.1f}M"
        if abs(v)>=1_000: return f"{v/1_000:.1f}K"
        return f"{v:,.0f}"
    except Exception:
        return str(v)


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem with safe numeric sorting.

    BUG-007: The previous implementation called ``super().__lt__`` as a
    fallback. In PySide this can re-enter the Python override during table
    sorting and produce a RecursionError / stack overflow. This version never
    calls the Qt base comparator; it compares stored numeric keys when both
    exist, otherwise compares display text directly in Python.
    """

    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        other_sort_value = getattr(other, "sort_value", None)
        if self.sort_value is not None and other_sort_value is not None:
            try:
                return float(self.sort_value) < float(other_sort_value)
            except Exception:
                pass

        # Safe non-recursive fallback for text columns and invalid numbers.
        try:
            return self.text().casefold() < other.text().casefold()
        except Exception:
            return str(self.text()).casefold() < str(other).casefold()


def table_item(value, numeric=False, display=None):
    text = str(value if display is None else display)
    if numeric:
        try:
            return SortableTableWidgetItem(text, float(value))
        except Exception:
            return SortableTableWidgetItem(text, None)
    return SortableTableWidgetItem(text, None)


# Colours for the favorable / neutral / caution reads, reused across the
# Market panel's tables and headline so the traffic-light meaning is consistent.
_READ_COLORS = {
    "Favorable": "#3fb950",
    "Neutral": "#e3b341",
    "Neutral / mixed": "#e3b341",
    "Caution": "#e5534b",
    "Avoid": "#e5534b",
}


class _HistoryWorker(QThread):
    """Fetches one symbol's price history off the UI thread.

    Clicking a row used to call get_history() inline, which blocks Qt's event
    loop for the whole network round-trip - the window freezes and the cursor
    spins until Yahoo answers. Charting now goes through this worker instead.
    """
    done = Signal(str, object, str)   # symbol, DataFrame|None, error message

    def __init__(self, symbol, period, interval):
        super().__init__()
        self.symbol = symbol
        self.period = period
        self.interval = interval

    def run(self):
        df, err = None, ""
        try:
            df = get_history(self.symbol, self.period, self.interval)
        except BaseException as exc:      # never let a bad symbol kill the thread
            err = str(exc)
        try:
            self.done.emit(self.symbol, df, err)
        except RuntimeError:              # panel already torn down
            pass


def _fill_table(table, columns, rows):
    """Populate a QTableWidget from a list of dicts (or (k,v) pairs)."""
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, key in enumerate(columns):
            val = row.get(key, "") if isinstance(row, dict) else row[c]
            table.setItem(r, c, QTableWidgetItem(str(val)))
    table.resizeColumnsToContents()


def _hint(text):
    """A muted, wrapped one-line explanation shown above a control, so the
    Backtest tab explains itself in plain language rather than assuming the
    user already knows what a walk-forward or profit factor is."""
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color:#8b98a5; font-style:italic;")
    return lbl


def _prices_as_of(iso_date) -> str:
    """'prices as of Fri 09 Oct' for a valuation's oldest price, or '' when
    nothing was priced. Shown wherever a book is valued, because a total read
    on Friday evening from Thursday's closes looks exactly like a current one."""
    if not iso_date:
        return ""
    try:
        return f"prices as of {pd.Timestamp(iso_date):%a %d %b}"
    except (TypeError, ValueError):
        return ""


class FlowLayout(QLayout):
    """A layout that lays its items left-to-right and wraps to new rows as
    width runs out (the classic Qt flow-layout). Used for the tab bar so every
    tab button stays visible across two (or more) rows instead of overflowing
    into a scroll arrow."""

    def __init__(self, parent=None, margin=0, hspacing=3, vspacing=3):
        super().__init__(parent)
        self._hspace = hspacing
        self._vspace = vspacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._hspace
            if next_x - self._hspace > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._vspace
                next_x = x + hint.width() + self._hspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()

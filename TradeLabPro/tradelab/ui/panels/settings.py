"""The Settings tab: data source, refresh, updates and backups."""
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
from tradelab.ui.common import (AUTO_REFRESH_KEY, AUTO_REFRESH_MINUTES_KEY, StatusLabel, _hint, auto_refresh_settings, flag_problem, open_external, report_problem, show_problem)

log = get_logger(__name__)


UPDATE_FOLDER_KEY = "Updates/installerFolder"


UPDATE_AT_START_KEY = "Updates/checkAtStartup"


UPDATE_TOLD_KEY = "Updates/toldAbout"   # GitHub version already announced


def restart_app():
    """Start a fresh TradeLab and close this one - the installed .exe, or the
    same script when run from source."""
    from PySide6.QtCore import QProcess
    from tradelab.core import config as _config
    args = sys.argv[1:] if _config.FROZEN else sys.argv
    if not QProcess.startDetached(sys.executable, list(args)):
        show_problem("TradeLab could not restart itself - close it and open it again "
                     "to finish.")
        return
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QMainWindow):
            QTimer.singleShot(200, widget.close)
            return
    QTimer.singleShot(200, QApplication.quit)


def apply_restore_at_startup():
    """Before anything opens the database: put a staged backup in place."""
    if not backup.restore_pending(DATA_DIR):
        return
    try:
        names = backup.apply_pending_restore(DATA_DIR)
        log.info("Restored a backup: %s", ", ".join(names))
        QTimer.singleShot(1500, lambda: QMessageBox.information(
            QApplication.activeWindow(), "Backup restored",
            "Your backup is restored. What it replaced was backed up first, in the "
            "backups folder."))
    except Exception as exc:
        report_problem(f"Could not restore the backup yet: {exc}. A file is probably in "
                       "use by another program (Claude's TradeLab connection, for one); "
                       "it will be tried again the next time TradeLab starts.")


class _UpdateCheckWorker(QThread):
    """Asks GitHub for the newest published version, off the UI thread."""
    done = Signal(object)   # version tuple, or None if GitHub could not be read

    def run(self):
        try:
            result = updates.latest_published()
        except Exception:
            result = None
        try:
            self.done.emit(result)
        except RuntimeError:
            pass


class _BackupWorker(QThread):
    """Makes one backup of the data folder, off the UI thread."""
    done = Signal(str, str)   # zip path, error ("" when it worked)

    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = data_dir

    def run(self):
        path, err = "", ""
        try:
            path = str(backup.make_backup(self.data_dir))
            log.info("Backed up the data folder to %s", path)
        except Exception as exc:
            err = str(exc) or type(exc).__name__
        try:
            self.done.emit(path, err)
        except RuntimeError:
            pass


class SettingsPanel(QWidget):
    """App settings — currently the data-source (provider) selector plus
    database/info. The provider abstraction lets the app swap where prices &
    fundamentals come from without touching any other tab."""

    def __init__(self, db: Database, settings=None):
        super().__init__()
        self.db = db
        self._settings = settings or app_settings()
        from tradelab.data import providers
        layout = QVBoxLayout(self)

        box = QGroupBox("Data source")
        v = QVBoxLayout(box)
        v.addWidget(_hint(
            "Where the app gets prices and fundamentals. Switch to Offline (synthetic) "
            "to run with no network (demos/testing) — new data loads use the selected "
            "source. The architecture supports adding more sources (Alpaca, Polygon, "
            "IBKR feed) later."))
        row = QHBoxLayout()
        self.source = QComboBox(); self.source.addItems(providers.provider_names())
        self.source.setCurrentText(providers.active_name())
        self.source.currentTextChanged.connect(self._on_source_changed)
        row.addWidget(QLabel("Provider")); row.addWidget(self.source, 1)
        v.addLayout(row)
        self.source_desc = QLabel(); self.source_desc.setWordWrap(True)
        self.source_desc.setStyleSheet("color:#8b98a5;")
        v.addWidget(self.source_desc)
        layout.addWidget(box)

        refresh_box = QGroupBox("Data refresh")
        rv = QVBoxLayout(refresh_box)
        rv.addWidget(_hint(
            "When you open a tab, its data is fetched again if it has gone stale. "
            "Prices, book value and the market read go stale after the time below; "
            "dividends, sectors and the retirement indices once a day, because nothing "
            "in them moves during a session. The ETF Screener, and anything you run "
            "yourself - scans, backtests, projections - never refresh on their own."))
        rrow = QHBoxLayout()
        enabled, minutes = auto_refresh_settings(self._settings)
        self.auto_refresh = QCheckBox("Refresh a tab when it is opened, if older than")
        self.auto_refresh.setChecked(enabled)
        self.auto_refresh_minutes = QSpinBox()
        self.auto_refresh_minutes.setRange(1, 240)
        self.auto_refresh_minutes.setSuffix(" min")
        self.auto_refresh_minutes.setValue(minutes)
        self.auto_refresh_minutes.setEnabled(enabled)
        self.auto_refresh.toggled.connect(self._save_auto_refresh)
        self.auto_refresh_minutes.valueChanged.connect(self._save_auto_refresh)
        rrow.addWidget(self.auto_refresh); rrow.addWidget(self.auto_refresh_minutes)
        rrow.addStretch()
        rv.addLayout(rrow)
        layout.addWidget(refresh_box)

        self.data_dir = DATA_DIR
        self._update_worker = None
        self._backup_worker = None

        upd_box = QGroupBox("Updates")
        uv = QVBoxLayout(upd_box)
        uv.addWidget(_hint(
            "TradeLab looks for a newer installer in the folder below (where new "
            "versions are built - TradeLabPro\\installer\\Output) and offers to install "
            "it in one click; it also checks which version is published on GitHub."))
        urow = QHBoxLayout()
        self.update_folder = QLineEdit(str(self._settings.value(UPDATE_FOLDER_KEY, "") or ""))
        self.update_folder.setPlaceholderText("Folder holding TradeLabPro-Setup-X.Y.Z.exe")
        self.update_folder.editingFinished.connect(self._save_update_folder)
        browse = QPushButton("Browse…"); browse.clicked.connect(self._browse_update_folder)
        check = QPushButton("Check now"); check.clicked.connect(lambda: self.check_updates())
        urow.addWidget(QLabel("Installer folder")); urow.addWidget(self.update_folder, 1)
        urow.addWidget(browse); urow.addWidget(check)
        uv.addLayout(urow)
        self.update_at_start = QCheckBox("Check when TradeLab starts")
        self.update_at_start.setChecked(
            str(self._settings.value(UPDATE_AT_START_KEY, "true")).lower() in ("true", "1"))
        self.update_at_start.toggled.connect(
            lambda on: (self._settings.setValue(UPDATE_AT_START_KEY, on), self._settings.sync()))
        uv.addWidget(self.update_at_start)
        self.update_status = StatusLabel(f"You have {version_text(parse_version(APP_VERSION))}.")
        uv.addWidget(self.update_status)
        layout.addWidget(upd_box)

        bak_box = QGroupBox("Backups")
        bv = QVBoxLayout(bak_box)
        bv.addWidget(_hint(
            f"Once a week TradeLab copies your data (portfolios, cash, journal, retirement "
            f"plan, alerts, links, notes) into a zip in the backups folder; the last "
            f"{backup.KEEP} are kept. To restore, close TradeLab, unzip a backup and copy "
            f"its files back into the data folder."))
        brow = QHBoxLayout()
        now_btn = QPushButton("Back up now"); now_btn.clicked.connect(lambda: self.backup_now())
        restore_btn = QPushButton("Restore…"); restore_btn.clicked.connect(lambda: self.restore())
        open_btn = QPushButton("Open backup folder"); open_btn.clicked.connect(self._open_backups)
        brow.addWidget(now_btn); brow.addWidget(restore_btn); brow.addWidget(open_btn)
        brow.addStretch()
        bv.addLayout(brow)
        self.backup_status = StatusLabel()
        bv.addWidget(self.backup_status)
        layout.addWidget(bak_box)
        self._show_backup_state()

        self.info = QTextEdit(); self.info.setReadOnly(True)
        layout.addWidget(self.info, 1)
        self._refresh_info()
        self._update_desc()

    # --- updates -------------------------------------------------------------
    def _save_update_folder(self):
        self._settings.setValue(UPDATE_FOLDER_KEY, self.update_folder.text().strip())
        self._settings.sync()

    def _browse_update_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Installer folder", self.update_folder.text())
        if folder:
            self.update_folder.setText(folder)
            self._save_update_folder()

    def check_updates(self, quiet=False):
        """Offer a newer installer from the folder; else ask GitHub what is
        published. quiet (at startup): say nothing unless there is news."""
        mine = parse_version(APP_VERSION)
        folder = self.update_folder.text().strip()
        found = updates.newer_installer(folder, APP_VERSION)
        if found:
            self._offer_install(*found)
            return
        if not quiet and folder and not Path(folder).is_dir():
            flag_problem(self.update_status, f"The installer folder does not exist: {folder}")
            return
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        self.update_status.setText(f"You have {version_text(mine)}. Asking GitHub…")
        self._update_worker = _UpdateCheckWorker()
        self._update_worker.done.connect(lambda v: self._on_published(v, quiet))
        self._update_worker.start()

    def _offer_install(self, version, path):
        mine = version_text(parse_version(APP_VERSION))
        self.update_status.setText(f"TradeLab {version_text(version)} is ready to install (you have {mine}).")
        answer = QMessageBox.question(
            self.window(), "Update available",
            f"TradeLab {version_text(version)} is ready to install - you have {mine}.\n\n"
            "Install it now? TradeLab closes while the installer runs.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        reason = open_external(QUrl.fromLocalFile(str(path)))
        if reason is not None:
            flag_problem(self.update_status, f"Could not start the installer: {reason}", str(path))
            return
        QTimer.singleShot(300, self.window().close)

    def _on_published(self, version, quiet):
        mine = parse_version(APP_VERSION)
        if version is None:
            text = f"You have {version_text(mine)}. GitHub could not be reached to compare."
            if quiet:
                self.update_status.setText(text)
            else:
                flag_problem(self.update_status, text)
            return
        if version <= mine:
            self.update_status.setText(f"You have {version_text(mine)}, the latest version.")
            return
        text = (f"TradeLab {version_text(version)} is published on GitHub (you have "
                f"{version_text(mine)}), but its installer is not in the installer folder yet.")
        self.update_status.setText(text)
        told = str(self._settings.value(UPDATE_TOLD_KEY, ""))
        if not quiet or told != version_text(version):
            self._settings.setValue(UPDATE_TOLD_KEY, version_text(version))
            QMessageBox.information(self.window(), "Update available", text)

    # --- backups -------------------------------------------------------------
    def _show_backup_state(self):
        last = backup.latest(backup.backup_dir(self.data_dir))
        self.backup_status.setText(
            f"Last backup: {last[0]:%Y-%m-%d %H:%M} ({last[1].name})." if last
            else "No backup yet.")

    def backup_now(self, quiet=False):
        if self._backup_worker is not None and self._backup_worker.isRunning():
            return
        self.backup_status.setText("Backing up…")
        self._backup_worker = _BackupWorker(self.data_dir)
        self._backup_worker.done.connect(lambda path, err: self._on_backup_done(path, err, quiet))
        self._backup_worker.start()

    def _on_backup_done(self, path, error, quiet):
        if error:
            flag_problem(self.backup_status, f"Backup failed: {error}")
            return
        self._show_backup_state()
        if not quiet:
            self.backup_status.setText(f"Backed up to {path}.")

    def restore(self, path=None):
        """Put a backup back: pick it, confirm, then TradeLab restarts and swaps
        it in before opening anything - after backing up what it replaces."""
        folder = backup.backup_dir(self.data_dir)
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Restore a backup", str(folder),
                                                  "TradeLab backups (*.zip)")
        if not path:
            return
        answer = QMessageBox.question(
            self.window(), "Restore a backup",
            f"Restore {Path(path).name}?\n\nEverything entered since that backup is "
            "replaced by what it holds. Your current data is backed up first, so this "
            "can be undone. TradeLab restarts to do it.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            names = backup.stage_restore(path, self.data_dir)
        except Exception as exc:
            flag_problem(self.backup_status, f"Could not restore {Path(path).name}: {exc}")
            return
        log.info("Restore of %s staged (%s); restarting", path, ", ".join(names))
        self.backup_status.setText(f"Restoring {Path(path).name} - TradeLab is restarting…")
        restart_app()

    def _open_backups(self):
        folder = backup.backup_dir(self.data_dir)
        folder.mkdir(parents=True, exist_ok=True)
        reason = open_external(QUrl.fromLocalFile(str(folder)))
        if reason is not None:
            flag_problem(self.backup_status, f"Could not open {folder}: {reason}")

    def startup_checks(self):
        """At launch: the weekly backup when due, and - in the installed app -
        the update check."""
        try:
            if backup.due(backup.backup_dir(self.data_dir)):
                self.backup_now(quiet=True)
        except Exception:
            log.exception("Could not start the weekly backup")
        from tradelab.core import config as _config
        if _config.FROZEN and self.update_at_start.isChecked():
            self.check_updates(quiet=True)

    def shutdown(self):
        for worker in (self._update_worker, self._backup_worker):
            if worker is not None and worker.isRunning():
                worker.wait(7000)

    def _save_auto_refresh(self, *_):
        self._settings.setValue(AUTO_REFRESH_KEY, self.auto_refresh.isChecked())
        self._settings.setValue(AUTO_REFRESH_MINUTES_KEY, self.auto_refresh_minutes.value())
        self._settings.sync()
        self.auto_refresh_minutes.setEnabled(self.auto_refresh.isChecked())

    def _on_source_changed(self, name):
        from tradelab.data import providers
        if providers.set_active(name):
            self._settings.setValue("data/provider", name)
        self._update_desc()

    def _update_desc(self):
        from tradelab.data import providers
        p = providers.get(self.source.currentText())
        text = p.description if p else ""
        if p and p.requires_network and not p.available():
            text += "  ⚠ yfinance is not installed — this source falls back to synthetic data."
        self.source_desc.setText(text)

    def _refresh_info(self):
        self.info.setText(
            f"Database: {self.db.path}\nData folder: {DATA_DIR}\n"
            f"Scan history rows: {self.db.scan_history_count()}\n"
            f"Scan result rows: {self.db.scan_result_count()}")

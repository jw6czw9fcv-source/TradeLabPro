"""Where the app's preferences live.

One factory rather than one QSettings constructor per panel, because tests
have to be able to point it somewhere else: the default is the real Windows
registry key, so a test saving a column width used to write into the settings
of the app the person actually uses. QSettings.setDefaultFormat() does not
redirect that constructor on Windows, so the override is an explicit
environment variable - matching how TRADELAB_DATA_DIR and TRADELAB_LOG_DIR
keep the suite out of real data and logs.

QtCore only, so a process with no window - the MCP server - can read the same
preferences the app writes without importing the whole interface.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

SETTINGS_FILE_ENV = "TRADELAB_SETTINGS_FILE"


def app_settings() -> QSettings:
    override = os.environ.get(SETTINGS_FILE_ENV)
    if override:
        return QSettings(override, QSettings.IniFormat)
    return QSettings("TradeLabPro", "TradeLabPro")

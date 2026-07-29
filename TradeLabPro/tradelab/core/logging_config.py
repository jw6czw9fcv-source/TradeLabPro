"""Centralized logging setup for TradeLab Pro.

Call configure_logging() once, early (main.py / launch_tradelab.py).
Every module then just does: `log = logging.getLogger(__name__)`.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from tradelab.core.config import LOG_DIR

LOG_FILE = LOG_DIR / "tradelab.log"

# Set TRADELAB_LOG_DIR to send the log somewhere else. The test suite uses this
# so a run can't leave fake tracebacks in the log you'd actually read when
# something has gone wrong (one test deliberately raises to prove startup
# survives a broken panel).
LOG_DIR_ENV = "TRADELAB_LOG_DIR"

_configured = False


def log_dir() -> Path:
    """Where the log is written — the override if one is set, else the app's own
    logs/ folder. Resolved per call so setting the variable always takes."""
    override = os.environ.get(LOG_DIR_ENV)
    return Path(override) if override else LOG_DIR


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "tradelab.log"

    root = logging.getLogger("tradelab")
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    _configured = True
    root.info("Logging configured. Writing to %s", log_file)


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(name)

"""Centralized logging setup for TradeLab Pro.

Call configure_logging() once, early (main.py / launch_tradelab.py).
Every module then just does: `log = logging.getLogger(__name__)`.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from tradelab.core.config import ROOT_DIR

LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "tradelab.log"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger("tradelab")
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    _configured = True
    root.info("Logging configured. Writing to %s", LOG_FILE)


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(name)

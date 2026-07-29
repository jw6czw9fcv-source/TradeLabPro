import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "TradeLab Pro"
APP_VERSION = '2.38.0 Coming up: earnings and ex-dividend dates for your holdings'

# True when running from a packaged .exe rather than the source tree.
FROZEN = bool(getattr(sys, "frozen", False))

# ROOT_DIR is where the app's own files live: read-only things that ship with
# it, like the user manual the Help viewer reads. Inside the bundle when frozen,
# the source tree otherwise.
ROOT_DIR = (Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
            if FROZEN else Path(__file__).resolve().parents[2])

# Point this somewhere else to run against a different set of data.
DATA_DIR_ENV = "TRADELAB_DATA_DIR"


def user_data_dir() -> Path:
    """The one place your data lives, however the app was started.

    Deliberately outside both the source tree and the bundle, so the packaged
    .exe and a run from source see the *same* portfolio, journal and alerts
    instead of quietly drifting apart as two separate installs. It also keeps
    real positions out of a git checkout, and a one-file build unpacks to a temp
    folder Windows deletes on exit — writing a database there would throw the
    whole portfolio away every time the app closed.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME


DATA_DIR = user_data_dir()
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "tradelab.db"

# Plugins are code shipped with the app rather than data you accumulate, so they
# stay with the install: the samples in the repo for a source run, the bundled
# copy for the .exe.
PLUGINS_DIR = ROOT_DIR / "plugins"

@dataclass
class ScannerConfig:
    min_price: float = 5.0
    max_price: float = 10000.0
    min_volume: int = 500_000
    min_market_cap: float = 2_000_000_000.0
    max_symbols: int = 0  # 0 = scan all selected symbols
    interval: str = "1d"
    period: str = "1y"
    ema_fast: int = 9
    ema_slow: int = 30
    ema_extra: int = 5
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    min_score: int = 60
    min_rel_volume: float = 0.0
    min_rsi: float = 0.0
    max_rsi: float = 100.0
    require_ema_trend: bool = False
    require_positive_macd: bool = False
    min_atr_percent: float = 0.0
    max_atr_percent: float = 100.0
    # SCN-026: arbitrary additional conditions (list of FilterCondition.to_dict()),
    # ANDed with everything above rather than replacing it - see tradelab/core/filters.py.
    custom_filters: list = field(default_factory=list)
    # SCN-030: which strategy scores/signals each symbol - key into
    # tradelab.strategies.STRATEGIES. Kept as a plain string default here
    # (not imported from tradelab.strategies) to avoid a needless import
    # coupling between config and the strategies package.
    strategy: str = "ema_macd"

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "TradeLab Pro"
APP_VERSION = '2.38.0 Coming up: earnings and ex-dividend dates for your holdings'

# True when running from a packaged .exe rather than the source tree.
FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # Two different roots once packaged, and conflating them loses data.
    #
    # ROOT_DIR is where the bundle unpacked itself: read-only files that ship
    # inside the executable, like the user manual.
    ROOT_DIR = Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
    # Everything the app *writes* has to live outside the bundle. A one-file
    # build unpacks to a temp folder that Windows deletes on exit — writing the
    # database there would throw away your portfolio every time you closed the
    # app — and an installed copy under Program Files is read-only anyway.
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
    LOG_DIR = DATA_DIR / "logs"
    PLUGINS_DIR = DATA_DIR / "plugins"
else:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    DATA_DIR = ROOT_DIR / "data"
    LOG_DIR = ROOT_DIR / "logs"
    PLUGINS_DIR = ROOT_DIR / "plugins"

DB_PATH = DATA_DIR / "tradelab.db"

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

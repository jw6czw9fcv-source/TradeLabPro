from dataclasses import dataclass
from pathlib import Path

APP_NAME = "TradeLab Pro"
APP_VERSION = '2.2.2 Installer fix, part 2'
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
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

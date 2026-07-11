import sqlite3
from pathlib import Path
from tradelab.core.config import DATA_DIR, DB_PATH
from tradelab.core.logging_config import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Schema is versioned. Each entry in MIGRATIONS is applied, in order, exactly
# once (tracked in schema_version). This replaces ad hoc "ALTER TABLE if not
# exists" sprawl with a single, testable, ordered migration list.
# ---------------------------------------------------------------------------

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS watchlist_symbols (
    watchlist_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, symbol)
);
CREATE TABLE IF NOT EXISTS portfolio_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio TEXT NOT NULL DEFAULT 'Swing',
    symbol TEXT NOT NULL,
    shares REAL NOT NULL DEFAULT 0,
    entry_price REAL NOT NULL DEFAULT 0,
    stop_price REAL,
    target_price REAL,
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_name TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    settings_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS scan_results (
    scan_id INTEGER,
    symbol TEXT,
    signal TEXT,
    score REAL,
    price REAL,
    volume REAL,
    market_cap REAL,
    details TEXT
);
"""

# v2: Chart Engine persistence - saved dockable layouts + per-symbol drawings
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS chart_layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    layout_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chart_drawings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1d',
    drawings_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timeframe)
);
"""

MIGRATIONS: list[str] = [SCHEMA_V1, SCHEMA_V2]

# Kept for backward compatibility with any external code importing SCHEMA directly.
SCHEMA = SCHEMA_V1 + SCHEMA_V2


class Database:
    def __init__(self, path: Path = DB_PATH):
        DATA_DIR.mkdir(exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate()
        self.ensure_default_watchlist()

    def _migrate(self):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = self.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] if row and row["v"] is not None else 0
        for idx, script in enumerate(MIGRATIONS, start=1):
            if idx <= current:
                continue
            log.info("Applying database migration v%d", idx)
            self.conn.executescript(script)
            self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (idx,))
            self.conn.commit()

    def ensure_default_watchlist(self):
        self.conn.execute("INSERT OR IGNORE INTO watchlists(name) VALUES (?)", ("Default",))
        self.conn.commit()

    def add_watch_symbol(self, symbol: str, watchlist: str = "Default"):
        cur = self.conn.execute("SELECT id FROM watchlists WHERE name=?", (watchlist,))
        row = cur.fetchone()
        if not row:
            self.conn.execute("INSERT INTO watchlists(name) VALUES (?)", (watchlist,))
            self.conn.commit()
            row = self.conn.execute("SELECT id FROM watchlists WHERE name=?", (watchlist,)).fetchone()
        self.conn.execute("INSERT OR IGNORE INTO watchlist_symbols(watchlist_id, symbol) VALUES (?,?)", (row["id"], symbol.upper()))
        self.conn.commit()

    def remove_watch_symbol(self, symbol: str, watchlist: str = "Default"):
        row = self.conn.execute("SELECT id FROM watchlists WHERE name=?", (watchlist,)).fetchone()
        if row:
            self.conn.execute("DELETE FROM watchlist_symbols WHERE watchlist_id=? AND symbol=?", (row["id"], symbol.upper()))
            self.conn.commit()

    def watch_symbols(self, watchlist: str = "Default"):
        row = self.conn.execute("SELECT id FROM watchlists WHERE name=?", (watchlist,)).fetchone()
        if not row:
            return []
        rows = self.conn.execute("SELECT symbol FROM watchlist_symbols WHERE watchlist_id=? ORDER BY symbol", (row["id"],)).fetchall()
        return [r["symbol"] for r in rows]

    def add_position(self, symbol: str, shares: float, entry_price: float, portfolio: str = "Swing"):
        self.conn.execute(
            "INSERT INTO portfolio_positions(portfolio,symbol,shares,entry_price) VALUES (?,?,?,?)",
            (portfolio, symbol.upper(), shares, entry_price),
        )
        self.conn.commit()

    def positions(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM portfolio_positions ORDER BY symbol").fetchall()]

    def delete_position(self, position_id: int):
        self.conn.execute("DELETE FROM portfolio_positions WHERE id=?", (position_id,))
        self.conn.commit()

    def save_scan(self, scan_name: str, settings_json: str, rows: list[dict]):
        cur = self.conn.execute("INSERT INTO scan_history(scan_name, settings_json) VALUES (?,?)", (scan_name, settings_json))
        scan_id = cur.lastrowid
        for r in rows:
            self.conn.execute(
                "INSERT INTO scan_results(scan_id,symbol,signal,score,price,volume,market_cap,details) VALUES (?,?,?,?,?,?,?,?)",
                (scan_id, r.get('Symbol',''), r.get('Signal',''), float(r.get('Score') or 0), float(r.get('Price') or 0), float(r.get('Volume') or 0), float(r.get('Market Cap') or 0), r.get('Details',''))
            )
        self.conn.commit()
        return scan_id

    def scan_history_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM scan_history").fetchone()["n"]

    def scan_result_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM scan_results").fetchone()["n"]

    # -- Chart Engine: dockable layout persistence --------------------------
    def save_chart_layout(self, name: str, layout_json: str):
        self.conn.execute(
            "INSERT INTO chart_layouts(name, layout_json, updated_at) VALUES (?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(name) DO UPDATE SET layout_json=excluded.layout_json, updated_at=CURRENT_TIMESTAMP",
            (name, layout_json),
        )
        self.conn.commit()

    def load_chart_layout(self, name: str) -> str | None:
        row = self.conn.execute("SELECT layout_json FROM chart_layouts WHERE name=?", (name,)).fetchone()
        return row["layout_json"] if row else None

    def list_chart_layouts(self) -> list[str]:
        rows = self.conn.execute("SELECT name FROM chart_layouts ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    def delete_chart_layout(self, name: str):
        self.conn.execute("DELETE FROM chart_layouts WHERE name=?", (name,))
        self.conn.commit()

    # -- Chart Engine: drawing persistence -----------------------------------
    def save_drawings(self, symbol: str, timeframe: str, drawings_json: str):
        self.conn.execute(
            "INSERT INTO chart_drawings(symbol, timeframe, drawings_json, updated_at) VALUES (?,?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(symbol, timeframe) DO UPDATE SET drawings_json=excluded.drawings_json, updated_at=CURRENT_TIMESTAMP",
            (symbol.upper(), timeframe, drawings_json),
        )
        self.conn.commit()

    def load_drawings(self, symbol: str, timeframe: str) -> str | None:
        row = self.conn.execute(
            "SELECT drawings_json FROM chart_drawings WHERE symbol=? AND timeframe=?",
            (symbol.upper(), timeframe),
        ).fetchone()
        return row["drawings_json"] if row else None

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tradelab.core.config import DATA_DIR, DB_PATH
from tradelab.core.logging_config import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

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

# v3: ETF Screener - one row per fund, mirroring the columns of the
# Portefeuille_FNB.xlsx workbook this replaces. Two kinds of column live side
# by side and must never overwrite each other: what you typed (category,
# weights, risk, notes, the model portfolios) and what yfinance computed
# (returns, volatility, drawdown, Sharpe). Returns are stored as fractions
# (0.25 = 25%), the way the workbook stored them.
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS etf_screener (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    exchange TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    pct_can REAL,
    pct_us REAL,
    pct_intl REAL,
    pct_bond REAL,
    pct_gold REAL,
    risk INTEGER,
    mer REAL,
    ret_1m REAL,
    ret_3m REAL,
    ret_6m REAL,
    ret_1a REAL,
    ret_3a REAL,
    ret_5a REAL,
    ret_10a REAL,
    volatility REAL,
    max_drawdown REAL,
    sharpe REAL,
    reco_star REAL,
    spec_star REAL,
    ma_compo REAL,
    notes TEXT DEFAULT '',
    suggested_account TEXT DEFAULT '',
    yahoo TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);
"""

# v4: the model portfolios named by what they are rather than by what the
# workbook called them - a low / mid / high risk ladder plus your own mix.
# Renamed rather than re-created so the weights already typed survive: the
# columns carry real allocations.
SCHEMA_V4 = """
ALTER TABLE etf_screener RENAME COLUMN reco_star TO mid_risk;
ALTER TABLE etf_screener RENAME COLUMN spec_star TO high_risk;
ALTER TABLE etf_screener RENAME COLUMN ma_compo TO my_mix;
ALTER TABLE etf_screener ADD COLUMN low_risk REAL;
"""

# v5: the published risk rating (NI 81-102 Appendix F), a distribution yield,
# and the gold bucket generalised. Gold was one commodity in a list built for
# index funds; a silver or a lithium fund needed the same column, and what it
# holds is already named in `category`. Nothing is dropped: `risk`, `sharpe`
# and `my_mix` stay in the table (my_mix duplicated mid_risk on every row) and
# simply leave the screen, so no judgement anyone typed is destroyed.
SCHEMA_V5 = """
ALTER TABLE etf_screener RENAME COLUMN pct_gold TO pct_alt;
ALTER TABLE etf_screener ADD COLUMN csa_stdev REAL;
ALTER TABLE etf_screener ADD COLUMN csa_level TEXT;
ALTER TABLE etf_screener ADD COLUMN csa_months INTEGER;
ALTER TABLE etf_screener ADD COLUMN dividend_yield REAL;
"""

# v6: the retirement simulator's inputs. Accounts and incomes are rows rather
# than a blob because they are edited one line at a time, and because a
# projection nobody can audit line by line is not worth running.
SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS retirement_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'registered',
    balance REAL NOT NULL DEFAULT 0,
    owner TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS retirement_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER NOT NULL DEFAULT 65
);
CREATE TABLE IF NOT EXISTS retirement_incomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    annual REAL NOT NULL DEFAULT 0,
    starts_at_age INTEGER NOT NULL DEFAULT 65,
    ends_at_age INTEGER
);
"""

MIGRATIONS: list[str] = [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5,
                         SCHEMA_V6]

# Kept for backward compatibility with any external code importing SCHEMA directly.
SCHEMA = SCHEMA_V1 + SCHEMA_V2 + SCHEMA_V3 + SCHEMA_V4 + SCHEMA_V5 + SCHEMA_V6


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

    def set_portfolio_positions(self, portfolio: str, positions: list) -> int:
        """Replace all rows in a named portfolio with `positions` (dicts with
        symbol / shares / entry_price). Used to sync an imported book (e.g. from
        IBKR) without accumulating duplicates on re-import. Returns rows written."""
        self.conn.execute("DELETE FROM portfolio_positions WHERE portfolio=?", (portfolio,))
        written = 0
        for p in positions:
            symbol = str(p.get("symbol", "")).upper().strip()
            shares = float(p.get("shares", 0) or 0)
            if not symbol or shares == 0:
                continue
            self.conn.execute(
                "INSERT INTO portfolio_positions(portfolio,symbol,shares,entry_price) VALUES (?,?,?,?)",
                (portfolio, symbol, shares, float(p.get("entry_price", 0) or 0)))
            written += 1
        self.conn.commit()
        return written

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

    # -- ETF Screener ---------------------------------------------------------
    ETF_COLUMNS = [
        "ticker", "name", "category", "exchange", "currency", "region",
        "pct_can", "pct_us", "pct_intl", "pct_bond", "pct_alt", "risk", "mer",
        "ret_1m", "ret_3m", "ret_6m", "ret_1a", "ret_3a", "ret_5a", "ret_10a",
        "volatility", "max_drawdown", "sharpe", "low_risk", "mid_risk",
        "high_risk", "my_mix", "notes", "suggested_account", "yahoo",
        "csa_stdev", "csa_level", "csa_months", "dividend_yield", "updated_at",
    ]

    # Everything etf_metrics computes. Kept apart from the rest so a refresh
    # can never reach a column you typed by hand.
    ETF_METRIC_COLUMNS = {
        "ret_1m", "ret_3m", "ret_6m", "ret_1a", "ret_3a", "ret_5a", "ret_10a",
        "volatility", "max_drawdown", "sharpe",
        "csa_stdev", "csa_level", "csa_months", "dividend_yield",
    }

    def etf_list(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM etf_screener ORDER BY ticker").fetchall()
        return [dict(r) for r in rows]

    def etf_get(self, ticker: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM etf_screener WHERE ticker=?", (ticker.upper(),)).fetchone()
        return dict(row) if row else None

    def etf_upsert(self, ticker: str, **fields):
        """Insert or update one fund. Only the columns named in `fields` are
        touched, so the same call serves both "add a ticker" (sparse fields)
        and "edit one cell" (e.g. Ma compo) without clobbering the rest of the
        row. Unknown keys are ignored rather than raising - the panel passes
        whatever column it just edited."""
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return
        cols = [c for c in fields if c in self.ETF_COLUMNS and c != "ticker"]
        if self.etf_get(ticker) is None:
            all_cols = ["ticker"] + cols
            placeholders = ",".join("?" for _ in all_cols)
            values = [ticker] + [fields[c] for c in cols]
            self.conn.execute(
                f"INSERT INTO etf_screener({','.join(all_cols)}) VALUES ({placeholders})", values)
        elif cols:
            set_clause = ",".join(f"{c}=?" for c in cols)
            values = [fields[c] for c in cols] + [ticker]
            self.conn.execute(f"UPDATE etf_screener SET {set_clause} WHERE ticker=?", values)
        self.conn.commit()

    def etf_delete(self, ticker: str):
        self.conn.execute("DELETE FROM etf_screener WHERE ticker=?", (ticker.upper(),))
        self.conn.commit()

    # -- Retirement simulator inputs -----------------------------------------
    RETIREMENT_TABLES = {"people": ("retirement_people", ("name", "age")),
                         "accounts": ("retirement_accounts",
                                      ("name", "kind", "balance", "owner")),
                         "incomes": ("retirement_incomes",
                                     ("name", "owner", "annual", "starts_at_age",
                                      "ends_at_age"))}

    def retirement_rows(self, what: str) -> list[dict]:
        table, _cols = self.RETIREMENT_TABLES[what]
        return [dict(r) for r in
                self.conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]

    # What a missing key means, rather than letting None hit a NOT NULL column
    # and blow up on a row someone simply typed sparsely.
    RETIREMENT_DEFAULTS = {"kind": "registered", "owner": "", "balance": 0.0,
                           "annual": 0.0, "starts_at_age": 65, "ends_at_age": None,
                           "age": 65}

    def set_retirement_rows(self, what: str, rows: list[dict]) -> int:
        """Replace the whole set. These are edited as a table, and a partial
        update would leave a deleted line behind."""
        table, cols = self.RETIREMENT_TABLES[what]
        self.conn.execute(f"DELETE FROM {table}")
        written = 0
        for row in rows:
            if not str(row.get("name", "")).strip():
                continue
            placeholders = ",".join("?" for _ in cols)
            self.conn.execute(f"INSERT INTO {table}({','.join(cols)}) "
                              f"VALUES ({placeholders})",
                              [row.get(c, self.RETIREMENT_DEFAULTS.get(c))
                               if row.get(c) is not None
                               else self.RETIREMENT_DEFAULTS.get(c)
                               for c in cols])
            written += 1
        self.conn.commit()
        return written

    def etf_update_metrics(self, ticker: str, metrics: dict):
        """Write back the computed columns only. A None is dropped rather than
        written: a fund with eight years of history has no ten-year number,
        and blanking the one already in the row would lose data the refresh
        cannot replace."""
        fields = {k: v for k, v in metrics.items()
                  if k in self.ETF_METRIC_COLUMNS and v is not None}
        if not fields:
            return
        fields["updated_at"] = _now_iso()
        self.etf_upsert(ticker, **fields)

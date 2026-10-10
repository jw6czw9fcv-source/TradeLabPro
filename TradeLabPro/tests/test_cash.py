"""Cash beside the positions.

Recorded per portfolio and currency, and added to the account's value - what a
broker calls net liquidation - without touching the P&L, the weights or the
risk figures, which describe what is invested. Without it, an account holding
part of its value in cash read as worth only its positions.
"""
import pandas as pd
import pytest

from tradelab.core import home
from tradelab.core import portfolio_analytics as pa
from tradelab.data.database import Database


def _daily(closes, end="2026-10-09"):
    idx = pd.date_range(end=end, periods=len(closes), freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                         "Volume": [1000] * len(closes)}, index=idx)


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "cash.db")
    yield d
    d.conn.close()


# --- storage -------------------------------------------------------------------

def test_cash_is_one_amount_per_portfolio_and_currency(db):
    db.set_cash("RRSP", "cad", 2500.00)
    db.set_cash("RRSP", "CAD", 2600.00)                   # replaces, never adds
    db.set_cash("RRSP", "USD", -120.50)                   # a margin loan is kept
    rows = db.cash()
    assert [(r["portfolio"], r["currency"], r["amount"]) for r in rows] == [
        ("RRSP", "CAD", 2600.00), ("RRSP", "USD", -120.50)]
    assert all(r["updated_at"] for r in rows)
    db.delete_cash("RRSP", "usd")
    assert [r["currency"] for r in db.cash()] == ["CAD"]


def test_cash_needs_a_portfolio_and_a_currency(db):
    with pytest.raises(ValueError):
        db.set_cash("", "CAD", 10)
    with pytest.raises(ValueError):
        db.set_cash("REER", " ", 10)
    assert db.cash() == []


def test_a_database_from_before_cash_gains_the_table(tmp_path):
    # Opening an older file runs the new migration; the positions stay put.
    import sqlite3
    from tradelab.data import database
    path = tmp_path / "old.db"
    old = Database(path=path)
    old.set_portfolio_positions("IBKR", [{"symbol": "VTI", "shares": 1, "entry_price": 300}])
    old.conn.execute("DROP TABLE portfolio_cash")
    old.conn.execute("DELETE FROM schema_version WHERE version = ?", (len(database.MIGRATIONS),))
    old.conn.commit()
    old.conn.close()
    reopened = Database(path=path)
    assert reopened.cash() == [] and len(reopened.positions()) == 1
    reopened.conn.close()
    assert sqlite3.connect(path).execute("SELECT MAX(version) FROM schema_version").fetchone()[0] \
        == len(database.MIGRATIONS)


# --- valuation -----------------------------------------------------------------

def test_cash_adds_to_the_account_value_and_nothing_else():
    positions = [{"symbol": "NVDA", "shares": 10, "entry_price": 240.0}]
    hist = {"NVDA": _daily([230.48, 229.28]), "USDCAD=X": _daily([1.4258, 1.4256])}
    fx = {"USD": hist["USDCAD=X"]}
    bare = pa.summarize(positions, hist, target_currency="CAD", fx=fx)
    full = pa.summarize(positions, hist, target_currency="CAD", fx=fx,
                        cash=[{"portfolio": "RRSP", "currency": "CAD", "amount": 2500.0}])
    assert full["total_value"] == pytest.approx(bare["total_value"])
    assert full["account_value"] == pytest.approx(bare["total_value"] + 2500.0)
    assert full["total_unrealized"] == pytest.approx(bare["total_unrealized"])
    assert full["holdings"][0]["weight_pct"] == pytest.approx(100.0)
    assert "Account worth $" in full["text"] and "cash $2,500" in full["text"]
    assert bare["account_value"] == pytest.approx(bare["total_value"])
    assert "Account worth" not in bare["text"]


def test_foreign_cash_is_converted_and_a_missing_rate_is_named():
    hist = {"RY.TO": _daily([150.0, 151.0]), "USDCAD=X": _daily([1.40, 1.42])}
    positions = [{"symbol": "RY.TO", "shares": 10, "entry_price": 140.0}]
    usd = pa.summarize(positions, hist, target_currency="CAD", fx={"USD": hist["USDCAD=X"]},
                       cash=[{"portfolio": "IBKR", "currency": "USD", "amount": 100.0}])
    assert usd["cash_value"] == pytest.approx(142.0)
    assert usd["fx_missing"] == []
    eur = pa.summarize(positions, hist, target_currency="CAD", fx={},
                       cash=[{"portfolio": "IBKR", "currency": "EUR", "amount": 100.0}])
    assert eur["cash"][0]["converted"] is False
    assert "EUR" in eur["fx_missing"]


def test_home_counts_the_cash_in_the_book_value():
    positions = [{"symbol": "RY.TO", "shares": 10, "entry_price": 140.0}]
    r = home.summarize(positions, {"RY.TO": _daily([150.0, 151.0])}, target_currency="CAD",
                       cash=[{"portfolio": "IBKR", "currency": "CAD", "amount": 500.0}])
    assert home.book_value(r["analytics"]) == pytest.approx(1510.0 + 500.0)
    assert "$2,010 CAD" in r["text"] and "$500 of it in cash" in r["text"]


def test_cash_never_stands_in_for_an_unpriced_book():
    # Holdings that could not be priced, plus the cash, would read as a crash.
    r = home.summarize([{"symbol": "GONE", "shares": 10, "entry_price": 140.0}], {},
                       target_currency="CAD",
                       cash=[{"portfolio": "IBKR", "currency": "CAD", "amount": 500.0}])
    assert home.book_value(r["analytics"]) is None
    assert "unavailable" in r["text"]

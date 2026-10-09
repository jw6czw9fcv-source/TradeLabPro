"""Tests for tradelab.mcp_server.tools - what an AI assistant can ask TradeLab.

Every tool reads the app's own data through a read-only connection and runs
the same core calculations the tabs do. These tests build a temporary
database, journal and preferences, and stub every download: nothing here
touches the network or the real data folder.
"""
import sqlite3

import numpy as np
import pandas as pd
import pytest

from tradelab.mcp_server import tools
from tradelab.mcp_server.tools import ToolError


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A populated database and journal in a temporary folder."""
    from tradelab.core import config
    from tradelab.core import journal as jr
    from tradelab.data.database import Database
    db_path = tmp_path / "tradelab.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(jr, "JOURNAL_PATH", tmp_path / "journal.json")
    db = Database(path=db_path)
    db.set_portfolio_positions("IBKR", [
        {"symbol": "RY.TO", "shares": 100, "entry_price": 120},
        {"symbol": "VTI", "shares": 20, "entry_price": 250}])
    db.set_retirement_rows("people", [{"name": "Pierre", "age": 65}])
    db.set_retirement_rows("accounts", [
        {"name": "REER", "kind": "registered", "balance": 400_000, "owner": "Pierre"},
        {"name": "CELI", "kind": "tfsa", "balance": 100_000, "owner": "Pierre"}])
    db.set_retirement_rows("incomes", [
        {"name": "RRQ", "owner": "Pierre", "annual": 15_000, "starts_at_age": 65,
         "indexed": 1}])
    db.etf_upsert("XIC.TO", name="iShares Core S&P/TSX", mer=0.0006)
    db.conn.close()
    return db_path


def _frame(seed, start, rows=260):
    idx = pd.date_range(end="2026-10-01", periods=rows, freq="B")
    r = np.random.default_rng(seed).normal(0.0004, 0.01, rows)
    c = start * np.exp(np.cumsum(r))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99,
                         "Close": c, "Volume": 1e6}, index=idx)


@pytest.fixture
def prices(monkeypatch):
    """Real-looking (not synthetic-tagged) histories for every symbol asked."""
    from tradelab.data import market_data
    start = {"RY.TO": 130, "VTI": 280, "SPY": 560, "USDCAD=X": 1.37}

    def fake(symbols, period="1y", interval="1d"):
        return {s: _frame(hash(s) % 1000, start.get(s, 100)) for s in symbols}
    monkeypatch.setattr(market_data, "get_histories", fake)
    return fake


# -- the read-only guarantee -------------------------------------------------------

def test_the_database_refuses_writes_when_opened_for_the_tools(data):
    db = tools.open_database()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.conn.execute("DELETE FROM portfolio_positions")
    db.conn.close()


def test_using_every_local_tool_leaves_the_file_untouched(data):
    before = data.read_bytes()
    tools.portfolio()
    tools.retirement_projection()
    tools.etf_screener()
    tools.quebec_tax(income=60_000, age=66)
    assert data.read_bytes() == before


def test_no_data_yet_says_what_to_do(tmp_path, monkeypatch):
    from tradelab.core import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "absent.db")
    with pytest.raises(ToolError, match="open the app once"):
        tools.portfolio()


def test_a_database_behind_the_code_is_not_read(data):
    conn = sqlite3.connect(data)
    conn.execute("DELETE FROM schema_version WHERE version = (SELECT MAX(version) "
                 "FROM schema_version)")
    conn.commit()
    conn.close()
    with pytest.raises(ToolError, match="upgrade"):
        tools.portfolio()


# -- what the tools say -------------------------------------------------------------

def test_portfolio_lists_what_is_stored(data):
    out = tools.portfolio()
    assert out["count"] == 2
    assert {p["symbol"] for p in out["positions"]} == {"RY.TO", "VTI"}


def test_quebec_tax_is_the_core_model(data):
    from tradelab.core.tax_quebec import tax_for
    out = tools.quebec_tax(income=60_000, age=66, pension_income=8_000)
    direct = tax_for(60_000, 66, 8_000)
    assert out["total"] == pytest.approx(direct["total"])
    assert 0 < out["marginal_rate"] < 0.6
    assert out["tax_year"] == 2026


def test_quebec_tax_indexes_a_future_year(data):
    now = tools.quebec_tax(income=60_000, age=66)
    later = tools.quebec_tax(income=60_000, age=66, years_ahead=10, inflation_pct=2.0)
    assert later["tax_year"] == 2036
    assert later["total"] < now["total"]          # same nominal income, wider brackets


def test_the_projection_runs_the_stored_plan(data):
    out = tools.retirement_projection(until_age=90)
    assert out["years"][0]["ages"] == {"Pierre": 65}
    assert out["years"][-1]["ages"] == {"Pierre": 90}
    assert "lasts_to_age" in out["summary"] or "runs_short_at_age" in out["summary"]
    assert any("not financial advice" in n for n in out["notes"])


def test_the_projection_matches_the_tab(data):
    """Same rows, same assumptions, same core functions - same answer."""
    from tradelab.core import retirement_plan as rp
    from tradelab.core.tax_quebec import household_tax_fn
    from tradelab.data.database import Database
    db = Database(path=data, read_only=True)
    plan = rp.plan_from_rows(db.retirement_rows("people"), db.retirement_rows("accounts"),
                             db.retirement_rows("incomes"), spending=40_000,
                             nominal_return=0.05, inflation=0.02, until_age=90,
                             tax_fn=household_tax_fn(0.0, 0.02))
    db.conn.close()
    direct = rp.project(plan)[-1]["closing"]
    out = tools.retirement_projection(spending=40_000, nominal_return_pct=5,
                                      inflation_pct=2, until_age=90, pension_split_pct=0)
    assert out["summary"]["final_balance"] == pytest.approx(direct)


def test_live_balances_can_replace_the_stored_ones(data):
    base = tools.retirement_projection(spending=40_000, until_age=90)
    richer = tools.retirement_projection(spending=40_000, until_age=90,
                                         balances={"reer": 600_000})
    assert richer["summary"]["final_balance"] > base["summary"]["final_balance"]
    assert richer["assumptions"]["balances_overridden"] == ["reer"]


def test_an_unknown_account_name_is_refused_not_ignored(data):
    with pytest.raises(ToolError, match="No account named Margin"):
        tools.retirement_projection(balances={"Margin": 1_000})


def test_splitting_beyond_the_rules_is_refused(data):
    with pytest.raises(ToolError, match="50%"):
        tools.retirement_projection(pension_split_pct=80)


def test_todays_dollars_reads_the_same_run_deflated(data):
    nominal = tools.retirement_projection(spending=30_000, until_age=90, inflation_pct=2)
    real = tools.retirement_projection(spending=30_000, until_age=90, inflation_pct=2,
                                       todays_dollars=True)
    assert real["summary"]["final_balance"] < nominal["summary"]["final_balance"]
    assert real["years"][0]["spending"] == pytest.approx(30_000)


def test_many_paths_report_a_share_not_a_probability(data):
    out = tools.retirement_projection(until_age=85, paths=50)
    assert 0 <= out["paths"]["share_never_short"] <= 1
    assert "not a probability" in out["paths"]["note"]


def test_nothing_to_project_says_so(data, monkeypatch):
    from tradelab.data.database import Database
    db = Database(path=data)
    db.set_retirement_rows("accounts", [])
    db.conn.close()
    with pytest.raises(ToolError, match="no people or no accounts"):
        tools.retirement_projection()


def test_the_saved_assumptions_are_the_defaults(data):
    from tradelab.settings import app_settings
    s = app_settings()
    s.beginGroup("RetirementSim")
    s.setValue("spending", 33_000)
    s.setValue("nominal_return", 4.0)
    s.endGroup()
    s.sync()
    out = tools.retirement_projection()
    assert out["assumptions"]["spending"] == pytest.approx(33_000)
    assert out["assumptions"]["nominal_return_pct"] == pytest.approx(4.0)


def test_etf_screener_returns_the_stored_table(data):
    out = tools.etf_screener()
    assert out["count"] == 1 and out["funds"][0]["ticker"] == "XIC.TO"


def test_an_empty_journal_says_so(data):
    with pytest.raises(ToolError, match="empty"):
        tools.journal_summary()


def test_the_journal_summary_includes_the_coach(data):
    from tradelab.core import journal as jr
    entry = jr.JournalEntry("RY.TO", qty=10, entry_price=100, stop=95, strategy="Breakout",
                            entry_date="2026-09-01")
    entry.close(110, "2026-09-10")
    j = jr.Journal()
    j.add(entry)
    out = tools.journal_summary()
    assert "stats" in out and "coach" in out


# -- the tools that download --------------------------------------------------------------

def test_book_summary_values_the_book_without_the_daily_curve(data, prices):
    out = tools.book_summary()
    assert out["currency"] == "CAD"
    assert out["total_value"] > 0
    assert "equity" not in out                     # 260 daily points stay out
    assert len(out["holdings"]) == 2


def test_made_up_prices_are_never_used_for_real_money(data, monkeypatch):
    from tradelab.data import market_data

    def synthetic(symbols, period="1y", interval="1d"):
        out = {}
        for s in symbols:
            df = _frame(1, 100)
            df.attrs["synthetic"] = True
            out[s] = df
        return out
    monkeypatch.setattr(market_data, "get_histories", synthetic)
    monkeypatch.setattr(market_data, "is_synthetic", lambda df: bool(df.attrs.get("synthetic")))
    out = tools.book_summary()
    assert set(out["no_data"]) >= {"RY.TO", "VTI"}


def test_dividend_income_runs_the_dividends_model(data, prices, monkeypatch):
    from tradelab.data import market_data
    pays = pd.Series([1.0, 1.0, 1.0, 1.0],
                     index=pd.date_range(end=pd.Timestamp.today(), periods=4, freq="QE"))
    monkeypatch.setattr(market_data, "get_dividends",
                        lambda s: pays if s == "RY.TO" else pd.Series(dtype=float))
    out = tools.dividend_income()
    assert out["currency"] == "CAD"
    assert "Projected from past payments" in out["note"]


def test_look_through_opens_funds_up(data, prices, monkeypatch):
    from tradelab.data import market_data
    monkeypatch.setattr(market_data, "get_fund_composition", lambda s: (
        {"holdings": [{"symbol": "AAPL", "weight": 0.07}], "sectors": {"Technology": 0.3}}
        if s == "VTI" else {}))
    monkeypatch.setattr(market_data, "get_quote_meta",
                        lambda s: {"sector": "Financial Services"})
    out = tools.look_through()
    assert out["companies"]
    assert "floor" in out["note"]


# -- the JSON they return ------------------------------------------------------------------

def test_missing_numbers_read_as_missing():
    assert tools.jsonable({"a": float("nan"), "b": np.float64(2.5), "c": np.int64(3)}) == \
        {"a": None, "b": 2.5, "c": 3}


def test_a_long_series_is_summarised_not_sent_whole():
    s = pd.Series(range(300), index=pd.date_range("2026-01-01", periods=300))
    out = tools.jsonable(s)
    assert out["points"] == 300 and out["first"] == 0 and out["last"] == 299

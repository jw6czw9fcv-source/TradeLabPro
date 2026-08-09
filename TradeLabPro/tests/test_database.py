import pytest

from tradelab.data.database import Database


def test_fresh_database_applies_all_migrations(tmp_db_path):
    db = Database(path=tmp_db_path)
    row = db.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] == 3  # SCHEMA_V1 + SCHEMA_V2 + SCHEMA_V3 currently defined


def test_default_watchlist_created(tmp_db_path):
    db = Database(path=tmp_db_path)
    names = [r["name"] for r in db.conn.execute("SELECT name FROM watchlists").fetchall()]
    assert "Default" in names


def test_reopening_database_does_not_reapply_migrations(tmp_db_path):
    db1 = Database(path=tmp_db_path)
    db1.conn.close()
    db2 = Database(path=tmp_db_path)  # should not raise / duplicate anything
    count = db2.conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
    assert count == 3


def test_save_and_load_chart_layout(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.save_chart_layout("My Layout", '{"dock_state": "abc", "panels": []}')
    loaded = db.load_chart_layout("My Layout")
    assert loaded == '{"dock_state": "abc", "panels": []}'
    assert "My Layout" in db.list_chart_layouts()


def test_save_chart_layout_upserts_on_same_name(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.save_chart_layout("Swing Review", '{"v":1}')
    db.save_chart_layout("Swing Review", '{"v":2}')
    assert db.load_chart_layout("Swing Review") == '{"v":2}'
    assert db.list_chart_layouts().count("Swing Review") == 1


def test_save_and_load_drawings(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.save_drawings("AAPL", "1d", '[{"kind": "hline"}]')
    assert db.load_drawings("AAPL", "1d") == '[{"kind": "hline"}]'
    assert db.load_drawings("AAPL", "1wk") is None
    assert db.load_drawings("MSFT", "1d") is None


def test_drawings_are_per_symbol_and_timeframe(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.save_drawings("AAPL", "1d", '[{"kind": "hline"}]')
    db.save_drawings("AAPL", "1wk", '[{"kind": "vline"}]')
    assert db.load_drawings("AAPL", "1d") != db.load_drawings("AAPL", "1wk")


# -- ETF Screener -----------------------------------------------------------

def test_etf_upsert_inserts_new_fund(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV", name="Vanguard S&P 500", yahoo="VFV.TO", mer=0.0009)
    fund = db.etf_get("VFV")
    assert fund["name"] == "Vanguard S&P 500"
    assert fund["yahoo"] == "VFV.TO"
    assert fund["mer"] == pytest.approx(0.0009)


def test_etf_upsert_uppercases_and_trims_the_ticker(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("  vfv ", yahoo="VFV.TO")
    assert db.etf_get("VFV") is not None
    assert db.etf_get("vfv") is not None      # lookup normalises too


def test_etf_upsert_edits_only_the_given_fields(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV", name="Vanguard S&P 500", category="S&P 500")
    db.etf_upsert("VFV", ma_compo=0.2)        # one edited cell
    fund = db.etf_get("VFV")
    assert fund["name"] == "Vanguard S&P 500"   # untouched
    assert fund["category"] == "S&P 500"        # untouched
    assert fund["ma_compo"] == pytest.approx(0.2)


def test_etf_upsert_ignores_unknown_columns(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV", not_a_real_column="x")   # must not raise
    assert db.etf_get("VFV") is not None


def test_etf_upsert_ignores_a_blank_ticker(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("   ", name="nowhere")
    assert db.etf_list() == []


def test_etf_list_is_sorted_by_ticker(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("XUU"); db.etf_upsert("VFV"); db.etf_upsert("QQC")
    tickers = [f["ticker"] for f in db.etf_list()]
    assert tickers == sorted(tickers)


def test_etf_delete_removes_fund(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV")
    db.etf_delete("VFV")
    assert db.etf_get("VFV") is None


def test_etf_update_metrics_writes_only_metric_columns(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV", name="Vanguard S&P 500", notes="cœur US", ma_compo=0.2)
    db.etf_update_metrics("VFV", {"ret_1a": 0.25, "sharpe": 1.1,
                                  "name": "should not overwrite", "ma_compo": 0.99})
    fund = db.etf_get("VFV")
    assert fund["ret_1a"] == pytest.approx(0.25)
    assert fund["sharpe"] == pytest.approx(1.1)
    # A refresh must never reach what you typed.
    assert fund["name"] == "Vanguard S&P 500"
    assert fund["notes"] == "cœur US"
    assert fund["ma_compo"] == pytest.approx(0.2)
    assert fund["updated_at"]


def test_etf_update_metrics_skips_none_values(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV", ret_10a=0.15)
    db.etf_update_metrics("VFV", {"ret_1a": None, "ret_3a": 0.10})
    fund = db.etf_get("VFV")
    assert fund["ret_1a"] is None
    assert fund["ret_3a"] == pytest.approx(0.10)
    # A fund with too little history keeps the figure already on file rather
    # than having it blanked by a refresh that could not compute one.
    assert fund["ret_10a"] == pytest.approx(0.15)


def test_etf_update_metrics_on_empty_dict_does_not_stamp(tmp_db_path):
    db = Database(path=tmp_db_path)
    db.etf_upsert("VFV")
    db.etf_update_metrics("VFV", {})
    assert db.etf_get("VFV")["updated_at"] is None

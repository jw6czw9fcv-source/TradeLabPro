from tradelab.data.database import Database


def test_fresh_database_applies_all_migrations(tmp_db_path):
    db = Database(path=tmp_db_path)
    row = db.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] == 2  # SCHEMA_V1 + SCHEMA_V2 currently defined


def test_default_watchlist_created(tmp_db_path):
    db = Database(path=tmp_db_path)
    names = [r["name"] for r in db.conn.execute("SELECT name FROM watchlists").fetchall()]
    assert "Default" in names


def test_reopening_database_does_not_reapply_migrations(tmp_db_path):
    db1 = Database(path=tmp_db_path)
    db1.conn.close()
    db2 = Database(path=tmp_db_path)  # should not raise / duplicate anything
    count = db2.conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
    assert count == 2


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

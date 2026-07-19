"""Trade journal engine tests - pure/offline."""
import math

import pytest

from tradelab.core.journal import (JournalEntry, Journal, summarize, group_stats,
                                    extract_trades_from_fills, parse_ibkr_trades_csv,
                                    parse_ibkr_flex_xml, fetch_ibkr_flex, LONG, SHORT)


# --- single-trade math ------------------------------------------------------

def test_long_pnl_and_pct():
    e = JournalEntry(symbol="AAPL", side=LONG, qty=10, entry_price=100.0)
    assert e.is_open and e.pnl is None
    e.close(120.0)
    assert not e.is_open
    assert e.pnl == 200.0                 # (120-100)*10
    assert math.isclose(e.pnl_pct, 20.0)
    assert e.is_win is True


def test_short_pnl_is_inverted():
    e = JournalEntry(symbol="TSLA", side=SHORT, qty=5, entry_price=200.0)
    e.close(180.0)
    assert e.pnl == 100.0                 # (180-200)*-1*5 = +100
    assert e.is_win is True
    e2 = JournalEntry(symbol="TSLA", side=SHORT, qty=5, entry_price=200.0)
    e2.close(210.0)
    assert e2.pnl == -50.0


def test_r_multiple_uses_stop():
    # Long 100, stop 90 -> risk 10/share. Exit 120 -> +20/share -> +2R.
    e = JournalEntry(symbol="X", side=LONG, qty=1, entry_price=100.0, stop=90.0)
    e.close(120.0)
    assert math.isclose(e.r_multiple, 2.0)
    e2 = JournalEntry(symbol="X", side=LONG, qty=1, entry_price=100.0, stop=90.0)
    e2.close(90.0)
    assert math.isclose(e2.r_multiple, -1.0)     # full stop-out


def test_r_multiple_none_without_stop():
    e = JournalEntry(symbol="X", side=LONG, qty=1, entry_price=100.0)
    e.close(120.0)
    assert e.r_multiple is None


def test_holding_days_and_tags_parsing():
    e = JournalEntry(symbol="X", side=LONG, qty=1, entry_price=1, entry_date="2024-01-01",
                     tags="breakout, momentum")
    e.close(2, "2024-01-11")
    assert e.holding_days == 10
    assert e.tags == ["breakout", "momentum"]


def test_roundtrip_to_from_dict():
    e = JournalEntry(symbol="aapl", side="short", qty=3, entry_price=50, stop=55,
                     strategy="mean-reversion", tags=["a", "b"], notes="hi")
    e.close(45)
    r = JournalEntry.from_dict(e.to_dict())
    assert r.symbol == "AAPL" and r.side == SHORT and r.stop == 55
    assert r.exit_price == 45 and r.strategy == "mean-reversion" and r.tags == ["a", "b"]
    assert r.id == e.id


# --- aggregate stats --------------------------------------------------------

def _closed(symbol, side, qty, entry, exit_, stop=None, strategy="", tags=None):
    e = JournalEntry(symbol=symbol, side=side, qty=qty, entry_price=entry, stop=stop,
                     strategy=strategy, tags=tags or [])
    e.close(exit_)
    return e


def test_summarize_win_rate_expectancy_profit_factor():
    entries = [
        _closed("A", LONG, 1, 100, 110),   # +10
        _closed("B", LONG, 1, 100, 130),   # +30
        _closed("C", LONG, 1, 100, 80),    # -20
        JournalEntry(symbol="D", side=LONG, qty=1, entry_price=100),  # open
    ]
    s = summarize(entries)
    assert s["trades"] == 4 and s["closed"] == 3 and s["open"] == 1
    assert s["wins"] == 2 and s["losses"] == 1
    assert math.isclose(s["win_rate"], 2 / 3 * 100)
    assert math.isclose(s["total_pnl"], 20.0)         # 10+30-20
    assert math.isclose(s["expectancy"], 20.0 / 3)
    assert math.isclose(s["profit_factor"], 40.0 / 20.0)   # gross win / gross loss
    assert math.isclose(s["avg_win"], 20.0)           # (10+30)/2


def test_avg_r_only_over_trades_with_stops():
    entries = [
        _closed("A", LONG, 1, 100, 120, stop=90),   # +2R
        _closed("B", LONG, 1, 100, 90, stop=90),    # -1R
        _closed("C", LONG, 1, 100, 110),            # no stop -> excluded from avg_r
    ]
    s = summarize(entries)
    assert math.isclose(s["avg_r"], (2.0 + -1.0) / 2)


def test_group_stats_by_strategy_orders_by_pnl():
    entries = [
        _closed("A", LONG, 1, 100, 110, strategy="breakout"),   # +10
        _closed("B", LONG, 1, 100, 90, strategy="fade"),        # -10
        _closed("C", LONG, 1, 100, 140, strategy="breakout"),   # +40
    ]
    groups = group_stats(entries, "strategy")
    assert groups[0][0] == "breakout"
    assert math.isclose(groups[0][1]["total_pnl"], 50.0)
    assert groups[1][0] == "fade"


def test_group_stats_by_tag_counts_each_tag():
    entries = [
        _closed("A", LONG, 1, 100, 110, tags=["breakout", "gap"]),
        _closed("B", LONG, 1, 100, 120, tags=["breakout"]),
    ]
    groups = dict(group_stats(entries, "tag"))
    assert groups["breakout"]["closed"] == 2
    assert groups["gap"]["closed"] == 1


# --- importing paper fills --------------------------------------------------

def _fill(symbol, side, qty, price, at):
    return {"symbol": symbol, "side": side, "filled_qty": qty, "filled_price": price,
            "filled_at": at, "status": "FILLED"}


def test_extract_trades_pairs_a_round_trip():
    fills = [_fill("AAPL", "BUY", 10, 100.0, 1), _fill("AAPL", "SELL", 10, 120.0, 2)]
    trades = extract_trades_from_fills(fills)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == LONG and t.qty == 10 and not t.is_open
    assert t.entry_price == 100.0 and t.exit_price == 120.0
    assert t.pnl == 200.0


def test_extract_trades_weighted_entry_and_partial_exits():
    # Buy 10@100 then 10@120 (avg 110), sell 20@130.
    fills = [_fill("X", "BUY", 10, 100.0, 1), _fill("X", "BUY", 10, 120.0, 2),
             _fill("X", "SELL", 20, 130.0, 3)]
    t = extract_trades_from_fills(fills)[0]
    assert t.qty == 20 and math.isclose(t.entry_price, 110.0)
    assert t.exit_price == 130.0 and math.isclose(t.pnl, (130 - 110) * 20)


def test_extract_trades_leaves_open_position():
    # Position-level model: buy 10, sell 4 is a scale-out of a still-open
    # trade, not a separate closed trade -> one OPEN trade of 6 shares.
    fills = [_fill("X", "BUY", 10, 100.0, 1), _fill("X", "SELL", 4, 110.0, 2)]
    trades = extract_trades_from_fills(fills)
    assert len(trades) == 1
    assert trades[0].is_open and trades[0].qty == 6 and trades[0].entry_price == 100.0


def test_extract_trades_scale_out_then_flat_is_one_trade():
    # Buy 10@100, sell 4@110, sell 6@130 -> one closed trade, size-weighted
    # exit = (4*110 + 6*130)/10 = 122.
    fills = [_fill("X", "BUY", 10, 100.0, 1), _fill("X", "SELL", 4, 110.0, 2),
             _fill("X", "SELL", 6, 130.0, 3)]
    trades = extract_trades_from_fills(fills)
    assert len(trades) == 1 and not trades[0].is_open
    assert trades[0].qty == 10 and math.isclose(trades[0].exit_price, 122.0)


def test_extract_trades_short_round_trip():
    fills = [_fill("X", "SELL", 5, 200.0, 1), _fill("X", "BUY", 5, 180.0, 2)]
    t = extract_trades_from_fills(fills)[0]
    assert t.side == SHORT and t.entry_price == 200.0 and t.exit_price == 180.0
    assert t.pnl == 100.0


# --- store ------------------------------------------------------------------

def test_journal_store_add_close_persist(tmp_path):
    path = tmp_path / "journal.json"
    j = Journal(path)
    e = j.add(JournalEntry(symbol="AAPL", side=LONG, qty=1, entry_price=100))
    assert len(j.all()) == 1
    assert j.close_trade(e.id, 120.0)
    reloaded = Journal(path)
    assert reloaded.get(e.id).exit_price == 120.0
    assert reloaded.remove(e.id)
    assert Journal(path).all() == []


def test_journal_import_fills_is_idempotent(tmp_path):
    j = Journal(tmp_path / "journal.json")
    fills = [_fill("AAPL", "BUY", 10, 100.0, 1), _fill("AAPL", "SELL", 10, 120.0, 2)]
    assert j.import_fills(fills) == 1
    assert j.import_fills(fills) == 0          # already imported -> no dupes
    assert len(j.all()) == 1


def test_journal_survives_corrupt_file(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text("{ not json", encoding="utf-8")
    assert Journal(path).all() == []


# --- IBKR CSV import --------------------------------------------------------

def test_parse_ibkr_flex_query_csv():
    # Flat Flex Query export: header + rows, explicit Buy/Sell column.
    text = (
        "Symbol,DateTime,Quantity,TradePrice,Buy/Sell,AssetClass\n"
        "AAPL,2024-01-02 10:31:00,10,100.0,BUY,STK\n"
        "AAPL,2024-01-05 14:00:00,10,120.0,SELL,STK\n"
    )
    fills = parse_ibkr_trades_csv(text)
    assert [f["side"] for f in fills] == ["BUY", "SELL"]
    trades = extract_trades_from_fills(fills)
    assert len(trades) == 1 and trades[0].pnl == 200.0
    assert trades[0].symbol == "AAPL"


def test_parse_ibkr_flex_signed_quantity_without_buysell():
    text = (
        "Symbol,DateTime,Quantity,TradePrice\n"
        "MSFT,2024-01-02,5,400.0\n"
        "MSFT,2024-01-03,-5,420.0\n"
    )
    fills = parse_ibkr_trades_csv(text)
    assert [f["side"] for f in fills] == ["BUY", "SELL"]
    assert extract_trades_from_fills(fills)[0].pnl == 100.0


def test_parse_ibkr_activity_statement_csv():
    # Sectioned Activity Statement: Trades,Header then Trades,Data rows.
    text = (
        'Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price\n'
        'Trades,Data,Order,Stocks,USD,TSLA,"2024-02-01, 09:31:00",10,200.0\n'
        'Trades,Data,Order,Stocks,USD,TSLA,"2024-02-02, 15:00:00",-10,220.0\n'
        'Trades,Data,Order,Forex,USD,EUR.USD,"2024-02-02, 15:00:00",1000,1.08\n'  # non-stock, skipped
    )
    fills = parse_ibkr_trades_csv(text)
    assert {f["symbol"] for f in fills} == {"TSLA"}      # forex row filtered out
    trades = extract_trades_from_fills(fills)
    assert len(trades) == 1 and trades[0].pnl == 200.0


def test_import_ibkr_csv_via_store_is_idempotent(tmp_path):
    csv_path = tmp_path / "ibkr.csv"
    csv_path.write_text(
        "Symbol,DateTime,Quantity,TradePrice,Buy/Sell\n"
        "AAPL,2024-01-02,10,100.0,BUY\n"
        "AAPL,2024-01-05,10,120.0,SELL\n", encoding="utf-8")
    j = Journal(tmp_path / "journal.json")
    assert j.import_ibkr_csv(csv_path) == 1
    assert j.import_ibkr_csv(csv_path) == 0        # no duplicates
    assert j.all()[0].pnl == 200.0


def test_parse_ibkr_garbage_returns_empty():
    assert parse_ibkr_trades_csv("") == []
    assert parse_ibkr_trades_csv("some,random,columns\n1,2,3\n") == []


# --- IBKR Flex Web Service (direct pull) ------------------------------------

_FLEX_REPORT = """<?xml version="1.0"?>
<FlexQueryResponse queryName="Trades" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1" fromDate="20240101" toDate="20240131">
      <Trades>
        <Trade symbol="AAPL" assetCategory="STK" buySell="BUY"  quantity="10" tradePrice="100.0" dateTime="20240102;103100"/>
        <Trade symbol="AAPL" assetCategory="STK" buySell="SELL" quantity="10" tradePrice="120.0" dateTime="20240105;140000"/>
        <Trade symbol="EUR.USD" assetCategory="CASH" buySell="BUY" quantity="1000" tradePrice="1.08" dateTime="20240105;140000"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def test_parse_ibkr_flex_xml_stocks_only():
    fills = parse_ibkr_flex_xml(_FLEX_REPORT)
    assert {f["symbol"] for f in fills} == {"AAPL"}      # forex (CASH) skipped
    trades = extract_trades_from_fills(fills)
    assert len(trades) == 1 and trades[0].pnl == 200.0


def test_fetch_ibkr_flex_two_step_with_transport():
    calls = []

    def fake_transport(url):
        calls.append(url)
        if "SendRequest" in url:
            return ('<FlexStatementResponse><Status>Success</Status>'
                    '<ReferenceCode>REF123</ReferenceCode>'
                    '<Url>https://x/GetStatement</Url></FlexStatementResponse>')
        return _FLEX_REPORT

    text = fetch_ibkr_flex("tok", "q1", transport=fake_transport)
    assert "FlexQueryResponse" in text
    assert any("SendRequest" in u and "t=tok" in u and "q=q1" in u for u in calls)
    assert any("GetStatement" in u and "q=REF123" in u for u in calls)


def test_fetch_ibkr_flex_retries_while_in_progress():
    state = {"n": 0}

    def fake_transport(url):
        if "SendRequest" in url:
            return '<FlexStatementResponse><Status>Success</Status><ReferenceCode>R</ReferenceCode></FlexStatementResponse>'
        state["n"] += 1
        if state["n"] == 1:
            return ('<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>'
                    '<ErrorMessage>Statement generation in progress</ErrorMessage></FlexStatementResponse>')
        return _FLEX_REPORT

    text = fetch_ibkr_flex("t", "q", transport=fake_transport, max_wait=5, sleep=0)
    assert "FlexQueryResponse" in text and state["n"] == 2


def test_fetch_ibkr_flex_raises_on_bad_token():
    def fake_transport(url):
        return ('<FlexStatementResponse><Status>Fail</Status><ErrorCode>1015</ErrorCode>'
                '<ErrorMessage>Token has expired</ErrorMessage></FlexStatementResponse>')
    with pytest.raises(RuntimeError) as e:
        fetch_ibkr_flex("bad", "q", transport=fake_transport)
    assert "1015" in str(e.value)


def test_import_ibkr_flex_via_store(tmp_path):
    def fake_transport(url):
        if "SendRequest" in url:
            return '<FlexStatementResponse><Status>Success</Status><ReferenceCode>R</ReferenceCode></FlexStatementResponse>'
        return _FLEX_REPORT
    j = Journal(tmp_path / "journal.json")
    assert j.import_ibkr_flex("t", "q", transport=fake_transport) == 1
    assert j.import_ibkr_flex("t", "q", transport=fake_transport) == 0   # idempotent
    assert j.all()[0].pnl == 200.0

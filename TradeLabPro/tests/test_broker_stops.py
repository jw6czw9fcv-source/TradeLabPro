"""Tests for stop / stop-limit / trailing-stop / bracket (OCO) orders.
Prices are injected via a mutable source, so nothing hits the network."""
import pytest

from tradelab.core.broker import (
    PaperBroker, BUY, SELL, MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP,
    FILLED, PENDING, CANCELLED,
)


class _Prices:
    def __init__(self, **prices):
        self.prices = prices

    def __call__(self, symbol):
        return self.prices[symbol]

    def set(self, symbol, px):
        self.prices[symbol] = px


def _broker(**prices):
    src = _Prices(**prices)
    return PaperBroker(starting_cash=100_000.0, price_fn=src), src


# --- stop-market ------------------------------------------------------------

def test_sell_stop_triggers_when_price_falls():
    b, px = _broker(AAPL=100.0)
    b.place_order("AAPL", BUY, 10, MARKET)                 # long 10 @ 100
    stop = b.place_order("AAPL", SELL, 10, STOP, stop_price=95.0)
    assert stop.status == PENDING
    px.set("AAPL", 96.0); b.poll()
    assert stop.status == PENDING                          # not hit yet
    px.set("AAPL", 94.5); b.poll()
    assert stop.status == FILLED                           # fell through 95 -> sold
    assert b.positions() == []                             # flat


def test_buy_stop_triggers_when_price_rises():
    b, px = _broker(TSLA=200.0)
    s = b.place_order("TSLA", BUY, 5, STOP, stop_price=210.0)   # breakout buy-stop
    px.set("TSLA", 205.0); b.poll()
    assert s.status == PENDING
    px.set("TSLA", 211.0); b.poll()
    assert s.status == FILLED


# --- stop-limit -------------------------------------------------------------

def test_stop_limit_becomes_working_limit_then_fills():
    b, px = _broker(X=100.0)
    b.place_order("X", BUY, 10, MARKET)
    o = b.place_order("X", SELL, 10, STOP_LIMIT, stop_price=95.0, limit_price=94.0)
    px.set("X", 94.5); b.poll()          # crosses stop 95 (triggered) and 94.5 >= 94 limit -> fills
    assert o.triggered and o.status == FILLED


def test_stop_limit_holds_below_limit():
    b, px = _broker(X=100.0)
    b.place_order("X", BUY, 10, MARKET)
    o = b.place_order("X", SELL, 10, STOP_LIMIT, stop_price=95.0, limit_price=94.0)
    px.set("X", 93.0); b.poll()                            # gapped past the limit
    assert o.triggered and o.status == PENDING             # working, unfilled (93 < 94)
    px.set("X", 94.5); b.poll()
    assert o.status == FILLED


# --- trailing stop ----------------------------------------------------------

def test_trailing_stop_ratchets_up_and_triggers():
    b, px = _broker(A=100.0)
    b.place_order("A", BUY, 10, MARKET)
    t = b.place_order("A", SELL, 10, TRAILING_STOP, trail_amount=5.0)
    assert t.stop_price == 95.0                            # 100 - 5
    px.set("A", 120.0); b.poll()
    assert t.stop_price == 115.0                           # ratcheted up with the high
    px.set("A", 118.0); b.poll()
    assert t.status == PENDING and t.stop_price == 115.0   # never ratchets down
    px.set("A", 114.0); b.poll()
    assert t.status == FILLED                              # fell through 115


def test_trailing_stop_percent():
    b, px = _broker(A=100.0)
    b.place_order("A", BUY, 10, MARKET)
    t = b.place_order("A", SELL, 10, TRAILING_STOP, trail_pct=10.0)
    assert t.stop_price == pytest.approx(90.0)             # 100 * (1 - 10%)
    px.set("A", 200.0); b.poll()
    assert t.stop_price == pytest.approx(180.0)


# --- bracket / OCO ----------------------------------------------------------

def test_bracket_exits_activate_after_entry_and_are_oco():
    b, px = _broker(Z=100.0)
    entry = b.place_bracket("Z", BUY, 10, take_profit=110.0, stop_loss=95.0)
    assert entry.status == FILLED                          # market entry filled
    # Two children: a take-profit limit and a stop, both active now.
    children = [o for o in b.orders() if o.parent_id == entry.id]
    assert len(children) == 2 and all(c.active for c in children)
    # Price rallies to the target -> take-profit fills, stop is cancelled (OCO).
    px.set("Z", 111.0); b.poll()
    tp = [c for c in children if c.order_type == LIMIT][0]
    sl = [c for c in children if c.order_type == STOP][0]
    assert tp.status == FILLED and sl.status == CANCELLED
    assert b.positions() == []                             # flat again


def test_bracket_stop_side_cancels_take_profit():
    b, px = _broker(Z=100.0)
    entry = b.place_bracket("Z", BUY, 10, take_profit=110.0, stop_loss=95.0)
    px.set("Z", 94.0); b.poll()                            # stop hit first
    children = [o for o in b.orders() if o.parent_id == entry.id]
    tp = [c for c in children if c.order_type == LIMIT][0]
    sl = [c for c in children if c.order_type == STOP][0]
    assert sl.status == FILLED and tp.status == CANCELLED


def test_bracket_children_inactive_until_limit_entry_fills():
    b, px = _broker(Z=100.0)
    entry = b.place_bracket("Z", BUY, 10, entry_type=LIMIT, entry_price=98.0,
                            take_profit=110.0, stop_loss=95.0)
    assert entry.status == PENDING
    children = [o for o in b.orders() if o.parent_id == entry.id]
    assert all(not c.active for c in children)             # dormant until entry fills
    px.set("Z", 97.0); b.poll()                            # entry limit fills
    assert entry.status == FILLED
    assert all(c.active for c in children)


# --- validation & persistence ----------------------------------------------

def test_validation_errors():
    from tradelab.core.broker import BrokerError
    b, _ = _broker(X=100.0)
    with pytest.raises(BrokerError):
        b.place_order("X", SELL, 10, STOP)                 # missing stop price
    with pytest.raises(BrokerError):
        b.place_order("X", SELL, 10, TRAILING_STOP)        # missing trail


def test_stop_orders_persist(tmp_path):
    path = tmp_path / "acct.json"
    src = _Prices(X=100.0)
    b = PaperBroker(starting_cash=100_000.0, price_fn=src, persist_path=path)
    b.place_order("X", BUY, 10, MARKET)
    b.place_order("X", SELL, 10, TRAILING_STOP, trail_amount=5.0)
    b2 = PaperBroker(starting_cash=100_000.0, price_fn=src, persist_path=path)
    trail = [o for o in b2.orders() if o.order_type == TRAILING_STOP]
    assert len(trail) == 1 and trail[0].trail_amount == 5.0

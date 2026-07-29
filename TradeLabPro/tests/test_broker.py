"""Tests for the Phase 8 paper-trading broker. All prices are injected, so
these never hit the network."""
import pytest

from tradelab.core.broker import (
    PaperBroker, BrokerError, BUY, SELL, MARKET, LIMIT, FILLED, PENDING,
    CANCELLED, REJECTED,
)


class _Prices:
    """Mutable injectable price source."""
    def __init__(self, **prices):
        self.prices = prices

    def __call__(self, symbol):
        return self.prices[symbol]


def _broker(cash=100_000.0, commission=0.0, **prices):
    return PaperBroker(starting_cash=cash, commission=commission, price_fn=_Prices(**prices))


def test_market_buy_fills_and_debits_cash():
    b = _broker(AAPL=100.0)
    o = b.place_order("AAPL", BUY, 10, MARKET)
    assert o.status == FILLED
    assert o.filled_price == 100.0
    assert b.cash == 100_000.0 - 1000.0
    pos = b.positions()
    assert len(pos) == 1 and pos[0].symbol == "AAPL" and pos[0].qty == 10


def test_average_cost_on_add():
    b = _broker(AAPL=100.0)
    b.place_order("AAPL", BUY, 10, MARKET)
    b._price_fn.prices["AAPL"] = 120.0
    b.place_order("AAPL", BUY, 10, MARKET)
    pos = b.positions()[0]
    assert pos.qty == 20
    assert pos.avg_price == pytest.approx(110.0)


def test_sell_realizes_pnl():
    b = _broker(AAPL=100.0)
    b.place_order("AAPL", BUY, 10, MARKET)         # cost 1000
    b._price_fn.prices["AAPL"] = 130.0
    b.place_order("AAPL", SELL, 10, MARKET)        # +1300, realize +300
    assert b.positions() == []
    assert b.realized_pnl == pytest.approx(300.0)
    assert b.cash == pytest.approx(100_000.0 + 300.0)


def test_partial_close_keeps_avg_price():
    b = _broker(AAPL=100.0)
    b.place_order("AAPL", BUY, 10, MARKET)
    b._price_fn.prices["AAPL"] = 150.0
    b.place_order("AAPL", SELL, 4, MARKET)         # realize 4*50 = 200
    pos = b.positions()[0]
    assert pos.qty == 6
    assert pos.avg_price == pytest.approx(100.0)
    assert b.realized_pnl == pytest.approx(200.0)


def test_short_position_and_cover():
    b = _broker(AAPL=100.0)
    b.place_order("AAPL", SELL, 10, MARKET)        # open short, +1000 cash
    assert b.positions()[0].qty == -10
    assert b.cash == pytest.approx(101_000.0)
    b._price_fn.prices["AAPL"] = 90.0
    b.place_order("AAPL", BUY, 10, MARKET)         # cover at 90 -> profit 100
    assert b.positions() == []
    assert b.realized_pnl == pytest.approx(100.0)


def test_account_summary_marks_to_market():
    b = _broker(AAPL=100.0)
    b.place_order("AAPL", BUY, 10, MARKET)
    b._price_fn.prices["AAPL"] = 110.0
    s = b.account_summary()
    assert s["positions_value"] == pytest.approx(1100.0)
    assert s["unrealized_pnl"] == pytest.approx(100.0)
    assert s["equity"] == pytest.approx(b.cash + 1100.0)
    assert s["total_pnl"] == pytest.approx(100.0)


def test_limit_order_rests_then_fills_on_poll():
    b = _broker(AAPL=100.0)
    o = b.place_order("AAPL", BUY, 5, LIMIT, limit_price=95.0)
    assert o.status == PENDING
    assert b.poll() is False               # price 100 > 95, no fill
    b._price_fn.prices["AAPL"] = 94.0
    assert b.poll() is True                # crosses -> fills
    assert o.status == FILLED and o.filled_price == 94.0


def test_cancel_pending_limit_order():
    b = _broker(AAPL=100.0)
    o = b.place_order("AAPL", BUY, 5, LIMIT, limit_price=90.0)
    assert b.cancel_order(o.id) is True
    assert o.status == CANCELLED
    assert b.cancel_order(o.id) is False   # already cancelled


def test_invalid_orders_raise():
    b = _broker(AAPL=100.0)
    with pytest.raises(BrokerError):
        b.place_order("AAPL", "HODL", 10, MARKET)
    with pytest.raises(BrokerError):
        b.place_order("AAPL", BUY, 0, MARKET)
    with pytest.raises(BrokerError):
        b.place_order("AAPL", BUY, 10, LIMIT)  # missing limit price


def test_market_order_rejected_when_no_price():
    b = PaperBroker(price_fn=lambda s: (_ for _ in ()).throw(BrokerError("no price")))
    o = b.place_order("ZZZZ", BUY, 10, MARKET)
    assert o.status == REJECTED
    assert "no price" in o.note


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "paper.json"
    b = PaperBroker(starting_cash=50_000.0, price_fn=_Prices(AAPL=100.0), persist_path=path)
    b.place_order("AAPL", BUY, 3, MARKET)
    b2 = PaperBroker(price_fn=_Prices(AAPL=100.0), persist_path=path)
    assert b2.cash == pytest.approx(50_000.0 - 300.0)
    assert b2.positions()[0].qty == 3
    assert len(b2.orders()) == 1


def test_reset_restores_starting_cash(tmp_path):
    b = PaperBroker(starting_cash=25_000.0, price_fn=_Prices(AAPL=100.0),
                    persist_path=tmp_path / "p.json")
    b.place_order("AAPL", BUY, 5, MARKET)
    b.reset()
    assert b.cash == 25_000.0
    assert b.positions() == []
    assert b.orders() == []

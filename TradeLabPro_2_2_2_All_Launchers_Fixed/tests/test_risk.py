"""Risk & position-sizing tests - pure/offline."""
import math

from tradelab.core.risk import size_position, r_targets, sector_exposure


# --- position sizing --------------------------------------------------------

def test_basic_share_count_from_risk_pct():
    # $100k, risk 1% = $1,000. Entry 50, stop 45 -> $5/share risk -> 200 shares.
    r = size_position(100_000, 1.0, entry=50.0, stop=45.0)
    assert r.valid
    assert r.risk_amount == 1000.0
    assert r.risk_per_share == 5.0
    assert r.shares == 200
    assert r.position_value == 200 * 50.0
    assert math.isclose(r.actual_risk, 1000.0)
    assert math.isclose(r.stop_pct, 10.0)          # 5/50


def test_shares_floor_when_not_exact():
    # $1,000 risk / $3 per share = 333.33 -> 333 shares (never round up risk).
    r = size_position(100_000, 1.0, entry=20.0, stop=17.0)
    assert r.shares == 333
    assert r.actual_risk == 333 * 3.0


def test_explicit_risk_amount_overrides_pct():
    r = size_position(100_000, 1.0, entry=50.0, stop=45.0, risk_amount=500.0)
    assert r.risk_amount == 500.0 and r.shares == 100


def test_short_side_sizes_the_same():
    r = size_position(100_000, 1.0, entry=45.0, stop=50.0, side="Short")
    assert r.side == "Short" and r.risk_per_share == 5.0 and r.shares == 200


def test_max_position_pct_caps_size():
    # Tight stop would risk-size a huge position; cap at 20% of equity.
    r = size_position(100_000, 1.0, entry=50.0, stop=49.9, max_position_pct=20.0)
    assert r.capped_by == "max position %"
    assert r.position_value <= 20_000 + 50    # within one share of the cap
    assert r.shares == int(20_000 // 50)


def test_buying_power_caps_size():
    r = size_position(100_000, 5.0, entry=50.0, stop=45.0, buying_power=1000.0)
    assert r.capped_by == "buying power"
    assert r.shares == 20                       # 1000 / 50


def test_invalid_inputs():
    assert not size_position(100_000, 1.0, entry=0, stop=45).valid
    assert not size_position(100_000, 1.0, entry=50, stop=50).valid   # stop == entry
    bad = size_position(100_000, 0.0, entry=50, stop=45)
    assert not bad.valid and "Risk" in bad.reason


def test_risk_too_small_for_one_share():
    # $10 risk, $50/share stop distance -> 0 shares -> invalid with a reason.
    r = size_position(1000, 1.0, entry=100.0, stop=50.0)
    assert r.shares == 0 and not r.valid and "one share" in r.reason


# --- R targets --------------------------------------------------------------

def test_r_targets_long():
    tg = r_targets(entry=50.0, stop=45.0, side="Long", multiples=(1, 2, 3), shares=200)
    assert [t.price for t in tg] == [55.0, 60.0, 65.0]
    assert [t.pnl for t in tg] == [1000.0, 2000.0, 3000.0]   # R × $5 × 200


def test_r_targets_short_go_down():
    tg = r_targets(entry=45.0, stop=50.0, side="Short", multiples=(1, 2), shares=100)
    assert [t.price for t in tg] == [40.0, 35.0]
    assert tg[0].pnl == 500.0


def test_r_targets_degenerate():
    assert r_targets(50, 50) == []      # no risk distance
    assert r_targets(0, 5) == []


# --- sector exposure --------------------------------------------------------

def test_sector_exposure_groups_and_percents():
    positions = [
        {"symbol": "AAPL", "market_value": 6000},
        {"symbol": "MSFT", "market_value": 2000},
        {"symbol": "XOM", "market_value": 2000},
    ]
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}
    rows, total = sector_exposure(positions, sector_of=lambda s: sectors[s])
    assert total == 10000
    assert rows[0] == ("Technology", 8000, 80.0)
    assert rows[1] == ("Energy", 2000, 20.0)


def test_sector_exposure_from_shares_and_price():
    positions = [{"symbol": "AAPL", "shares": 10, "price": 100}]
    rows, total = sector_exposure(positions, sector_of=lambda s: "Technology")
    assert total == 1000 and rows[0] == ("Technology", 1000, 100.0)


def test_sector_exposure_skips_empty_and_zero():
    positions = [{"symbol": "", "market_value": 100},
                 {"symbol": "AAPL", "market_value": 0},
                 {"symbol": "MSFT", "market_value": 500}]
    rows, total = sector_exposure(positions, sector_of=lambda s: "Tech")
    assert total == 500 and rows == [("Tech", 500, 100.0)]

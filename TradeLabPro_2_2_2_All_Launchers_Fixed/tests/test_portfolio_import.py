"""Tests for IBKR portfolio-position import (tradelab/core/portfolio_import.py)
and the DB sync helper. All offline; the Flex fetch is transport-injected.
"""
from tradelab.core import portfolio_import as pi
from tradelab.data.database import Database


_XML = """<FlexQueryResponse>
 <FlexStatements><FlexStatement>
  <OpenPositions>
   <OpenPosition symbol="AAPL" position="100" costBasisPrice="150.5" multiplier="1" assetCategory="STK"/>
   <OpenPosition symbol="AAPL" position="50" costBasisPrice="160" multiplier="1"/>
   <OpenPosition symbol="MSFT" position="-20" costBasisPrice="300" multiplier="1"/>
   <OpenPosition symbol="NOPX" position="10" costBasisMoney="1000" multiplier="1"/>
  </OpenPositions>
 </FlexStatement></FlexStatements>
</FlexQueryResponse>"""


def test_to_yahoo_symbol_normalization():
    f = pi._to_yahoo_symbol
    assert f("XDIV", "TSE", "CAD") == "XDIV.TO"       # Toronto listing
    assert f("XDIV", "", "CAD") == "XDIV.TO"          # CAD account, no exchange col
    assert f("XDIV.TO", "TSE", "CAD") == "XDIV.TO"    # already suffixed -> unchanged
    assert f("AAPL", "NASDAQ", "USD") == "AAPL"       # US -> no suffix
    assert f("BRK B", "NYSE", "USD") == "BRK-B"       # class share, space -> dash
    assert f("BRK.B", None, "USD") == "BRK-B"         # class share, dot -> dash
    assert f("VOD", "LSE", "GBP") == "VOD.L"          # London
    assert f("SHOP", "VENTURE", "CAD") == "SHOP.V"    # TSX Venture


def test_import_canadian_account_gets_to_suffix():
    xml = ('<FlexQueryResponse><FlexStatements><FlexStatement><OpenPositions>'
           '<OpenPosition symbol="XDIV" position="500" costBasisPrice="40" '
           'listingExchange="TSE" currency="CAD" multiplier="1"/>'
           '<OpenPosition symbol="VFV" position="100" costBasisPrice="100" '
           'currency="CAD" multiplier="1"/>'
           '</OpenPositions></FlexStatement></FlexStatements></FlexQueryResponse>')
    pos = {p["symbol"]: p for p in pi.parse_ibkr_positions_xml(xml)}
    assert set(pos) == {"XDIV.TO", "VFV.TO"}          # both mapped to Yahoo form
    assert pos["XDIV.TO"]["shares"] == 500


def test_activity_csv_currency_drives_suffix():
    csv = (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Cost Price\n"
        "Open Positions,Data,Summary,Stocks,CAD,XDIV,500,40\n"
    )
    pos = pi.parse_ibkr_positions_csv(csv)
    assert pos[0]["symbol"] == "XDIV.TO"


def test_choose_symbol_by_cost_basis_proximity():
    # Real prices probed from Yahoo for each candidate listing.
    prices = {
        "XDIV": 30.11, "XDIV.TO": 46.42, "XDIV.V": None,   # Toronto ETF
        "NVDA": 206.84, "NVDA.TO": 46.29, "NVDA.V": None,  # US stock vs Canadian CDR
        "XIC": None, "XIC.TO": 56.46, "XIC.V": None,        # bare has no listing
        "VTI": 364.80, "VTI.TO": None, "VTI.V": None,       # US-only
    }
    probe = lambda s: prices.get(s)
    assert pi.choose_symbol("XDIV", 43.26, probe) == "XDIV.TO"   # cost near .TO
    assert pi.choose_symbol("NVDA", 100.0, probe) == "NVDA"      # cost near US, not CDR
    assert pi.choose_symbol("XIC", 55.63, probe) == "XIC.TO"     # only .TO exists
    assert pi.choose_symbol("VTI", 367.43, probe) == "VTI"       # US-only stays bare


def test_choose_symbol_guards():
    probe = lambda s: 50.0
    assert pi.choose_symbol("XDIV.TO", 43.0, probe) == "XDIV.TO"  # already suffixed
    assert pi.choose_symbol("AAPL", 0, probe) == "AAPL"           # no cost basis -> bare
    assert pi.choose_symbol("AAPL", 150, lambda s: None) == "AAPL"  # no data -> bare


def test_resolve_positions_uses_probe():
    prices = {"XDIV": 30.11, "XDIV.TO": 46.42, "AAPL": 210.0, "AAPL.TO": None}
    positions = [{"symbol": "XDIV", "shares": 300, "entry_price": 43.26},
                 {"symbol": "AAPL", "shares": 10, "entry_price": 200.0}]
    out = {p["symbol"]: p for p in pi.resolve_positions(positions, probe=lambda s: prices.get(s))}
    assert set(out) == {"XDIV.TO", "AAPL"}
    assert out["XDIV.TO"]["shares"] == 300


def test_parse_xml_merges_lots_and_keeps_short_sign():
    pos = {p["symbol"]: p for p in pi.parse_ibkr_positions_xml(_XML)}
    assert set(pos) == {"AAPL", "MSFT", "NOPX"}
    # cost-weighted entry: (100*150.5 + 50*160) / 150 = 153.6667
    assert pos["AAPL"]["shares"] == 150
    assert round(pos["AAPL"]["entry_price"], 4) == 153.6667
    assert pos["MSFT"]["shares"] == -20            # short kept negative
    # entry derived from cost basis money / quantity: 1000/10 = 100
    assert pos["NOPX"]["entry_price"] == 100.0


def test_parse_xml_ignores_junk():
    assert pi.parse_ibkr_positions_xml("not xml") == []
    assert pi.parse_ibkr_positions_xml("<x/>") == []


_ACTIVITY_CSV = (
    "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis\n"
    "Open Positions,Data,Summary,Stocks,USD,AAPL,100,1,150.5,15050\n"
    "Open Positions,Data,Summary,Stocks,USD,TSLA,30,1,250,7500\n"
    "Open Positions,Data,Lot,Stocks,USD,AAPL,100,1,150.5,15050\n"
    "Open Positions,Total,,Stocks,USD,,130,,,\n"
)


def test_parse_activity_csv_uses_summary_rows_only():
    pos = {p["symbol"]: p for p in pi.parse_ibkr_positions_csv(_ACTIVITY_CSV)}
    assert set(pos) == {"AAPL", "TSLA"}            # Lot row not double-counted
    assert pos["AAPL"]["shares"] == 100
    assert pos["AAPL"]["entry_price"] == 150.5
    assert pos["TSLA"]["shares"] == 30


_FLAT_CSV = (
    "Symbol,Quantity,CostBasisPrice,Multiplier\n"
    "AAPL,100,150.5,1\n"
    "MSFT,50,300,1\n"
)


def test_parse_flat_csv():
    pos = {p["symbol"]: p for p in pi.parse_ibkr_positions_csv(_FLAT_CSV)}
    assert pos["AAPL"]["shares"] == 100 and pos["AAPL"]["entry_price"] == 150.5
    assert pos["MSFT"]["shares"] == 50


def test_parse_dispatch_prefers_xml_then_csv():
    assert pi.parse_ibkr_positions(_XML)                     # xml path
    assert pi.parse_ibkr_positions(_FLAT_CSV)                # csv path


def test_fetch_uses_injected_transport():
    # fetch_ibkr_flex does a two-step exchange; the fake transport returns a
    # SendRequest response first, then the report.
    send = ('<FlexStatementResponse><Status>Success</Status>'
            '<ReferenceCode>REF</ReferenceCode>'
            '<Url>https://x/GetStatement</Url></FlexStatementResponse>')
    calls = []

    def transport(url):
        calls.append(url)
        return send if "SendRequest" in url or len(calls) == 1 else _XML

    out = {p["symbol"]: p for p in pi.fetch_ibkr_positions("tok", "qid", transport=transport)}
    assert "AAPL" in out and out["AAPL"]["shares"] == 150


def test_db_set_portfolio_positions_replaces(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.add_position("OLD", 5, 1.0, portfolio="IBKR")
    n = db.set_portfolio_positions("IBKR", pi.parse_ibkr_positions_xml(_XML))
    assert n == 3                                   # AAPL, MSFT, NOPX (short kept)
    syms = {p["symbol"] for p in db.positions()}
    assert "OLD" not in syms and "AAPL" in syms
    # Re-importing replaces, not appends.
    db.set_portfolio_positions("IBKR", pi.parse_ibkr_positions_xml(_XML))
    assert len([p for p in db.positions() if p["portfolio"] == "IBKR"]) == 3

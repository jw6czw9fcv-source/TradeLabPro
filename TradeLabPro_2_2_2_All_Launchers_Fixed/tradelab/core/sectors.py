"""Sector, industry and ETF baskets for the Scanner (Qt-free).

Yahoo only reports a symbol's sector through a per-symbol metadata call, so
filtering a multi-thousand-symbol exchange list by sector would mean thousands
of network round-trips before a scan could even start. Instead we ship curated
baskets: pick "Gold & Precious Metals" or "Technology" and the scanner runs
against that list directly, with no lookup pass.

Baskets are separated by market the same way the Market tab is - you choose
US or Canada first, then the sector - so a scan is never a silent mix of two
exchanges. Three levels within each region, coarse to fine:
  * sectors    - the 11 GICS sectors, as liquid large-cap constituents.
  * industries - sub-sectors that cut across or drill into them (gold, banks,
                 uranium, REITs ...), including the Heatmap's theme baskets so
                 the two features share one definition instead of drifting.
  * ETFs       - funds rather than single names.

Kept independent of Qt and of any live fetch, same pattern as
tradelab/core/market.py, so it stays unit-testable offline.
"""
from __future__ import annotations

from tradelab.core.heatmap import THEMES

REGIONS = ("US", "Canada")

# Yahoo suffixes for the Canadian venues (TSX, TSX-V, CSE, NEO).
_CANADIAN_SUFFIXES = (".TO", ".V", ".CN", ".NE")

# The 11 GICS sectors on US exchanges, each a handful of liquid, representative
# large caps. Deliberately not exhaustive - a scannable shortlist, not an index.
US_SECTORS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE",
                   "CSCO", "ACN", "INTU", "IBM", "QCOM", "TXN", "NOW", "PANW"],
    "Financials": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP",
                   "SPGI", "BLK", "C", "SCHW", "CB", "PGR", "USB"],
    "Health Care": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "PFE",
                    "DHR", "AMGN", "ISRG", "BMY", "GILD", "CVS", "MDT", "VRTX"],
    "Energy": ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY",
               "WMB", "KMI", "HES", "DVN", "HAL", "BKR", "FANG"],
    "Industrials": ["GE", "CAT", "RTX", "UNP", "HON", "BA", "DE", "LMT", "UPS",
                    "ETN", "ADP", "NOC", "WM", "EMR", "CSX", "GD"],
    "Consumer Staples": ["WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "MDLZ",
                         "CL", "TGT", "KMB", "GIS", "STZ", "KDP", "SYY", "KHC"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "BKNG", "LOW", "NKE",
                               "SBUX", "TJX", "ORLY", "CMG", "MAR", "GM", "F"],
    "Utilities": ["NEE", "SO", "DUK", "CEG", "SRE", "AEP", "D", "PCG", "EXC",
                  "XEL", "ED", "PEG", "WEC", "ES", "AWK", "DTE"],
    "Materials": ["LIN", "SHW", "APD", "ECL", "FCX", "NEM", "NUE", "DOW", "DD",
                  "PPG", "VMC", "MLM", "IFF", "ALB", "CE", "STLD"],
    "Real Estate": ["PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "O", "CCI",
                    "DLR", "CBRE", "VICI", "EXR", "AVB", "EQR", "IRM", "SBAC"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "T",
                               "VZ", "TMUS", "CHTR", "EA", "TTWO", "WBD", "OMC"],
}

# The same 11 sectors on the TSX. Canada's market is far more concentrated in
# financials, energy and materials, and correspondingly thin in health care -
# these lists reflect that rather than padding to a uniform length.
CANADA_SECTORS = {
    "Technology": ["CSU.TO", "SHOP.TO", "OTEX.TO", "DSG.TO", "GIB-A.TO",
                   "CLS.TO", "DND.TO", "NVEI.TO", "REAL.TO", "TIXT.TO"],
    "Financials": ["RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
                   "MFC.TO", "SLF.TO", "GWO.TO", "IFC.TO", "POW.TO", "FFH.TO",
                   "EQB.TO", "IGM.TO", "X.TO", "IAG.TO"],
    "Health Care": ["BHC.TO", "WEED.TO", "TLRY.TO", "ACB.TO", "CRON.TO", "OGI.TO"],
    "Energy": ["CNQ.TO", "SU.TO", "IMO.TO", "CVE.TO", "TOU.TO", "ARX.TO",
               "WCP.TO", "MEG.TO", "ENB.TO", "TRP.TO", "PPL.TO", "KEY.TO",
               "ALA.TO", "PKI.TO"],
    "Industrials": ["CNR.TO", "CP.TO", "WCN.TO", "TFII.TO", "STN.TO", "WSP.TO",
                    "TIH.TO", "CAE.TO", "GFL.TO", "BYD.TO", "ATS.TO"],
    "Consumer Staples": ["L.TO", "MRU.TO", "ATD.TO", "SAP.TO", "EMP-A.TO",
                         "WN.TO", "PBH.TO"],
    "Consumer Discretionary": ["QSR.TO", "DOO.TO", "GIL.TO", "CTC-A.TO",
                               "MG.TO", "DOL.TO", "TOY.TO", "GOOS.TO"],
    "Utilities": ["FTS.TO", "EMA.TO", "H.TO", "CU.TO", "AQN.TO", "BLX.TO",
                  "ACO-X.TO", "CPX.TO", "BEP-UN.TO", "BIP-UN.TO"],
    "Materials": ["ABX.TO", "AEM.TO", "K.TO", "FNV.TO", "WPM.TO", "TECK-B.TO",
                  "FM.TO", "LUN.TO", "NTR.TO", "AGI.TO", "BTO.TO", "CCL-B.TO",
                  "IVN.TO", "ELD.TO"],
    "Real Estate": ["REI-UN.TO", "CAR-UN.TO", "SRU-UN.TO", "DIR-UN.TO",
                    "GRT-UN.TO", "IIP-UN.TO", "AP-UN.TO", "HR-UN.TO",
                    "FSV.TO", "TCN.TO"],
    "Communication Services": ["BCE.TO", "T.TO", "RCI-B.TO", "QBR-B.TO"],
}

# Sub-sectors. These are the "gold / banks / uranium"-style cuts people
# actually scan by, several of which sit inside a GICS sector rather than
# beside it. Each list carries both markets' names; they are split by region
# on the way out (see region_baskets), so there is one definition to maintain.
INDUSTRIES = {
    "Gold & Precious Metals": ["NEM", "GOLD", "AEM", "WPM", "FNV", "KGC", "AU",
                               "AGI", "BTG", "PAAS", "HL", "EGO", "IAG", "RGLD",
                               "ABX.TO", "AEM.TO", "K.TO", "FNV.TO", "WPM.TO",
                               "AGI.TO", "BTO.TO", "ELD.TO", "OR.TO", "OSK.TO"],
    "Silver & Base Metals": ["PAAS", "AG", "HL", "FCX", "SCCO", "TECK", "RIO",
                             "BHP", "VALE", "LUN.TO", "FM.TO", "TECK-B.TO",
                             "IVN.TO", "CS.TO"],
    "Uranium & Nuclear": ["CCJ", "UEC", "DNN", "NXE", "UUUU", "LEU", "SMR",
                          "CCO.TO", "DML.V", "NXE.TO", "FCU.TO"],
    "Oil & Gas": ["XOM", "CVX", "COP", "EOG", "OXY", "DVN", "FANG", "HES",
                  "MRO", "APA", "CNQ.TO", "SU.TO", "IMO.TO", "CVE.TO",
                  "TOU.TO", "ARX.TO", "WCP.TO", "MEG.TO", "BTE.TO"],
    "Oilfield Services & Pipelines": ["SLB", "HAL", "BKR", "NOV", "FTI", "WMB",
                                      "KMI", "OKE", "EPD", "ET", "ENB.TO",
                                      "TRP.TO", "PPL.TO", "KEY.TO", "ALA.TO"],
    "Banks": ["JPM", "BAC", "WFC", "C", "USB", "PNC", "TFC", "MTB", "FITB",
              "RF", "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
              "EQB.TO", "CWB.TO", "LB.TO"],
    "Insurance": ["BRK-B", "PGR", "CB", "TRV", "ALL", "AIG", "MET", "PRU",
                  "AFL", "HIG", "MFC.TO", "SLF.TO", "GWO.TO", "IFC.TO",
                  "IAG.TO", "FFH.TO"],
    "Asset Managers & Exchanges": ["BLK", "BX", "KKR", "APO", "SCHW", "SPGI",
                                   "CME", "ICE", "NDAQ", "TROW", "BN.TO",
                                   "BAM.TO", "IGM.TO", "X.TO", "ONEX.TO"],
    "REITs & Real Estate": ["PLD", "AMT", "EQIX", "SPG", "PSA", "O", "WELL",
                            "AVB", "EQR", "REI-UN.TO", "CAR-UN.TO",
                            "SRU-UN.TO", "DIR-UN.TO", "GRT-UN.TO", "IIP-UN.TO",
                            "AP-UN.TO", "HR-UN.TO"],
    "Airlines & Travel": ["DAL", "UAL", "AAL", "LUV", "ALK", "BKNG", "ABNB",
                          "MAR", "HLT", "RCL", "CCL", "NCLH", "AC.TO",
                          "DOO.TO", "TOY.TO"],
    "Homebuilders & Construction": ["DHI", "LEN", "PHM", "NVR", "TOL", "VMC",
                                    "MLM", "MAS", "BLDR", "STN.TO", "WSP.TO",
                                    "ARE.TO", "BDGI.TO"],
    "Retail": ["WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST", "DG", "DLTR",
               "BBY", "KR", "ATD.TO", "DOL.TO", "L.TO", "MRU.TO", "CTC-A.TO",
               "EMP-A.TO"],
    "Pharma": ["LLY", "JNJ", "MRK", "PFE", "ABBV", "BMY", "AZN", "NVO", "GSK",
               "NVS", "ZTS", "VTRS", "BHC.TO"],
    "Telecom": ["T", "VZ", "TMUS", "CHTR", "CMCSA", "LUMN", "BCE.TO", "T.TO",
                "RCI-B.TO", "QBR-B.TO"],
    "Shipping & Logistics": ["UPS", "FDX", "ZIM", "MATX", "GSL", "SBLK",
                             "CP.TO", "CNR.TO", "TFII.TO", "AC.TO"],
    "Cannabis": ["TLRY", "CGC", "CRON", "ACB", "OGI", "SNDL", "WEED.TO",
                 "ACB.TO", "OGI.TO", "TLRY.TO"],
    "Railways & Infrastructure": ["UNP", "CSX", "NSC", "CP", "CNI", "WM", "RSG",
                                  "CNR.TO", "CP.TO", "WCN.TO", "GFL.TO",
                                  "BIP-UN.TO", "STN.TO"],
}
# The Heatmap's theme baskets are sub-sectors too (Semiconductors, Biotech,
# Cybersecurity, Fintech ...). Share them rather than keeping a second copy.
INDUSTRIES.update(THEMES)

# Fund baskets - for scanning ETFs themselves rather than single names.
ETF_BASKETS = {
    "US": {
        "ETFs - Sector SPDRs": ["XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY",
                                "XLU", "XLB", "XLRE", "XLC"],
        "ETFs - Index & assets": ["SPY", "QQQ", "DIA", "IWM", "VTI", "VOO",
                                  "GLD", "SLV", "TLT", "HYG", "LQD", "ARKK",
                                  "EEM", "EFA"],
        "ETFs - Commodities & metals": ["GLD", "SLV", "IAU", "GDX", "GDXJ",
                                        "SIL", "USO", "UNG", "DBC", "URA",
                                        "COPX", "PPLT"],
    },
    "Canada": {
        "ETFs - TSX sectors": ["XEG.TO", "XFN.TO", "XMA.TO", "XIT.TO", "XUT.TO",
                               "XST.TO", "XRE.TO"],
        "ETFs - Index & assets": ["XIU.TO", "XIC.TO", "XEI.TO", "ZCN.TO",
                                  "VCN.TO", "VDY.TO", "ZEB.TO", "XSP.TO",
                                  "XQQ.TO", "ZSP.TO", "VFV.TO"],
    },
}

# Prefix used to expose baskets as scanner universes. Names carry their region
# ("Sector - Canada - Banks") so the two markets can never be scanned as one
# accidental blend. The Scanner groups anything starting with this into its
# own "Sectors" section and filters it by the selected region.
BASKET_PREFIX = "Sector - "


def is_canadian(symbol: str) -> bool:
    """True for TSX / TSX-V / CSE / NEO listings, by Yahoo suffix."""
    return str(symbol).upper().endswith(_CANADIAN_SUFFIXES)


def _for_region(symbols, region: str) -> list:
    canadian = region == "Canada"
    return [s for s in symbols if is_canadian(s) == canadian]


def region_baskets(region: str) -> dict:
    """Every basket for one market, name -> symbols: the 11 sectors first,
    then sub-sectors, then ETF groups. Industry lists are filtered down to the
    market's own listings, and any basket with nothing left is dropped (Canada
    has no domestic semiconductor names, for instance)."""
    if region not in REGIONS:
        region = "US"
    out = {}
    sectors = CANADA_SECTORS if region == "Canada" else US_SECTORS
    for name, symbols in sectors.items():
        out[name] = list(symbols)
    for name, symbols in INDUSTRIES.items():
        scoped = _for_region(symbols, region)
        if scoped:
            out.setdefault(name, scoped)
    for name, symbols in ETF_BASKETS.get(region, {}).items():
        out.setdefault(name, list(symbols))
    return out


def basket_choices(region: str = "US") -> list:
    return list(region_baskets(region).keys())


def universe_name(region: str, basket: str) -> str:
    """Scanner universe key for a basket, e.g. 'Sector - Canada - Banks'."""
    return f"{BASKET_PREFIX}{region} - {basket}"


def split_universe_name(name: str):
    """('Canada', 'Banks') from 'Sector - Canada - Banks'; (None, name) if it
    isn't a basket key."""
    text = str(name or "")
    if not text.startswith(BASKET_PREFIX):
        return None, text
    rest = text[len(BASKET_PREFIX):]
    for region in REGIONS:
        tag = f"{region} - "
        if rest.startswith(tag):
            return region, rest[len(tag):]
    return None, rest


def basket_symbols(name: str, region: str = "US") -> list:
    """Symbols for one basket. Accepts a bare name ('Banks') with a region, or
    a full universe key ('Sector - Canada - Banks') which carries its own.
    Unknown names give []."""
    parsed_region, basket = split_universe_name(name)
    return list(region_baskets(parsed_region or region).get(basket, []))


def scanner_universes() -> dict:
    """Every basket in both markets, keyed the way the Scanner expects."""
    out = {}
    for region in REGIONS:
        for basket, symbols in region_baskets(region).items():
            out[universe_name(region, basket)] = list(symbols)
    return out

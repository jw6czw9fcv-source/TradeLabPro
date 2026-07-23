"""Sector, industry and ETF baskets for the Scanner (Qt-free).

Yahoo only reports a symbol's sector through a per-symbol metadata call, so
filtering a multi-thousand-symbol exchange list by sector would mean thousands
of network round-trips before a scan could even start. Instead we ship curated
baskets: pick "Gold & Precious Metals" or "Technology" and the scanner runs
against that list directly, with no lookup pass.

Three levels, coarse to fine:
  * SECTORS    - the 11 GICS sectors, as liquid large-cap constituents.
  * INDUSTRIES - sub-sectors that cut across or drill into them (gold, banks,
                 uranium, REITs ...), including the Heatmap's theme baskets so
                 the two features share one definition instead of drifting.
  * ETF_BASKETS - funds rather than single names (sector SPDRs, index,
                 commodity, Canadian).

Kept independent of Qt and of any live fetch, same pattern as
tradelab/core/market.py, so it stays unit-testable offline.
"""
from __future__ import annotations

from tradelab.core.heatmap import THEMES

# The 11 GICS sectors, each as a handful of liquid, representative large caps.
# Deliberately not exhaustive - this is a scannable shortlist, not an index.
SECTORS = {
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

# Sub-sectors. These are the "gold / finance / tech"-style cuts people actually
# scan by, several of which sit inside a GICS sector rather than beside it.
INDUSTRIES = {
    "Gold & Precious Metals": ["NEM", "GOLD", "AEM", "WPM", "FNV", "KGC", "AU",
                               "AGI", "BTG", "PAAS", "HL", "EGO", "IAG", "RGLD",
                               "ABX.TO", "AEM.TO", "K.TO", "FNV.TO", "WPM.TO"],
    "Silver & Base Metals": ["PAAS", "AG", "HL", "FCX", "SCCO", "TECK", "RIO",
                             "BHP", "VALE", "LUN.TO", "FM.TO", "TECK-B.TO"],
    "Uranium & Nuclear": ["CCJ", "UEC", "DNN", "NXE", "UUUU", "LEU", "SMR",
                          "CCO.TO", "DML.V", "NXE.TO"],
    "Oil & Gas": ["XOM", "CVX", "COP", "EOG", "OXY", "DVN", "FANG", "HES",
                  "MRO", "APA", "CNQ.TO", "SU.TO", "IMO.TO", "CVE.TO", "TOU.TO"],
    "Oilfield Services & Pipelines": ["SLB", "HAL", "BKR", "NOV", "FTI", "WMB",
                                      "KMI", "OKE", "EPD", "ET", "ENB.TO",
                                      "TRP.TO", "PPL.TO", "KEY.TO"],
    "Banks": ["JPM", "BAC", "WFC", "C", "USB", "PNC", "TFC", "MTB", "FITB",
              "RF", "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO"],
    "Insurance": ["BRK-B", "PGR", "CB", "TRV", "ALL", "AIG", "MET", "PRU",
                  "AFL", "HIG", "MFC.TO", "SLF.TO", "GWO.TO", "IFC.TO"],
    "Asset Managers & Exchanges": ["BLK", "BX", "KKR", "APO", "SCHW", "SPGI",
                                   "CME", "ICE", "NDAQ", "TROW", "BN.TO", "IGM.TO"],
    "REITs & Real Estate": ["PLD", "AMT", "EQIX", "SPG", "PSA", "O", "WELL",
                            "AVB", "EQR", "REI-UN.TO", "CAR-UN.TO", "SRU-UN.TO"],
    "Airlines & Travel": ["DAL", "UAL", "AAL", "LUV", "ALK", "BKNG", "ABNB",
                          "MAR", "HLT", "RCL", "CCL", "NCLH", "AC.TO"],
    "Homebuilders & Construction": ["DHI", "LEN", "PHM", "NVR", "TOL", "VMC",
                                    "MLM", "MAS", "BLDR", "STN.TO", "WSP.TO"],
    "Retail": ["WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST", "DG", "DLTR",
               "BBY", "KR", "ATD.TO", "DOL.TO", "L.TO", "MRU.TO"],
    "Pharma": ["LLY", "JNJ", "MRK", "PFE", "ABBV", "BMY", "AZN", "NVO", "GSK",
               "NVS", "ZTS", "VTRS"],
    "Telecom": ["T", "VZ", "TMUS", "CHTR", "CMCSA", "LUMN", "BCE.TO", "T.TO",
                "RCI-B.TO", "QBR-B.TO"],
    "Shipping & Logistics": ["UPS", "FDX", "ZIM", "MATX", "GSL", "SBLK", "CP.TO",
                             "CNR.TO", "TFII.TO"],
    "Cannabis": ["TLRY", "CGC", "CRON", "ACB", "OGI", "SNDL", "WEED.TO"],
}
# The Heatmap's theme baskets are sub-sectors too (Semiconductors, Biotech,
# Cybersecurity, Fintech ...). Share them rather than keeping a second copy.
INDUSTRIES.update(THEMES)

# Fund baskets - for scanning ETFs themselves rather than single names.
ETF_BASKETS = {
    "ETFs - US sector SPDRs": ["XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY",
                               "XLU", "XLB", "XLRE", "XLC"],
    "ETFs - US index & assets": ["SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "GLD",
                                 "SLV", "TLT", "HYG", "LQD", "ARKK", "EEM", "EFA"],
    "ETFs - Commodities & metals": ["GLD", "SLV", "IAU", "GDX", "GDXJ", "SIL",
                                    "USO", "UNG", "DBC", "URA", "COPX", "PPLT"],
    "ETFs - Canada": ["XIU.TO", "XIC.TO", "XEI.TO", "XRE.TO", "XFN.TO", "XEG.TO",
                      "XIT.TO", "XMA.TO", "XUT.TO", "XST.TO", "ZEB.TO", "ZSP.TO",
                      "VFV.TO", "VCN.TO", "VDY.TO"],
}

# Prefix used to expose baskets as scanner universes. The Scanner groups any
# universe whose name starts with this into its own "Sectors" section.
BASKET_PREFIX = "Sector - "


def all_baskets() -> dict:
    """Every basket, name -> symbols, coarse (sectors) to fine (industries,
    then ETF groups). Later keys never clobber earlier ones."""
    out = {}
    for group in (SECTORS, INDUSTRIES, ETF_BASKETS):
        for name, symbols in group.items():
            out.setdefault(name, list(symbols))
    return out


def basket_choices() -> list:
    return list(all_baskets().keys())


def basket_symbols(name: str) -> list:
    """Symbols for one basket, accepting the bare name or its scanner-universe
    form ('Sector - Gold & Precious Metals'). Unknown names give []."""
    key = str(name or "")
    if key.startswith(BASKET_PREFIX):
        key = key[len(BASKET_PREFIX):]
    return list(all_baskets().get(key, []))


def scanner_universes() -> dict:
    """Baskets keyed the way the Scanner's universe list expects them."""
    return {f"{BASKET_PREFIX}{name}": list(symbols)
            for name, symbols in all_baskets().items()}

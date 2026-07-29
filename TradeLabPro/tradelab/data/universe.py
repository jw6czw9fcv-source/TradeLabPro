from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Iterable
import io
import json
import re
import time
import urllib.request

import pandas as pd

from tradelab.core.config import DATA_DIR

CACHE_PATH = DATA_DIR / "universe_cache.json"
# Bump this when universe logic changes so old starter-only caches refresh automatically.
CACHE_VERSION = 11
CACHE_MAX_AGE_HOURS = 24

@dataclass(frozen=True)
class UniverseSymbol:
    symbol: str
    name: str
    exchange: str
    country: str

# Offline safety universe only. These are used only when live exchange-list downloads fail.
US_NASDAQ = ['AAPL','MSFT','NVDA','AMZN','META','GOOGL','GOOG','TSLA','AVGO','COST','NFLX','AMD','ADBE','PEP','QCOM','INTC','AMAT','MU','CSCO','INTU','AMGN','TXN','ISRG','BKNG','VRTX','PANW','REGN','LRCX','KLAC','MELI','ADI','SBUX','MDLZ','GILD','PYPL','MAR','ABNB','CRWD','SNPS','CDNS','MRVL','ADP','ORLY','CSX','NXPI','FTNT','ROP','MNST','KDP','AEP','PAYX','PCAR','ROST','FAST','CTAS','DDOG','TEAM','ZS','MDB','WDAY','DXCM','IDXX','ODFL','EA','EXC','XEL','KHC','BKR','GEHC','BIIB','ON','FANG','TTWO','CHTR','ILMN','WBD','SIRI']
US_NYSE = ['JPM','UNH','XOM','V','MA','HD','PG','LLY','MRK','CVX','ABBV','KO','BAC','WMT','DIS','MCD','CRM','ORCL','NKE','TMO','ABT','ACN','LIN','DHR','WFC','PM','RTX','NEE','UPS','LOW','HON','SPGI','CAT','GS','BLK','DE','BA','IBM','GE','AXP','T','VZ','PFE','COP','C','MS','SCHW','USB','LMT','ELV','CI','CVS','MDT','AMT','PLD','SO','DUK','PNC','CL','MMM','MO','GM','F','NOC','FDX','SLB','APD','EOG','AON','MMC','ICE','CME','CB','HUM','TGT','DG','PSX','OXY','MPC']
US_AMEX = ['SPY','QQQ','DIA','IWM','XLF','XLK','XLE','XLY','XLV','XLI','XLP','XLU','XLB','XLRE','GLD','SLV','TLT','HYG','LQD','ARKK']
CAN_TSX = ['SHOP.TO','RY.TO','TD.TO','BNS.TO','BMO.TO','CM.TO','CNR.TO','CP.TO','ENB.TO','SU.TO','CNQ.TO','TRP.TO','BCE.TO','T.TO','ATD.TO','WCN.TO','CSU.TO','MFC.TO','NA.TO','AQN.TO','FM.TO','ABX.TO','NTR.TO','TECK-B.TO','GIB-A.TO','IFC.TO','POW.TO','QSR.TO','CVE.TO','IMO.TO','SLF.TO','FFH.TO','WPM.TO','AEM.TO','TRI.TO','DOL.TO','L.TO','MRU.TO','WN.TO','SAP.TO','MG.TO','BAM.TO','BN.TO','BIP-UN.TO','BEP-UN.TO','FTS.TO','EMA.TO','H.TO','CU.TO','PPL.TO','KEY.TO','ARX.TO','TOU.TO','WCP.TO','MEG.TO','GIL.TO','CTC-A.TO','CAR-UN.TO','REI-UN.TO','SRU-UN.TO','DIR-UN.TO','K.TO','LUN.TO','PAAS.TO','AGI.TO','BTO.TO','EQB.TO','GWO.TO','IGM.TO','X.TO','TFII.TO','CAE.TO','CCL-B.TO','BYD.TO','DOO.TO','OTEX.TO','DSG.TO','REAL.TO','NVEI.TO','CLS.TO','DND.TO','ALA.TO','ACO-X.TO','IAG.TO','PKI.TO','GFL.TO','TIH.TO','STN.TO','WSP.TO','BLX.TO','EMP-A.TO','QBR-B.TO','RCI-B.TO']
CAN_TSXV = ['DML.V','NILI.V','ETL.V','KNT.V','VLE.V','SKE.V','NEXE.V','GRN.V']

# Expanded offline fallback. This is not a complete exchange list, but it gives
# the scanner a practical Canadian universe even when TMX or Wikipedia blocks
# automatic refresh. Keep Yahoo suffixes here so chart/scanner calls work.
CAN_TSX_EXPANDED = sorted(set(CAN_TSX + [
    'XIU.TO','XIC.TO','XEI.TO','XRE.TO','XFN.TO','XEG.TO','XIT.TO','XSP.TO','XQQ.TO','ZSP.TO','ZCN.TO','ZEB.TO','VDY.TO','VCN.TO','VFV.TO',
    'AC.TO','ADEN.TO','AIF.TO','ALS.TO','AP-UN.TO','ARE.TO','ATS.TO','BDGI.TO','BEI-UN.TO','BHC.TO','BIR.TO','BTE.TO','CCO.TO','CDAY.TO','CG.TO','CPX.TO','CTC.TO','CWB.TO','EFN.TO','ELD.TO','ERF.TO','ERO.TO','FNV.TO','FSV.TO','GEI.TO','GOOS.TO','GRT-UN.TO','HR-UN.TO','IIP-UN.TO','IVN.TO','JWEL.TO','LB.TO','LSPD.TO','MDA.TO','MFI.TO','MND.TO','NGD.TO','ONEX.TO','OR.TO','OSK.TO','PBH.TO','PET.TO','PSK.TO','RBA.TO','RCH.TO','SIA.TO','SJR-B.TO','SOY.TO','SNC.TO','STLC.TO','TCL-A.TO','TCN.TO','TOY.TO','TPZ.TO','TVE.TO','UNS.TO','WFG.TO','YRI.TO'
]))
CAN_TSXV_EXPANDED = sorted(set(CAN_TSXV + [
    'AOT.V','AVL.V','BEE.V','BIG.V','BQE.V','BRW.V','CNC.V','CRE.V','EGLX.V','FOM.V','FWZ.V','GLO.V','GOT.V','HPQ.V','IAU.V','KDK.V','LAC.V','LI.V','MAI.V','NOU.V','NTH.V','ORE.V','PDM.V','PTK.V','QIMC.V','RCK.V','SGQ.V','SLL.V','SMY.V','SVM.V','TLO.V','UCU.V','VPT.V','WRLG.V','XIM.V','ZEN.V'
]))

DEFAULT_UNIVERSE: Dict[str, List[str]] = {
    'US - NASDAQ starter fallback': US_NASDAQ,
    'US - NYSE starter fallback': US_NYSE,
    'US - ETFs starter fallback': US_AMEX,
    'Canada - TSX expanded fallback': CAN_TSX_EXPANDED,
    'Canada - TSXV expanded fallback': CAN_TSXV_EXPANDED,
}

YAHOO_SUFFIX = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN", "NEO": ".NE"}


def normalize_symbol(raw: str, country: str = "US", exchange: str = "") -> str:
    s = str(raw or "").strip().upper().replace('\xa0', ' ')
    if not s or s in {"NAN", "SYMBOL", "TICKER", "FILECREATIONTIME", "NONE"}:
        return ""
    if ':' in s:
        s = s.split(':')[-1]
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'\([^)]*\)', '', s) if s.count('(') and not re.search(r'[A-Z]\.[A-Z]', s) else s
    s = re.sub(r'^(NYSE|NASDAQ|AMEX|NYSEAMERICAN|TSX|TSXV|CSE)\s*[-–]\s*', '', s)
    s = re.split(r'[\s,/;]+', s)[0].strip(' .;,*')
    if not s:
        return ""
    if country == "Canada":
        if re.search(r"\.(TO|V|CN|NE)$", s):
            return s.replace('.', '-')[:-3] + s[-3:] if s[-3:] in ['.TO'] else s
        suffix = YAHOO_SUFFIX.get(exchange, ".TO")
        return s.replace('.', '-') + suffix
    return s.replace('.', '-')


def is_tradeable_symbol(symbol: str) -> bool:
    symbol = str(symbol or '').strip().upper()
    if not symbol or symbol in ['NAN', 'NONE']:
        return False
    if any(bad in symbol for bad in ['^', '$', ':', '|', '=']):
        return False
    # Skip many rights/warrants/units from full feeds; user can still import them manually if wanted.
    if any(symbol.endswith(f'-{x}') for x in ['W','WS','WT','R','U']):
        return False
    if not re.fullmatch(r'[A-Z0-9.-]+', symbol):
        return False
    # A real ticker always contains at least one letter. A purely numeric
    # string like "41" is junk from a bad feed line (e.g. a stray column
    # value parsed as a symbol), never a tradeable symbol.
    return bool(re.search(r'[A-Z]', symbol))


def _exchange_country(name: str):
    if name.startswith('My List') or name.startswith('Custom'):
        return ('List', 'List')
    if name.startswith('Canada'):
        if 'TSXV' in name or 'Venture' in name:
            return ('TSXV', 'Canada')
        if 'CSE' in name:
            return ('CSE', 'Canada')
        return ('TSX', 'Canada')
    if 'NYSE' in name and 'Other' not in name:
        return ('NYSE', 'US')
    if 'AMEX' in name or 'ETF' in name:
        return ('AMEX/ETF', 'US')
    if 'Other listed' in name or 'All US' in name:
        return ('NYSE/AMEX', 'US')
    return ('NASDAQ', 'US')


def _dedup(items: Iterable[UniverseSymbol]) -> List[UniverseSymbol]:
    seen=set(); dedup=[]
    for item in items:
        if item.symbol and item.symbol not in seen:
            seen.add(item.symbol); dedup.append(item)
    return dedup


def _read_cache():
    try:
        return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _write_cache(data):
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')


def _download_bytes(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 TradeLabPro/1.0",
        "Accept": "text/html,text/plain,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download_text(url: str, timeout: int = 30) -> str:
    raw = _download_bytes(url, timeout=timeout)
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1', errors='replace')




def _post_json(url: str, body: dict, timeout: int = 30) -> dict:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, headers={
        "User-Agent": "Mozilla/5.0 TradeLabPro/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
        "Origin": "https://finance.yahoo.com",
        "Referer": "https://finance.yahoo.com/research-hub/screener/equity/",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    cols=[]
    for col in df.columns:
        if isinstance(col, tuple):
            parts=[str(x).strip() for x in col if str(x).strip() and str(x).lower()!='nan']
            cols.append(' '.join(parts))
        else:
            cols.append(str(col).strip())
    df.columns=cols
    return df


def _find_symbol_column(df: pd.DataFrame):
    wanted = {'symbol','act symbol','ticker','ticker symbol','security symbol','root symbol'}
    for c in df.columns:
        cl = re.sub(r'\s+', ' ', str(c).strip().lower())
        if cl in wanted or ('symbol' in cl and 'name' not in cl and 'company' not in cl):
            return c
    return df.columns[0] if len(df.columns) else None


def _find_name_column(df: pd.DataFrame, symbol_col=None):
    preferred = ['security', 'security name', 'company', 'company name', 'name', 'issuer', 'description']
    for wanted in preferred:
        for c in df.columns:
            if symbol_col is not None and c == symbol_col:
                continue
            cl = re.sub(r'\s+', ' ', str(c).strip().lower())
            if cl == wanted or cl.endswith(' ' + wanted):
                return c
    return None


def _exchange_suffix_for_canadian_row(value):
    v = str(value or '').strip().upper()
    if 'VENTURE' in v or 'TSXV' in v or v == 'V':
        return '.V'
    if 'CSE' in v:
        return '.CN'
    if 'NEO' in v:
        return '.NE'
    return '.TO'


def _symbols_from_dataframe(df: pd.DataFrame, country: str, exchange: str) -> list[str]:
    df = _flatten_columns(df)
    col = _find_symbol_column(df)
    if col is None:
        return []
    out=[]
    for raw in df[col].dropna().astype(str):
        s = normalize_symbol(raw, country, exchange)
        if s and is_tradeable_symbol(s):
            out.append(s)
    return sorted(set(out))


def _looks_like_exchange_token(value: str) -> bool:
    v = str(value or '').strip().upper()
    return v in {'TSX', 'TSXV', 'TSX VENTURE', 'TSX VENTURE EXCHANGE', 'TORONTO STOCK EXCHANGE'} or 'TSXV' in v or 'VENTURE' in v


def _looks_like_symbol_token(value: str) -> bool:
    v = str(value or '').strip().upper()
    if not v or v in {'TSX', 'TSXV', 'ETF', 'NEX', 'CAD', 'CANADA', 'COMMON', 'CLASS', 'THE'}:
        return False
    if len(v) > 12:
        return False
    return bool(re.fullmatch(r'[A-Z][A-Z0-9.-]{0,10}', v))


def _parse_tmx_table(df: pd.DataFrame) -> list[str]:
    """Extract TSX/TSXV symbols from TMX resource 571.

    TMX periodically changes this workbook.  Sometimes the file has proper
    headers; sometimes rows resemble:
        571 | COG0001 | TSX | Cogeco Inc. | CGO | ...
    This parser first tries normal header discovery, then falls back to a
    row-wise exchange/symbol heuristic so a small layout change does not make
    the Canadian universe empty.
    """
    df = _flatten_columns(df)

    # Normal header-based path.
    symbol_col = _find_symbol_column(df)
    if symbol_col is not None and not str(symbol_col).isdigit() and not str(symbol_col).lower().startswith('unnamed'):
        exchange_col = None
        for c in df.columns:
            cl = str(c).lower()
            if 'exchange' in cl or 'market' in cl:
                exchange_col = c
                break
        symbols=[]
        for _, row in df.iterrows():
            raw = row.get(symbol_col, '')
            raw_ex = row.get(exchange_col, '') if exchange_col else ''
            suffix = _exchange_suffix_for_canadian_row(raw_ex)
            ex = 'TSXV' if suffix == '.V' else 'TSX'
            s = normalize_symbol(raw, 'Canada', ex)
            if s and is_tradeable_symbol(s):
                symbols.append(s)
        if len(symbols) >= 25:
            return sorted(set(symbols))

    # Headerless / shifted workbook fallback.
    symbols=[]
    for _, row in df.iterrows():
        vals = [str(x).strip() for x in row.tolist() if str(x).strip() and str(x).strip().lower() != 'nan']
        if not vals:
            continue
        for i, value in enumerate(vals):
            if not _looks_like_exchange_token(value):
                continue
            ex = 'TSXV' if ('V' in str(value).upper() or 'VENTURE' in str(value).upper()) else 'TSX'
            # In TMX resource rows the symbol is usually 1-3 columns after the exchange/name.
            candidates = vals[i+1:i+5]
            for cand in reversed(candidates):
                if _looks_like_symbol_token(cand):
                    sym = normalize_symbol(cand, 'Canada', ex)
                    if sym and is_tradeable_symbol(sym):
                        symbols.append(sym)
                    break
    return sorted(set(symbols))


def _fetch_canada_wikipedia_index_lists() -> list[str]:
    """Fallback Canadian universe from public Wikipedia index constituent pages.

    This is not the complete TSX/TSXV exchange, but it is much larger and more
    useful than the small offline starter list when TMX blocks resource 571.
    """
    pages = [
        ('https://en.wikipedia.org/wiki/S%26P/TSX_60', 'TSX'),
        ('https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index', 'TSX'),
        ('https://en.wikipedia.org/wiki/S%26P/TSX_Venture_Composite_Index', 'TSXV'),
    ]
    all_syms=[]
    for url, exchange in pages:
        try:
            html = _download_text(url, timeout=35)
            for table in pd.read_html(io.StringIO(html)):
                table = _flatten_columns(table)
                col = _find_symbol_column(table)
                if col is None:
                    continue
                syms = _symbols_from_dataframe(table[[col]].rename(columns={col:'Symbol'}), 'Canada', exchange)
                # Avoid tiny navigation tables. Index constituent pages should yield many rows.
                if len(syms) >= 5:
                    all_syms.extend(syms)
        except Exception:
            continue
    return sorted(set([s for s in all_syms if s and is_tradeable_symbol(s)]))


def _fetch_yahoo_canada_screener() -> list[str]:
    """Best-effort Canadian equity list from Yahoo screener endpoints.

    Uses the current POST screener API first, then older predefined GET
    endpoints as a fallback. Yahoo can rate-limit or change these APIs, so
    failure here never stops the app.
    """
    out=[]
    # Newer screener POST API.  Pull multiple pages so this can return hundreds
    # or thousands of symbols when Yahoo allows anonymous access.
    try:
        for offset in range(0, 5000, 250):
            body = {
                "offset": offset,
                "size": 250,
                "sortField": "intradaymarketcap",
                "sortType": "DESC",
                "quoteType": "EQUITY",
                "query": {
                    "operator": "AND",
                    "operands": [
                        {"operator": "eq", "operands": ["region", "ca"]},
                        {"operator": "eq", "operands": ["quoteType", "EQUITY"]},
                    ],
                },
                "userId": "",
                "userIdType": "guid",
            }
            data = _post_json("https://query2.finance.yahoo.com/v1/finance/screener", body, timeout=25)
            result = data.get('finance', {}).get('result', [])
            quotes = result[0].get('quotes', []) if result else []
            if not quotes:
                break
            for q in quotes:
                sym = str(q.get('symbol', '')).upper().strip()
                if not sym:
                    continue
                # Yahoo Canada symbols usually already include .TO/.V/.CN.
                if re.search(r"\.(TO|V|CN|NE)$", sym) and is_tradeable_symbol(sym):
                    out.append(sym)
            if len(quotes) < 250:
                break
    except Exception:
        pass

    # Older predefined endpoints.
    urls = [
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives_ca&count=250&start=0",
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives_ca&count=250&start=0",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers_ca&count=250&start=0",
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers_ca&count=250&start=0",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_losers_ca&count=250&start=0",
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_losers_ca&count=250&start=0",
    ]
    for url in urls:
        try:
            data = json.loads(_download_text(url, timeout=25))
            quotes = data.get('finance', {}).get('result', [{}])[0].get('quotes', [])
            for q in quotes:
                sym = str(q.get('symbol', '')).upper().strip()
                if sym and re.search(r"\.(TO|V|CN|NE)$", sym) and is_tradeable_symbol(sym):
                    out.append(sym)
        except Exception:
            continue
    return sorted(set(out))


def _fetch_stockanalysis_cse() -> list[str]:
    """Best-effort CSE symbol list from stockanalysis.com.

    The page is public HTML and usually contains the active CSE symbol table.
    Convert to Yahoo's .CN suffix.
    """
    try:
        html = _download_text('https://stockanalysis.com/list/canadian-securities-exchange/', timeout=35)
    except Exception:
        return []
    symbols=[]
    try:
        tables = pd.read_html(io.StringIO(html))
        for table in tables:
            table = _flatten_columns(table)
            col = _find_symbol_column(table)
            if col is None:
                continue
            for raw in table[col].dropna().astype(str):
                s = normalize_symbol(raw, 'Canada', 'CSE')
                if s and is_tradeable_symbol(s):
                    symbols.append(s)
    except Exception:
        # Regex fallback for simple table markup.
        for m in re.finditer(r'>([A-Z][A-Z0-9.-]{0,9})</a>', html):
            s = normalize_symbol(m.group(1), 'Canada', 'CSE')
            if s and is_tradeable_symbol(s):
                symbols.append(s)
    return sorted(set(symbols))

def _fetch_tmx_full_list() -> list[str]:
    """Best-effort full TSX/TSXV issuer list.

    Tries several TMX resource URLs.  Resource 571 is the current TSX/TSXV
    listed issuers file referenced from the Listed Company Directory.
    """
    urls = [
        'https://www.tsx.com/en/resource/571',
        'https://www.tsx.com/en/resource/571/',
        'https://tsx.com/en/resource/571',
        'https://tsx.com/en/resource/571/',
    ]
    best=[]
    errors=[]
    for url in urls:
        try:
            raw = _download_bytes(url, timeout=45)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue
        # Normal case: Excel workbook.
        try:
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, dtype=str, header=None)
            for table in sheets.values():
                syms = _parse_tmx_table(table)
                if len(syms) > len(best):
                    best = syms
        except Exception:
            pass
        # Try with inferred headers too.
        try:
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, dtype=str)
            for table in sheets.values():
                syms = _parse_tmx_table(table)
                if len(syms) > len(best):
                    best = syms
        except Exception:
            pass
        decoded = raw.decode('utf-8', errors='replace')
        try:
            syms = _parse_tmx_table(pd.read_csv(io.StringIO(decoded), dtype=str, header=None, on_bad_lines='skip'))
            if len(syms) > len(best):
                best = syms
        except Exception:
            pass
        try:
            for table in pd.read_html(io.StringIO(decoded)):
                syms = _parse_tmx_table(table)
                if len(syms) > len(best):
                    best = syms
        except Exception:
            pass
        if len(best) >= 2500:
            break
    best = sorted(set([s for s in best if s and is_tradeable_symbol(s)]))
    if best:
        return best
    # Last online fallback: index constituents.
    return _fetch_canada_wikipedia_index_lists()


def import_universe_file(path: str | Path, label: str | None = None, country: str = "Canada", exchange: str = "TSX") -> int:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    label = label or f"Imported - {path.stem}"
    suffix = path.suffix.lower()
    if suffix in {'.xlsx', '.xls'}:
        df = pd.read_excel(path)
    elif suffix in {'.txt', '.lst'}:
        text = path.read_text(encoding='utf-8', errors='replace')
        rows = [line.strip().split()[0] for line in text.splitlines() if line.strip()]
        df = pd.DataFrame({'Symbol': rows})
    else:
        df = pd.read_csv(path)
    symbols = _symbols_from_dataframe(df, country, exchange)
    cache = _read_cache()
    if cache.get('version') != CACHE_VERSION:
        cache = {'version': CACHE_VERSION, 'timestamp': time.time(), 'sources': {}, 'messages': []}
    cache.setdefault('sources', {})[label] = {'exchange': exchange, 'country': country, 'symbols': symbols, 'imported_from': str(path)}
    cache['timestamp'] = time.time()
    cache.setdefault('messages', []).append(f"Imported {label}: {len(symbols)} symbols")
    _write_cache(cache)
    return len(symbols)


def _split_canada_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    tsx = [s for s in symbols if s.endswith('.TO')]
    tsxv = [s for s in symbols if s.endswith('.V')]
    other = [s for s in symbols if not (s.endswith('.TO') or s.endswith('.V'))]
    return sorted(set(tsx + other)), sorted(set(tsxv))


def refresh_exchange_cache() -> dict:
    """Best-effort online update for US and Canadian exchange lists."""
    cache={'version': CACHE_VERSION, 'timestamp': time.time(), 'sources': {}, 'messages': []}
    try:
        us_sources = [
            ('US Exchange - NASDAQ Full', 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt', 'NASDAQ', None),
            ('US Exchange - NYSE/AMEX/Other Full', 'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt', 'NYSE/AMEX', None),
        ]
        etf_symbols = []
        for label, url, exchange, _ in us_sources:
            text = _download_text(url)
            df = pd.read_csv(io.StringIO(text), sep='|', dtype=str, on_bad_lines='skip')
            if 'Test Issue' in df.columns:
                df = df[df['Test Issue'].fillna('N').str.upper() != 'Y']
            if 'ETF' in df.columns:
                etf_df = df[df['ETF'].fillna('N').astype(str).str.upper() == 'Y']
                etf_symbols.extend(_symbols_from_dataframe(etf_df, 'US', exchange))
            syms = _symbols_from_dataframe(df, 'US', exchange)
            syms = [s for s in syms if s and not s.startswith('FILE') and s != 'N']
            cache['sources'][label]={'exchange': exchange, 'country': 'US', 'symbols': sorted(set(syms))}
            cache['messages'].append(f"{label}: {len(syms)} symbols")
        all_us = sorted(set(cache['sources'].get('US Exchange - NASDAQ Full',{}).get('symbols',[]) + cache['sources'].get('US Exchange - NYSE/AMEX/Other Full',{}).get('symbols',[])))
        cache['sources']['US Exchange - All US Listed Full']={'exchange':'US','country':'US','symbols':all_us}
        etf_symbols = sorted(set([s for s in etf_symbols if s and is_tradeable_symbol(s)]))
        if not etf_symbols:
            etf_symbols = list(US_AMEX)
        cache['sources']['US Exchange - ETFs Full']={'exchange':'ETF','country':'US','symbols':etf_symbols}
        cache['messages'].append(f"US Exchange - All US Listed Full: {len(all_us)} symbols")
        cache['messages'].append(f"US Exchange - ETFs Full: {len(etf_symbols)} symbols")
    except Exception as exc:
        cache['us_error']=str(exc)
        cache['messages'].append(f"US refresh failed, using starter fallback: {exc}")
    try:
        canada_errors=[]
        can_syms=[]
        try:
            can_syms.extend(_fetch_tmx_full_list())
        except Exception as exc:
            canada_errors.append(f"TMX: {exc}")
        try:
            can_syms.extend(_fetch_yahoo_canada_screener())
        except Exception as exc:
            canada_errors.append(f"Yahoo: {exc}")
        try:
            can_syms.extend(_fetch_canada_wikipedia_index_lists())
        except Exception as exc:
            canada_errors.append(f"Wikipedia: {exc}")
        try:
            can_syms.extend(_fetch_stockanalysis_cse())
        except Exception as exc:
            canada_errors.append(f"CSE: {exc}")
        can_syms = sorted(set([s for s in can_syms if s and is_tradeable_symbol(s)]))
        if can_syms:
            tsx, tsxv = _split_canada_symbols(can_syms)
            cse = sorted(set([s for s in can_syms if s.endswith('.CN')]))
            cache['sources']['Canada Exchange - TSX Full']={'exchange':'TSX','country':'Canada','symbols':tsx}
            cache['sources']['Canada Exchange - TSXV Full']={'exchange':'TSXV','country':'Canada','symbols':tsxv}
            cache['sources']['Canada Exchange - CSE Full']={'exchange':'CSE','country':'Canada','symbols':cse}
            cache['sources']['Canada Exchange - All Canada Full']={'exchange':'Canada','country':'Canada','symbols':can_syms}
            cache['messages'].append(f"Canada Exchange - All Canada Full: {len(can_syms)} symbols")
            # BUG-006E: keep Canada source warnings out of the Scanner tab.
            # The full details remain available through cache metadata/logs; the UI should not
            # show warning banners during normal scanning.
            if canada_errors:
                cache['messages'].append("Canada source warnings: " + " | ".join(canada_errors[:3]))
        else:
            raise RuntimeError('All online Canadian sources returned no symbols')
    except Exception as exc:
        cache['canada_error']=str(exc)
        cache['messages'].append("Canada offline fallback active")
        cache['sources']['Canada - TSX expanded fallback']={'exchange':'TSX','country':'Canada','symbols':CAN_TSX_EXPANDED}
        cache['sources']['Canada - TSXV expanded fallback']={'exchange':'TSXV','country':'Canada','symbols':CAN_TSXV_EXPANDED}
        cache['sources']['Canada - TSX + TSXV expanded fallback']={'exchange':'TSX/TSXV','country':'Canada','symbols':sorted(set(CAN_TSX_EXPANDED + CAN_TSXV_EXPANDED))}
    # Always write fallback starters if online source is absent, but do not make them the default when full exists.
    if not cache['sources']:
        for name, syms in DEFAULT_UNIVERSE.items():
            ex, country = _exchange_country(name)
            cache['sources'][name]={'exchange':ex,'country':country,'symbols':syms}
    _write_cache(cache)
    return cache


def _cache_valid(cache):
    return cache.get('version') == CACHE_VERSION and (time.time() - cache.get('timestamp', 0)) < CACHE_MAX_AGE_HOURS*3600


def available_universes(refresh: bool = False) -> Dict[str, List[str]]:
    cache=_read_cache()
    if refresh or not _cache_valid(cache):
        cache=refresh_exchange_cache()
    out={}
    # Prefer live/cache sources first.
    for name, rec in cache.get('sources', {}).items():
        out[name]=rec.get('symbols', [])
    # Add offline fallback choices only when no equivalent full list exists.
    has_us = any(name.startswith('US Exchange') for name in out)
    has_can = any(name.startswith('Canada Exchange') or name.startswith('Canada Index') for name in out)
    for k, v in DEFAULT_UNIVERSE.items():
        # Keep an ETF-only fallback available even when full US stock lists exist.
        # BUG-013: ETF must never mean "all exchanges".
        if k == 'US - ETFs starter fallback':
            out.setdefault(k, list(v))
            continue
        if k.startswith('US') and has_us:
            continue
        if k.startswith('Canada') and has_can:
            continue
        out.setdefault(k, list(v))
    # Sector / industry / ETF baskets, so the Scanner can target "Gold" or
    # "Technology" directly instead of looking up a sector per symbol.
    try:
        from tradelab.core.sectors import scanner_universes
        for name, symbols in scanner_universes().items():
            clean = [s for s in symbols if is_tradeable_symbol(s)]
            if clean:
                out.setdefault(name, sorted(set(clean)))
    except Exception:
        pass
    # User-created universes. This lets the user keep local custom lists even
    # when an exchange website blocks automatic refresh.
    try:
        custom_path = DATA_DIR / "custom_universes.json"
        custom = json.loads(custom_path.read_text(encoding="utf-8"))
        for name, symbols in custom.items():
            clean = [normalize_symbol(x, "US", "") if "." not in str(x) else str(x).strip().upper() for x in symbols]
            clean = [x for x in clean if is_tradeable_symbol(x)]
            out[f"My List - {name}"] = sorted(set(clean))
    except Exception:
        pass
    return out


def universe_metadata() -> dict:
    return _read_cache()


def list_symbols(exchanges: List[str] | None = None, countries: List[str] | None = None) -> List[UniverseSymbol]:
    sources = available_universes(refresh=False)
    selected = list(sources.keys()) if exchanges is None else list(exchanges)
    if exchanges is not None and not selected:
        return []
    out=[]
    for name in selected:
        syms=sources.get(name, [])
        ex,country=_exchange_country(name)
        if name.startswith('Sector - '):
            # Sector/industry baskets deliberately mix US and Canadian
            # listings (gold miners trade on both), so country - and the
            # country filter - has to be decided per symbol, not per list.
            for s in syms:
                is_can = str(s).upper().endswith(('.TO', '.V', '.CN', '.NE'))
                c = 'Canada' if is_can else 'US'
                if countries and c not in countries:
                    continue
                out.append(UniverseSymbol(s, s, 'TSX' if is_can else '', c))
            continue
        if name.startswith('US Exchange'):
            country='US'
        if name.startswith('Canada Exchange'):
            country='Canada'
            if 'CSE' in name:
                ex='CSE'
            elif 'TSXV' in name:
                ex='TSXV'
            elif 'TSX' in name:
                ex='TSX'
        if countries and country not in countries:
            continue
        for s in syms:
            out.append(UniverseSymbol(s, s, ex, country))
    if not out:
        for name, syms in DEFAULT_UNIVERSE.items():
            ex,country=_exchange_country(name)
            if countries and country not in countries:
                continue
            for s in syms:
                out.append(UniverseSymbol(s, s, ex, country))
    return _dedup(out)

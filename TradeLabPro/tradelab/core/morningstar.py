"""Read a Morningstar screener export (Qt-free, offline-testable).

Morningstar has no free API, so the user exports a screener view from their
subscription (Excel or CSV) and TradeLab reads it: the ratings and fees
Morningstar has, beside the facts the candidate check measures itself.

The export follows the site's language - French headers and numbers
("9,92 $ US", "350,12 M $", "19 oct. 2018") or English ones - so both are
read. The symbol column is required: without it a fund cannot be priced, and
a fund's name is not unique (one fund has several series).

The xlsx is read with the standard library (it is a zip of XML), so no extra
package goes into the executable.
"""
from __future__ import annotations

import csv
import re
import unicodedata
import zipfile
from datetime import date
from xml.etree import ElementTree

# Field -> header words that name it, accents dropped and lowercased. The
# first header containing all the words of an entry wins.
HEADERS = {
    "name": [("nom",), ("name",)],
    "symbol": [("symbole",), ("symbol",), ("ticker",)],
    "price": [("dernier", "prix"), ("last", "price"), ("price",), ("prix",)],
    "yield12": [("rendement", "12"), ("yield",)],
    "category": [("categorie",), ("category",)],
    "medalist": [("medaill",), ("medalist",)],
    "stars": [("cote", "morningstar"), ("star",), ("morningstar", "rating")],
    "esg": [("esg",)],
    "size": [("taille",), ("size",), ("net", "assets")],
    "mer": [("frais",), ("expense",), ("mer",)],
    "inception": [("creation",), ("inception",)],
}

# Morningstar's medalist ratings, best first; the French site writes them in
# English too, but a French label is accepted.
MEDALS = {"gold": 5, "or": 5, "silver": 4, "argent": 4, "bronze": 3,
          "neutral": 2, "neutre": 2, "negative": 1, "negatif": 1}
MEDAL_NAMES = {5: "Gold", 4: "Silver", 3: "Bronze", 2: "Neutral", 1: "Negative"}

MONTHS = {"janv": 1, "jan": 1, "fevr": 2, "fev": 2, "feb": 2, "mars": 3, "mar": 3,
          "avr": 4, "apr": 4, "mai": 5, "may": 5, "juin": 6, "jun": 6, "juil": 7,
          "jul": 7, "aout": 8, "aug": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11,
          "dec": 12}

SCALE = {"k": 1e3, "m": 1e6, "mil": 1e6, "g": 1e9, "md": 1e9, "b": 1e9, "bil": 1e9,
         "t": 1e12, "bn": 1e9}


def _plain(text) -> str:
    """Lowercase, accents dropped, spaces of any kind made plain."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def number(text):
    """A number written either way - "1 234,56", "1,234.56", "0,03" - or None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = re.sub(r"[^\d,.\-]", "", str(text).replace("−", "-"))
    if not s or s in "-.,":
        return None
    if "," in s and "." in s:
        # The last one is the decimal mark.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def money(text):
    """(amount, currency) from "9,92 $ US", "350,12 M $", "1,12 G $ US",
    "$1.2 Bil" - currency "USD" when US is marked, else "CAD"."""
    if text is None or str(text).strip() == "":
        return None, None
    if isinstance(text, (int, float)):
        return float(text), None
    raw = _plain(text)
    digits = re.search(r"-?\d[\d\s.,]*", raw)
    amount = number(digits.group(0)) if digits else None
    if amount is None:
        return None, None
    words = re.findall(r"[a-z]+", raw)
    for w in words:
        if w in SCALE:
            amount *= SCALE[w]
            break
    currency = "USD" if ("us" in words or "usd" in words or "us$" in raw) else "CAD"
    return amount, currency


def when(text):
    """A date from "19 oct. 2018", "Oct 19, 2018", "2018-10-19" - or None."""
    if text is None or str(text).strip() == "":
        return None
    if isinstance(text, date):
        return text
    s = _plain(text)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    day = re.search(r"\b(\d{1,2})\b", s)
    year = re.search(r"\b(\d{4})\b", s)
    month = next((n for word in re.findall(r"[a-z]+", s) for k, n in MONTHS.items()
                  if word.startswith(k)), None)
    if day and year and month:
        try:
            return date(int(year[1]), month, int(day[1]))
        except ValueError:
            return None
    return None


def yahoo_symbol(symbol: str, currency: str | None) -> str:
    """Morningstar's ticker as Yahoo writes it: a Canadian listing (priced in
    CAD) gets .TO, and a class suffix uses a dash (ZSP.U -> ZSP-U.TO)."""
    s = str(symbol or "").strip().upper()
    if not s:
        return s
    if s.endswith((".TO", ".V", ".NE", ".CN")):
        return s
    s = s.replace(".", "-")
    return s + ".TO" if currency == "CAD" else s


def _columns(header: list) -> dict:
    """{field: column index} for the fields the header has."""
    plain = [_plain(h) for h in header]
    out = {}
    for field, choices in HEADERS.items():
        for words in choices:
            idx = next((i for i, h in enumerate(plain)
                        if i not in out.values() and all(w in h for w in words)), None)
            if idx is not None:
                out[field] = idx
                break
    return out


def _xlsx_rows(path) -> list:
    """The first sheet's cells as lists of text/numbers - standard library only."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet = next((n for n in sorted(z.namelist())
                      if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")), None)
        if sheet is None:
            raise ValueError("No sheet in this Excel file.")
        root = ElementTree.fromstring(z.read(sheet))
    rows = []
    for row in root.iter(f"{{{ns['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", ns):
            ref = re.match(r"[A-Z]+", c.get("r", "")).group(0) if c.get("r") else None
            col = 0
            for ch in ref or "":
                col = col * 26 + ord(ch) - 64
            col = (col - 1) if ref else len(cells)
            kind = c.get("t")
            v = c.find("m:v", ns)
            if kind == "s" and v is not None:
                value = shared[int(v.text)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
            elif v is None:
                value = None
            elif kind in ("str", "e"):
                value = v.text
            elif kind == "b":
                value = v.text == "1"
            else:
                value = number(v.text)
            cells[col] = value
        if cells:
            rows.append([cells.get(i) for i in range(max(cells) + 1)])
    return rows


def _csv_rows(path) -> list:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [row for row in csv.reader(fh, dialect)]


def read_export(path) -> list:
    """The funds in a Morningstar export, as dicts: name, symbol, yahoo,
    currency, price, yield12 / mer (fractions), category, medalist, medal_rank,
    stars, esg, size, inception - None where the export has no figure.
    "Rendement sur 12 mois" is the 12-month yield, not a return.
    Raises ValueError when it is not a Morningstar export TradeLab can use."""
    p = str(path)
    rows = _xlsx_rows(p) if p.lower().endswith((".xlsx", ".xlsm")) else _csv_rows(p)
    start = next((i for i, r in enumerate(rows[:10]) if "symbol" in _columns(r)), None)
    if start is None:
        raise ValueError("No symbol column in this file. In Morningstar's screener, add the "
                         "Ticker (Symbole) column to the view, then export again.")
    cols = _columns(rows[start])
    out, seen = [], set()

    def cell(row, field):
        i = cols.get(field)
        v = row[i] if i is not None and i < len(row) else None
        return None if v is None or str(v).strip() in ("", "-", "--", "—") else v

    for row in rows[start + 1:]:
        symbol = str(cell(row, "symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        price, currency = money(cell(row, "price"))
        size, size_currency = money(cell(row, "size"))
        medal = _plain(cell(row, "medalist"))
        rank = MEDALS.get(medal)
        stars = number(cell(row, "stars"))
        esg = number(cell(row, "esg"))
        yield12, mer = number(cell(row, "yield12")), number(cell(row, "mer"))
        out.append({
            "name": str(cell(row, "name") or symbol).strip(), "symbol": symbol,
            "yahoo": yahoo_symbol(symbol, currency), "currency": currency, "price": price,
            "yield12": None if yield12 is None else yield12 / 100.0,
            "category": str(cell(row, "category") or "").strip(),
            "medalist": MEDAL_NAMES.get(rank, ""), "medal_rank": rank,
            "stars": int(stars) if stars else None, "esg": int(esg) if esg else None,
            "size": size, "size_currency": size_currency,
            "mer": None if mer is None else mer / 100.0,
            "inception": when(cell(row, "inception"))})
    if not out:
        raise ValueError("The file has a symbol column but no funds in it.")
    return out


# Categories that are not for a safe, low-effort REER/CELI: leveraged,
# inverse and other trading products, and crypto.
SPECULATIVE = ("trading", "leveraged", "inverse", "digital asset", "crypto")


def is_speculative(row: dict) -> bool:
    text = _plain(row.get("category")) + " " + _plain(row.get("name"))
    return any(w in text for w in SPECULATIVE) or bool(re.search(r"\b-?\d(\.\d)?x\b", text))


def pick(rows: list, *, hide_speculative=True, min_stars=0, max_mer=None) -> list:
    """The rows left after the filters - an unknown star rating or fee never
    passes a filter that asks for one."""
    out = []
    for r in rows:
        if hide_speculative and is_speculative(r):
            continue
        if min_stars and (r.get("stars") or 0) < min_stars:
            continue
        if max_mer is not None and (r.get("mer") is None or r["mer"] > max_mer):
            continue
        out.append(r)
    return out


def by_symbol(rows: list) -> dict:
    """{Yahoo symbol and Morningstar symbol: row} - to find a shortlist's ratings."""
    out = {}
    for r in rows:
        out.setdefault(r["yahoo"], r)
        out.setdefault(r["symbol"], r)
    return out

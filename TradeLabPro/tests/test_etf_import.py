"""Tests for tools/import_etf_screener.py — the one-off Excel import.

The workbook itself is personal data and is not in the repo, so the mapping is
tested against a synthetic sheet built here with the same layout. The real
file, when it is present locally, gets a smoke test rather than assertions
about its contents.
"""
import sys
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.import_etf_screener import (  # noqa: E402
    COLUMN_MAP, DEFAULT_WORKBOOK, HEADER_ROW, read_rows,
)
from tradelab.data.database import Database  # noqa: E402

HEADERS = ["Ticker", "Nom", "Catégorie", "Bourse", "Devise", "Région",
           "% Can", "% US", "% Intl", "% Obl.", "% Or/Alt", "Risque", "MER",
           "Rend 1M", "Rend 3M", "Rend 6M", "Rend 1A", "Rend 3A", "Rend 5A",
           "Rend 10A", "Volatilité (ann.)", "Pire baisse", "Sharpe", "Reco ★",
           "Spéculatif ★", "Ma compo ✏️", "Notes",
           "Compte suggéré (REER/CELI)", "Yahoo"]


@pytest.fixture
def sheet():
    """A two-fund sheet laid out like the real workbook: five lines of
    preamble, headers on row 7, funds from row 8."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portefeuille"
    for c, label in enumerate(HEADERS, start=1):
        ws.cell(HEADER_ROW, c, label)
    rows = [
        ["VFV", "Vanguard S&P 500", "S&P 500", "TSX", "CAD", "États-Unis",
         0, 1, 0, 0, 0, 4, 0.0009, None, None, None, 0.25, None, None, 0.159,
         None, None, None, 0.2, 0.2, 0.2, "Cœur US.", "CELI", "VFV.TO"],
        ["VAB", "Vanguard Oblig Canada", "Obligations", "TSX", "CAD", "Obligations",
         0, 0, 0, 1, 0, 1, 0.0009, None, None, None, 0.04, None, None, 0.02,
         None, None, None, 0.28, 0.14, 0.28, "Amortisseur.", "REER", "VAB.TO"],
    ]
    for r, values in enumerate(rows, start=HEADER_ROW + 1):
        for c, value in enumerate(values, start=1):
            if value is not None:
                ws.cell(r, c, value)
    return ws


def test_reads_one_dict_per_fund(sheet):
    funds = read_rows(sheet)
    assert [f["ticker"] for f in funds] == ["VFV", "VAB"]


def test_maps_headers_onto_database_columns(sheet):
    vfv = read_rows(sheet)[0]
    assert vfv["name"] == "Vanguard S&P 500"
    assert vfv["pct_us"] == 1
    assert vfv["mer"] == pytest.approx(0.0009)
    assert vfv["ret_1a"] == pytest.approx(0.25)
    assert vfv["my_mix"] == pytest.approx(0.2)
    assert vfv["yahoo"] == "VFV.TO"


def test_french_workbook_text_is_imported_in_english(sheet):
    """The tab is English; the workbook is French. Translating on the way in
    beats an English table full of French cells."""
    vfv, vab = read_rows(sheet)
    assert vfv["region"] == "United States"
    assert vfv["category"] == "S&P 500"          # already language-neutral
    assert vfv["suggested_account"] == "TFSA"
    assert vfv["notes"] == "US core. Unhedged (currency)."
    assert vab["region"] == "Bonds"
    assert vab["suggested_account"] == "RRSP"


def test_unknown_text_is_left_alone_rather_than_guessed(sheet):
    sheet.cell(HEADER_ROW + 1, 3, "Une catégorie inventée")
    sheet.cell(HEADER_ROW + 1, 1, "ZZZZ")        # no note translation for it
    fund = read_rows(sheet)[0]
    assert fund["category"] == "Une catégorie inventée"
    assert fund["notes"] == "Cœur US."           # left verbatim, not blanked


def test_blank_cells_are_omitted_not_zeroed(sheet):
    vfv = read_rows(sheet)[0]
    # The workbook leaves 3A/5A empty for funds it never computed them for.
    assert "ret_3a" not in vfv
    assert "volatility" not in vfv


def test_stops_at_the_first_empty_ticker(sheet):
    # Row 40 of the real workbook starts a totals block; the reader must have
    # stopped long before reaching it.
    sheet.cell(40, 1, "RÉSULTATS DE LA COMPOSITION")
    assert len(read_rows(sheet)) == 2


def test_missing_ticker_column_is_an_error():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(HEADER_ROW, 1, "Nom")
    with pytest.raises(SystemExit):
        read_rows(ws)


def test_every_mapped_column_exists_in_the_table():
    for db_col in COLUMN_MAP.values():
        assert db_col in Database.ETF_COLUMNS


def test_import_is_idempotent(sheet, tmp_db_path):
    db = Database(path=tmp_db_path)
    for _ in range(2):
        for fund in read_rows(sheet):
            db.etf_upsert(fund.pop("ticker"), **fund)
    assert [f["ticker"] for f in db.etf_list()] == ["VAB", "VFV"]
    assert db.etf_get("VFV")["my_mix"] == pytest.approx(0.2)


@pytest.mark.skipif(not DEFAULT_WORKBOOK.exists(),
                    reason="Portefeuille_FNB.xlsx is personal data, not in the repo")
def test_the_real_workbook_still_parses():
    wb = openpyxl.load_workbook(DEFAULT_WORKBOOK, data_only=True)
    ws = wb["Portefeuille"] if "Portefeuille" in wb.sheetnames else wb.active
    funds = read_rows(ws)
    assert funds, "the workbook should contain at least one fund"
    assert all(f["ticker"] and f.get("yahoo") for f in funds)

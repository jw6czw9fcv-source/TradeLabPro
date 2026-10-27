"""The Morningstar export reader and its place in the AI Assist shortlist.
Made-up funds only."""
import zipfile
from datetime import date
from xml.sax.saxutils import escape

import pytest

from tradelab.core import candidate as cd
from tradelab.core import morningstar as ms

FR_HEADER = ["Nom", "Symbole", "Dernier prix", "Rendement sur 12 mois", "Catégorie Morningstar",
             "Cote de médaillé (Globale)", "Cote Morningstar pour les fonds (Globale)",
             "Cote de risque ESG du portefeuille", "Taille du fonds (devise de base)",
             "Ratio des frais de gestion", "Date de création"]
NB = " "
FR_ROWS = [
    ["Alpha Global Equity ETF", "AAAA", f"25,10{NB}${NB}US", "1,52", "Global Large-Stock Blend",
     "Silver", "4", "3", f"1,12{NB}G{NB}${NB}US", "0,09", "19 oct. 2018"],
    ["Beta Canadian Index ETF", "BBBB", f"31,40{NB}$", 0, "Canadian Equity", "Gold", "5", "2",
     f"276{NB}670,00{NB}$", "0,20", "3 déc. 2025"],
    ["Gamma 2x Long Widget ETF", "GGGG", f"12,00{NB}${NB}US", None, "Trading—Leveraged Equity",
     None, None, None, f"4,27{NB}M{NB}${NB}US", None, "29 avr. 2026"],
    ["Delta Units", "DD.U", f"10,00{NB}$", "2,00", "Canadian Fixed Income", "Neutral", "3", None,
     f"50,00{NB}M{NB}$", "0,55", "2 mai 2023"],
    ["Alpha Global Equity ETF (dup)", "AAAA", "1", None, "", None, None, None, None, None, None],
]


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path, rows):
    """A minimal Excel file: text in shared strings, numbers as numbers."""
    strings, sheet_rows = [], []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{_col(c)}{r}"
            if v is None:
                continue
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                strings.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<worksheet xmlns="{main}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{main}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
                   + "</sst>")


@pytest.fixture
def fr_export(tmp_path):
    path = tmp_path / "sanstitre.xlsx"
    write_xlsx(path, [FR_HEADER] + FR_ROWS)
    return path


def test_reads_a_french_export(fr_export):
    rows = ms.read_export(fr_export)
    assert [r["symbol"] for r in rows] == ["AAAA", "BBBB", "GGGG", "DD.U"]   # duplicate dropped
    a, b, _g, d = rows
    assert a["yahoo"] == "AAAA" and a["currency"] == "USD" and a["price"] == pytest.approx(25.10)
    assert a["mer"] == pytest.approx(0.0009) and a["yield12"] == pytest.approx(0.0152)
    assert a["stars"] == 4 and a["medalist"] == "Silver" and a["medal_rank"] == 4
    assert a["size"] == pytest.approx(1.12e9) and a["inception"] == date(2018, 10, 19)
    assert b["yahoo"] == "BBBB.TO" and b["currency"] == "CAD"
    assert b["size"] == pytest.approx(276670.0) and b["inception"] == date(2025, 12, 3)
    assert b["yield12"] == 0.0
    assert d["yahoo"] == "DD-U.TO"


def test_reads_an_english_csv(tmp_path):
    path = tmp_path / "export.csv"
    path.write_text("Name,Ticker,Last Price,12 Month Yield,Morningstar Category,"
                    "Medalist Rating,Morningstar Rating,Expense Ratio,Inception Date\n"
                    'Epsilon ETF,EEEE,"$1,234.50",2.5,US Large Blend,Bronze,3,0.03,"Oct 19, 2018"\n',
                    encoding="utf-8")
    (row,) = ms.read_export(path)
    assert row["symbol"] == "EEEE" and row["price"] == pytest.approx(1234.5)
    assert row["mer"] == pytest.approx(0.0003) and row["medalist"] == "Bronze"
    assert row["inception"] == date(2018, 10, 19)


def test_an_export_without_symbols_says_how_to_fix_it(tmp_path):
    path = tmp_path / "noticker.xlsx"
    write_xlsx(path, [[h for h in FR_HEADER if h != "Symbole"], ["Alpha", "1"]])
    with pytest.raises(ValueError, match="Ticker"):
        ms.read_export(path)


def test_filters(fr_export):
    rows = ms.read_export(fr_export)
    assert [r["symbol"] for r in ms.pick(rows)] == ["AAAA", "BBBB", "DD.U"]   # 2x hidden
    assert len(ms.pick(rows, hide_speculative=False)) == 4
    assert [r["symbol"] for r in ms.pick(rows, min_stars=4)] == ["AAAA", "BBBB"]
    assert [r["symbol"] for r in ms.pick(rows, max_mer=0.005)] == ["AAAA", "BBBB"]
    assert ms.by_symbol(rows)["BBBB.TO"]["symbol"] == "BBBB"


def test_shortlist_orders_and_explains_by_ratings():
    rows = [{"symbol": "A", "stars": 3, "medal_rank": 5, "medalist": "Gold"},
            {"symbol": "B", "stars": 5, "medal_rank": None, "medalist": ""},
            {"symbol": "C", "stars": None, "medal_rank": 4, "medalist": "Silver"}]
    assert [r["symbol"] for r in cd.rank(rows, "Most Morningstar stars")] == ["B", "A", "C"]
    assert [r["symbol"] for r in cd.rank(rows, "Best medalist rating")] == ["A", "C", "B"]
    assert cd.morningstar_text(rows[0]) == "3 stars, Gold"
    assert cd.morningstar_text({"stars": None, "medalist": ""}) == ""


def test_panel_imports_filters_and_feeds_the_shortlist(fr_export, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from tradelab.ui import app as app_mod
    QApplication.instance() or QApplication([])
    panel = app_mod.AIAssistantPanel(None)
    panel._settings.remove(panel.MS_KEY)
    panel.morningstar = []
    panel.import_morningstar(str(fr_export))
    assert panel.ms_table.rowCount() == 3                 # the 2x fund hidden
    panel.ms_hide.setChecked(False)
    assert panel.ms_table.rowCount() == 4
    panel.ms_stars.setCurrentIndex(3)                     # 5 stars
    assert panel.ms_table.rowCount() == 1 and panel.ms_table.item(0, 0).text() == "BBBB.TO"

    # Saved: a new panel shows the same import.
    again = app_mod.AIAssistantPanel(None)
    assert len(again.morningstar) == 4

    checked = []
    monkeypatch.setattr(panel, "check_shortlist", lambda: checked.append(panel.shortlist_symbols.text()))
    panel.shortlist_symbols.setText("XEQT.TO")
    panel.ms_table.selectRow(0)
    panel.add_morningstar_selection()
    assert checked == ["XEQT.TO BBBB.TO"]

    # The shortlist's rows carry the rating and Morningstar's fee.
    monkeypatch.setattr(app_mod, "flag_problem", lambda *a, **k: None)
    panel._on_shortlist({"BBBB.TO": {"prices": None, "meta": {"name": "Beta", "quote_type": "ETF"}}}, [])
    row = panel.shortlist[0]
    assert row["stars"] == 5 and row["medalist"] == "Gold"
    assert row["mer"] == pytest.approx(0.002) and row["mer_source"] == "Morningstar"
    assert panel.shortlist_table.item(0, 10).text() == "5 stars, Gold"
    assert "5 stars, Gold" in cd.table_text(panel.shortlist)
    panel._settings.remove(panel.MS_KEY)

"""Headless smoke tests for the Links panel."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp, tmp_path):
    from tradelab.ui.app import LinksPanel
    from tradelab.core.links import LinkStore
    return LinksPanel(store=LinkStore(tmp_path / "links.json"))


def test_panel_constructs(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    texts = " ".join(lbl.text() for lbl in panel.findChildren(QLabel))
    assert "browser" in texts.lower()


def test_add_link_normalizes_and_shows(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.f_name.setText("Finviz Map")
    panel.f_url.setText("finviz.com/map.ashx")
    panel.f_group.setText("Screeners")
    panel.save()
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == "Finviz Map"
    assert panel.table.item(0, 1).text() == "https://finviz.com/map.ashx"   # scheme added
    assert len(panel.store.all()) == 1
    # Form was cleared and reset to add-mode.
    assert panel.f_name.text() == "" and panel.save_btn.text() == "Add"


def test_add_requires_name_and_url(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.f_name.setText("NoUrl"); panel.f_url.setText("")
    panel.save()
    assert panel.table.rowCount() == 0


def test_selecting_a_row_loads_edit_mode(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.f_name.setText("Yahoo"); panel.f_url.setText("finance.yahoo.com"); panel.save()
    panel.table.selectRow(0)
    assert panel._editing_id is not None
    assert panel.save_btn.text() == "Save changes"
    assert panel.f_url.text() == "https://finance.yahoo.com"
    # Editing updates instead of adding a duplicate.
    panel.f_name.setText("Yahoo Finance"); panel.save()
    assert panel.table.rowCount() == 1
    assert panel.store.all()[0].name == "Yahoo Finance"


def test_double_click_opens_in_browser(qapp, tmp_path, monkeypatch):
    from tradelab.ui import app as appmod
    opened = {}
    monkeypatch.setattr(appmod.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.update(u=url.toString()) or True))
    panel = _panel(qapp, tmp_path)
    panel.f_name.setText("Finviz"); panel.f_url.setText("finviz.com"); panel.save()
    panel._open_row(0, 0)
    assert opened["u"] == "https://finviz.com"


def test_remove_selected(qapp, tmp_path):
    panel = _panel(qapp, tmp_path)
    panel.f_name.setText("A"); panel.f_url.setText("a.com"); panel.save()
    panel.table.selectRow(0)
    panel.remove_selected()
    assert panel.table.rowCount() == 0 and panel.store.all() == []

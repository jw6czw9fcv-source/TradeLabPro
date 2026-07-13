"""UI-level tests for the Phase 5 no-code Strategy Builder panel."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def builder(qapp, tmp_path, monkeypatch):
    # Point strategy persistence at a tmp dir so tests never touch real data/.
    monkeypatch.setattr("tradelab.core.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("tradelab.strategies.custom.DATA_DIR", tmp_path)
    import tradelab.ui.app as app
    changed = {"n": 0}
    panel = app.StrategyBuilderPanel(on_strategies_changed=lambda: changed.__setitem__("n", changed["n"] + 1))
    panel._changed = changed
    return panel


def test_builder_starts_with_example_conditions(builder):
    assert len(builder.buy_conditions.get_conditions()) == 1
    assert len(builder.sell_conditions.get_conditions()) == 1
    assert "BUY when ALL of" in builder.preview.toPlainText()


def test_add_and_remove_buy_condition(builder):
    builder.buy_conditions.add_row()
    assert len(builder.buy_conditions.get_conditions()) == 2
    first = builder.buy_conditions._rows[0]["row"]
    builder.buy_conditions.remove_row(first)
    assert len(builder.buy_conditions.get_conditions()) == 1


def test_save_then_load_round_trips_conditions(builder):
    from tradelab.core.filters import FilterCondition
    builder.name.setEditText("Test Strat")
    builder.buy_conditions.set_conditions([FilterCondition(field="rsi14", operator="Below", value1=25)])
    builder.sell_conditions.set_conditions([FilterCondition(field="rsi14", operator="Above", value1=75)])
    builder.save_strategy()
    assert builder._changed["n"] == 1  # callback fired to refresh dropdowns

    # Wipe the editor, then load it back.
    builder.new_strategy()
    builder.load_strategy("Test Strat")
    buys = builder.buy_conditions.get_conditions()
    assert buys[0].field == "rsi" and buys[0].period == 14 and buys[0].value1 == 25


def test_save_requires_a_buy_condition(builder, monkeypatch):
    warned = {"n": 0}
    monkeypatch.setattr("tradelab.ui.app.QMessageBox.warning", lambda *a, **k: warned.__setitem__("n", 1))
    builder.buy_conditions.set_conditions([])
    builder.save_strategy()
    assert warned["n"] == 1  # blocked with a warning
    assert builder._changed["n"] == 0  # nothing saved


def test_delete_strategy(builder):
    from tradelab.core.filters import FilterCondition
    builder.name.setEditText("To Delete")
    builder.buy_conditions.set_conditions([FilterCondition(field="rsi14", operator="Below", value1=30)])
    builder.save_strategy()
    from tradelab.strategies.custom import list_custom_strategies
    assert "To Delete" in list_custom_strategies()

    builder.delete_strategy()
    assert "To Delete" not in list_custom_strategies()


def test_saved_strategy_appears_in_registry_choices(builder):
    from tradelab.core.filters import FilterCondition
    builder.name.setEditText("Registry Strat")
    builder.buy_conditions.set_conditions([FilterCondition(field="macd_hist", operator="Above", value1=0)])
    builder.save_strategy()

    from tradelab.strategies import strategy_choices, strategy_module
    choices = dict(strategy_choices())
    assert "custom:Registry Strat" in choices
    strat = strategy_module("custom:Registry Strat")
    assert strat.name == "Registry Strat"


def test_preview_updates_with_conditions(builder):
    from tradelab.core.filters import FilterCondition
    builder.buy_conditions.set_conditions([FilterCondition(field="adx14", operator="Above", value1=25)])
    builder.update_preview()
    assert "ADX" in builder.preview.toPlainText()


def test_field_vs_field_condition_round_trips_through_widget(builder):
    from tradelab.core.filters import FilterCondition
    cond = FilterCondition(field="ema", period=9, operator="Above field", field2="ema", period2=30)
    builder.buy_conditions.set_conditions([cond])
    out = builder.buy_conditions.get_conditions()
    assert out[0].operator == "Above field"
    assert out[0].field == "ema" and out[0].period == 9
    assert out[0].field2 == "ema" and out[0].period2 == 30
    # Preview reads the crossover naturally, with the real periods.
    builder.update_preview()
    assert "EMA 9 above EMA 30" in builder.preview.toPlainText()


def test_indicator_period_is_editable_inline(builder):
    from tradelab.core.filters import FilterCondition
    # Load an RSI condition and change its period to 7 via the row's spinbox.
    builder.buy_conditions.set_conditions([FilterCondition(field="rsi", period=14, operator="Below", value1=30)])
    w = builder.buy_conditions._rows[0]
    assert w["period"].value() == 14  # default period pre-filled
    w["period"].setValue(7)
    out = builder.buy_conditions.get_conditions()
    assert out[0].field == "rsi" and out[0].period == 7


def test_period_spinbox_hidden_for_fields_without_a_period(builder):
    from tradelab.core.filters import FilterCondition
    # VWAP has no tunable period -> its period spinbox is hidden.
    builder.buy_conditions.set_conditions([FilterCondition(field="vwap", operator="Above", value1=0)])
    w = builder.buy_conditions._rows[0]
    assert w["period"].isHidden()

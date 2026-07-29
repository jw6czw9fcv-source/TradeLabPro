"""Tests for the Phase 6 plugin SDK (auto-discovery + field registration)."""
import pandas as pd
import pytest

from tradelab.core import filters, plugins


@pytest.fixture(autouse=True)
def _clean_plugin_fields():
    # Each test starts and ends with no plugin fields leaking into FIELD_SPECS.
    plugins.discover_plugins("/nonexistent-dir-xyz")
    yield
    plugins.discover_plugins("/nonexistent-dir-xyz")


def _write(dir_, name, body):
    (dir_ / name).write_text(body, encoding="utf-8")


def test_discovers_a_valid_plugin(tmp_path):
    _write(tmp_path, "my_ind.py",
           "PLUGIN_NAME = 'My Ind'\ndef compute(df):\n    return df['Close'] * 2\n")
    result = plugins.discover_plugins(tmp_path)
    assert "My Ind" in result["loaded"]
    assert result["errors"] == {}


def test_valid_plugin_becomes_a_field(tmp_path):
    _write(tmp_path, "dbl.py",
           "PLUGIN_NAME = 'Double Close'\ndef compute(df):\n    return df['Close'] * 2\n")
    plugins.discover_plugins(tmp_path)
    assert "plugin:Double Close" in filters.FIELD_SPECS
    labels = dict(filters.field_choices())
    assert labels["plugin:Double Close"] == "Double Close (plugin)"


def test_plugin_field_evaluates_in_a_condition(tmp_path):
    _write(tmp_path, "dbl.py",
           "PLUGIN_NAME = 'Double Close'\ndef compute(df):\n    return df['Close'] * 2\n")
    plugins.discover_plugins(tmp_path)
    from tradelab.core.filters import FilterCondition, ensure_columns, evaluate_condition
    from tradelab.core.config import ScannerConfig

    df = pd.DataFrame({"Open": [10], "High": [11], "Low": [9], "Close": [10.0], "Volume": [100]})
    cond = FilterCondition(field="plugin:Double Close", operator="Above", value1=15)
    ensure_columns(df, [cond])
    assert df["PLUGIN_DOUBLE_CLOSE"].iloc[0] == 20.0
    assert evaluate_condition(df.iloc[0], ScannerConfig(), cond) is True  # 20 > 15


def test_plugin_missing_name_or_compute_is_an_error(tmp_path):
    _write(tmp_path, "bad.py", "X = 1\n")  # no PLUGIN_NAME, no compute
    result = plugins.discover_plugins(tmp_path)
    assert "bad.py" in result["errors"]
    assert result["loaded"] == []


def test_plugin_with_import_error_is_recorded_not_raised(tmp_path):
    _write(tmp_path, "boom.py", "import a_module_that_does_not_exist\nPLUGIN_NAME='X'\n")
    result = plugins.discover_plugins(tmp_path)  # must not raise
    assert "boom.py" in result["errors"]


def test_rediscovery_replaces_old_plugin_fields(tmp_path):
    _write(tmp_path, "a.py", "PLUGIN_NAME='A'\ndef compute(df):\n    return df['Close']\n")
    plugins.discover_plugins(tmp_path)
    assert "plugin:A" in filters.FIELD_SPECS

    (tmp_path / "a.py").unlink()
    _write(tmp_path, "b.py", "PLUGIN_NAME='B'\ndef compute(df):\n    return df['Close']\n")
    plugins.discover_plugins(tmp_path)
    assert "plugin:A" not in filters.FIELD_SPECS  # stale field removed
    assert "plugin:B" in filters.FIELD_SPECS


def test_missing_directory_is_safe(tmp_path):
    result = plugins.discover_plugins(tmp_path / "does-not-exist")
    assert result == {"loaded": [], "errors": {}}


def test_bundled_sample_plugin_loads():
    # The sample plugin shipped in plugins/ should load cleanly.
    from tradelab.core.config import ROOT_DIR
    result = plugins.discover_plugins(ROOT_DIR / "plugins")
    assert "High-Low Range %" in result["loaded"]


def test_plugin_panel_lists_loaded_and_errored_plugins(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    _write(tmp_path, "good.py", "PLUGIN_NAME='Good One'\ndef compute(df):\n    return df['Close']\n")
    _write(tmp_path, "bad.py", "X=1\n")
    monkeypatch.setattr(plugins, "PLUGINS_DIR", tmp_path)

    import tradelab.ui.app as app
    panel = app.PluginPanel()
    text = panel.text.toPlainText()
    assert "Good One" in text
    assert "bad.py" in text  # error shown

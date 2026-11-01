"""A restart starts a separate TradeLab, not a child of the old one: the
one-file .exe's markers are dropped and PyInstaller told to start fresh. With
them inherited, a restart in 2.70.0 relaunched itself in a loop."""
import pytest

pytest.importorskip("PySide6")


def test_the_restart_environment_is_a_fresh_one(monkeypatch):
    from tradelab.ui.panels import settings as s
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI123")
    monkeypatch.setenv("_MEIPASS2", r"C:\Temp\_MEI123")
    monkeypatch.setenv(s.SELFTEST_RESTART_ENV, "1")
    monkeypatch.setenv("PATH_KEEP_ME", "yes")
    env = s.restart_environment()
    keys = set(env.keys())
    assert env.value("PYINSTALLER_RESET_ENVIRONMENT") == "1"
    assert not any(k.startswith("_PYI_") for k in keys)
    assert "_MEIPASS2" not in keys and s.SELFTEST_RESTART_ENV not in keys
    assert env.value("PATH_KEEP_ME") == "yes"

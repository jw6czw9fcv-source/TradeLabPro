"""The test suite must not write into the app's real log.

Importing tradelab.ui.app configures logging as a side effect, and one test
deliberately raises to prove startup survives a broken panel. Left alone, a run
would leave fake tracebacks in logs/tradelab.log — the file you open when
something has genuinely gone wrong. Same principle as tests never touching the
real data/tradelab.db.
"""
import os
from pathlib import Path

from tradelab.core import logging_config


def test_logging_is_redirected_away_from_the_real_log():
    real = Path(logging_config.LOG_DIR).resolve()
    active = logging_config.log_dir().resolve()
    assert os.environ.get(logging_config.LOG_DIR_ENV), "conftest should set the override"
    assert active != real, "the suite is writing into the app's own logs/ folder"


def test_the_override_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv(logging_config.LOG_DIR_ENV, str(tmp_path / "elsewhere"))
    assert logging_config.log_dir() == tmp_path / "elsewhere"
    monkeypatch.delenv(logging_config.LOG_DIR_ENV)
    assert logging_config.log_dir() == logging_config.LOG_DIR   # default unchanged


def test_no_handler_points_at_the_real_log():
    import logging
    real = (Path(logging_config.LOG_DIR) / "tradelab.log").resolve()
    for handler in logging.getLogger("tradelab").handlers:
        target = getattr(handler, "baseFilename", None)
        if target:
            assert Path(target).resolve() != real

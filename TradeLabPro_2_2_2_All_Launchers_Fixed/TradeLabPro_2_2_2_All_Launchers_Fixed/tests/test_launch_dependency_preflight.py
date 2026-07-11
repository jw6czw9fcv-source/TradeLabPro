"""Regression tests for the launch_tradelab.py dependency preflight.

Context: 2.2.1 fixed check_install.py to include pyqtgraph, but the fix
only lived in run_tradelab.bat. A different launcher (run_tradelab_console.bat)
called launch_tradelab.py directly and never ran the check, so the same
ModuleNotFoundError still reached the user. The fix was to move the check
into launch_tradelab.py itself (ensure_dependencies / missing_modules), so
it runs no matter which .bat/.vbs entry point was used. These tests guard
that logic directly, plus check REQUIRED_MODULES stays in sync with
requirements.txt (same guarantee as test_installer_consistency.py, applied
to this second location).
"""
from pathlib import Path
from unittest.mock import patch
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch_tradelab

ROOT = Path(__file__).resolve().parents[1]


def test_missing_modules_returns_empty_when_all_present():
    # In this test environment all required packages are actually installed.
    assert launch_tradelab.missing_modules() == []


def test_missing_modules_detects_a_simulated_missing_package():
    def fake_import_module(name):
        if name == "pyqtgraph":
            raise ModuleNotFoundError("No module named 'pyqtgraph'")
        return object()

    with patch.object(launch_tradelab.importlib, "import_module", side_effect=fake_import_module):
        missing = launch_tradelab.missing_modules()
    assert missing == ["pyqtgraph"]


def test_ensure_dependencies_returns_true_when_nothing_missing():
    with patch.object(launch_tradelab, "missing_modules", return_value=[]):
        assert launch_tradelab.ensure_dependencies() is True


def test_ensure_dependencies_reports_failure_if_install_and_retry_both_fail():
    with patch.object(launch_tradelab, "missing_modules", return_value=["pyqtgraph"]), \
         patch.object(launch_tradelab.subprocess, "run"), \
         patch.object(launch_tradelab, "show_error") as mock_show_error:
        result = launch_tradelab.ensure_dependencies()
    assert result is False
    mock_show_error.assert_called_once()


def test_required_modules_stay_in_sync_with_requirements_txt():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    required_packages = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[=<>!~\[]", line, maxsplit=1)[0].strip()
        if name and name != "pytest":  # dev-only, not needed at app runtime
            required_packages.append(name)

    missing_from_launcher = [p for p in required_packages if p not in launch_tradelab.REQUIRED_MODULES]
    assert not missing_from_launcher, (
        f"requirements.txt has packages not checked by launch_tradelab.py's "
        f"preflight: {missing_from_launcher}. Add them to REQUIRED_MODULES."
    )

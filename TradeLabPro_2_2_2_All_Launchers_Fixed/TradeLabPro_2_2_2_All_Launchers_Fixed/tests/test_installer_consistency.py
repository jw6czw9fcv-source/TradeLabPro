"""Regression test for the installer/dependency-check scripts.

This directly caused a real user-facing crash in 2.2.0: pyqtgraph was added
to requirements.txt but not to check_install.py's module list, so the
checker reported "All dependencies are installed" on an environment that
was actually missing pyqtgraph, and ModuleNotFoundError only surfaced when
the app itself tried to import it.

This test parses both files and fails the build if a runtime package in
requirements.txt has no corresponding import check in check_install.py.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Packages that are dev/test-only (not imported by the running app) are
# intentionally excluded from check_install.py and don't need to appear here.
DEV_ONLY_PACKAGES = {"pytest"}

# requirements.txt package name -> the module name Python actually imports.
# Kept explicit rather than guessed, since these don't always match
# (e.g. PySide6 imports as "PySide6", but plenty of real-world packages
# differ from their PyPI name).
PACKAGE_TO_IMPORT = {
    "PySide6": "PySide6",
    "pyqtgraph": "pyqtgraph",
    "pandas": "pandas",
    "numpy": "numpy",
    "yfinance": "yfinance",
    "matplotlib": "matplotlib",
    "pytest": "pytest",
}


def _parse_requirements() -> list[str]:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[=<>!~\[]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def _parse_check_install_modules() -> set[str]:
    text = (ROOT / "check_install.py").read_text(encoding="utf-8")
    # module list is a list of ("import_name", "package_name") tuples
    return set(re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', text) and
               [pkg for _imp, pkg in re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', text)])


def test_every_runtime_requirement_has_a_check_install_entry():
    required = _parse_requirements()
    checked = _parse_check_install_modules()
    missing = [
        pkg for pkg in required
        if pkg not in DEV_ONLY_PACKAGES and pkg not in checked
    ]
    assert not missing, (
        f"These packages are in requirements.txt but check_install.py never "
        f"verifies they're importable: {missing}. Add them to the `modules` "
        f"list in check_install.py, or this can silently ship a broken "
        f"install again like pyqtgraph did in 2.2.0."
    )


def test_requirements_file_is_not_empty():
    assert len(_parse_requirements()) >= 5

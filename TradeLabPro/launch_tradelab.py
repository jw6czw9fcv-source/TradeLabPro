from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys
import traceback

# Kept in sync with requirements.txt / check_install.py (see
# tests/test_installer_consistency.py, which fails the build if they drift).
REQUIRED_MODULES = ["PySide6", "pyqtgraph", "pandas", "numpy", "yfinance", "matplotlib"]


def show_error(message: str) -> None:
    log_dir = pathlib.Path.home() / "TradeLabPro" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "startup_error.log"
    log_file.write_text(message, encoding="utf-8")
    try:
        from tkinter import Tk, messagebox
        root = Tk()
        root.withdraw()
        messagebox.showerror("TradeLab Pro Error", f"TradeLab Pro encountered an error.\n\n{message[:1800]}\n\nFull log:\n{log_file}")
        root.destroy()
    except Exception:
        print(message)
        print(f"Full log: {log_file}")


def missing_modules() -> list[str]:
    missing = []
    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    return missing


def ensure_dependencies() -> bool:
    """Single point-of-truth dependency check, run no matter which launcher
    (run_tradelab.bat, run_tradelab_console.bat, the VBS shortcut, or a
    direct `python launch_tradelab.py`) started the app. Previously each
    launcher had to remember to check this itself, and one of them
    (run_tradelab_console.bat) didn't - which is how a missing pyqtgraph
    install slipped through as a raw ModuleNotFoundError instead of a clear
    message. Returns True if the app is safe to start.
    """
    missing = missing_modules()
    if not missing:
        return True

    project_root = pathlib.Path(__file__).resolve().parent
    requirements = project_root / "requirements.txt"
    print(f"Missing packages detected: {', '.join(missing)}")
    print("Attempting to install from requirements.txt using the current Python interpreter...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements)],
            check=True,
        )
    except Exception:
        show_error(
            "TradeLab Pro is missing required packages and the automatic "
            f"install failed: {', '.join(missing)}.\n\n"
            "Please run install_requirements.bat, then try again."
        )
        return False

    still_missing = missing_modules()
    if still_missing:
        show_error(
            "TradeLab Pro is still missing required packages after an "
            f"automatic install attempt: {', '.join(still_missing)}.\n\n"
            "Please run install_requirements.bat manually, then try again."
        )
        return False

    print("All required packages are now installed.")
    return True


def main() -> int:
    try:
        if not ensure_dependencies():
            return 1
        from tradelab.ui.app import run_app
        run_app()
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        show_error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

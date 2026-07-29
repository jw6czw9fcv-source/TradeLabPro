"""Build everything a release ships: the icon, the .exe, and the installer.

    python tools/build_release.py            # all three
    python tools/build_release.py --exe      # skip the installer

Produces:
    resources/tradelab.ico
    dist/TradeLabPro.exe                     (~130 MB, standalone)
    installer/Output/TradeLabPro-Setup-<version>.exe

Requires PyInstaller (`pip install pyinstaller`), and Inno Setup for the
installer step (`winget install JRSoftware.InnoSetup`). The installer is
skipped with a note rather than failing the build if Inno Setup is absent.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "TradeLabPro.iss"

# winget installs Inno Setup per-user; a machine-wide install lands in Program
# Files. Check both rather than assume.
ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def _run(label: str, args: list) -> None:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode:
        raise SystemExit(f"{label} failed (exit {result.returncode})")


def find_iscc() -> Path | None:
    return next((p for p in ISCC_CANDIDATES if p.is_file()), None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", action="store_true",
                    help="build the executable only, skipping the installer")
    args = ap.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    print(f"Building TradeLab Pro {version}")

    _run("icon", [sys.executable, "tools/make_icon.py"])
    _run("executable", [sys.executable, "-m", "PyInstaller", "TradeLabPro.spec",
                        "--noconfirm", "--log-level", "WARN"])

    exe = ROOT / "dist" / "TradeLabPro.exe"
    print(f"\n  {exe.relative_to(ROOT)} — {exe.stat().st_size / 1024 / 1024:,.0f} MB")

    if args.exe:
        return
    iscc = find_iscc()
    if iscc is None:
        print("\nInno Setup not found — skipping the installer.")
        print("  winget install JRSoftware.InnoSetup")
        return
    _run("installer", [str(iscc), str(ISS)])
    setup = ROOT / "installer" / "Output" / f"TradeLabPro-Setup-{version}.exe"
    if setup.is_file():
        print(f"\n  {setup.relative_to(ROOT)} — "
              f"{setup.stat().st_size / 1024 / 1024:,.0f} MB")


if __name__ == "__main__":
    main()

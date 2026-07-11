import sys

modules = [
    ("PySide6", "PySide6"),
    ("pyqtgraph", "pyqtgraph"),
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("yfinance", "yfinance"),
    ("matplotlib", "matplotlib"),
]

missing = []
for import_name, package_name in modules:
    try:
        __import__(import_name)
        print(f"OK: {package_name}")
    except Exception as exc:
        print(f"MISSING/ERROR: {package_name}: {exc}")
        missing.append(package_name)

if missing:
    print("\nMissing packages:", ", ".join(missing))
    print("Run install_requirements.bat, or manually run:")
    print("python -m pip install -r requirements.txt")
    sys.exit(1)

print("\nAll dependencies are installed.")

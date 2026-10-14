"""Weekly copies of your data (Qt-free, offline-testable).

Everything you have typed into TradeLab - portfolios, cash, journal, retirement
plan, alerts, links, notes - lives in one folder (config.DATA_DIR). One bad
disk, one stray delete, and it is gone. A backup is a zip in `backups/` beside
it: the database copied with SQLite's own backup API (consistent even while the
app has it open) plus the small JSON and text files. The newest few are kept.

To restore: close TradeLab, unzip a backup, and copy its files back into the
data folder.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

BACKUP_DIR_NAME = "backups"
BACKUP_EVERY_DAYS = 7
KEEP = 8
_PREFIX = "TradeLab-backup-"
_STAMP = "%Y-%m-%d_%H%M%S"
_EXTRA_SUFFIXES = (".json", ".txt")


def backup_dir(data_dir) -> Path:
    return Path(data_dir) / BACKUP_DIR_NAME


def backups(dest) -> list:
    """[(when, path)] of the backups in dest, newest first."""
    found = []
    try:
        entries = list(Path(dest).glob(f"{_PREFIX}*.zip"))
    except OSError:
        return []
    for path in entries:
        try:
            when = dt.datetime.strptime(path.stem[len(_PREFIX):], _STAMP)
        except ValueError:
            continue
        found.append((when, path))
    return sorted(found, reverse=True)


def latest(dest) -> Optional[tuple]:
    found = backups(dest)
    return found[0] if found else None


def due(dest, now=None, every_days: int = BACKUP_EVERY_DAYS) -> bool:
    """True when there is no backup yet, or the newest is every_days old."""
    now = now or dt.datetime.now()
    last = latest(dest)
    return last is None or now - last[0] >= dt.timedelta(days=every_days)


def make_backup(data_dir, dest=None, now=None, keep: int = KEEP) -> Path:
    """Zip the data folder's database and small files into dest; prune to keep.
    Returns the zip's path. Raises OSError/sqlite3.Error if it can't be made."""
    data_dir = Path(data_dir)
    dest = Path(dest) if dest else backup_dir(data_dir)
    now = now or dt.datetime.now()
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{_PREFIX}{now.strftime(_STAMP)}.zip"
    partial = target.with_suffix(".zip.part")
    with tempfile.TemporaryDirectory() as tmp, \
            zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
        for db in sorted(data_dir.glob("*.db")):
            copy = Path(tmp) / db.name
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                out = sqlite3.connect(copy)
                try:
                    src.backup(out)
                finally:
                    out.close()
            finally:
                src.close()
            zf.write(copy, db.name)
        for extra in sorted(data_dir.iterdir()):
            if (extra.is_file() and extra.suffix.lower() in _EXTRA_SUFFIXES
                    and "cache" not in extra.name.lower()):
                zf.write(extra, extra.name)
    partial.replace(target)
    for _, old in backups(dest)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target

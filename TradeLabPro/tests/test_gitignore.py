"""What git is allowed to see.

The repo is public, and the folders the app (and its older versions) wrote
your data into must stay invisible to `git add`. But the rule that hid them
was a bare `data/`, which matches every directory of that name at any depth -
including the source package `tradelab/data/`, home of database.py and
market_data.py. A new module created there would have been silently left out
of every commit, working on this machine and missing from every clone.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _ignored(path: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    if result.returncode not in (0, 1):
        pytest.skip("not inside a git checkout")
    return result.returncode == 0


@pytest.mark.parametrize("path", [
    "tradelab/data/a_new_module.py",
    "tradelab/data/database.py",
    "tradelab/core/a_new_module.py",
])
def test_source_is_never_ignored(path):
    assert not _ignored(path), f"{path} would be silently left out of commits"


@pytest.mark.parametrize("path", [
    "data/tradelab.db",                 # what older versions wrote into the checkout
    "data/logs/ibkr_flex_last.xml",     # the raw IBKR report: your trade history
    "data.old/journal.json",
    "logs/tradelab.log",
    "tools/Portefeuille_FNB.xlsx",      # your own target allocations
])
def test_private_data_stays_out_of_the_repo(path):
    assert _ignored(path), f"{path} is visible to git and could be published"

"""CELI / REER contribution room, and the return of the money once what you
put in is left out (Qt-free, offline-testable).

The room comes from CRA (My Account, or the REER deduction limit on the
Notice of Assessment) on a date you type; TradeLab counts the deposits and
withdrawals you record since then. The rules, read on canada.ca on 2026-11-01:

- CELI (TFSA): the 2026 dollar limit is $7,000, added to everyone's room on
  January 1. A withdrawal comes back as room only on January 1 of the next
  year - putting it back the same year without spare room is an
  over-contribution. Any excess is taxed 1% a month, on the highest excess in
  each month it stays.
  https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/tax-free-savings-account/contributing/calculate-room.html
  https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/tax-free-savings-account/owing-tax/excess.html
- REER (RRSP): contributions beyond the deduction limit by more than $2,000
  are taxed 1% a month. A withdrawal does not give the room back.
  https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/rrsps-related-plans/contributing-a-rrsp-prpp/contributions-affect-your-rrsp-prpp-deduction-limit.html

A year's CELI limit is added here only once it is known (TFSA_LIMIT); a later
year asks for the room to be typed again from CRA.
"""
from __future__ import annotations

import datetime as dt

from tradelab.i18n import tr

CELI, REER = "CELI", "REER"
ACCOUNTS = (CELI, REER)
TFSA_LIMIT = {2026: 7000.0}      # canada.ca, read 2026-11-01
RRSP_BUFFER = 2000.0             # excess beyond the limit before the 1% a month


def _d(value) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])


def status(account: str, room: float, as_of, entries: list, today=None) -> dict:
    """The room left today. `entries` are dicts with account, day, amount (+
    deposit, - withdrawal); only this account's since `as_of` count.
    Returns {left, used, back, pending_back, added, unknown_years, over,
    excess} - `over` is how far past the room, `excess` the part taxed."""
    today = today or dt.date.today()
    start = _d(as_of)
    mine = [e for e in entries if e.get("account") == account and start <= _d(e["day"]) <= today]
    used = sum(e["amount"] for e in mine if e["amount"] > 0)
    back = pending = added = 0.0
    unknown = []
    if account == CELI:
        for e in mine:
            if e["amount"] < 0:
                if dt.date(_d(e["day"]).year + 1, 1, 1) <= today:
                    back += -e["amount"]
                else:
                    pending += -e["amount"]
        for year in range(start.year + 1, today.year + 1):
            if year in TFSA_LIMIT:
                added += TFSA_LIMIT[year]
            else:
                unknown.append(year)
    left = float(room) + added + back - used
    over = max(0.0, -left)
    excess = max(0.0, over - RRSP_BUFFER) if account == REER else over
    return {"account": account, "left": left, "used": used, "back": back,
            "pending_back": pending, "added": added, "unknown_years": unknown,
            "over": over, "excess": excess}


def check_items(statuses: list) -> list:
    """The room as Plan checklist items: [(kind, text)]."""
    items = []
    for s in statuses:
        name = s["account"]
        if s["unknown_years"]:
            items.append(("warn", tr("{name} room: a new year began - type the room CRA shows "
                                     "now (My Account) so it stays right.").format(name=name)))
        if s["excess"] > 0:
            taxed = tr("1% a month on the highest excess each month" if name == CELI
                       else "1% a month on what is beyond the $2,000 allowance")
            items.append(("warn", tr("{name}: {over} over your room - taxed {taxed}. Withdrawing "
                                     "the excess soon limits the tax.").format(
                name=name, over=f"${s['over']:,.0f}", taxed=taxed)))
        elif s["over"] > 0:
            items.append(("warn", tr("{name}: {over} over your deduction limit, inside the "
                                     "$2,000 allowance - not taxed, but not deductible this "
                                     "year.").format(name=name, over=f"${s['over']:,.0f}")))
        else:
            text = tr("{name}: {left} of room left.").format(name=name, left=f"${s['left']:,.0f}")
            if s["pending_back"]:
                text += tr(" {amount} withdrawn comes back on January 1.").format(
                    amount=f"${s['pending_back']:,.0f}")
            items.append(("ok", text))
    return items


def would_exceed(s: dict, amount: float) -> float:
    """How far past the room a deposit of `amount` would go (0 when it fits)."""
    return max(0.0, float(amount) - max(0.0, s["left"]))


# --- the return, with the money put in left out ------------------------------------

def modified_dietz(start_value: float, end_value: float, flows: list, start, end) -> float | None:
    """The return between two values when money went in or out between them:
    each deposit (+) or withdrawal (-) weighed by how long it was invested.
    `flows` are (day, amount). None when there is nothing to measure on."""
    start, end = _d(start), _d(end)
    days = (end - start).days
    if days <= 0:
        return None
    inside = [(_d(d), float(a)) for d, a in flows if start < _d(d) <= end]
    net = sum(a for _d_, a in inside)
    weighted = sum(a * (end - d).days / days for d, a in inside)
    base = start_value + weighted
    if base <= 0:
        return None
    return (end_value - start_value - net) / base


def annualized(ret: float, days: int) -> float:
    return (1 + ret) ** (365.0 / days) - 1 if days > 0 else ret

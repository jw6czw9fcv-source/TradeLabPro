"""The dates that matter around retirement, per person (Qt-free).

Each rule below was read on the official page named in its source on
2026-10-14; the dates are worked out from the person's birth month (the
People table's "Born" column) and from when the plan starts each pension.
They are reminders of what to do and when, not advice on what to choose.

- RRQ: nothing starts by itself; you apply, up to 12 months before the first
  payment - Retraite Québec suggests about 3 months before. (Retraite Québec,
  "How to apply for your retirement pension?")
- PSV (OAS): Service Canada sends an enrolment letter around the 64th birthday
  when it has your information; one month past it with no letter, contact
  them - an online application opens then too. (canada.ca, "Old Age Security -
  Apply, delay, or change your start date")
- RRSP: in the year you turn 71 it has to be withdrawn, moved to a RRIF or
  turned into an annuity; December 31 of that year is the last day to
  contribute. (canada.ca, "Options for your own RRSPs")
- TFSA: the new dollar limit is set every January 1, and what you withdrew
  the year before is added back to your room that day. (canada.ca, "Calculate
  your TFSA contribution room")
"""
from __future__ import annotations

import datetime as dt
import re

SOURCES = {
    "RRQ": "Retraite Québec - How to apply for your retirement pension (read 2026-10-14)",
    "PSV": "canada.ca - Old Age Security: Apply, delay, or change your start date (read 2026-10-14)",
    "RRSP": "canada.ca - Options for your own RRSPs (read 2026-10-14)",
    "TFSA": "canada.ca - Calculate your TFSA contribution room (read 2026-10-14)",
}


def parse_born(text) -> dt.date | None:
    """'1962-08', '1962-08-01', '08/1962' -> the first of that month; None if
    it can't be read."""
    s = str(text or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", s) or None
    if m:
        year, month = int(m.group(1)), int(m.group(2))
    else:
        m = re.match(r"^(\d{1,2})/(\d{4})$", s)
        if not m:
            return None
        month, year = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return dt.date(year, month, 1)


def _add_months(day: dt.date, months: int) -> dt.date:
    total = day.year * 12 + day.month - 1 + months
    return dt.date(total // 12, total % 12 + 1, 1)


def _benefit(name: str) -> str | None:
    n = " ".join(str(name or "").lower().split())
    if n.startswith(("rrq", "qpp", "régime de rentes")):
        return "RRQ"
    if n.startswith(("psv", "oas", "sv")) or "old age security" in n or "sécurité de la vieillesse" in n:
        return "PSV"
    return None


def checklist(people: list, incomes: list, today: dt.date | None = None) -> list:
    """Every dated reminder for each person with a readable birth month, oldest
    first: [{date, person, what, source, past}]. `people` and `incomes` are the
    Retirement Sim rows (name/born, name/owner/starts_at_age). Someone without
    a birth month gets one row saying so."""
    today = today or dt.date.today()
    out = []
    for person in people or []:
        name = str(person.get("name") or "").strip()
        if not name:
            continue
        born = parse_born(person.get("born"))
        if born is None:
            out.append({"date": None, "person": name, "source": "",
                        "what": "Add the birth month (Born, e.g. 1962-08) to date the reminders."})
            continue
        at = lambda age, months=0: _add_months(born, age * 12 + months)   # noqa: E731
        starts = {}
        for inc in incomes or []:
            kind = _benefit(inc.get("name"))
            if kind and str(inc.get("owner") or "").strip() == name and inc.get("starts_at_age"):
                starts.setdefault(kind, int(inc["starts_at_age"]))
        rrq = starts.get("RRQ")
        if rrq:
            first = at(rrq)
            out.append({"date": at(rrq, -12), "person": name, "source": SOURCES["RRQ"],
                        "what": f"RRQ application opens (12 months before a start at {rrq}, "
                                f"{first:%B %Y}). Nothing starts by itself."})
            out.append({"date": at(rrq, -3), "person": name, "source": SOURCES["RRQ"],
                        "what": f"Apply for the RRQ - Retraite Québec suggests about 3 months "
                                f"before the first payment ({first:%B %Y})."})
        out.append({"date": at(64), "person": name, "source": SOURCES["PSV"],
                    "what": "PSV enrolment letter expected around now (64th birthday)."})
        psv = starts.get("PSV")
        out.append({"date": at(64, 1), "person": name, "source": SOURCES["PSV"],
                    "what": "No PSV letter yet? Contact Service Canada - the online "
                            "application opens one month after the 64th birthday."
                            + (f" Your plan starts the PSV at {psv}: ask for that start "
                               f"({at(psv):%B %Y}) - waiting adds 0.6% a month."
                               if psv and psv > 65 else "")})
        out.append({"date": dt.date(born.year + 71, 12, 31), "person": name,
                    "source": SOURCES["RRSP"],
                    "what": "Last day for the RRSPs: withdraw, move to a RRIF or buy an "
                            "annuity - and the last day to contribute to them."})
    next_jan = dt.date(today.year + 1, 1, 1)
    out.append({"date": next_jan, "person": "Everyone", "source": SOURCES["TFSA"],
                "what": "New TFSA dollar limit, and this year's TFSA withdrawals come back "
                        "as room."})
    for item in out:
        item["past"] = bool(item["date"] and item["date"] < today)
    return sorted(out, key=lambda i: (i["date"] is not None, i["date"] or dt.date.min))

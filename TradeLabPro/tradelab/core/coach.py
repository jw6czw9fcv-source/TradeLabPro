"""AI Trading Coach (Qt-free, offline-testable).

A retrospective, PROCESS-focused review of the user's own journal trades. It
grades each closed trade on how well it was *executed* - risk defined, stop
honored, reward vs risk, plan documented - NOT merely whether it made money. A
lucky trade taken with no stop can still grade poorly; a small, contained -1R
loss taken with a stop and a plan grades well. From the whole journal it derives
process metrics (how often risk was undefined, whether losses stayed within the
planned risk, whether losers are held longer than winners, ...) and plain-English
improvement suggestions.

Everything here is deterministic and needs no network or API key: the LLM in the
Coach tab only *narrates* these numbers, it does not invent them. This keeps the
Coach squarely inside the app's educational-only safety model - it reviews the
past, it never tells the user what to trade next.
"""
from __future__ import annotations

from tradelab.core.journal import summarize, group_stats

# --- grading rubric ---------------------------------------------------------
#
# Additive and transparent, in the same spirit as market.market_condition and
# the scanner's confidence score: everyone starts at a neutral base and each
# process check moves the number, with the reason recorded. Outcome (profit in
# dollars) is deliberately NOT a direct input - the R-multiple is, because it is
# the risk-adjusted result, which is what process review actually cares about.

BASE_SCORE = 50

# Cornerstone: was risk defined with a protective stop? Its absence is punished
# harder than its presence is rewarded - trading with undefined risk is the
# single worst process habit, so a no-stop trade can never grade well no matter
# how it turned out.
STOP_PRESENT_BONUS = 20
STOP_ABSENT_PENALTY = 28

# A loss a hair beyond 1R is still "honored" (slippage/gaps happen); well beyond
# means the stop was widened, ignored, or the position gapped through it.
STOP_SLIPPAGE_R = 1.15
STOP_HONORED_BONUS = 5
STOP_BROKEN_PENALTY = 15

# Reward captured relative to the risk taken (needs a stop to have an R).
REWARD_TIERS = [
    (2.0, 20, "Captured a strong {r:.1f}R — good reward for the risk taken"),
    (1.0, 10, "Made {r:.1f}R — a positive reward-to-risk result"),
    (0.0, 0, "Small {r:.1f}R win — below a 1:1 reward-to-risk"),
]

DOCUMENTED_BONUS = 8
UNDOCUMENTED_PENALTY = 6

# Score -> letter. Bands are inclusive lower bounds, checked high to low.
GRADE_BANDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F")]


def letter_for(score: float) -> str:
    for threshold, letter in GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"


def _is_documented(entry) -> bool:
    return bool((entry.strategy or "").strip() or (entry.notes or "").strip())


def _is_loss(entry) -> bool:
    return entry.pnl is not None and entry.pnl < 0


def grade_trade(entry) -> dict:
    """Process grade for ONE trade.

    Returns {gradeable, score, grade, reasons, summary}. `reasons` is a list of
    (delta, text) so the UI can show what moved the number and by how much (a
    green + or red -), mirroring the market/scanner "how this is scored" panels.

    An OPEN trade can't be graded on outcome, so it returns gradeable=False with
    a partial *setup* read (did it at least have a stop and a written plan).
    """
    has_stop = entry.stop is not None and entry.risk_per_share is not None
    documented = _is_documented(entry)

    if entry.is_open:
        setup = [
            (0, "Has a protective stop" if has_stop else "No protective stop set"),
            (0, "Has a documented plan" if documented else "No strategy/notes recorded"),
        ]
        return {"gradeable": False, "score": None, "grade": None, "reasons": setup,
                "summary": "Open trade — not graded until it is closed."}

    score = BASE_SCORE
    reasons: list = []

    # 1) Risk defined with a stop — the cornerstone.
    if has_stop:
        score += STOP_PRESENT_BONUS
        reasons.append((STOP_PRESENT_BONUS, "Risk was defined with a protective stop"))
    else:
        score -= STOP_ABSENT_PENALTY
        reasons.append((-STOP_ABSENT_PENALTY, "No protective stop — risk was undefined"))

    r = entry.r_multiple           # None when there was no stop

    # 2) Stop honored — only meaningful on a losing trade that had a stop.
    if has_stop and _is_loss(entry):
        if r is not None and r < -STOP_SLIPPAGE_R:
            score -= STOP_BROKEN_PENALTY
            reasons.append((-STOP_BROKEN_PENALTY,
                            f"Loss ran to {r:.1f}R — beyond the planned 1R risk "
                            "(stop widened, ignored, or gapped through)"))
        else:
            score += STOP_HONORED_BONUS
            reasons.append((STOP_HONORED_BONUS,
                            "Loss was contained within the planned risk (stop honored)"))

    # 3) Reward vs risk realised (asymmetry). Positive R only; a negative R is a
    #    loss already accounted for by the stop-honored check above — no double hit.
    if r is not None and r > 0:
        for threshold, delta, template in REWARD_TIERS:
            if r >= threshold:
                if delta:
                    score += delta
                reasons.append((delta, template.format(r=r)))
                break
    elif r is None:
        reasons.append((0, "Reward-to-risk can't be measured without a stop"))

    # 4) Documented plan — so the trade can actually be reviewed later.
    if documented:
        score += DOCUMENTED_BONUS
        reasons.append((DOCUMENTED_BONUS, "Trade rationale was documented (strategy/notes)"))
    else:
        score -= UNDOCUMENTED_PENALTY
        reasons.append((-UNDOCUMENTED_PENALTY,
                        "No strategy or notes — hard to review what worked"))

    score = max(0, min(100, score))
    grade = letter_for(score)
    return {"gradeable": True, "score": score, "grade": grade, "reasons": reasons,
            "summary": _grade_summary(grade, entry, has_stop)}


def _grade_summary(grade: str, entry, has_stop: bool) -> str:
    r = entry.r_multiple
    r_txt = f"{r:+.1f}R" if r is not None else "unmeasured R"
    if grade in ("A", "B"):
        base = "Well-executed trade"
    elif grade == "C":
        base = "Mixed execution"
    else:
        base = "Poorly-executed trade"
    if not has_stop:
        return f"{base}: no stop, so risk was undefined ({r_txt})."
    return f"{base}: risk defined, result {r_txt}."


# --- aggregate report -------------------------------------------------------

def _avg(values):
    vals = [v for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def coach_report(entries: list) -> dict:
    """Whole-journal process review: base stats, per-trade grades rolled up, the
    process metrics that matter, and concrete improvement suggestions. Pure and
    deterministic - this is what the offline (no-API-key) Coach shows, and what
    the LLM is given to narrate."""
    closed = [e for e in entries if not e.is_open]
    base = summarize(entries)

    graded = [(e, grade_trade(e)) for e in closed]
    scored = [g for _, g in graded if g["gradeable"] and g["score"] is not None]
    avg_score = _avg([g["score"] for g in scored])
    distribution = {}
    for g in scored:
        distribution[g["grade"]] = distribution.get(g["grade"], 0) + 1

    n = len(closed)
    with_stop = [e for e in closed if e.stop is not None and e.risk_per_share is not None]
    no_stop_pct = ((n - len(with_stop)) / n * 100.0) if n else 0.0

    losers_with_stop = [e for e in with_stop if _is_loss(e)]
    honored = [e for e in losers_with_stop
               if e.r_multiple is None or e.r_multiple >= -STOP_SLIPPAGE_R]
    stop_honored_pct = (len(honored) / len(losers_with_stop) * 100.0) if losers_with_stop else None

    documented = [e for e in closed if _is_documented(e)]
    documented_pct = (len(documented) / n * 100.0) if n else 0.0

    winners = [e for e in closed if e.pnl is not None and e.pnl > 0]
    losers = [e for e in closed if _is_loss(e)]
    avg_hold_win = _avg([e.holding_days for e in winners])
    avg_hold_loss = _avg([e.holding_days for e in losers])

    win_loss_ratio = (base["avg_win"] / abs(base["avg_loss"])) if base["avg_loss"] else None

    by_strategy = [(name, s) for name, s in group_stats(closed, "strategy")
                   if s["closed"] > 0]

    report = {
        "base": base,
        "closed": n,
        "avg_grade_score": avg_score,
        "avg_grade": letter_for(avg_score) if avg_score is not None else None,
        "grade_distribution": distribution,
        "no_stop_pct": no_stop_pct,
        "stop_honored_pct": stop_honored_pct,
        "documented_pct": documented_pct,
        "win_loss_ratio": win_loss_ratio,
        "avg_hold_win": avg_hold_win,
        "avg_hold_loss": avg_hold_loss,
        "by_strategy": by_strategy,
    }
    report["suggestions"] = _suggestions(report)
    return report


def _suggestions(r: dict) -> list:
    """Turn the process metrics into a ranked list of {kind, text} where kind is
    'warn' (a habit to fix), 'good' (positive reinforcement) or 'info'. Warnings
    come first. Every claim cites the number behind it so nothing is a black box.
    """
    warn, good, info = [], [], []
    n = r["closed"]
    if n == 0:
        return [{"kind": "info", "text": "No closed trades yet — close some trades (or "
                 "import them) and the Coach will grade your process."}]
    if n < 5:
        info.append({"kind": "info", "text": f"Only {n} closed trade(s) so far — the "
                     "stats below are directional, not yet statistically reliable."})

    base = r["base"]

    # Stops / risk definition — the most important habit.
    nsp = r["no_stop_pct"]
    if nsp > 30:
        warn.append({"kind": "warn", "text": f"{nsp:.0f}% of your trades had no protective "
                     "stop — risk was undefined on those. Decide your stop (and therefore your "
                     "1R risk) before you enter."})
    elif nsp > 10:
        warn.append({"kind": "warn", "text": f"{nsp:.0f}% of trades had no stop. Aim to define "
                     "a stop on every trade so each one has a measurable R."})
    elif nsp == 0:
        good.append({"kind": "good", "text": "Every trade had a defined stop — excellent risk "
                     "discipline. It's what makes the rest of these numbers meaningful."})

    shp = r["stop_honored_pct"]
    if shp is not None and shp < 80:
        warn.append({"kind": "warn", "text": f"Losses stayed within the planned risk on only "
                     f"{shp:.0f}% of stopped losers — the rest ran past 1R. Honor the stop; "
                     "widening it turns a planned loss into an outsized one."})

    # Reward/risk shape of the edge.
    wlr = r["win_loss_ratio"]
    wr = base["win_rate"]
    if wlr is not None:
        if wlr < 1 and wr < 50:
            warn.append({"kind": "warn", "text": f"Your average loss is bigger than your average "
                         f"win (ratio {wlr:.2f}) and you win under half the time ({wr:.0f}%) — a "
                         "fragile combination. Aim to cut losers sooner or let winners run further."})
        elif wlr >= 2:
            good.append({"kind": "good", "text": f"Your average win is {wlr:.1f}× your average loss "
                         "— strong reward-to-risk. Keep letting winners run."})

    exp = base["expectancy"]
    pf = base["profit_factor"]
    if exp > 0 and pf >= 1.5:
        good.append({"kind": "good", "text": f"Positive expectancy (${exp:,.0f}/trade, profit "
                     f"factor {pf:.2f}) — your process is paying off. Consistency is the goal now."})
    elif exp < 0:
        warn.append({"kind": "warn", "text": f"Negative expectancy (${exp:,.0f}/trade) — the "
                     "current process loses money on average. Focus on the stop and reward-to-risk "
                     "points above before sizing up."})

    # Behavioural: riding losers, cutting winners.
    ahw, ahl = r["avg_hold_win"], r["avg_hold_loss"]
    if ahw is not None and ahl is not None and ahw > 0 and ahl > ahw * 1.3:
        warn.append({"kind": "warn", "text": f"You hold losers about {ahl / ahw:.1f}× longer than "
                     f"winners ({ahl:.0f} vs {ahw:.0f} days) — a classic sign of hoping losers come "
                     "back. Consider a time stop."})

    # Record-keeping.
    dp = r["documented_pct"]
    if dp < 50:
        warn.append({"kind": "warn", "text": f"Only {dp:.0f}% of trades have a strategy or notes. "
                     "Writing down the reason for each trade is what lets you review what actually "
                     "works."})

    # Best / worst playbook.
    strat = r["by_strategy"]
    named = [(name, s) for name, s in strat if name and not name.startswith("(no ") and s["closed"] >= 2]
    if len(named) >= 2:
        best = named[0]
        worst = named[-1]
        info.append({"kind": "info", "text": f"By expectancy, '{best[0]}' is your best playbook "
                     f"(${best[1]['expectancy']:,.0f}/trade over {best[1]['closed']}) and "
                     f"'{worst[0]}' your weakest (${worst[1]['expectancy']:,.0f}/trade over "
                     f"{worst[1]['closed']})."})

    return warn + good + info


# --- LLM narration ----------------------------------------------------------

COACH_SYSTEM_PROMPT = (
    "You are the AI Trading Coach built into TradeLabPro. You review the user's "
    "OWN past trades (from their journal) and coach them on their PROCESS. Your "
    "job is retrospective and educational: help them see the habits behind their "
    "results and how to trade more disciplined next time.\n\n"
    "Focus on process, not prediction: risk management, stop discipline, "
    "reward-to-risk (R-multiples), consistency, position/holding discipline, and "
    "record-keeping. Reference the specific numbers in the journal summary you are "
    "given.\n\n"
    "Hard rules you must never break:\n"
    "- You are NOT a licensed financial advisor. Never tell the user to buy, sell, "
    "hold, or size a specific position, and never predict prices or give price "
    "targets. You are reviewing the past, not recommending future trades.\n"
    "- Base everything on the journal data provided. Do NOT invent trades, "
    "figures, or symbols you were not given. If the data is too thin for a "
    "conclusion, say so.\n"
    "- Be direct but constructive — name the habit, show the number behind it, and "
    "give a concrete process change.\n"
    "- Keep answers concise and end with a brief reminder that this is educational "
    "process feedback, not financial advice."
)


def build_coach_context(entries: list, recent: int = 25) -> str:
    """Compact text block summarising the journal for the LLM: the process report
    plus a line per recent graded trade. Bounded so a large journal never blows
    the token budget."""
    r = coach_report(entries)
    base = r["base"]
    lines = ["Journal process summary:"]
    lines.append(f"- Closed trades: {r['closed']} (open: {base['open']})")
    if r["avg_grade"]:
        dist = ", ".join(f"{g}:{n}" for g, n in sorted(r["grade_distribution"].items()))
        lines.append(f"- Average process grade: {r['avg_grade']} "
                     f"({r['avg_grade_score']:.0f}/100); distribution {dist}")
    lines.append(f"- Win rate: {base['win_rate']:.0f}%  |  Expectancy: ${base['expectancy']:,.0f}/trade"
                 f"  |  Profit factor: {base['profit_factor']:.2f}"
                 + (f"  |  Avg R: {base['avg_r']:+.2f}" if base["avg_r"] is not None else ""))
    lines.append(f"- Avg win ${base['avg_win']:,.0f} vs avg loss ${base['avg_loss']:,.0f}"
                 + (f" (ratio {r['win_loss_ratio']:.2f})" if r["win_loss_ratio"] is not None else ""))
    lines.append(f"- Trades with no stop: {r['no_stop_pct']:.0f}%  |  Stop honored on losers: "
                 + (f"{r['stop_honored_pct']:.0f}%" if r["stop_honored_pct"] is not None else "n/a")
                 + f"  |  Documented: {r['documented_pct']:.0f}%")
    if r["avg_hold_win"] is not None and r["avg_hold_loss"] is not None:
        lines.append(f"- Avg holding: winners {r['avg_hold_win']:.0f}d vs losers {r['avg_hold_loss']:.0f}d")
    if r["suggestions"]:
        lines.append("Process observations:")
        lines += [f"  - [{s['kind']}] {s['text']}" for s in r["suggestions"]]

    closed = [e for e in entries if not e.is_open]
    closed.sort(key=lambda e: (e.exit_date or e.entry_date or ""), reverse=True)
    if closed:
        lines.append(f"Most recent {min(recent, len(closed))} closed trades (grade · symbol · side · R · P&L):")
        for e in closed[:recent]:
            g = grade_trade(e)
            r_txt = f"{e.r_multiple:+.1f}R" if e.r_multiple is not None else "—R"
            pnl = e.pnl if e.pnl is not None else 0.0
            lines.append(f"  - {g['grade']} · {e.symbol} · {e.side} · {r_txt} · ${pnl:,.0f}"
                         + (f" · {e.strategy}" if e.strategy else ""))
    return "\n".join(lines)


def offline_coach_report(entries: list) -> str:
    """Plain-text process report — the no-API-key answer, and what the Coach tab
    shows in its report pane. Built entirely from the offline `coach_report`."""
    r = coach_report(entries)
    base = r["base"]
    out = ["AI Trading Coach — process review (offline, rules-based)", ""]
    if r["closed"] == 0:
        out.append("No closed trades yet. Add or import trades and close them, then refresh — "
                   "the Coach grades how each trade was executed, not just whether it won.")
        out.append("")
        out.append("Educational process feedback only — not financial advice.")
        return "\n".join(out)

    if r["avg_grade"]:
        out.append(f"Overall process grade: {r['avg_grade']}  ({r['avg_grade_score']:.0f}/100)")
        dist = "   ".join(f"{g}: {n}" for g, n in sorted(r["grade_distribution"].items()))
        out.append(f"Grade distribution:  {dist}")
    out.append("")
    out.append(f"Closed trades: {r['closed']}   ·   Win rate: {base['win_rate']:.0f}%   ·   "
               f"Expectancy: ${base['expectancy']:,.0f}/trade   ·   Profit factor: {base['profit_factor']:.2f}")
    out.append(f"Avg win: ${base['avg_win']:,.0f}   ·   Avg loss: ${base['avg_loss']:,.0f}"
               + (f"   ·   Avg R: {base['avg_r']:+.2f}" if base["avg_r"] is not None else ""))
    out.append(f"No-stop trades: {r['no_stop_pct']:.0f}%   ·   Stop honored on losers: "
               + (f"{r['stop_honored_pct']:.0f}%" if r["stop_honored_pct"] is not None else "n/a")
               + f"   ·   Documented: {r['documented_pct']:.0f}%")
    out.append("")
    out.append("What to work on:")
    icon = {"warn": "⚠", "good": "✓", "info": "•"}
    for s in r["suggestions"]:
        out.append(f"  {icon.get(s['kind'], '•')} {s['text']}")
    out.append("")
    out.append("Educational process feedback only — not financial advice.")
    return "\n".join(out)


def coach_answer(messages: list, api_key: str | None, model: str, entries: list,
                 transport=None) -> str:
    """Send a coach chat turn to the LLM with the journal summary as context and
    the retrospective-coach system prompt. `transport` is injectable for tests.
    The UI handles the no-key case by showing offline_coach_report instead."""
    from tradelab.core import ai_assistant
    context = build_coach_context(entries)
    return ai_assistant.ask(messages, api_key, model=model,
                            system=COACH_SYSTEM_PROMPT, context=context,
                            transport=transport)

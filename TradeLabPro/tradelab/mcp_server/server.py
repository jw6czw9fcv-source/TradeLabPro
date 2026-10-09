"""TradeLab Pro as an MCP server - an AI assistant can use your own figures.

Local and stdio only: the assistant starts it as a subprocess on this machine,
it opens no port and accepts no connection, and every tool is read-only - the
database is opened in SQLite's read-only mode (see tools.py).

The point is the pairing. IBKR's own connector gives an assistant the live
account - balances, positions, prices. This one adds what TradeLab computes on
top of it: the book opened up by company, the Quebec + federal tax model, the
retirement projection in nominal dollars. One conversation, both halves.

    python TradeLabPro/tradelab_mcp.py          (or: python -m tradelab.mcp_server)
"""
from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as AnticipatedToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from tradelab.core.config import APP_VERSION
from tradelab.mcp_server import tools

INSTRUCTIONS = """\
TradeLab Pro is the user's own investment workstation (Canadian, CAD-based, Quebec \
resident). These tools read what they stored in it and run its calculations; all \
are read-only and none can trade.

Prefer a brokerage connector (such as Interactive Brokers) for live balances and \
positions, and these tools for what TradeLab adds: look_through (exposure by \
underlying company), quebec_tax, retirement_projection (which accepts live account \
balances through `balances`), dividend_income, and the user's ETF comparison and \
trade journal. Money is in CAD unless a tool says otherwise. Results are \
calculations on the user's figures and assumptions, not financial advice - say so \
when presenting them, and never present a simulated success rate as a probability."""

LOCAL = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                        idempotent_hint=True, open_world_hint=False)
ONLINE = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                         idempotent_hint=True, open_world_hint=True)

server = MCPServer(name="tradelab", title="TradeLab Pro",
                   version=APP_VERSION.split()[0], instructions=INSTRUCTIONS)

def _answer(fn, **kwargs) -> dict[str, Any]:
    """Run a tool, turning a failure it saw coming into one the assistant can read.

    The SDK hides the message of any exception it does not recognise - the
    model sees only "Error executing tool portfolio". Its own ToolError is the
    one it passes through, so ours are translated into it here, keeping
    tools.py free of the MCP library."""
    try:
        return fn(**kwargs)
    except tools.ToolError as exc:
        raise AnticipatedToolError(str(exc)) from exc


Currency = Annotated[str, Field(description="CAD (default), USD, or 'native' to keep each "
                                            "holding in its own currency.")]


@server.tool(annotations=LOCAL)
def portfolio() -> dict[str, Any]:
    """List the holdings stored in TradeLab: symbol, shares, average entry price and the
    portfolio each belongs to (an IBKR import lands in a portfolio named IBKR). No prices -
    use book_summary for values, or a brokerage connector for live quantities."""
    return _answer(tools.portfolio)


@server.tool(annotations=ONLINE)
def book_summary(currency: Currency = "CAD",
                 period: Annotated[str, Field(description="History window: 6mo, 1y, 2y "
                                                          "or 5y.")] = "1y",
                 benchmark: Annotated[str, Field(description="Benchmark symbol.")] = "SPY",
                 ) -> dict[str, Any]:
    """Value the stored book at current prices, as TradeLab's Analytics tab does: total
    value and cost, unrealized P&L, return and CAGR over the window versus the benchmark,
    beta, annualised volatility, maximum drawdown, concentration and correlation, plus one
    row per holding. Downloads prices (a few seconds); a symbol that cannot be priced is
    listed under no_data rather than valued on made-up prices."""
    return _answer(tools.book_summary, currency=currency, period=period, benchmark=benchmark)


@server.tool(annotations=ONLINE)
def look_through(currency: Currency = "CAD") -> dict[str, Any]:
    """Restate the book by underlying company: each ETF is opened up to the companies it
    holds and merged with direct holdings, so a bank owned directly and through two funds
    shows as one exposure. Also returns sector weights for the whole book. Figures are
    floors - sources publish only each fund's top holdings, and the rest is reported as
    unallocated. Downloads prices and fund compositions."""
    return _answer(tools.look_through, currency=currency)


@server.tool(annotations=ONLINE)
def dividend_income(currency: Currency = "CAD") -> dict[str, Any]:
    """The income the stored book pays: annual and monthly-average income, portfolio yield
    and yield on cost, each holding's payment frequency and growth, and a month-by-month
    calendar of expected payments - projected from past payments."""
    return _answer(tools.dividend_income, currency=currency)


@server.tool(annotations=LOCAL)
def retirement_projection(
        spending: Annotated[float | None, Field(
            description="Household spending per year in today's dollars; it grows with "
                        "inflation. Omit to use the value saved in TradeLab.")] = None,
        nominal_return_pct: Annotated[float | None, Field(
            description="Expected nominal annual return in percent (5 = 5%). "
                        "Omit for the saved value.")] = None,
        inflation_pct: Annotated[float | None, Field(
            description="Inflation in percent. Omit for the saved value.")] = None,
        until_age: Annotated[int | None, Field(
            description="Project until the oldest person reaches this age.")] = None,
        pension_split_pct: Annotated[float | None, Field(
            description="Share of eligible pension income moved to the lower-income "
                        "spouse, 0 to 50.")] = None,
        balances: Annotated[dict[str, float] | None, Field(
            description="Replace stored account balances by account name - for example "
                        "with live balances from a brokerage connector. Names must match "
                        "the plan's accounts.")] = None,
        todays_dollars: Annotated[bool, Field(
            description="Express every figure in today's purchasing power instead of "
                        "each year's own dollars.")] = False,
        paths: Annotated[int, Field(
            description="If above 0, also run that many randomised return orderings "
                        "(e.g. 500) to show sequence risk.", ge=0, le=5000)] = 0,
        volatility_pct: Annotated[float | None, Field(
            description="Annual volatility for the randomised paths, in percent.")] = None,
) -> dict[str, Any]:
    """Project the household's retirement year by year, from the plan stored in
    TradeLab's Retirement Sim tab: incomes (RRQ, PSV, pensions - indexed or not), the
    forced RRIF minimum from 71, real Quebec + federal tax with pension splitting and
    indexed brackets, and what must come out of capital to cover the spending. Returns
    whether and when the money runs short. Any assumption can be overridden for this
    call only; nothing is saved."""
    return _answer(tools.retirement_projection, 
        spending=spending, nominal_return_pct=nominal_return_pct,
        inflation_pct=inflation_pct, until_age=until_age,
        pension_split_pct=pension_split_pct, balances=balances,
        todays_dollars=todays_dollars, paths=paths, volatility_pct=volatility_pct)


@server.tool(annotations=LOCAL)
def quebec_tax(
        income: Annotated[float, Field(description="Taxable income for the year, CAD.", ge=0)],
        age: Annotated[int, Field(description="Age at the end of the year.", ge=0, le=120)],
        pension_income: Annotated[float, Field(
            description="Part of the income eligible for the pension income amount "
                        "(RRIF/FERR withdrawals at 65+; not RRQ or PSV).", ge=0)] = 0.0,
        family_income: Annotated[float | None, Field(
            description="Couple's combined net income, which reduces Quebec's age "
                        "amount. Omit for a single person.")] = None,
        years_ahead: Annotated[int, Field(
            description="Tax year as years after 2026; tables are indexed by "
                        "inflation_pct.", ge=0, le=60)] = 0,
        inflation_pct: Annotated[float, Field(
            description="Indexation rate for future tables, in percent.")] = 2.0,
) -> dict[str, Any]:
    """Quebec + federal income tax for one person with TradeLab's model: 2026 brackets
    and credits (basic personal amounts, age amount, pension income amount, Quebec's
    family-income reduction, the Quebec abatement), the average rate and the marginal
    rate on the next dollar. The OAS recovery tax is not modelled."""
    return _answer(tools.quebec_tax, income=income, age=age, pension_income=pension_income,
                            family_income=family_income, years_ahead=years_ahead,
                            inflation_pct=inflation_pct)


@server.tool(annotations=LOCAL)
def etf_screener() -> dict[str, Any]:
    """The user's own ETF comparison table from TradeLab's ETF Screener: each fund's fees,
    trailing returns, volatility, the regulator's risk band, yield, holdings summary and the
    target weights of their Low / Mid / High risk allocations. As last refreshed in the
    app - nothing is downloaded."""
    return _answer(tools.etf_screener)


@server.tool(annotations=LOCAL)
def journal_summary() -> dict[str, Any]:
    """The user's trade journal: win rate, expectancy, P&L and R-multiples, plus the
    Coach's process grades (A-F, judging execution - plan, stop, sizing - not outcome)
    and its suggestions."""
    return _answer(tools.journal_summary)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()

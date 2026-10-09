"""``python -m equity_research.fundamentals AAPL [--years 10] [--as-of YYYY-MM-DD]``

Normalized statements, yearly metrics, growth, consistency checks and data-quality issues."""

from __future__ import annotations

import argparse
import re
from datetime import date

from equity_research.data.__main__ import CACHE_DIR
from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient, user_agent_from_env
from equity_research.data.sec_edgar import SecEdgar
from equity_research.fundamentals import analysis, checks
from equity_research.fundamentals.statements import build_annual

STATEMENT_ROWS = ("revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "capex",
                  "total_assets", "equity", "cash", "short_term_investments", "long_term_investments")
SHARE_ROWS = ("diluted_shares", "eps_diluted")
METRIC_ROWS = ("fcf", "gross_margin", "operating_margin", "net_margin", "fcf_margin", "fcf_conversion", "roe", "roic",
               "return_on_capital_incl_cash",
               "accruals_ratio", "effective_tax_rate", "total_debt", "net_debt", "net_debt_to_ebitda",
               "interest_coverage", "current_ratio", "shareholder_payout", "diluted_shares_change")


def _fmt(value, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "ratio":
        return f"{value:.1%}"
    if unit == "multiple":
        return f"{value:.2f}x"
    if unit == "USD/shares":
        return f"{value:.2f}"
    return f"{value / 1e9:,.1f}"


def _row(label: str, cells: list[str]) -> str:
    return f"{label:<24}" + "".join(f"{c:>10}" for c in cells)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.fundamentals")
    parser.add_argument("ticker")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    edgar = SecEdgar(HttpClient(user_agent_from_env()), DiskCache(CACHE_DIR))
    facts = edgar.company_facts(edgar.cik_for_ticker(args.ticker))
    st = build_annual(facts, as_of=args.as_of)
    metrics = analysis.yearly_metrics(st)
    years = st.fiscal_years[-args.years:]

    print(f"{st.entity_name}  CIK {st.cik}  source SEC EDGAR companyfacts, retrieved {facts.retrieved}"
          f"{f', as of {args.as_of}' if args.as_of else ''}")
    print("USD bn unless noted; shares in bn; EPS in USD\n")
    print(_row("fiscal year end", [str(y) for y in years]))
    for item in STATEMENT_ROWS + SHARE_ROWS:
        unit = "USD/shares" if item == "eps_diluted" else "USD"
        print(_row(item, [_fmt(f.value if (f := st.get(item, y)) else None, unit) for y in years]))
    print()
    for name in METRIC_ROWS:
        print(_row(name, [_fmt(m.value if (m := metrics.get(name, {}).get(y)) else None, m.unit if m else "")
                          for y in years]))

    print("\nGrowth (CAGR to latest fiscal year)")
    for item, by_n in analysis.growth(st, metrics=metrics).items():
        print(_row(item, [f"{n}y {_fmt(d.value, 'ratio')}" for n, d in by_n.items()]))

    print("\nConsistency checks")
    for r in checks.run_all(st):
        if r.passed is not True:
            print(f"  {'FAIL' if r.passed is False else 'N/A '} {r.name} {r.period_end or ''}: {r.detail}")
    print(f"  {sum(r.passed is True for r in checks.run_all(st))} other checks passed")

    print("\nData quality")
    hidden = 0
    for issue in st.issues:
        dates = [date.fromisoformat(d) for d in re.findall(r"(?<!\d)(?:19|20)\d{2}-\d{2}-\d{2}(?!\d)", issue)]
        if dates and max(dates) < years[0] and "split" not in issue:
            hidden += 1
            continue
        print(f"  - {issue}")
    if hidden:
        print(f"  - ({hidden} more issues concern years before {years[0]} only)")
    latest = years[-1]
    for name in METRIC_ROWS:
        m = metrics.get(name, {}).get(latest)
        if m and (m.missing_reason or m.note):
            print(f"  - {name} {latest}: {m.missing_reason or m.note}")


if __name__ == "__main__":
    main()

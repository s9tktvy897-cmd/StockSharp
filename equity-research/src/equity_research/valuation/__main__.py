"""``python -m equity_research.valuation AAPL [options]`` -- two-stage FCFF DCF with sources.

Market inputs come from Stooq (price, regression beta) and Damodaran (ERP, industry beta). When
a source is unreachable the value can be given by hand, but only together with its source
(``--price 231.5 --price-source "Nasdaq official close 2026-10-08"``). Nothing is filled in
silently: without a WACC the model shows value per share over a WACC range instead."""

from __future__ import annotations

import argparse

from equity_research.fundamentals.concepts import DEBT_COMPONENTS
from equity_research.provenance import DerivedValue, SourcedValue
from equity_research.valuation import assumptions as default_assumptions
from equity_research.valuation.run import ValuationRun, add_market_arguments, run


def _origin(v) -> str:
    if isinstance(v, SourcedValue):
        when = f" {v.period_end}" if v.period_end else ""
        return f"{v.source}{when}: {v.reference}"
    if isinstance(v, DerivedValue):
        return v.note or v.formula
    return ""


def _bn(x: float | None) -> str:
    return "-" if x is None else f"{x / 1e9:,.1f}"


def grid_lines(grid: dict) -> list[str]:
    waccs = sorted({w for w, _ in grid})
    growths = sorted({g for _, g in grid})
    lines = ["    " + " " * 8 + "".join(f"{g:>9.2%}" for g in growths)]
    for w in waccs:
        cells = ["-" if grid[(w, g)] is None else f"{grid[(w, g)]:.2f}" for g in growths]
        lines.append(f"    {w:>8.2%}" + "".join(f"{c:>9}" for c in cells))
    return lines


def print_run(r: ValuationRun) -> None:
    p = r.profile
    print(f"# DCF {p.name} ({r.ticker}), valuation date {r.today}")
    print(f"CIK {p.cik}, SIC {p.sic} {p.sic_description}, fiscal year end {p.fiscal_year_end}, "
          f"exchanges {', '.join(p.exchanges)}; USD bn unless noted\n")
    print("## Facts (with source)")
    for item, v in r.flows.items():
        span = f"TTM to {v.period_end}" if v.value is not None else ""
        print(f"  {item + ' (' + span + ')':<44} {_bn(v.value):>10}   {v.missing_reason or v.note or v.formula}")
    print(f"  balance sheet at {r.balance.period_end}:")
    for item in ("cash", "short_term_investments", "long_term_investments", *DEBT_COMPONENTS, "minority_interest"):
        v = r.balance.get(item)
        print(f"    {item:<40} {_bn(v.value):>10}   {getattr(v, 'accession', '') or v.missing_reason or v.note or ''}")
    print(f"  {'diluted shares (bn)':<44} {r.diluted.value / 1e9:>10.3f}   "
          f"{r.diluted.period_start}..{r.diluted.period_end} {r.diluted.accession}")
    print(f"  {'shares outstanding (bn)':<44} {r.outstanding.value / 1e9:>10.3f}   cover {r.outstanding.period_end} "
          f"{r.outstanding.accession}")
    for label, v in (("risk-free rate", r.rf), ("inflation expectation", r.inflation), ("share price (USD)", r.price),
                     ("equity risk premium", r.erp), ("beta", r.beta), ("cost of debt (pre-tax)", r.cost_of_debt)):
        if v is None or v.value is None:
            print(f"  {label:<44} {'MISSING':>10}")
        else:
            shown = f"{v.value:.2f}" if label in ("beta", "share price (USD)") else f"{v.value:.2%}"
            print(f"  {label:<44} {shown:>10}   {_origin(v)}")

    print(f"\n## WACC\n  {'%.2f%%' % (r.wacc * 100) if r.wacc is not None else '-'}  ({r.wacc_text})")
    if r.scenarios:
        print("\n## Assumptions (not data)")
        for scenario, values in r.scenarios.scenarios.items():
            print(f"  {scenario}:")
            for a in values.values():
                print(f"    {a.name:<20} {a.value:>8.2%}   {a.rationale}")
        print(f"    stage 1: {default_assumptions.HIGH_GROWTH_YEARS} years at revenue_growth, then "
              f"{default_assumptions.FADE_YEARS} years fading linearly to terminal_growth")
        for name, why in r.scenarios.missing.items():
            print(f"    MISSING {name}: {why}")

    if r.grid is not None and r.wacc is None:
        print("\n## Value per share without a WACC (base assumptions; WACC not determined)")
        print("\n".join(grid_lines(r.grid)))
    if r.results or r.refused:
        print("\n## Results")
        for scenario in ("bear", "base", "bull"):
            if scenario in r.refused:
                print(f"  {scenario}: refused -- {r.refused[scenario]}")
            elif scenario in r.results:
                x = r.results[scenario]
                print(f"  {scenario:<5} EV {_bn(x.enterprise_value):>8}  equity {_bn(x.equity_value):>8}  "
                      f"per share {x.value_per_share:>8.2f}  TV {x.terminal_share_of_ev:.0%} of EV  "
                      f"implied exit EV/EBIT {x.implied_exit_ev_ebit:.1f}x")
        if "base" in r.results:
            print("\n  base forecast: year, growth, revenue, EBIT, FCFF, discount factor")
            for pr in r.results["base"].projections:
                print(f"    {pr.year:>2} {pr.growth:>7.2%} {_bn(pr.revenue):>8} {_bn(pr.ebit):>8} {_bn(pr.fcff):>8} "
                      f"{pr.discount_factor:.3f}")
    if r.grid is not None and r.wacc is not None:
        print("\n## Sensitivity: base value per share, WACC (rows) x terminal growth (columns)")
        print("\n".join(grid_lines(r.grid)))
    if r.price and r.base_value is not None:
        print(f"\n## Market\n  price {r.price.value:.2f}; base value {r.base_value:.2f} "
              f"({r.base_value / r.price.value - 1:+.1%} vs price)")
        if r.implied_growth is not None:
            print(f"  reverse DCF: the price implies {r.implied_growth:.2%} stage-1 revenue growth "
                  f"(base assumption {r.scenarios['base']['revenue_growth'].value:.2%})")
        else:
            print(f"  reverse DCF: {r.implied_growth_error}")
        if r.multiples:
            print("  TTM multiples: " + ", ".join(
                f"{k} {_bn(v)}" if k in ("market_cap", "enterprise_value") else f"{k} {v:.2f}"
                for k, v in r.multiples.items() if v is not None))
    if r.warnings:
        print("\n## Warnings")
        for w in r.warnings:
            print(f"  - {w}")
    if r.missing:
        print("\n## Missing sources")
        for m in r.missing:
            print(f"  - {m}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.valuation")
    add_market_arguments(parser)
    print_run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    main()

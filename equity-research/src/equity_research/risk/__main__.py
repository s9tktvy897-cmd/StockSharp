"""``python -m equity_research.risk AAPL [valuation options]`` -- quality, risk and screens.

Piotroski F, Altman Z (variant by SIC) and Beneish M for the last fiscal years, market risk from
prices (Yahoo Finance or Stooq), and the undervalued/growth screens of docs/METHODOLOGY.md."""

from __future__ import annotations

import argparse

from equity_research.risk import scores
from equity_research.risk.assess import RiskAssessment, assess
from equity_research.valuation.run import Sources, ValuationRun, add_market_arguments, run

MARK = {True: "+", False: "-", None: "?"}


def print_assessment(r: ValuationRun, a: RiskAssessment) -> None:
    print(f"# Quality and risk: {r.profile.name} ({r.ticker}), SIC {r.profile.sic}, as of {r.today}\n")
    print("## Piotroski F-score (Piotroski 2000; >= 7 strong, <= 3 weak)")
    for y, f in a.piotroski.items():
        print(f"  FY{y.year}: {f.value} of {f.testable} testable signals")
    for s in a.piotroski[a.years[-1]].signals.values():
        print(f"    [{MARK[s.passed]}] {s.name:<20} {s.detail}")

    print("\n## Altman Z")
    for y, line in a.altman.items():
        z = line.result
        if z is None:
            print(f"  FY{y.year}: not applicable -- {line.note}")
            continue
        value = "missing: " + z.missing_reason if z.value is None else f"{z.value:.2f} ({z.zone})"
        print(f"  FY{y.year} {z.variant:<3} {value}" + (f"  -- {line.note}" if line.note and y == a.years[0] else ""))
        if y == a.years[-1] and z.value is not None:
            print("    " + ", ".join(f"{k} {v:.3f}" for k, v in z.components.items()))
            if z.components.get("x2_retained_earnings", 0) < 0:
                print("    note: retained earnings are negative (e.g. after buybacks), which lowers X2 regardless of risk")

    print(f"\n## Beneish M-score (8 variables, flag above {scores.BENEISH_THRESHOLD})")
    for y, m in a.beneish.items():
        if m.value is None:
            print(f"  FY{y.year}: {m.missing_reason}")
        else:
            print(f"  FY{y.year}: {m.value:.2f} ({'FLAG' if m.flagged else 'below threshold'})  "
                  + ", ".join(f"{k} {v:.3f}" for k, v in m.components.items()))

    print("\n## Market risk (prices: Yahoo Finance or Stooq, secondary)")
    if a.market:
        print(f"  volatility ({a.market['months']} monthly returns, annualized) {a.market['volatility']:.1%}")
        print(f"  max drawdown (5 years of daily closes) {a.market['max_drawdown']:.1%}")
        print(f"  beta vs S&P 500 {a.market['beta']:.2f}")
    else:
        print(f"  missing: {a.market_missing}")

    print("\n## Screens (docs/METHODOLOGY.md; thresholds are hypotheses until backtested)")
    for result in a.screens:
        print(f"  {result.name}: {({True: 'PASSES', False: 'fails', None: 'cannot be decided'})[result.passed]}")
        for c in result.criteria.values():
            detail = c.detail.replace("ROIC", a.roic_label, 1) if c.name == "roic_above_wacc" else c.detail
            print(f"    [{MARK[c.passed]}] {c.name:<26} {detail}")
    if r.missing:
        print("\n## Missing sources")
        for m in r.missing:
            print(f"  - {m}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.risk")
    add_market_arguments(parser)
    sources = Sources.live()
    r = run(parser.parse_args(argv), sources)
    print_assessment(r, assess(r, sources))


if __name__ == "__main__":
    main()

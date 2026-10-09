"""``python -m equity_research.risk AAPL [valuation options]`` -- quality, risk and screens.

Piotroski F, Altman Z (variant by SIC) and Beneish M for the last fiscal years, market risk from
prices (Stooq), and the undervalued/growth screens of docs/METHODOLOGY.md, which reuse the
valuation (``valuation.run``)."""

from __future__ import annotations

import argparse

from equity_research.data.prices import close_on_or_before
from equity_research.fundamentals import analysis
from equity_research.provenance import MissingDataError
from equity_research.risk import market, scores
from equity_research.risk.scores import NotApplicableError
from equity_research.screening import screens
from equity_research.valuation.run import FETCH_ERRORS, Sources, add_market_arguments, run

YEARS = 3


def _altman(r, sources, year):
    try:
        variant = scores.altman_variant(r.profile.sic)
    except NotApplicableError as error:
        return None, str(error)
    if variant == "Z''":
        return scores.altman(r.st, year, "Z''"), None
    note = None
    try:
        close = close_on_or_before(sources.stooq.daily_closes(r.ticker), year)
        shares = r.st.get("diluted_shares", year)
        z = scores.altman(r.st, year, "Z", market_value_equity=close.value * shares.value if shares else None)
    except FETCH_ERRORS as error:
        z = scores.altman(r.st, year, "Z")
        note = f"market value at fiscal year end unavailable ({error.__class__.__name__}): " \
               "showing the book-based Z'' instead (a different model with its own zones)"
    if z.value is None:
        fallback = scores.altman(r.st, year, "Z''")
        return fallback, note or z.missing_reason
    return z, note


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.risk")
    add_market_arguments(parser)
    args = parser.parse_args(argv)
    sources = Sources.live()
    r = run(args, sources)
    years = r.st.fiscal_years[-YEARS:]
    print(f"# Quality and risk: {r.profile.name} ({r.ticker}), SIC {r.profile.sic}, as of {r.today}\n")

    print("## Piotroski F-score (Piotroski 2000; >= 7 strong, <= 3 weak)")
    f_scores = {y: scores.piotroski(r.st, y) for y in years}
    for y, f in f_scores.items():
        print(f"  FY{y.year}: {f.value} of {f.testable} testable signals")
    latest = f_scores[years[-1]]
    for s in latest.signals.values():
        mark = {True: "+", False: "-", None: "?"}[s.passed]
        print(f"    [{mark}] {s.name:<20} {s.detail}")

    print("\n## Altman Z")
    zones = {}
    for y in years:
        z, note = _altman(r, sources, y)
        if z is None:
            print(f"  FY{y.year}: not applicable -- {note}")
            continue
        # The screen only trusts the zone of the variant that fits the company (no silent fallback).
        zones[y] = z.zone if z.variant == scores.altman_variant(r.profile.sic) else None
        value = "missing: " + z.missing_reason if z.value is None else f"{z.value:.2f} ({z.zone})"
        print(f"  FY{y.year} {z.variant:<3} {value}" + (f"  -- {note}" if note and y == years[0] else ""))
        if y == years[-1] and z.components.get("x2_retained_earnings", 0) < 0:
            print("    note: retained earnings are negative (e.g. after buybacks), which lowers X2 regardless of risk")
        if y == years[-1] and z.value is not None:
            print("    " + ", ".join(f"{k} {v:.3f}" for k, v in z.components.items()))

    print(f"\n## Beneish M-score (8 variables, flag above {scores.BENEISH_THRESHOLD})")
    flags = {}
    for y in years:
        m = scores.beneish(r.st, y)
        flags[y] = m.flagged
        if m.value is None:
            print(f"  FY{y.year}: {m.missing_reason}")
            continue
        print(f"  FY{y.year}: {m.value:.2f} ({'FLAG' if m.flagged else 'below threshold'})  "
              + ", ".join(f"{k} {v:.3f}" for k, v in m.components.items()))

    print("\n## Market risk (prices: Stooq, secondary)")
    try:
        stock, index = sources.stooq.daily_closes(r.ticker), sources.stooq.daily_closes("^SPX")
        five_years = [p.value for p in stock if (r.today - p.period_end).days <= 5 * 365]
        s, m = market.aligned_monthly_returns(stock, index, 60)
        print(f"  volatility (60 monthly returns, annualized) {market.annualized_volatility(s, 12):.1%}")
        print(f"  max drawdown (5 years of daily closes) {market.max_drawdown(five_years):.1%}")
        print(f"  beta vs S&P 500 (60 months) {market.beta(s, m):.2f}")
    except (*FETCH_ERRORS, MissingDataError) as error:
        print(f"  missing: {error}")

    print("\n## Screens (docs/METHODOLOGY.md; thresholds are hypotheses until backtested)")
    growth_by = analysis.growth(r.st, metrics=r.metrics)["revenue"]
    roic = r.metrics["roic"].get(years[-1])
    roic_value, roic_label = (roic.value, "ROIC") if roic and roic.value is not None else (
        r.metrics["return_on_capital_incl_cash"][years[-1]].value, "return on capital incl. cash (ROIC undefined)")
    results = [
        screens.undervalued(r.base_value, r.price.value if r.price else None, latest.value,
                            zones.get(years[-1]), flags.get(years[-1])),
        screens.growth(growth_by[5].value if 5 in growth_by else None,
                       {y: v.value for y, v in r.metrics["fcf"].items()}, roic_value, r.wacc),
    ]
    for result in results:
        verdict = {True: "PASSES", False: "fails", None: "cannot be decided"}[result.passed]
        print(f"  {result.name}: {verdict}")
        for c in result.criteria.values():
            mark = {True: "+", False: "-", None: "?"}[c.passed]
            detail = c.detail.replace("ROIC", roic_label, 1) if c.name == "roic_above_wacc" else c.detail
            print(f"    [{mark}] {c.name:<26} {detail}")
    if r.missing:
        print("\n## Missing sources")
        for m in r.missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()

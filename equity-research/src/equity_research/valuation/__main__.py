"""``python -m equity_research.valuation AAPL [options]`` -- two-stage FCFF DCF with sources.

Market inputs come from Stooq (price, regression beta) and Damodaran (ERP, industry beta). When
a source is unreachable the value can be given by hand, but only together with its source
(``--price 231.5 --price-source "Nasdaq official close 2026-10-08"``). Nothing is filled in
silently: without a WACC the model shows value per share over a WACC range instead."""

from __future__ import annotations

import argparse
import dataclasses
import urllib.error
from datetime import date

from equity_research.data.__main__ import CACHE_DIR
from equity_research.data.cache import DiskCache
from equity_research.data.damodaran import Damodaran
from equity_research.data.fred import Fred, latest_on_or_before
from equity_research.data.http import HttpClient, HttpError, user_agent_from_env
from equity_research.data.prices import Stooq, close_on_or_before
from equity_research.data.sec_edgar import SecEdgar
from equity_research.fundamentals import analysis
from equity_research.fundamentals.concepts import DEBT_COMPONENTS
from equity_research.fundamentals.ratios import UndefinedRatioError
from equity_research.fundamentals.statements import build_annual
from equity_research.fundamentals.ttm import latest_balance, latest_share_count, ttm
from equity_research.provenance import Assumption, DerivedValue, MissingDataError, SourcedValue
from equity_research.risk import market
from equity_research.valuation import assumptions as default_assumptions
from equity_research.valuation import dcf, multiples, wacc as capm
from equity_research.valuation.dcf import DcfInputs, EquityBridge

FETCH_ERRORS = (HttpError, urllib.error.URLError, OSError, MissingDataError, ValueError, LookupError)
TV_WARNING = 0.75


class Report:
    def __init__(self) -> None:
        self.missing: list[str] = []
        self.warnings: list[str] = []

    def attempt(self, label: str, fetch):
        try:
            return fetch()
        except FETCH_ERRORS as error:
            self.missing.append(f"{label}: {error}")
            return None


def _manual(value: float | None, source: str | None, name: str, unit: str, today: date) -> SourcedValue | None:
    if value is None:
        return None
    if not source:
        raise SystemExit(f"--{name} needs --{name}-source: every number needs its origin")
    return SourcedValue(value=value, unit=unit, source=f"manual input: {source}", reference=source, retrieved=today)


def _pct(series_id: str, fred: Fred, day: date) -> SourcedValue:
    fact = latest_on_or_before(fred.series(series_id), day)
    return dataclasses.replace(fact, value=fact.value / 100, unit="ratio")


def _origin(v) -> str:
    if isinstance(v, SourcedValue):
        when = f" {v.period_end}" if v.period_end else ""
        return f"{v.source}{when}: {v.reference}"
    if isinstance(v, DerivedValue):
        return v.note or v.formula
    return ""


def _bn(x: float | None) -> str:
    return "-" if x is None else f"{x / 1e9:,.1f}"


def _implied_cost_of_debt(st, metrics) -> DerivedValue:
    for year in reversed(st.fiscal_years):
        interest, debt = st.get("interest_expense", year), metrics["total_debt"].get(year)
        years = st.fiscal_years
        prev = years[years.index(year) - 1] if years.index(year) > 0 else None
        prior_debt = metrics["total_debt"].get(prev) if prev else None
        if interest and debt and debt.value and prior_debt and prior_debt.value:
            value = interest.value / ((debt.value + prior_debt.value) / 2)
            stale = year != st.fiscal_years[-1]
            return DerivedValue("cost_of_debt", value, "ratio", "interest_expense / average total_debt",
                                (interest, debt, prior_debt), year, None,
                                f"FY{year.year}" + (" (latest year with reported interest expense; stale)" if stale else ""))
    return DerivedValue("cost_of_debt", None, "ratio", "interest_expense / average total_debt", (), None,
                        "no year with both interest expense and debt")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m equity_research.valuation")
    p.add_argument("ticker")
    p.add_argument("--as-of", type=date.fromisoformat, default=None, help="valuation date (default: today)")
    p.add_argument("--industry", help="Damodaran industry name for a bottom-up beta (an analyst choice)")
    for name in ("price", "beta", "erp", "cost-of-debt"):
        p.add_argument(f"--{name}", type=float)
        p.add_argument(f"--{name}-source")
    p.add_argument("--wacc", type=float, help="override WACC (an assumption; give --wacc-rationale)")
    p.add_argument("--wacc-rationale")
    args = p.parse_args(argv)

    today = args.as_of or date.today()
    report = Report()
    client, cache = HttpClient(user_agent_from_env()), DiskCache(CACHE_DIR)
    edgar, fred = SecEdgar(client, cache), Fred(client, cache)
    stooq, damodaran = Stooq(client, cache), Damodaran(client, cache)

    cik = edgar.cik_for_ticker(args.ticker)
    profile = edgar.profile(cik)
    if profile.sic.isdigit() and 6000 <= int(profile.sic) <= 6799:
        raise SystemExit(f"{profile.name} is a financial company (SIC {profile.sic}): an FCFF DCF does not apply; "
                         "use a dividend or excess-return model (not built yet).")
    facts = edgar.company_facts(cik)
    st = build_annual(facts, as_of=args.as_of)
    metrics = analysis.yearly_metrics(st)

    # --- facts --------------------------------------------------------------------------------
    flows = {item: ttm(facts, item, as_of=args.as_of) for item in
             ("revenue", "operating_income", "net_income", "operating_cash_flow", "capex")}
    balance = latest_balance(facts, st, as_of=args.as_of)
    diluted = latest_share_count(facts, st.splits, as_of=args.as_of)
    outstanding = latest_share_count(facts, st.splits, as_of=args.as_of,
                                     concept="EntityCommonStockSharesOutstanding", taxonomy="dei")
    debt_parts = [balance.get(c) for c in DEBT_COMPONENTS]
    debt = None if any(d.value is None for d in debt_parts) else sum(d.value for d in debt_parts)
    if debt is None:
        report.missing += [f"debt: {d.missing_reason}" for d in debt_parts if d.value is None]

    rf = report.attempt("risk-free rate (FRED DGS10)", lambda: _pct("DGS10", fred, today))
    inflation = report.attempt("inflation expectation (FRED T10YIE)", lambda: _pct("T10YIE", fred, today))

    price = _manual(args.price, args.price_source, "price", "USD/share", today) or report.attempt(
        "share price (Stooq)", lambda: close_on_or_before(stooq.daily_closes(args.ticker), today))
    erp = _manual(args.erp, args.erp_source, "erp", "ratio", today) or report.attempt(
        "equity risk premium (Damodaran implied ERP)", damodaran.implied_erp)
    cost_of_debt = _manual(args.cost_of_debt, args.cost_of_debt_source, "cost-of-debt", "ratio", today) \
        or _implied_cost_of_debt(st, metrics)
    if cost_of_debt.value is None:
        report.missing.append(f"cost of debt: {cost_of_debt.missing_reason}")

    market_cap = price.value * outstanding.value if price and outstanding else None
    tax_history = default_assumptions._recent(metrics.get("effective_tax_rate", {}), 3)
    tax = sum(v for _, v in tax_history) / len(tax_history) if tax_history else None

    beta = _manual(args.beta, args.beta_source, "beta", "beta", today)
    if beta is None and args.industry and market_cap and debt is not None and tax is not None:
        unlevered = report.attempt(f"industry beta (Damodaran, {args.industry})",
                                   lambda: damodaran.industry_beta(args.industry))
        if unlevered:
            beta = DerivedValue("beta", capm.relever_beta(unlevered.value, debt / market_cap, tax), "beta",
                                "Hamada: unlevered industry beta * (1 + (1 - t) * D/E)", (unlevered,), today,
                                note=f"bottom-up: {args.industry} unlevered {unlevered.value:.2f}, D/E {debt / market_cap:.1%}")
    if beta is None:
        def regression():
            s, m = market.aligned_monthly_returns(stooq.daily_closes(args.ticker), stooq.daily_closes("^SPX"), 60)
            if len(s) < 24:
                raise MissingDataError(f"only {len(s)} monthly returns")
            return DerivedValue("beta", market.beta(s, m), "beta", "OLS on 60 monthly returns vs S&P 500 (Stooq ^SPX)",
                                (), today, note=f"regression on {len(s)} months (secondary price source)")
        beta = report.attempt("regression beta (Stooq)", regression)

    # --- WACC ---------------------------------------------------------------------------------
    wacc_value: float | None = None
    wacc_text = ""
    if args.wacc is not None:
        if not args.wacc_rationale:
            raise SystemExit("--wacc needs --wacc-rationale: an assumption needs its reasoning")
        wacc_value, wacc_text = args.wacc, f"assumption: {args.wacc_rationale}"
    else:
        need = {"risk-free rate": rf, "beta": beta, "ERP": erp, "cost of debt": cost_of_debt.value,
                "market cap (price x shares)": market_cap, "debt": debt, "tax rate": tax}
        absent = [k for k, v in need.items() if v is None]
        if absent:
            wacc_text = f"not determined, missing: {', '.join(absent)}"
        else:
            re = capm.cost_of_equity(rf.value, beta.value, erp.value)
            wacc_value = capm.wacc(market_cap, debt, re, cost_of_debt.value, tax)
            wacc_text = (f"r_e = {rf.value:.2%} + {beta.value:.2f} x {erp.value:.2%} = {re:.2%}; "
                         f"r_d = {cost_of_debt.value:.2%}; t = {tax:.1%}; "
                         f"E/V = {market_cap / (market_cap + debt):.1%} (market cap), D/V at book value")

    scenario_set = default_assumptions.default_scenarios(st, metrics, rf, inflation, wacc_value) if rf and inflation \
        else None

    # --- print: scope and facts ---------------------------------------------------------------
    print(f"# DCF {profile.name} ({args.ticker.upper()}), valuation date {today}")
    print(f"CIK {profile.cik}, SIC {profile.sic} {profile.sic_description}, fiscal year end {profile.fiscal_year_end}, "
          f"exchanges {', '.join(profile.exchanges)}; USD bn unless noted\n")
    print("## Facts (with source)")
    for item, v in flows.items():
        span = f"TTM to {v.period_end}" if v.value is not None else ""
        print(f"  {item + ' (' + span + ')':<44} {_bn(v.value):>10}   {v.missing_reason or v.note or v.formula}")
    print(f"  balance sheet at {balance.period_end}:")
    for item in ("cash", "short_term_investments", "long_term_investments", *DEBT_COMPONENTS, "minority_interest"):
        v = balance.get(item)
        print(f"    {item:<40} {_bn(v.value):>10}   {getattr(v, 'accession', '') or v.missing_reason or v.note or ''}")
    print(f"  {'diluted shares (bn)':<44} {diluted.value / 1e9:>10.3f}   {diluted.period_start}..{diluted.period_end} "
          f"{diluted.accession}")
    print(f"  {'shares outstanding (bn)':<44} {outstanding.value / 1e9:>10.3f}   cover {outstanding.period_end} "
          f"{outstanding.accession}")
    for label, v in (("risk-free rate", rf), ("inflation expectation", inflation), ("share price (USD)", price),
                     ("equity risk premium", erp), ("beta", beta), ("cost of debt (pre-tax)", cost_of_debt)):
        if v is None or v.value is None:
            print(f"  {label:<44} {'MISSING':>10}")
        else:
            shown = f"{v.value:.2f}" if label in ("beta", "share price (USD)") else f"{v.value:.2%}"
            print(f"  {label:<44} {shown:>10}   {_origin(v)}")

    print(f"\n## WACC\n  {'%.2f%%' % (wacc_value * 100) if wacc_value is not None else '-'}  ({wacc_text})")

    if scenario_set is None:
        print("\nNo assumptions: risk-free rate or inflation expectation missing.")
        _print_missing(report)
        return
    print("\n## Assumptions (not data)")
    for scenario, values in scenario_set.scenarios.items():
        print(f"  {scenario}:")
        for a in values.values():
            print(f"    {a.name:<20} {a.value:>8.2%}   {a.rationale}")
    print(f"    stage 1: {default_assumptions.HIGH_GROWTH_YEARS} years at revenue_growth, then "
          f"{default_assumptions.FADE_YEARS} years fading linearly to terminal_growth")
    for name, why in scenario_set.missing.items():
        print(f"    MISSING {name}: {why}")

    missing_bridge = [k for k, v in {"debt": debt, "cash": balance.get("cash").value,
                                     "securities": balance.get("short_term_investments").value,
                                     "long-term securities": balance.get("long_term_investments").value,
                                     "minority interest": balance.get("minority_interest").value}.items() if v is None]
    if missing_bridge or flows["revenue"].value is None or not scenario_set.complete("base"):
        print(f"\nDCF not computed; missing: {', '.join(missing_bridge) or 'assumptions or TTM revenue'}")
        _print_missing(report)
        return
    bridge = EquityBridge(cash=balance.get("cash").value,
                          investments=balance.get("short_term_investments").value + balance.get("long_term_investments").value,
                          debt=debt, minority_interest=balance.get("minority_interest").value,
                          diluted_shares=diluted.value)

    def inputs(scenario: dict[str, Assumption], wacc_rate: float) -> DcfInputs:
        return DcfInputs(base_revenue=flows["revenue"].value, base_period_end=flows["revenue"].period_end,
                         valuation_date=today, high_growth_years=default_assumptions.HIGH_GROWTH_YEARS,
                         fade_years=default_assumptions.FADE_YEARS, wacc=wacc_rate,
                         **{k: scenario[k].value for k in default_assumptions.REQUIRED})

    base = scenario_set["base"]
    g = base["terminal_growth"].value
    if wacc_value is None:
        print("\n## Value per share without a WACC (base assumptions; WACC not determined)")
        _grid(dcf.sensitivity(inputs(base, 0.08), bridge, [x / 100 for x in range(6, 13)], [g - 0.01, g, g + 0.01]))
        _print_missing(report)
        return

    print("\n## Results")
    results = {}
    for scenario in ("bear", "base", "bull"):
        if not scenario_set.complete(scenario):
            print(f"  {scenario}: incomplete assumptions")
            continue
        try:
            results[scenario] = r = dcf.value(inputs(scenario_set[scenario], wacc_value), bridge)
        except UndefinedRatioError as error:
            print(f"  {scenario}: refused -- {error}")
            continue
        print(f"  {scenario:<5} EV {_bn(r.enterprise_value):>8}  equity {_bn(r.equity_value):>8}  "
              f"per share {r.value_per_share:>8.2f}  TV {r.terminal_share_of_ev:.0%} of EV  "
              f"implied exit EV/EBIT {r.implied_exit_ev_ebit:.1f}x")
        if r.terminal_share_of_ev > TV_WARNING:
            report.warnings.append(f"{scenario}: terminal value is {r.terminal_share_of_ev:.0%} of EV (> 75%)")
    if "base" in results:
        print("\n  base forecast: year, growth, revenue, EBIT, FCFF, discount factor")
        for pr in results["base"].projections:
            print(f"    {pr.year:>2} {pr.growth:>7.2%} {_bn(pr.revenue):>8} {_bn(pr.ebit):>8} {_bn(pr.fcff):>8} "
                  f"{pr.discount_factor:.3f}")

    print("\n## Sensitivity: base value per share, WACC (rows) x terminal growth (columns)")
    _grid(dcf.sensitivity(inputs(base, wacc_value), bridge,
                          [wacc_value + d / 100 for d in (-2, -1, 0, 1, 2)], [g + d / 1000 for d in (-10, -5, 0, 5, 10)]))

    if price and "base" in results:
        mos = results["base"].value_per_share / price.value - 1
        print(f"\n## Market\n  price {price.value:.2f}; base value {results['base'].value_per_share:.2f} "
              f"({mos:+.1%} vs price)")
        try:
            implied = dcf.implied_growth(inputs(base, wacc_value), bridge, price.value)
            print(f"  reverse DCF: the price implies {implied:.2%} stage-1 revenue growth "
                  f"(base assumption {base['revenue_growth'].value:.2%})")
        except UndefinedRatioError as error:
            print(f"  reverse DCF: {error}")
        m = multiples.market_multiples(price.value, outstanding.value, debt, bridge.cash, bridge.investments,
                                       bridge.minority_interest, flows["revenue"].value,
                                       flows["operating_income"].value, flows["net_income"].value,
                                       flows["operating_cash_flow"].value - flows["capex"].value)
        print("  TTM multiples: " + ", ".join(f"{k} {v:.2f}" if isinstance(v, float) and v < 1e6 else f"{k} {_bn(v)}"
                                             for k, v in m.items() if v is not None))
    if g > (rf.value if rf else g):
        report.warnings.append("terminal growth exceeds the risk-free rate")
    _print_missing(report)


def _grid(grid: dict) -> None:
    waccs = sorted({w for w, _ in grid})
    growths = sorted({g for _, g in grid})
    print("    " + " " * 8 + "".join(f"{g:>9.2%}" for g in growths))
    for w in waccs:
        cells = ["-" if grid[(w, g)] is None else f"{grid[(w, g)]:.2f}" for g in growths]
        print(f"    {w:>8.2%}" + "".join(f"{c:>9}" for c in cells))


def _print_missing(report: Report) -> None:
    if report.warnings:
        print("\n## Warnings")
        for w in report.warnings:
            print(f"  - {w}")
    if report.missing:
        print("\n## Missing sources")
        for m in report.missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()

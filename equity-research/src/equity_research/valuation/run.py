"""End-to-end valuation of one company: fetch sourced facts and market inputs, derive the
default assumptions, compute WACC, scenarios, sensitivity, reverse DCF and multiples.

Network failures and missing values are collected in ``missing`` (never filled in). Market
values may be supplied by hand, but only together with their source."""

from __future__ import annotations

import argparse
import dataclasses
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from equity_research.data.__main__ import CACHE_DIR
from equity_research.data.cache import DiskCache
from equity_research.data.damodaran import Damodaran
from equity_research.data.fred import Fred, latest_on_or_before
from equity_research.data.http import HttpClient, HttpError, user_agent_from_env
from equity_research.data.prices import Stooq, close_on_or_before
from equity_research.data.sec_edgar import CompanyFacts, CompanyProfile, EdgarFact, SecEdgar
from equity_research.fundamentals import analysis
from equity_research.fundamentals.concepts import DEBT_COMPONENTS
from equity_research.fundamentals.ratios import UndefinedRatioError
from equity_research.fundamentals.statements import AnnualStatements, build_annual
from equity_research.fundamentals.ttm import LatestBalance, latest_balance, latest_share_count, ttm
from equity_research.provenance import Assumption, DerivedValue, MissingDataError, SourcedValue
from equity_research.risk import market
from equity_research.valuation import assumptions as default_assumptions
from equity_research.valuation import dcf, multiples, wacc as capm
from equity_research.valuation.assumptions import ScenarioSet
from equity_research.valuation.dcf import DcfInputs, DcfResult, EquityBridge

FETCH_ERRORS = (HttpError, urllib.error.URLError, OSError, MissingDataError, ValueError, LookupError)
TV_WARNING = 0.75
FINANCIAL_SIC = range(6000, 6800)


class NotApplicable(SystemExit):
    pass


def add_market_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("ticker")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="valuation date (default: today)")
    parser.add_argument("--industry", help="Damodaran industry name for a bottom-up beta (an analyst choice)")
    for name in ("price", "beta", "erp", "cost-of-debt"):
        parser.add_argument(f"--{name}", type=float)
        parser.add_argument(f"--{name}-source")
    parser.add_argument("--wacc", type=float, help="override WACC (an assumption; give --wacc-rationale)")
    parser.add_argument("--wacc-rationale")


@dataclass
class Sources:
    edgar: SecEdgar
    fred: Fred
    stooq: Stooq
    damodaran: Damodaran
    yahoo: "YahooPrices | None" = None

    @classmethod
    def live(cls) -> "Sources":
        from equity_research.data.yahoo import YahooPrices

        client, cache = HttpClient(user_agent_from_env()), DiskCache(CACHE_DIR)
        return cls(SecEdgar(client, cache), Fred(client, cache), Stooq(client, cache), Damodaran(client, cache),
                   YahooPrices(CACHE_DIR))

    def closes(self, ticker: str) -> list[SourcedValue]:
        """Daily closes: Yahoo Finance first, Stooq as fallback (both secondary sources)."""
        errors = []
        for name, provider in (("Yahoo", self.yahoo), ("Stooq", self.stooq)):
            if provider is None:
                continue
            try:
                return provider.daily_closes(ticker)
            except Exception as error:  # noqa: BLE001 -- any provider failure falls through to the next
                errors.append(f"{name}: {error}")
        raise MissingDataError("; ".join(errors) or "no price provider")


@dataclass
class ValuationRun:
    ticker: str
    today: date
    profile: CompanyProfile
    facts: CompanyFacts
    st: AnnualStatements
    metrics: dict
    flows: dict[str, DerivedValue]
    balance: LatestBalance
    diluted: EdgarFact
    outstanding: EdgarFact
    debt: float | None
    rf: SourcedValue | None
    inflation: SourcedValue | None
    price: SourcedValue | None
    erp: SourcedValue | None
    beta: SourcedValue | DerivedValue | None
    cost_of_debt: SourcedValue | DerivedValue
    market_cap: float | None
    tax: float | None
    wacc: float | None
    wacc_text: str
    scenarios: ScenarioSet | None = None
    bridge: EquityBridge | None = None
    results: dict[str, DcfResult] = field(default_factory=dict)
    refused: dict[str, str] = field(default_factory=dict)
    grid: dict | None = None
    implied_growth: float | None = None
    implied_growth_error: str | None = None
    multiples: dict | None = None
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    make_inputs: Callable[[dict[str, Assumption], float], DcfInputs] | None = None

    @property
    def base_value(self) -> float | None:
        return self.results["base"].value_per_share if "base" in self.results else None


def _attempt(missing: list[str], label: str, fetch):
    try:
        return fetch()
    except FETCH_ERRORS as error:
        missing.append(f"{label}: {error}")
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


def implied_cost_of_debt(st: AnnualStatements, metrics: dict) -> DerivedValue:
    years = st.fiscal_years
    for index in range(len(years) - 1, 0, -1):
        year, prev = years[index], years[index - 1]
        interest, debt, prior = st.get("interest_expense", year), metrics["total_debt"].get(year), \
            metrics["total_debt"].get(prev)
        if interest and debt and debt.value and prior and prior.value:
            stale = year != years[-1]
            return DerivedValue("cost_of_debt", interest.value / ((debt.value + prior.value) / 2), "ratio",
                                "interest_expense / average total_debt", (interest, debt, prior), year, None,
                                f"FY{year.year}" + (" (latest year with reported interest expense; stale)" if stale else ""))
    return DerivedValue("cost_of_debt", None, "ratio", "interest_expense / average total_debt", (), None,
                        "no year with both interest expense and debt")


def run(args: argparse.Namespace, sources: Sources | None = None) -> ValuationRun:
    sources = sources or Sources.live()
    today = args.as_of or date.today()
    missing: list[str] = []

    profile = sources.edgar.profile(sources.edgar.cik_for_ticker(args.ticker))
    if profile.sic.isdigit() and int(profile.sic) in FINANCIAL_SIC:
        raise NotApplicable(f"{profile.name} is a financial company (SIC {profile.sic}): an FCFF DCF does not apply; "
                            "use a dividend or excess-return model (not built yet).")
    facts = sources.edgar.company_facts(profile.cik)
    st = build_annual(facts, as_of=args.as_of)
    metrics = analysis.yearly_metrics(st)

    flows = {item: ttm(facts, item, as_of=args.as_of) for item in
             ("revenue", "operating_income", "net_income", "operating_cash_flow", "capex")}
    balance = latest_balance(facts, st, as_of=args.as_of)
    diluted = latest_share_count(facts, st.splits, as_of=args.as_of)
    outstanding = latest_share_count(facts, st.splits, as_of=args.as_of,
                                     concept="EntityCommonStockSharesOutstanding", taxonomy="dei")
    debt_parts = [balance.get(c) for c in DEBT_COMPONENTS]
    debt = None if any(d.value is None for d in debt_parts) else sum(d.value for d in debt_parts)
    if debt is None:
        missing += [f"debt: {d.missing_reason}" for d in debt_parts if d.value is None]

    rf = _attempt(missing, "risk-free rate (FRED DGS10)", lambda: _pct("DGS10", sources.fred, today))
    inflation = _attempt(missing, "inflation expectation (FRED T10YIE)", lambda: _pct("T10YIE", sources.fred, today))
    price = _manual(args.price, args.price_source, "price", "USD/share", today) or _attempt(
        missing, "share price (Yahoo/Stooq)", lambda: close_on_or_before(sources.closes(args.ticker), today))
    erp = _manual(args.erp, args.erp_source, "erp", "ratio", today) or _attempt(
        missing, "equity risk premium (Damodaran implied ERP)", sources.damodaran.implied_erp)
    cost_of_debt = _manual(args.cost_of_debt, args.cost_of_debt_source, "cost-of-debt", "ratio", today) \
        or implied_cost_of_debt(st, metrics)
    if cost_of_debt.value is None:
        missing.append(f"cost of debt: {cost_of_debt.missing_reason}")

    market_cap = price.value * outstanding.value if price and outstanding else None
    tax_history = default_assumptions._recent(metrics.get("effective_tax_rate", {}), 3)
    tax = sum(v for _, v in tax_history) / len(tax_history) if tax_history else None

    beta = _manual(args.beta, args.beta_source, "beta", "beta", today)
    if beta is None and args.industry and market_cap and debt is not None and tax is not None:
        unlevered = _attempt(missing, f"industry beta (Damodaran, {args.industry})",
                             lambda: sources.damodaran.industry_beta(args.industry))
        if unlevered:
            beta = DerivedValue("beta", capm.relever_beta(unlevered.value, debt / market_cap, tax), "beta",
                                "Hamada: unlevered industry beta * (1 + (1 - t) * D/E)", (unlevered,), today,
                                note=f"bottom-up: {args.industry} unlevered {unlevered.value:.2f}, "
                                     f"D/E {debt / market_cap:.1%}")
    if beta is None:
        def regression():
            s, m = market.aligned_monthly_returns(sources.closes(args.ticker), sources.closes("^SPX"), 60)
            if len(s) < 24:
                raise MissingDataError(f"only {len(s)} monthly returns")
            return DerivedValue("beta", market.beta(s, m), "beta", "OLS on monthly returns vs the S&P 500 index (secondary price source)",
                                (), today, note=f"regression on {len(s)} months (secondary price source)")
        beta = _attempt(missing, "regression beta (Yahoo/Stooq)", regression)

    wacc_value, wacc_text = None, ""
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

    out = ValuationRun(args.ticker.upper(), today, profile, facts, st, metrics, flows, balance, diluted, outstanding,
                       debt, rf, inflation, price, erp, beta, cost_of_debt, market_cap, tax, wacc_value, wacc_text,
                       missing=missing)
    if not (rf and inflation):
        return out
    out.scenarios = default_assumptions.default_scenarios(st, metrics, rf, inflation, wacc_value)

    bridge_values = {"debt": debt, "cash": balance.get("cash").value,
                     "securities": balance.get("short_term_investments").value,
                     "long-term securities": balance.get("long_term_investments").value,
                     "minority interest": balance.get("minority_interest").value}
    absent = [k for k, v in bridge_values.items() if v is None]
    if absent or flows["revenue"].value is None or not out.scenarios.complete("base"):
        missing.append(f"DCF not computed; missing: {', '.join(absent) or 'assumptions or TTM revenue'}")
        return out
    out.bridge = EquityBridge(cash=bridge_values["cash"],
                              investments=bridge_values["securities"] + bridge_values["long-term securities"],
                              debt=debt, minority_interest=bridge_values["minority interest"],
                              diluted_shares=diluted.value)

    def make_inputs(scenario: dict[str, Assumption], wacc_rate: float) -> DcfInputs:
        return DcfInputs(base_revenue=flows["revenue"].value, base_period_end=flows["revenue"].period_end,
                         valuation_date=today, high_growth_years=default_assumptions.HIGH_GROWTH_YEARS,
                         fade_years=default_assumptions.FADE_YEARS, wacc=wacc_rate,
                         **{k: scenario[k].value for k in default_assumptions.REQUIRED})
    out.make_inputs = make_inputs

    base = out.scenarios["base"]
    g = base["terminal_growth"].value
    if wacc_value is None:
        out.grid = dcf.sensitivity(make_inputs(base, 0.08), out.bridge, [x / 100 for x in range(6, 13)],
                                   [g - 0.01, g, g + 0.01])
        return out

    for scenario in ("bear", "base", "bull"):
        if not out.scenarios.complete(scenario):
            out.refused[scenario] = "incomplete assumptions"
            continue
        try:
            out.results[scenario] = r = dcf.value(make_inputs(out.scenarios[scenario], wacc_value), out.bridge)
        except UndefinedRatioError as error:
            out.refused[scenario] = str(error)
            continue
        if r.terminal_share_of_ev > TV_WARNING:
            out.warnings.append(f"{scenario}: terminal value is {r.terminal_share_of_ev:.0%} of EV (> 75%)")
    out.grid = dcf.sensitivity(make_inputs(base, wacc_value), out.bridge,
                               [wacc_value + d / 100 for d in (-2, -1, 0, 1, 2)],
                               [g + d / 1000 for d in (-10, -5, 0, 5, 10)])
    if price and "base" in out.results:
        try:
            out.implied_growth = dcf.implied_growth(make_inputs(base, wacc_value), out.bridge, price.value)
        except UndefinedRatioError as error:
            out.implied_growth_error = str(error)
        out.multiples = multiples.market_multiples(
            price.value, outstanding.value, debt, out.bridge.cash, out.bridge.investments,
            out.bridge.minority_interest, flows["revenue"].value, flows["operating_income"].value,
            flows["net_income"].value, flows["operating_cash_flow"].value - flows["capex"].value)
    if rf and g > rf.value:
        out.warnings.append("terminal growth exceeds the risk-free rate")
    return out

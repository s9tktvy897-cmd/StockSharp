"""Yearly fundamental metrics and growth rates. Every result is a DerivedValue that keeps its
input facts; a metric that cannot be computed carries the reason instead of a number."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from equity_research.fundamentals import ratios
from equity_research.fundamentals.concepts import DEBT_COMPONENTS
from equity_research.fundamentals.ratios import UndefinedRatioError
from equity_research.fundamentals.statements import AnnualStatements
from equity_research.data.sec_edgar import EdgarFact
from equity_research.provenance import DerivedValue

# Balance-sheet components (investments, debt parts) that a company may simply not have: an item
# it never reports counts as zero with a note; a gap in an item it does report is missing data.


def derive(name: str, unit: str, formula: str, year: date | None, fn: Callable[..., float], note: str | None = None,
           **inputs) -> DerivedValue:
    present = tuple(v for v in inputs.values() if v is not None and v.value is not None)
    missing = [v.missing_reason for v in inputs.values() if v.value is None]
    if missing:
        return DerivedValue(name, None, unit, formula, present, year, "; ".join(missing), note)
    try:
        value = fn(*(v.value for v in inputs.values()))
    except UndefinedRatioError as error:
        return DerivedValue(name, None, unit, formula, present, year, str(error), note)
    return DerivedValue(name, value, unit, formula, present, year, None, note)


def _optional(st: AnnualStatements, item: str, year: date) -> DerivedValue | EdgarFact:
    fact = st.get(item, year)
    if fact is not None:
        return fact
    if st.items.get(item):
        reported = sorted(st.items[item])
        return DerivedValue(item, None, "USD", item, (), year,
                            f"{item} reported for {reported[0]}..{reported[-1]} but not for {year}")
    return DerivedValue(item, 0.0, "USD", f"{item} never reported", (), year, None, f"{item} never reported, taken as 0")


def _total_debt(st: AnnualStatements, year: date) -> DerivedValue:
    formula = " + ".join(DEBT_COMPONENTS) + " (reported components; leases excluded)"
    parts = [_optional(st, c, year) for c in DEBT_COMPONENTS]
    gaps = [p.missing_reason for p in parts if p.value is None]
    if gaps:
        return DerivedValue("total_debt", None, "USD", formula, (), year, "; ".join(gaps))
    if all(isinstance(p, DerivedValue) for p in parts):
        return DerivedValue("total_debt", None, "USD", formula, (), year, "no debt component ever reported")
    notes = [p.note for p in parts if isinstance(p, DerivedValue)]
    return DerivedValue("total_debt", sum(p.value for p in parts), "USD", formula,
                        tuple(p for p in parts if not isinstance(p, DerivedValue)), year, None,
                        "; ".join(notes) or None)


def _fact(st: AnnualStatements, item: str, year: date | None) -> EdgarFact | DerivedValue:
    """The reported fact, or a placeholder whose missing_reason says what is absent."""
    if year is None:
        return DerivedValue(item, None, "", item, (), None, f"{item}: no prior fiscal year")
    return st.get(item, year) or DerivedValue(item, None, "", item, (), year, f"{item} not reported for {year}")


def _invested_capital(st: AnnualStatements, year: date, debt: DerivedValue) -> DerivedValue:
    return derive("invested_capital", "USD", "equity + total_debt - cash - short_term_investments - long_term_investments",
                  year, lambda e, d, c, s, l: ratios.invested_capital(e, d, c, s + l),
                  e=_fact(st, "equity", year), d=debt, c=_fact(st, "cash", year),
                  s=_optional(st, "short_term_investments", year), l=_optional(st, "long_term_investments", year))


def yearly_metrics(st: AnnualStatements) -> dict[str, dict[date, DerivedValue]]:
    out: dict[str, dict[date, DerivedValue]] = {}

    def put(metric: DerivedValue) -> DerivedValue:
        out.setdefault(metric.name, {})[metric.period_end] = metric
        return metric

    years = st.fiscal_years
    for index, y in enumerate(years):
        # The prior fiscal year must be adjacent (52/53-week years), not the year before a gap.
        prev = years[index - 1] if index > 0 and (y - years[index - 1]).days <= 380 else None
        g = lambda item, year=y: _fact(st, item, year)
        revenue, ni, ocf = g("revenue"), g("net_income"), g("operating_cash_flow")

        fcf = put(derive("fcf", "USD", "operating_cash_flow - capex", y, lambda o, c: o - c, o=ocf, c=g("capex")))
        gross = st.get("gross_profit", y) or derive("gross_profit", "USD", "revenue - cost_of_revenue", y,
                                                    lambda r, c: r - c, r=revenue, c=g("cost_of_revenue"))
        put(derive("gross_margin", "ratio", "gross_profit / revenue", y, ratios.safe_div, n=gross, d=revenue))
        put(derive("operating_margin", "ratio", "operating_income / revenue", y, ratios.safe_div,
                   n=g("operating_income"), d=revenue))
        put(derive("net_margin", "ratio", "net_income / revenue", y, ratios.safe_div, n=ni, d=revenue))
        put(derive("fcf_margin", "ratio", "fcf / revenue", y, ratios.safe_div, n=fcf, d=revenue))
        put(derive("fcf_conversion", "ratio", "fcf / net_income", y, ratios.safe_div, n=fcf, d=ni))
        tax = put(derive("effective_tax_rate", "ratio", "income_tax / pretax_income", y, ratios.effective_tax_rate,
                         t=g("income_tax"), p=g("pretax_income")))
        nopat = put(derive("nopat", "USD", "operating_income * (1 - effective_tax_rate)", y, ratios.nopat,
                           e=g("operating_income"), t=tax))
        debt = put(_total_debt(st, y))
        net_debt = put(derive("net_debt", "USD", "total_debt - cash - short_term_investments", y, ratios.net_debt,
                              d=debt, c=g("cash"), s=_optional(st, "short_term_investments", y)))
        ebitda = put(derive("ebitda", "USD", "operating_income + depreciation_amortization", y, lambda o, d: o + d,
                            o=g("operating_income"), d=g("depreciation_amortization")))
        put(derive("net_debt_to_ebitda", "multiple", "net_debt / ebitda", y, ratios.net_debt_to_ebitda,
                   n=net_debt, e=ebitda))
        put(derive("interest_coverage", "multiple", "operating_income / interest_expense", y, ratios.interest_coverage,
                   e=g("operating_income"), i=g("interest_expense")))
        put(derive("current_ratio", "multiple", "current_assets / current_liabilities", y, ratios.safe_div,
                   a=g("current_assets"), l=g("current_liabilities")))
        ic = put(_invested_capital(st, y, debt))
        capital = put(derive("capital_incl_cash", "USD", "equity + total_debt", y, lambda e, d: e + d,
                             e=g("equity"), d=debt))
        put(derive("shareholder_payout", "ratio", "(dividends_paid + buybacks) / fcf", y,
                   lambda d, b, f: ratios.safe_div(d + b, f), d=g("dividends_paid"), b=g("buybacks"), f=fcf))

        for name, formula, fn, inputs in (
            ("roe", "net_income / average equity", ratios.return_on_average,
             dict(n=ni, b=g("equity", prev), e=g("equity"))),
            ("roic", "nopat / average invested_capital", ratios.roic,
             dict(n=nopat, b=out["invested_capital"][prev] if prev else _fact(st, "invested_capital", None), e=ic)),
            ("return_on_capital_incl_cash", "nopat / average (equity + total_debt)", ratios.return_on_average,
             dict(n=nopat, b=out["capital_incl_cash"][prev] if prev else _fact(st, "capital_incl_cash", None),
                  e=capital)),
            ("accruals_ratio", "(net_income - operating_cash_flow) / average total_assets", ratios.accruals_ratio,
             dict(n=ni, o=ocf, b=g("total_assets", prev), e=g("total_assets"))),
            ("diluted_shares_change", "diluted_shares / prior diluted_shares - 1", lambda b, e: ratios.safe_div(e, b) - 1,
             dict(b=g("diluted_shares", prev), e=g("diluted_shares"))),
        ):
            put(derive(name, "ratio", formula, y, fn, **inputs))
    return out


GROWTH_ITEMS = ("revenue", "operating_income", "net_income", "eps_diluted", "fcf")


def growth(st: AnnualStatements, periods: tuple[int, ...] = (3, 5, 10),
           metrics: dict[str, dict[date, DerivedValue]] | None = None) -> dict[str, dict[int, DerivedValue]]:
    metrics = metrics or yearly_metrics(st)
    years = st.fiscal_years
    out: dict[str, dict[int, DerivedValue]] = {}
    for item in GROWTH_ITEMS:
        source = metrics.get(item) or {y: st.get(item, y) for y in years}
        for n in periods:
            name = f"{item}_cagr_{n}y"
            formula = f"({item} latest / {item} {n} years earlier)^(1/{n}) - 1"
            if len(years) <= n:
                out.setdefault(item, {})[n] = DerivedValue(name, None, "ratio", formula, (), years[-1] if years else None,
                                                           f"only {len(years)} fiscal years available")
                continue
            end, start = years[-1], years[-1 - n]
            out.setdefault(item, {})[n] = derive(name, "ratio", formula, end, lambda s, e: ratios.cagr(s, e, n),
                                                 s=source.get(start) or _fact(st, item, start),
                                                 e=source.get(end) or _fact(st, item, end))
    return out

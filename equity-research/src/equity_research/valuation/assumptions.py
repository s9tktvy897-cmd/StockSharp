"""Default DCF assumptions derived from the company's own reported history and market data.

They are assumptions, not facts: every one carries a rationale naming the history it comes
from, and the analyst can override any of them. Bear/base/bull differ in revenue growth, EBIT
margin and RONIC; WACC and terminal growth are varied in the sensitivity grid instead."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from equity_research.fundamentals import analysis
from equity_research.fundamentals.statements import AnnualStatements
from equity_research.provenance import Assumption, DerivedValue, SourcedValue

HIGH_GROWTH_YEARS = 5
FADE_YEARS = 5
REQUIRED = ("revenue_growth", "ebit_margin", "tax_rate", "da_pct_revenue", "capex_pct_revenue", "nwc_pct_revenue",
            "terminal_growth", "ronic")


@dataclass
class ScenarioSet:
    scenarios: dict[str, dict[str, Assumption]]
    missing: dict[str, str] = field(default_factory=dict)  # assumption name -> why it could not be derived

    def __getitem__(self, name: str) -> dict[str, Assumption]:
        return self.scenarios[name]

    def complete(self, scenario: str) -> bool:
        return all(key in self.scenarios[scenario] for key in REQUIRED)


def mean_of(values: list[float], label: str) -> float:
    if not values:
        raise LookupError(f"no reported history for {label}")
    return sum(values) / len(values)


def _recent(series: dict[date, DerivedValue], n: int) -> list[tuple[date, float]]:
    points = sorted((d, v.value) for d, v in series.items() if v.value is not None)
    return points[-n:]


def _span(points: list[tuple[date, float]]) -> str:
    return f"FY{points[0][0].year}-FY{points[-1][0].year}" if points else "none"


def _fmt(points: list[tuple[date, float]]) -> str:
    return ", ".join(f"FY{d.year} {v:.1%}" for d, v in points)


def _share_of_revenue(st: AnnualStatements, item: str, n: int = 3) -> list[tuple[date, float]]:
    points = []
    for year in st.fiscal_years:
        value, revenue = st.get(item, year), st.get("revenue", year)
        if value and revenue and revenue.value:
            points.append((year, value.value / revenue.value))
    return points[-n:]


def _operating_nwc_share(st: AnnualStatements, n: int = 3) -> list[tuple[date, float]]:
    points = []
    for year in st.fiscal_years:
        parts = {name: analysis._optional(st, name, year) for name in
                 ("short_term_investments", "long_term_debt_current", "commercial_paper", "short_term_borrowings")}
        core = {name: st.get(name, year) for name in ("current_assets", "cash", "current_liabilities", "revenue")}
        if any(v is None or v.value is None for v in list(parts.values()) + list(core.values())):
            continue
        assets = core["current_assets"].value - core["cash"].value - parts["short_term_investments"].value
        liabilities = (core["current_liabilities"].value - parts["long_term_debt_current"].value
                       - parts["commercial_paper"].value - parts["short_term_borrowings"].value)
        points.append((year, (assets - liabilities) / core["revenue"].value))
    return points[-n:]


def default_scenarios(st: AnnualStatements, metrics: dict[str, dict[date, DerivedValue]],
                      risk_free: SourcedValue, inflation: SourcedValue, wacc: float | None = None) -> ScenarioSet:
    base: dict[str, Assumption] = {}
    bear: dict[str, Assumption] = {}
    bull: dict[str, Assumption] = {}
    missing: dict[str, str] = {}

    growth = analysis.growth(st, metrics=metrics)["revenue"]
    cagrs = [(n, d.value) for n, d in growth.items() if d.value is not None]
    if cagrs:
        listed = ", ".join(f"{n}y {v:.1%}" for n, v in cagrs)
        values = [v for _, v in cagrs]
        bear["revenue_growth"] = Assumption("revenue_growth", min(values), f"lowest reported revenue CAGR ({listed})")
        base["revenue_growth"] = Assumption("revenue_growth", median(values), f"median reported revenue CAGR ({listed})")
        bull["revenue_growth"] = Assumption("revenue_growth", max(values), f"highest reported revenue CAGR ({listed})")
    else:
        missing["revenue_growth"] = "no revenue CAGR computable"

    margins = metrics.get("operating_margin", {})
    last5, last3 = _recent(margins, 5), _recent(margins, 3)
    if last3:
        base["ebit_margin"] = Assumption("ebit_margin", mean_of([v for _, v in last3], "EBIT margin"),
                                         f"mean operating margin {_span(last3)} ({_fmt(last3)})")
        bear["ebit_margin"] = Assumption("ebit_margin", min(v for _, v in last5),
                                         f"lowest operating margin {_span(last5)} ({_fmt(last5)})")
        bull["ebit_margin"] = Assumption("ebit_margin", max(v for _, v in last5),
                                         f"highest operating margin {_span(last5)} ({_fmt(last5)})")
    else:
        missing["ebit_margin"] = "no operating margin history"

    def shared(name: str, points: list[tuple[date, float]], label: str) -> None:
        if not points:
            missing[name] = f"no reported history for {label}"
            return
        base[name] = Assumption(name, mean_of([v for _, v in points], label),
                                f"mean {label} {_span(points)} ({_fmt(points)})")

    shared("tax_rate", _recent(metrics.get("effective_tax_rate", {}), 3), "effective tax rate")
    shared("da_pct_revenue", _share_of_revenue(st, "depreciation_amortization"), "D&A / revenue")
    shared("capex_pct_revenue", _share_of_revenue(st, "capex"), "capex / revenue")
    shared("nwc_pct_revenue", _operating_nwc_share(st),
           "operating NWC / revenue ((current assets - cash - securities) - (current liabilities - short-term debt))")

    if inflation.value is not None and risk_free.value is not None:
        cap = inflation.value > risk_free.value
        base["terminal_growth"] = Assumption(
            "terminal_growth", min(inflation.value, risk_free.value),
            f"market-implied inflation ({inflation.source} {inflation.reference}, {inflation.period_end}: "
            f"{inflation.value:.2%}), i.e. zero real growth in perpetuity"
            + (f"; capped at the risk-free rate {risk_free.value:.2%}" if cap else ""))
    else:
        missing["terminal_growth"] = "inflation expectation or risk-free rate missing"

    roc = _recent(metrics.get("return_on_capital_incl_cash", {}), 3)
    if roc:
        base["ronic"] = Assumption("ronic", mean_of([v for _, v in roc], "return on capital"),
                                   f"mean return on capital incl. cash {_span(roc)} ({_fmt(roc)})")
        bull["ronic"] = base["ronic"]
    else:
        missing["ronic"] = "no return-on-capital history"
    if wacc is not None:
        bear["ronic"] = Assumption("ronic", wacc, "new capital earns only its cost (RONIC = WACC): no excess returns")
    else:
        missing.setdefault("ronic (bear)", "bear RONIC equals WACC, which is not determined")

    shared_keys = ("tax_rate", "da_pct_revenue", "capex_pct_revenue", "nwc_pct_revenue", "terminal_growth")
    for scenario in (bear, bull):
        for key in shared_keys:
            if key in base:
                scenario[key] = base[key]
    return ScenarioSet({"bear": bear, "base": base, "bull": bull}, missing)

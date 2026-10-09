"""Quality and manipulation scores from the original papers (pure, on AnnualStatements).

- Piotroski (2000) F-score: nine binary signals, year t against t-1.
- Altman (1968) Z for public manufacturers; Altman (1995) Z'' for non-manufacturers.
- Beneish (1999) eight-variable M-score.

A signal or score whose inputs are missing is None with a reason, never a guess."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from equity_research.fundamentals import analysis
from equity_research.fundamentals.statements import AnnualStatements

BENEISH_THRESHOLD = -1.78
ALTMAN_ZONES = {"Z": (2.99, 1.81), "Z''": (2.60, 1.10)}  # (safe above, distress below)


class NotApplicableError(ValueError):
    pass


@dataclass(frozen=True)
class Signal:
    name: str
    passed: bool | None
    detail: str


@dataclass
class PiotroskiResult:
    year: date
    value: int
    testable: int
    signals: dict[str, Signal]


@dataclass
class ScoreResult:
    name: str
    year: date
    value: float | None
    components: dict[str, float] = field(default_factory=dict)
    missing_reason: str | None = None
    zone: str | None = None
    flagged: bool | None = None
    variant: str | None = None


def _v(st: AnnualStatements, item: str, year: date | None) -> float | None:
    fact = st.get(item, year) if year else None
    return fact.value if fact else None


def _optional_v(st: AnnualStatements, item: str, year: date | None) -> float | None:
    return analysis._optional(st, item, year).value if year else None


def prior_year(st: AnnualStatements, year: date) -> date | None:
    dates = {d for values in st.items.values() for d in values}
    earlier = [d for d in dates if d < year and (year - d).days <= 380]
    return max(earlier) if earlier else None


def _gross_profit(st: AnnualStatements, year: date | None) -> float | None:
    gross = _v(st, "gross_profit", year)
    if gross is not None:
        return gross
    revenue, cost = _v(st, "revenue", year), _v(st, "cost_of_revenue", year)
    return revenue - cost if revenue is not None and cost is not None else None


def _div(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0) else None


def _avg(a: float | None, b: float | None) -> float | None:
    return (a + b) / 2 if a is not None and b is not None else None


def _signal(name: str, now: float | None, before: float | None, test, label: str) -> Signal:
    if now is None or before is None:
        return Signal(name, None, f"{label}: input missing")
    return Signal(name, bool(test(now, before)), f"{label}: {now:.4g} vs {before:.4g}")


def piotroski(st: AnnualStatements, year: date) -> PiotroskiResult:
    t1 = prior_year(st, year)
    t2 = prior_year(st, t1) if t1 else None
    ta = {y: _v(st, "total_assets", y) for y in (year, t1, t2)}
    roa = _div(_v(st, "net_income", year), ta[t1])
    roa_prev = _div(_v(st, "net_income", t1), ta[t2])
    cfo = _div(_v(st, "operating_cash_flow", year), ta[t1])
    leverage = _div(_optional_v(st, "long_term_debt_noncurrent", year), _avg(ta[year], ta[t1]))
    leverage_prev = _div(_optional_v(st, "long_term_debt_noncurrent", t1), _avg(ta[t1], ta[t2]))
    current = _div(_v(st, "current_assets", year), _v(st, "current_liabilities", year))
    current_prev = _div(_v(st, "current_assets", t1), _v(st, "current_liabilities", t1))
    margin = _div(_gross_profit(st, year), _v(st, "revenue", year))
    margin_prev = _div(_gross_profit(st, t1), _v(st, "revenue", t1))
    turnover = _div(_v(st, "revenue", year), ta[t1])
    turnover_prev = _div(_v(st, "revenue", t1), ta[t2])

    signals = [
        _signal("roa_positive", roa, 0.0, lambda a, b: a > b, "ROA (NI / beginning assets) > 0"),
        _signal("cfo_positive", cfo, 0.0, lambda a, b: a > b, "CFO / beginning assets > 0"),
        _signal("delta_roa", roa, roa_prev, lambda a, b: a > b, "ROA up"),
        _signal("accruals", cfo, roa, lambda a, b: a > b, "CFO/assets > ROA"),
        _signal("delta_leverage", leverage, leverage_prev, lambda a, b: a <= b,
                "long-term debt / average assets not up"),
        _signal("delta_liquidity", current, current_prev, lambda a, b: a > b, "current ratio up"),
        _signal("no_dilution", _v(st, "diluted_shares", year), _v(st, "diluted_shares", t1), lambda a, b: a <= b,
                "diluted shares not up (proxy for no equity issue)"),
        _signal("delta_gross_margin", margin, margin_prev, lambda a, b: a > b, "gross margin up"),
        _signal("delta_turnover", turnover, turnover_prev, lambda a, b: a > b, "asset turnover up"),
    ]
    return PiotroskiResult(year, sum(s.passed is True for s in signals), sum(s.passed is not None for s in signals),
                           {s.name: s for s in signals})


def altman_variant(sic: str) -> str:
    code = int(sic) if sic and sic.isdigit() else None
    if code is not None and 6000 <= code <= 6799:
        raise NotApplicableError(f"Altman Z does not apply to financial companies (SIC {sic})")
    return "Z" if code is not None and 2000 <= code <= 3999 else "Z''"


def altman_zone(value: float, variant: str) -> str:
    safe, distress = ALTMAN_ZONES[variant]
    return "safe" if value > safe else "distress" if value < distress else "grey"


def altman(st: AnnualStatements, year: date, variant: str, market_value_equity: float | None = None) -> ScoreResult:
    ta = _v(st, "total_assets", year)
    equity = _v(st, "equity_including_nci", year) or _v(st, "equity", year)
    liabilities = _v(st, "total_liabilities", year)
    if liabilities is None and _v(st, "liabilities_and_equity", year) is not None and equity is not None:
        liabilities = _v(st, "liabilities_and_equity", year) - equity
    inputs = {"current_assets": _v(st, "current_assets", year), "current_liabilities": _v(st, "current_liabilities", year),
              "total_assets": ta, "retained_earnings": _v(st, "retained_earnings", year),
              "operating_income": _v(st, "operating_income", year), "total_liabilities": liabilities}
    if variant == "Z":
        inputs |= {"market value of equity": market_value_equity, "revenue": _v(st, "revenue", year)}
    else:
        inputs |= {"book equity": equity}
    absent = [k for k, v in inputs.items() if v is None]
    if absent or not ta or not liabilities:
        return ScoreResult("altman", year, None, missing_reason=f"missing: {', '.join(absent) or 'zero denominator'}",
                           variant=variant)
    x = {"x1_working_capital": (inputs["current_assets"] - inputs["current_liabilities"]) / ta,
         "x2_retained_earnings": inputs["retained_earnings"] / ta,
         "x3_ebit": inputs["operating_income"] / ta}
    if variant == "Z":
        x |= {"x4_market_equity_to_liabilities": market_value_equity / liabilities, "x5_sales": inputs["revenue"] / ta}
        value = (1.2 * x["x1_working_capital"] + 1.4 * x["x2_retained_earnings"] + 3.3 * x["x3_ebit"]
                 + 0.6 * x["x4_market_equity_to_liabilities"] + 1.0 * x["x5_sales"])
    else:
        x |= {"x4_book_equity_to_liabilities": equity / liabilities}
        value = (6.56 * x["x1_working_capital"] + 3.26 * x["x2_retained_earnings"] + 6.72 * x["x3_ebit"]
                 + 1.05 * x["x4_book_equity_to_liabilities"])
    return ScoreResult("altman", year, value, x, zone=altman_zone(value, variant), variant=variant)


def beneish(st: AnnualStatements, year: date) -> ScoreResult:
    t1 = prior_year(st, year)
    need = {}
    for y, tag in ((year, "t"), (t1, "t-1")):
        for item in ("receivables", "revenue", "current_assets", "ppe_net", "total_assets",
                     "depreciation_amortization", "sga", "current_liabilities"):
            need[f"{item} ({tag})"] = _v(st, item, y)
        need[f"gross_profit ({tag})"] = _gross_profit(st, y)
        need[f"long_term_debt_noncurrent ({tag})"] = _optional_v(st, "long_term_debt_noncurrent", y)
    need["net_income (t)"] = _v(st, "net_income", year)
    need["operating_cash_flow (t)"] = _v(st, "operating_cash_flow", year)
    absent = [k for k, v in need.items() if v is None]
    if t1 is None or absent:
        return ScoreResult("beneish", year, None, missing_reason="missing: " + (", ".join(absent) or "prior year"))

    def g(item: str, tag: str) -> float:
        return need[f"{item} ({tag})"]

    def ratio(fn) -> float:
        return fn("t") / fn("t-1")

    c = {
        "dsri": ratio(lambda t: g("receivables", t) / g("revenue", t)),
        "gmi": 1 / ratio(lambda t: g("gross_profit", t) / g("revenue", t)),
        "aqi": ratio(lambda t: 1 - (g("current_assets", t) + g("ppe_net", t)) / g("total_assets", t)),
        "sgi": ratio(lambda t: g("revenue", t)),
        "depi": 1 / ratio(lambda t: g("depreciation_amortization", t)
                          / (g("depreciation_amortization", t) + g("ppe_net", t))),
        "sgai": ratio(lambda t: g("sga", t) / g("revenue", t)),
        "lvgi": ratio(lambda t: (g("current_liabilities", t) + g("long_term_debt_noncurrent", t)) / g("total_assets", t)),
        "tata": (need["net_income (t)"] - need["operating_cash_flow (t)"]) / g("total_assets", "t"),
    }
    value = (-4.84 + 0.920 * c["dsri"] + 0.528 * c["gmi"] + 0.404 * c["aqi"] + 0.892 * c["sgi"] + 0.115 * c["depi"]
             - 0.172 * c["sgai"] + 4.679 * c["tata"] - 0.327 * c["lvgi"])
    return ScoreResult("beneish", year, value, c, flagged=value > BENEISH_THRESHOLD)

"""Quality, risk and screens for one company on top of a ValuationRun."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from equity_research.data.prices import close_on_or_before
from equity_research.fundamentals import analysis
from equity_research.provenance import MissingDataError
from equity_research.risk import market, scores
from equity_research.risk.scores import NotApplicableError, PiotroskiResult, ScoreResult
from equity_research.screening import screens
from equity_research.screening.screens import ScreenResult
from equity_research.valuation.run import FETCH_ERRORS, Sources, ValuationRun

YEARS = 3


@dataclass
class AltmanLine:
    result: ScoreResult | None
    note: str | None
    fits_company: bool  # the variant matches the company's SIC; only then the screen uses the zone


@dataclass
class RiskAssessment:
    years: list[date]
    piotroski: dict[date, PiotroskiResult]
    altman: dict[date, AltmanLine]
    beneish: dict[date, ScoreResult]
    market: dict[str, float] = field(default_factory=dict)
    market_missing: str | None = None
    screens: list[ScreenResult] = field(default_factory=list)
    roic_label: str = "ROIC"


def _altman(r: ValuationRun, sources: Sources, year: date) -> AltmanLine:
    try:
        variant = scores.altman_variant(r.profile.sic)
    except NotApplicableError as error:
        return AltmanLine(None, str(error), False)
    if variant == "Z''":
        return AltmanLine(scores.altman(r.st, year, "Z''"), None, True)
    try:
        close = close_on_or_before(sources.closes(r.ticker), year)
        shares = r.st.get("diluted_shares", year)
        z = scores.altman(r.st, year, "Z", market_value_equity=close.value * shares.value if shares else None)
        note = None
    except FETCH_ERRORS as error:
        z = scores.altman(r.st, year, "Z")
        note = f"market value at fiscal year end unavailable ({error.__class__.__name__})"
    if z.value is None:
        return AltmanLine(scores.altman(r.st, year, "Z''"),
                          (note or z.missing_reason) + "; showing the book-based Z'' (a different model with its "
                          "own zones), which the screen does not use", False)
    return AltmanLine(z, note, True)


def assess(r: ValuationRun, sources: Sources, years: int = YEARS) -> RiskAssessment:
    fiscal = r.st.fiscal_years[-years:]
    out = RiskAssessment(fiscal, {y: scores.piotroski(r.st, y) for y in fiscal},
                         {y: _altman(r, sources, y) for y in fiscal}, {y: scores.beneish(r.st, y) for y in fiscal})
    try:
        stock, index = sources.closes(r.ticker), sources.closes("^SPX")
        five_years = [p.value for p in stock if (r.today - p.period_end).days <= 5 * 365]
        s, m = market.aligned_monthly_returns(stock, index, 60)
        out.market = {"volatility": market.annualized_volatility(s, 12), "max_drawdown": market.max_drawdown(five_years),
                      "beta": market.beta(s, m), "months": len(s)}
    except (*FETCH_ERRORS, MissingDataError) as error:
        out.market_missing = str(error)

    if not fiscal:
        return out
    latest = fiscal[-1]
    altman = out.altman[latest]
    roic = r.metrics["roic"].get(latest)
    if roic and roic.value is not None:
        roic_value = roic.value
    else:
        roc = r.metrics["return_on_capital_incl_cash"].get(latest)
        roic_value, out.roic_label = (roc.value if roc else None), "return on capital incl. cash (ROIC undefined)"
    revenue_growth = analysis.growth(r.st, metrics=r.metrics)["revenue"]
    out.screens = [
        screens.undervalued(r.base_value, r.price.value if r.price else None, out.piotroski[latest].value,
                            altman.result.zone if altman.result and altman.fits_company else None,
                            out.beneish[latest].flagged),
        screens.growth(revenue_growth[5].value if 5 in revenue_growth else None,
                       {y: v.value for y, v in r.metrics["fcf"].items()}, roic_value, r.wacc),
    ]
    return out

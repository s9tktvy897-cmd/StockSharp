"""Value and growth screens with the thresholds of docs/METHODOLOGY.md.

Three-valued: a criterion passes, fails, or is unknown (missing input). A screen fails as soon
as one criterion fails, passes only when all pass, and is unknown otherwise."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MARGIN_OF_SAFETY = 1.25
MIN_PIOTROSKI = 5
MIN_REVENUE_CAGR_5Y = 0.10
MIN_FCF_YEARS = 3


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool | None
    detail: str


@dataclass
class ScreenResult:
    name: str
    criteria: dict[str, Criterion]

    @property
    def passed(self) -> bool | None:
        outcomes = [c.passed for c in self.criteria.values()]
        if False in outcomes:
            return False
        return True if all(o is True for o in outcomes) else None


def _crit(name: str, ok: bool | None, detail: str) -> Criterion:
    return Criterion(name, ok, detail)


def undervalued(intrinsic_value: float | None, price: float | None, piotroski: int | None, altman_zone: str | None,
                beneish_flagged: bool | None) -> ScreenResult:
    if intrinsic_value is None or price is None:
        mos = _crit("margin_of_safety", None, "base-case value or price missing")
    else:
        mos = _crit("margin_of_safety", intrinsic_value >= MARGIN_OF_SAFETY * price,
                    f"value {intrinsic_value:.2f} vs {MARGIN_OF_SAFETY} x price {price:.2f}")
    return ScreenResult("undervalued", {c.name: c for c in (
        mos,
        _crit("piotroski", None if piotroski is None else piotroski >= MIN_PIOTROSKI,
              f"F-score {piotroski} (>= {MIN_PIOTROSKI})"),
        _crit("altman_not_distress", None if altman_zone is None else altman_zone != "distress",
              f"zone {altman_zone}" if altman_zone else "no zone from the Altman variant that fits the company"),
        _crit("beneish_below_threshold", None if beneish_flagged is None else not beneish_flagged,
              "flagged" if beneish_flagged else "not flagged" if beneish_flagged is False else "unknown"),
    )})


def growth(revenue_cagr_5y: float | None, fcf_by_year: dict[date, float | None], roic: float | None,
           wacc: float | None) -> ScreenResult:
    years = sorted(fcf_by_year)
    if len(years) < 6 or any(fcf_by_year[y] is None for y in years[-6:]):
        fcf = _crit("fcf_positive_and_rising", None, "fewer than 6 consecutive fiscal years of FCF")
    else:
        last = years[-6:]
        hits = sum(fcf_by_year[b] > 0 and fcf_by_year[b] > fcf_by_year[a] for a, b in zip(last, last[1:]))
        fcf = _crit("fcf_positive_and_rising", hits >= MIN_FCF_YEARS, f"{hits} of 5 years positive and rising "
                                                                       f"(>= {MIN_FCF_YEARS})")
    return ScreenResult("growth", {c.name: c for c in (
        _crit("revenue_cagr_5y", None if revenue_cagr_5y is None else revenue_cagr_5y >= MIN_REVENUE_CAGR_5Y,
              "missing" if revenue_cagr_5y is None else f"{revenue_cagr_5y:.1%} (>= {MIN_REVENUE_CAGR_5Y:.0%})"),
        fcf,
        _crit("roic_above_wacc", None if roic is None or wacc is None else roic > wacc,
              "ROIC or WACC missing" if roic is None or wacc is None else f"{roic:.1%} vs WACC {wacc:.1%}"),
    )})

"""Point-in-time replay of the long-term screens (phase 5).

On each rebalance date the statements are rebuilt from the filings public on that date
(``build_annual(as_of=...)``), the scores and screen criteria are computed, and the stock's
return over the following ``horizon_days`` is measured from the next open. Results are reported
as excess return over the equal-weighted universe on the same date, so market swings cancel out.

Biases to keep in mind (also printed in the report): survivorship (a universe of today's
listings misses companies that disappeared), small samples, and data snooping when thresholds
are tuned on the same history."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from equity_research.data.sec_edgar import CompanyFacts
from equity_research.fundamentals import analysis
from equity_research.fundamentals.statements import build_annual
from equity_research.risk import scores
from equity_research.risk.scores import NotApplicableError
from equity_research.shortterm.bars import Bars
from equity_research.shortterm.evaluation import wilson

MAX_STATEMENT_AGE = timedelta(days=456)  # 15 months: the latest fiscal year must be this recent


@dataclass(frozen=True)
class Observation:
    ticker: str
    rebalance: date
    fiscal_year: date
    signals: dict
    forward_return: float | None


def forward_return(bars: Bars, start: date, horizon_days: int) -> float | None:
    """From the first open after ``start`` to the last close within ``horizon_days`` of that entry.
    None when the history stops before the horizon (delisting, missing data)."""
    after = [i for i, d in enumerate(bars.dates) if d > start]
    if not after:
        return None
    i = after[0]
    end = bars.dates[i] + timedelta(days=horizon_days)
    if bars.dates[-1] < end - timedelta(days=7):
        return None
    j = max(k for k, d in enumerate(bars.dates) if d <= end)
    return float(bars.close[j] / bars.open[i] - 1)


def _market_value(bars: Bars | None, day: date, shares) -> float | None:
    """Price actually traded on ``day`` (not adjusted for later splits) x the share count reported
    as of then; an adjusted price would understate the value after any later split."""
    if bars is None or shares is None or shares.value is None:
        return None
    before = [i for i, d in enumerate(bars.dates) if d <= day]
    return float(bars.traded_close[before[-1]] * shares.value) if before else None


def _ratio(numerator, denominator: float | None) -> float | None:
    value = getattr(numerator, "value", numerator)
    if value is None or denominator is None or not denominator > 0:
        return None
    return float(value) / denominator


def observe(ticker: str, sic: str, facts: CompanyFacts, bars: Bars | None, rebalance: date,
            horizon_days: int = 365) -> Observation | None:
    st = build_annual(facts, as_of=rebalance)
    if not st.fiscal_years or rebalance - st.fiscal_years[-1] > MAX_STATEMENT_AGE:
        return None
    fy = st.fiscal_years[-1]
    metrics = analysis.yearly_metrics(st)
    signals: dict = {}
    f = scores.piotroski(st, fy)
    signals["piotroski"], signals["piotroski_testable"] = f.value, f.testable
    m = scores.beneish(st, fy)
    signals["beneish_flagged"] = m.flagged
    try:
        variant = scores.altman_variant(sic)
        z = scores.altman(st, fy, variant, _market_value(bars, fy, st.get("diluted_shares", fy)) if variant == "Z" else None)
        signals["altman_zone"] = z.zone
    except NotApplicableError:
        signals["altman_zone"] = None
    growth = analysis.growth(st, periods=(5,), metrics=metrics)["revenue"][5].value
    signals["revenue_cagr_5y"] = growth
    fcf = [metrics["fcf"][y].value for y in st.fiscal_years[-6:] if y in metrics["fcf"]]
    rising = sum(b is not None and a is not None and b > 0 and b > a for a, b in zip(fcf, fcf[1:]))
    signals["fcf_rising_years"] = rising if len(fcf) == 6 else None
    # simple valuation factors at the rebalance date (market value from the traded price then)
    mcap = _market_value(bars, rebalance, st.get("diluted_shares", fy))
    signals["market_cap"] = mcap
    signals["earnings_yield"] = _ratio(st.get("net_income", fy), mcap)
    signals["fcf_yield"] = _ratio(metrics["fcf"].get(fy), mcap)
    signals["book_to_market"] = _ratio(st.get("equity", fy), mcap)
    return Observation(ticker, rebalance, fy, signals, forward_return(bars, rebalance, horizon_days) if bars else None)


def _ranks(x: list[float]) -> np.ndarray:
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x))
    values = np.asarray(x, dtype=float)[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and values[j + 1] == values[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    if len(x) < 3:
        return float("nan")
    rx, ry = _ranks(x), _ranks(y)
    return float(np.corrcoef(rx, ry)[0, 1])


def _excess(observations: list[Observation]) -> dict[int, float]:
    by_date = defaultdict(list)
    for k, o in enumerate(observations):
        if o.forward_return is not None:
            by_date[o.rebalance].append(k)
    excess = {}
    for rows in by_date.values():
        mean = sum(observations[k].forward_return for k in rows) / len(rows)
        for k in rows:
            excess[k] = observations[k].forward_return - mean
    return excess


def compare(observations: list[Observation], name: str, rule: Callable[[dict], bool | None]) -> dict:
    """Excess return of stocks for which ``rule`` is true vs the rest (rule None = unknown, left out)."""
    excess = _excess(observations)
    hit, rest = [], []
    for k, value in excess.items():
        try:
            verdict = rule(observations[k].signals)
        except (TypeError, KeyError):
            verdict = None
        if verdict is True:
            hit.append(value)
        elif verdict is False:
            rest.append(value)
    out = {"name": name, "n": len(hit), "rest_n": len(rest)}
    if hit:
        beats = sum(v > 0 for v in hit)
        sd = float(np.std(hit, ddof=1)) if len(hit) > 1 else float("nan")
        out |= {"mean_excess": float(np.mean(hit)), "median_excess": float(np.median(hit)),
                "beat_rate": beats / len(hit), "beat_ci": wilson(beats, len(hit)),
                "t_stat": float(np.mean(hit)) / (sd / math.sqrt(len(hit))) if sd and sd > 0 else float("nan")}
    if rest:
        out["rest_mean_excess"] = float(np.mean(rest))
    return out


RULES: dict[str, Callable[[dict], bool | None]] = {
    "Piotroski >= 7 (strong)": lambda s: None if s["piotroski_testable"] < 9 else s["piotroski"] >= 7,
    "Piotroski <= 3 (weak)": lambda s: None if s["piotroski_testable"] < 9 else s["piotroski"] <= 3,
    "Beneish flagged": lambda s: s["beneish_flagged"],
    "Altman distress zone": lambda s: None if s["altman_zone"] is None else s["altman_zone"] == "distress",
    "Revenue CAGR 5y >= 10%": lambda s: None if s["revenue_cagr_5y"] is None else s["revenue_cagr_5y"] >= 0.10,
    "FCF positive and rising >= 3 of 5 years": lambda s: None if s["fcf_rising_years"] is None
    else s["fcf_rising_years"] >= 3,
}


def information_coefficients(observations: list[Observation], signal: str) -> dict[date, float]:
    by_date = defaultdict(list)
    for o in observations:
        if o.forward_return is not None and o.signals.get(signal) is not None:
            by_date[o.rebalance].append((o.signals[signal], o.forward_return))
    return {d: spearman([a for a, _ in rows], [b for _, b in rows]) for d, rows in sorted(by_date.items())
            if len(rows) >= 10}


FACTORS = ("earnings_yield", "fcf_yield", "book_to_market", "piotroski", "revenue_cagr_5y")


def ic_summary(observations: list[Observation], signal: str) -> dict:
    """Mean rank correlation per date with its t statistic over dates (dates are the independent units)."""
    ic = [v for v in information_coefficients(observations, signal).values() if np.isfinite(v)]
    if not ic:
        return {"dates": 0}
    sd = float(np.std(ic, ddof=1)) if len(ic) > 1 else float("nan")
    return {"dates": len(ic), "mean_ic": float(np.mean(ic)),
            "t_stat": float(np.mean(ic)) / (sd / math.sqrt(len(ic))) if sd and sd > 0 else float("nan")}


def _composite(observations: list[Observation], signals: tuple[str, ...]) -> dict[int, float]:
    """Average cross-sectional rank (0..1) of the given signals per date; rows missing any signal are left out."""
    by_date = defaultdict(list)
    for k, o in enumerate(observations):
        if all(o.signals.get(s) is not None for s in signals):
            by_date[o.rebalance].append(k)
    out = {}
    for rows in by_date.values():
        if len(rows) < 10:
            continue
        ranks = np.zeros(len(rows))
        for s in signals:
            ranks += _ranks([observations[k].signals[s] for k in rows]) / len(rows)
        for k, r in zip(rows, ranks / len(signals)):
            out[k] = float(r)
    return out


def added_value(observations: list[Observation], base: tuple[str, ...] = ("earnings_yield", "fcf_yield", "book_to_market"),
                extra: str = "piotroski") -> dict:
    """Does ``extra`` add to a simple value composite? IC of the value composite vs value + extra
    on the same rows, per date."""
    both = _composite(observations, base + (extra,))
    value = _composite(observations, base)
    rows = [k for k in both if k in value and observations[k].forward_return is not None]
    out = {}
    for name, comp in (("value", value), ("value_plus_" + extra, both)):
        tagged = [Observation(observations[k].ticker, observations[k].rebalance, observations[k].fiscal_year,
                              {"score": comp[k]}, observations[k].forward_return) for k in rows]
        out[name] = ic_summary(tagged, "score")
    return out

"""Daily candidate list: at most ``top_n`` eligible stocks ranked by the model (or the fixed
scanner rule), each with its signals, catalysts, historical reliability and risks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from equity_research.shortterm import catalysts as cat
from equity_research.shortterm.backtest import BacktestResult
from equity_research.shortterm.catalysts import Filing
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel
from equity_research.shortterm.evaluation import OutOfSample


@dataclass
class Candidate:
    rank: int
    ticker: str
    name: str
    last_close: float
    last_date: date
    source: str
    score: float
    probability: dict[int, float | None]
    history: dict[int, dict]  # out-of-sample top-N stats per horizon
    signals: dict[str, float]
    catalysts: list[Filing] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    conclusion: str = ""


SIGNALS = ("ret_1d", "ret_5d", "gap", "rvol", "volume_trend", "breakout_20", "dist_52w_high", "close_location",
           "atr_pct")


def _window_filings(filings: list[Filing], day: date, days: int = 7) -> list[Filing]:
    return [f for f in filings if 0 <= (day - f.accepted_et.date()).days <= days]


def select(panel: Panel, ranking: np.ndarray, ranked_by: str, probabilities: dict[int, np.ndarray | None],
           oos: dict[int, OutOfSample], backtests: dict[int, BacktestResult], source: str, names: dict[str, str],
           filings: dict[str, list[Filing]] | None, data_problems: dict[str, list[str]], config: Config,
           allowed: bool) -> tuple[list[Candidate], list[str]]:
    """Returns the candidates and the reasons why the list is short or empty."""
    notes = []
    if not len(panel.dates):
        return [], ["no rows to rank"]
    latest = max(panel.dates)
    rows = np.where((panel.dates == latest) & panel.eligible & np.isfinite(ranking))[0]
    excluded = 0
    keep = []
    for row in rows[np.argsort(-ranking[rows], kind="stable")]:
        ticker = panel.tickers[row]
        recent = _window_filings((filings or {}).get(ticker, []), latest)
        if data_problems.get(ticker) or any(set(f.items) & {"3.01", "1.03", "4.02"} for f in recent):
            excluded += 1
            continue
        keep.append(row)
    if excluded:
        notes.append(f"{excluded} stocks left out for data problems or a delisting/bankruptcy/non-reliance 8-K")
    if not allowed:
        notes.append("no ranking passed the out-of-sample test, so no stock qualifies as a candidate")
        return [], notes

    out = []
    for rank, row in enumerate(keep[:config.top_n], 1):
        ticker = panel.tickers[row]
        signals = {name: float(panel.column(name)[row]) for name in SIGNALS}
        recent = _window_filings((filings or {}).get(ticker, []), latest)
        probability = {h: (float(p[row]) if p is not None and oos[h].gate.passed else None)
                       for h, p in probabilities.items()}
        history = {h: backtests[h].summary for h in backtests}
        risks = [f"typical daily range (ATR) {signals['atr_pct']:.1%} of the price"]
        h_max = max(backtests)
        if backtests[h_max].summary.get("trades"):
            s = backtests[h_max].summary
            risks.append(f"in the backtest {s['drop_rate']:.1%} of the top picks fell 10% or more within {h_max} day(s)")
        if signals["gap"] > 0.05 or signals["ret_1d"] > 0.10:
            risks.append("already up sharply: part of the move may be priced in (mean reversion risk)")
        spread = config.costs.per_side(panel.dollar_volume[row])
        risks.append(f"assumed cost {spread:.2%} per side (liquidity tier of {panel.dollar_volume[row] / 1e6:,.0f}M USD/day)")
        for f in recent:
            if set(f.items) & cat.NEGATIVE:
                risks.append(f"8-K {cat.leaning(f.items)} on {f.accepted_et:%Y-%m-%d}")
        validated = [h for h, p in probability.items() if p is not None]
        conclusion = (f"#{rank} by {ranked_by}. "
                      + (f"Calibrated probability available for {', '.join(f'{h}d' for h in validated)}. " if validated
                         else "No validated probability: ranking only. ")
                      + "A candidate for research, not a trade instruction.")
        out.append(Candidate(rank, ticker, names.get(ticker, ""), float(panel.price[row]), latest, source,
                             float(ranking[row]), probability, history, signals, recent, risks, conclusion))
    if len(out) < config.top_n:
        notes.append(f"{len(out)} of at most {config.top_n} stocks met the conditions")
    return out, notes

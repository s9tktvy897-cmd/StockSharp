"""Daily run of the short-term engine: validate data, build the panel, test every ranking out of
sample, backtest it, fit the production model and select the candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from equity_research.shortterm import backtest, evaluation, models
from equity_research.shortterm.backtest import BacktestResult
from equity_research.shortterm.bars import Bars, validate
from equity_research.shortterm.catalysts import Filing
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel, build_panel
from equity_research.shortterm.evaluation import OutOfSample
from equity_research.shortterm.top10 import Candidate, select

STALE_DAYS = 5


@dataclass
class EngineResult:
    scan_time: datetime
    config: Config
    bars_source: str
    universe_size: int
    panel: Panel
    data_problems: dict[str, list[str]]
    oos: dict[int, OutOfSample] = field(default_factory=dict)
    backtests: dict[int, BacktestResult] = field(default_factory=dict)
    scanner_backtests: dict[int, BacktestResult] = field(default_factory=dict)
    production_model: dict[int, str] = field(default_factory=dict)
    ranked_by: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    raw_scanner: list[tuple[str, float, dict]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def latest_date(self) -> date | None:
        return max(self.panel.dates) if len(self.panel.dates) else None


def _production(panel: Panel, horizon: int, embargo_days: int):
    """Model for today: trained on everything before the last full year, chosen and calibrated on it."""
    y = panel.outcomes[horizon]["hit"]
    usable = panel.eligible & np.isfinite(y)
    if not np.any(usable):
        return None
    last = max(panel.dates[usable])
    val_start = date(last.year - 1, last.month, last.day) if not (last.month == 2 and last.day == 29) else \
        date(last.year - 1, 2, 28)
    train = np.where(usable & np.array([d < val_start - timedelta(days=embargo_days) for d in panel.dates]))[0]
    val = np.where(usable & np.array([d >= val_start for d in panel.dates]))[0]
    if not len(train) or not len(val) or np.sum(y[train]) < 5:
        return None
    return evaluation._fit_select(panel.X, y, train, val)


def run(universe: dict[str, Bars], filings: dict[str, list[Filing]] | None, config: Config, names: dict[str, str],
        bars_source: str, scan_time: datetime) -> EngineResult:
    problems = {t: p for t, b in universe.items() if (p := validate(b))}
    panel = build_panel(universe, filings, config, last_decision=scan_time)
    result = EngineResult(scan_time, config, bars_source, len(universe), panel, problems)
    if not len(panel.dates):
        result.notes.append("no price history: nothing to scan or backtest")
        return result
    if (scan_time.date() - result.latest_date).days > STALE_DAYS:
        result.notes.append(f"latest bar {result.latest_date} is more than {STALE_DAYS} days before the scan")

    probabilities: dict[int, np.ndarray | None] = {}
    for h in config.horizons:
        oos = evaluation.out_of_sample(panel, h, config)
        result.oos[h] = oos
        result.backtests[h] = backtest.run(panel, oos.scores, universe, config, h)
        scanner = np.where(np.isfinite(oos.scores), models.scanner_score(panel.X, panel.names), np.nan)
        result.scanner_backtests[h] = backtest.run(panel, scanner, universe, config, h)
        model = _production(panel, h, embargo_days=h + 3)
        probabilities[h] = model.predict(panel.X) if model else None
        if model:
            result.production_model[h] = model.name

    scanner_all = models.scanner_score(panel.X, panel.names)
    latest = (panel.dates == result.latest_date) & panel.eligible
    order = np.where(latest)[0][np.argsort(-scanner_all[latest], kind="stable")][:config.top_n]
    result.raw_scanner = [(panel.tickers[r], float(scanner_all[r]),
                           {n: float(panel.column(n)[r]) for n in ("rvol", "ret_1d", "gap", "breakout_20")})
                          for r in order]

    model_ok = [h for h in sorted(config.horizons, reverse=True) if result.oos[h].gate.passed and probabilities[h] is not None]
    scanner_ok = [h for h in sorted(config.horizons, reverse=True) if result.oos[h].scanner_gate.passed]
    if model_ok:
        h = model_ok[0]
        ranking, result.ranked_by = probabilities[h], f"model score for {h} day(s) ({result.production_model[h]})"
    elif scanner_ok:
        ranking, result.ranked_by = scanner_all, f"scanner rule (validated as a ranking for {scanner_ok[0]} day(s))"
    else:
        ranking, result.ranked_by = scanner_all, "scanner rule (not validated)"
    result.candidates, notes = select(panel, ranking, result.ranked_by, probabilities, result.oos, result.backtests,
                                      bars_source, names, filings, problems, config, bool(model_ok or scanner_ok))
    result.notes += notes
    return result

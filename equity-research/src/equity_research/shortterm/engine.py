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
    oos_drop: dict[int, OutOfSample] = field(default_factory=dict)  # same test for a fall of 10% or more
    backtests: dict[int, BacktestResult] = field(default_factory=dict)
    scanner_backtests: dict[int, BacktestResult] = field(default_factory=dict)
    edge_backtests: dict[int, BacktestResult] = field(default_factory=dict)  # ranked by P(rise) - P(fall)
    ranking_backtest: BacktestResult | None = None  # the backtest of the ranking used for the candidates
    production_model: dict[int, str] = field(default_factory=dict)
    ranked_by: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    raw_scanner: list[tuple[str, float, dict]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def latest_date(self) -> date | None:
        return max(self.panel.dates) if len(self.panel.dates) else None


def _production(panel: Panel, horizon: int, embargo_days: int, target: str = "hit"):
    """Model for today: trained on everything before the last full year, chosen and calibrated on it."""
    y = panel.outcomes[horizon][target]
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
        result.notes.append("geen koershistorie: niets te scannen of te backtesten")
        return result
    if (scan_time.date() - result.latest_date).days > STALE_DAYS:
        result.notes.append(f"laatste koersdag {result.latest_date} ligt meer dan {STALE_DAYS} dagen voor de scan")

    probabilities: dict[int, np.ndarray | None] = {}
    drop_probabilities: dict[int, np.ndarray | None] = {}
    for h in config.horizons:
        result.oos_drop[h] = evaluation.out_of_sample(panel, h, config, target="drop")
        drop_model = _production(panel, h, embargo_days=h + 3, target="drop") if result.oos_drop[h].gate.passed else None
        drop_probabilities[h] = drop_model.predict(panel.X) if drop_model else None
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

    for h in config.horizons:
        edge = result.oos[h].scores - result.oos_drop[h].scores
        result.edge_backtests[h] = backtest.run(panel, edge, universe, config, h)

    def profitable(bt: BacktestResult) -> bool:
        return bool(bt.summary.get("trades")) and bt.summary["mean_net_ci"][0] > 0

    edge_ok = [h for h in sorted(config.horizons, reverse=True) if profitable(result.edge_backtests[h])
               and probabilities[h] is not None and drop_probabilities[h] is not None]
    model_ok = [h for h in sorted(config.horizons, reverse=True) if result.oos[h].gate.passed and probabilities[h] is not None]
    scanner_ok = [h for h in sorted(config.horizons, reverse=True) if result.oos[h].scanner_gate.passed]
    if edge_ok:
        h = edge_ok[0]
        ranking = probabilities[h] - drop_probabilities[h]
        result.ranked_by = f"kans op stijging min kans op daling voor {h} dag(en) (na kosten winstgevend in de backtest)"
        result.ranking_backtest = result.edge_backtests[h]
    elif model_ok:
        h = model_ok[0]
        ranking, result.ranked_by = probabilities[h], f"modelscore voor {h} dag(en) ({result.production_model[h]})"
        result.ranking_backtest = result.backtests[h]
    elif scanner_ok:
        ranking, result.ranked_by = scanner_all, f"scannerregel (gevalideerd als rangschikking voor {scanner_ok[0]} dag(en))"
        result.ranking_backtest = result.scanner_backtests[scanner_ok[0]]
    else:
        ranking, result.ranked_by = scanner_all, "scannerregel (niet gevalideerd)"
    result.candidates, notes = select(panel, ranking, result.ranked_by, probabilities, result.oos, result.backtests,
                                      bars_source, names, filings, problems, config,
                                      bool(edge_ok or model_ok or scanner_ok), drop_probabilities)
    result.notes += notes
    return result

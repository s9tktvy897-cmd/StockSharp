"""Out-of-sample evaluation: walk-forward folds with an embargo, calibration metrics and the gate
that decides whether a model's output may be reported as a probability.

Walk-forward: for test year Y the model is trained on years before Y-1, chosen and calibrated on
Y-1 (validation) and scored once on Y. Rows within ``embargo_days`` before a boundary are dropped
because their outcomes overlap the next period."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from equity_research.shortterm import models
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel

MIN_EVENTS = 30
ECE_FRACTION = 0.5


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def brier_skill(p: np.ndarray, y: np.ndarray, base_rate: float) -> float:
    reference = brier(np.full(len(y), base_rate), y)
    return 1 - brier(p, y) / reference if reference > 0 else float("nan")


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[tuple[float, float, int]]:
    """(mean prediction, observed rate, count) per quantile bin of the predictions."""
    order = np.argsort(p, kind="stable")
    return [(float(np.mean(p[g])), float(np.mean(y[g])), len(g)) for g in np.array_split(order, bins) if len(g)]


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    table = reliability(p, y, bins)
    total = sum(n for *_, n in table)
    return sum(n * abs(m - o) for m, o, n in table) / total if total else float("nan")


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    phat = hits / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n), (centre + margin) / (1 + z * z / n)


def daily_top(scores: np.ndarray, dates: np.ndarray, mask: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k highest scores per date among ``mask`` rows."""
    idx = np.where(mask & np.isfinite(scores))[0]
    if not len(idx):
        return idx
    ordinal = np.array([d.toordinal() for d in dates[idx]])
    order = np.lexsort((-scores[idx], ordinal))
    ordered, ords = idx[order], ordinal[order]
    starts = np.r_[0, np.flatnonzero(np.diff(ords)) + 1]
    rank = np.arange(len(ordered)) - np.repeat(starts, np.diff(np.r_[starts, len(ordered)]))
    return ordered[rank < k]


@dataclass
class Fold:
    test_year: int
    train: np.ndarray
    val: np.ndarray
    test: np.ndarray


def walk_forward(dates: np.ndarray, min_train_years: int = 2, embargo_days: int = 5) -> list[Fold]:
    if not len(dates):
        return []
    years = sorted({d.year for d in dates})
    embargo = timedelta(days=embargo_days)
    folds = []
    for year in years:
        if year - years[0] < min_train_years + 1:
            continue
        val_start, test_start = date(year - 1, 1, 1), date(year, 1, 1)
        train = np.array([d < val_start - embargo for d in dates])
        val = np.array([val_start <= d < test_start - embargo for d in dates])
        test = np.array([d.year == year for d in dates])
        folds.append(Fold(year, np.where(train)[0], np.where(val)[0], np.where(test)[0]))
    return folds


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]
    n: int = 0
    events: int = 0
    base_rate: float = float("nan")
    brier_skill: float = float("nan")
    ece: float = float("nan")
    top_k_rate: float = float("nan")
    top_k_ci: tuple[float, float] = (0.0, 1.0)
    top_k_n: int = 0
    reliability: list = field(default_factory=list)


def probability_gate(p: np.ndarray, y: np.ndarray, base_rate: float, top_hits: int, top_n: int,
                     min_events: int = MIN_EVENTS) -> GateResult:
    events = int(np.sum(y))
    g = GateResult(False, [], len(y), events, base_rate)
    if len(y) == 0:
        g.reasons.append("no out-of-sample rows")
        return g
    g.brier_skill, g.ece, g.reliability = brier_skill(p, y, base_rate), ece(p, y), reliability(p, y)
    g.top_k_n, g.top_k_rate = top_n, top_hits / top_n if top_n else float("nan")
    g.top_k_ci = wilson(top_hits, top_n)
    if events < min_events:
        g.reasons.append(f"only {events} events out of sample (< {min_events})")
    if not g.brier_skill > 0:
        g.reasons.append(f"no skill over the base rate (Brier skill {g.brier_skill:.4f} <= 0)")
    if not g.ece <= ECE_FRACTION * base_rate:
        g.reasons.append(f"poorly calibrated (ECE {g.ece:.4f} > {ECE_FRACTION} x base rate {base_rate:.4f})")
    if not g.top_k_ci[0] > base_rate:
        g.reasons.append(f"daily top picks not significantly above the base rate "
                         f"(hit rate {g.top_k_rate:.2%}, 95% CI lower bound {g.top_k_ci[0]:.2%} <= {base_rate:.2%})")
    g.passed = not g.reasons
    return g


@dataclass
class OutOfSample:
    horizon: int
    scores: np.ndarray        # out-of-sample prediction per panel row (NaN outside test years)
    chosen: dict[int, str]    # test year -> model chosen on validation
    gate: GateResult
    scanner_gate: GateResult  # the fixed scanner rule judged the same way (as a ranking only)
    folds: list[Fold]


def _fit_select(X, y, train, val):
    best, best_loss = None, float("inf")
    for model in models.candidates():
        if isinstance(model, models.GradientBoosting):
            model.fit(X[train], y[train], X[val], y[val])
        else:
            model.fit(X[train], y[train])
        loss = log_loss(model.predict(X[val]), y[val]) if len(val) else float("inf")
        if loss < best_loss:
            best, best_loss = model, loss
    return best


def out_of_sample(panel: Panel, horizon: int, config: Config) -> OutOfSample:
    y_all = panel.outcomes[horizon]["hit"] if panel.outcomes.get(horizon) else np.array([])
    usable = panel.eligible & np.isfinite(y_all) if len(y_all) else np.array([], dtype=bool)
    scores = np.full(len(panel.dates), np.nan)
    scanner = np.full(len(panel.dates), np.nan)
    chosen = {}
    folds = walk_forward(panel.dates, embargo_days=horizon + 3)
    for fold in folds:
        train, val, test = (fold.train[usable[fold.train]], fold.val[usable[fold.val]], fold.test[usable[fold.test]])
        if not len(train) or not len(val) or not len(test) or np.sum(y_all[train]) < 5:
            continue
        model = _fit_select(panel.X, y_all, train, val)
        scores[test] = model.predict(panel.X[test])
        scanner[test] = models.scanner_score(panel.X[test], panel.names)
        chosen[fold.test_year] = model.name

    tested = usable & np.isfinite(scores)
    first_test = min((date(y, 1, 1) for y in chosen), default=None)
    base_rows = usable & np.array([first_test is not None and d < first_test for d in panel.dates])
    base_rate = float(np.mean(y_all[base_rows])) if np.any(base_rows) else float("nan")

    def gate_for(values, as_probability: bool) -> GateResult:
        top = daily_top(values, panel.dates, tested, config.top_n)
        hits = int(np.sum(y_all[top]))
        if as_probability:
            return probability_gate(values[tested], y_all[tested], base_rate, hits, len(top))
        g = probability_gate(np.full(int(np.sum(tested)), base_rate), y_all[tested], base_rate, hits, len(top))
        g.reasons = [r for r in g.reasons if "top picks" in r or "events" in r]  # a ranking is judged on its picks
        g.passed = not g.reasons
        return g

    return OutOfSample(horizon, scores, chosen, gate_for(scores, True), gate_for(scanner, False), folds)

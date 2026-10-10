"""Expected-return ranking: models that predict the net result of the actual trade (buy at the next
open, sell at +10% or at the horizon close, after costs) instead of the chance of touching +10%.

Touching +10% mostly measures volatility: the same stocks also fall 10% as often. Predicting the
trade's net return puts the losses in the target, so a ranking only scores well when the gains
outweigh the falls and the costs. Trades are only taken when the predicted net return exceeds
``Config.min_expected_net`` (0: never a trade with a negative expectation), so on many days there
are no picks at all. Validated with the same walk-forward folds and embargo as the classifiers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import Panel
from equity_research.shortterm.evaluation import daily_top, walk_forward

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
except ImportError:  # optional dependency
    HistGradientBoostingRegressor = None

CLIP = 0.5  # labels clipped to +-50% so a handful of extreme moves cannot dominate the fit


class Ridge:
    """Least squares with an L2 penalty on standardized features; missing values -> training mean."""

    def __init__(self, l2: float = 10.0):
        self.l2 = l2
        self.name = f"ridge (L2 {l2:g})"

    def _design(self, X):
        Z = (np.asarray(X, dtype=float) - self.mean) / self.scale
        return np.column_stack([np.ones(len(Z)), np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0)])

    def fit(self, X, y):
        X = np.asarray(X, dtype=float)
        with np.errstate(all="ignore"):
            self.mean = np.nan_to_num(np.nanmean(np.where(np.isfinite(X), X, np.nan), axis=0))
            self.scale = np.nan_to_num(np.nanstd(np.where(np.isfinite(X), X, np.nan), axis=0), nan=1.0)
        self.scale[self.scale == 0] = 1.0
        A = self._design(X)
        penalty = np.full(A.shape[1], self.l2)
        penalty[0] = 0.0
        self.w = np.linalg.solve(A.T @ A + np.diag(penalty), A.T @ np.clip(y, -CLIP, CLIP))
        return self

    def predict(self, X):
        return self._design(X) @ self.w


class BoostedRegressor:
    name = "gradient boosting (regression)"

    def fit(self, X, y):
        self.model = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200,
                                                   l2_regularization=1.0, min_samples_leaf=200, random_state=0)
        self.model.fit(np.asarray(X, dtype=float), np.clip(y, -CLIP, CLIP))
        return self

    def predict(self, X):
        return self.model.predict(np.asarray(X, dtype=float))


def candidates() -> list:
    out = [Ridge(l2=10.0), Ridge(l2=10000.0)]
    if HistGradientBoostingRegressor is not None:
        out.append(BoostedRegressor())
    return out


def selective(scores: np.ndarray, config: Config) -> np.ndarray:
    """Scores with every row below the minimum expected net return removed (NaN = no trade)."""
    with np.errstate(invalid="ignore"):
        return np.where(scores > config.min_expected_net, scores, np.nan)


def _top_mean(model, X, y, dates, rows, config: Config) -> float:
    """Mean realized net return of the daily top picks the model would have taken on ``rows``."""
    s = np.full(len(dates), np.nan)
    s[rows] = model.predict(X[rows])
    picks = daily_top(selective(s, config), dates, np.isin(np.arange(len(dates)), rows), config.top_n)
    return float(np.mean(y[picks])) if len(picks) >= 30 else -np.inf


def fit_select(X, y, dates, train, val, config: Config):
    """Fit every candidate on ``train`` and keep the one whose selective top picks earned most on ``val``."""
    best, best_score = None, -np.inf
    for model in candidates():
        model.fit(X[train], y[train])
        score = _top_mean(model, X, y, dates, val, config) if len(val) else -np.inf
        if best is None or score > best_score:
            best, best_score = model, score
    return best


@dataclass
class ReturnOOS:
    horizon: int
    scores: np.ndarray       # out-of-sample expected net return per row (NaN outside test years)
    chosen: dict[int, str]   # test year -> model chosen on validation


def out_of_sample(panel: Panel, horizon: int, config: Config) -> ReturnOOS:
    y = panel.outcomes[horizon].get("net") if panel.outcomes.get(horizon) else None
    scores = np.full(len(panel.dates), np.nan)
    chosen: dict[int, str] = {}
    if y is None:
        return ReturnOOS(horizon, scores, chosen)
    usable = panel.eligible & np.isfinite(y)
    for fold in walk_forward(panel.dates, embargo_days=horizon + 3):
        train, val, test = (fold.train[usable[fold.train]], fold.val[usable[fold.val]], fold.test[usable[fold.test]])
        if len(train) < 100 or not len(val) or not len(test):
            continue
        model = fit_select(panel.X, y, panel.dates, train, val, config)
        scores[test] = model.predict(panel.X[test])
        chosen[fold.test_year] = model.name
    return ReturnOOS(horizon, scores, chosen)


def production(panel: Panel, horizon: int, config: Config):
    """Model for today: trained before the last year, chosen on the last year (as the classifiers)."""
    y = panel.outcomes[horizon].get("net")
    if y is None:
        return None
    usable = panel.eligible & np.isfinite(y)
    if not np.any(usable):
        return None
    last = max(panel.dates[usable])
    val_start = date(last.year - 1, last.month, min(last.day, 28))
    embargo = timedelta(days=horizon + 3)
    train = np.where(usable & np.array([d < val_start - embargo for d in panel.dates]))[0]
    val = np.where(usable & np.array([d >= val_start for d in panel.dates]))[0]
    if len(train) < 100 or not len(val):
        return None
    return fit_select(panel.X, y, panel.dates, train, val, config)

"""Strategy scores on the panel, exactly as defined in docs/RESEARCH_PROTOCOL.md. A score is a
number per panel row (higher = better); NaN means "not a candidate". Rule strategies use only the
row's own point-in-time features; fitted models are scored out of sample (walk-forward) and, for
the holdout, by a model trained on the development period only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from equity_research.research import protocol
from equity_research.shortterm import evaluation, expected, models
from equity_research.shortterm.dataset import Panel

MAX_TRAIN_ROWS = 1_500_000


def _col(panel: Panel, name: str) -> np.ndarray:
    return panel.column(name).astype(float) if name in panel.names else np.full(len(panel.dates), np.nan)


def rule_score(strategy: str, panel: Panel, spy_above_ma200: np.ndarray, dollar_volume: np.ndarray) -> np.ndarray:
    c = lambda n: _col(panel, n)
    with np.errstate(invalid="ignore"):
        if strategy == "MOMENTUM_12_1":
            return c("mom_12_1")
        if strategy == "REVERSAL_5D":
            return np.where(dollar_volume >= 50e6, -c("ret_5d"), np.nan)
        if strategy == "BREAKOUT_VOLUME":
            return models.scanner_score(panel.X, panel.names).astype(float)
        if strategy == "TREND_60D":
            ma50, ma200 = c("ma50_dist"), c("ma200_dist")
            up = (ma50 > 0) & (ma200 > ma50) & spy_above_ma200  # close > MA50 > MA200: c/MA200 > c/MA50
            return np.where(up, c("ret_60d"), np.nan)
        if strategy == "EARNINGS_DRIFT":
            ok = (c("cat_reaction_earnings") == 1) & (c("gap") >= 0.03) & \
                 (c("ret_1d") >= c("gap"))  # close >= open  <=>  close/prev - 1 >= open/prev - 1
            return np.where(ok, c("gap"), np.nan)
        if strategy == "VOL_COMPRESSION_BREAKOUT":
            ok = (c("breakout_20") > 0) & (c("rvol") >= 2) & (c("vol_ratio_20_120") < 0.9)
            return np.where(ok, c("rvol"), np.nan)
    raise ValueError(strategy)


@dataclass
class Fitted:
    dev: np.ndarray       # out-of-sample scores in the development period (walk-forward)
    holdout: np.ndarray   # scores in the holdout from a model trained on development data only
    chosen: dict


def _sample(rows: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.sort(rng.choice(rows, MAX_TRAIN_ROWS, replace=False)) if len(rows) > MAX_TRAIN_ROWS else rows


def _classifier(X, y, train, val):
    return evaluation._fit_select(X, y, train, val)


def _regressors(X, y, train):
    ridge, boost = expected.Ridge(l2=10.0).fit(X[train], y[train]), None
    if expected.HistGradientBoostingRegressor is not None:
        boost = expected.BoostedRegressor().fit(X[train], y[train])
    return ridge, boost


def _score(kind: str, fitted, X, rows, horizon: int, vol20: np.ndarray, threshold: float) -> np.ndarray:
    if kind in ("EXISTING_TARGET10", "MODEL_A_DIRECTION"):
        p = fitted.predict(X[rows])
        return p if kind == "EXISTING_TARGET10" else np.where(p > 0.5, p, np.nan)
    ridge, boost = fitted
    a = ridge.predict(X[rows])
    b = boost.predict(X[rows]) if boost is not None else a
    mean = (a + b) / 2
    if kind == "MODEL_B_EXPECTED_RETURN":
        return np.where(mean > threshold, mean, np.nan)
    edge = mean - np.abs(a - b)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(edge > threshold, edge / (vol20[rows] * np.sqrt(horizon)), np.nan)


def fitted_scores(kind: str, panel: Panel, horizon: int, labels: dict[str, np.ndarray], usable: np.ndarray,
                  vol20: np.ndarray, dev_end: date, holdout_start: date) -> Fitted:
    """Walk-forward out-of-sample scores in the development period and holdout scores."""
    rng = np.random.default_rng(protocol.SEED + horizon)
    y = labels["hit" if kind == "EXISTING_TARGET10" else "up" if kind == "MODEL_A_DIRECTION" else "net"]
    ok = usable & np.isfinite(y)
    dev_mask = np.array([d <= dev_end for d in panel.dates])
    dev = np.full(len(panel.dates), np.nan)
    chosen = {}
    folds = evaluation.walk_forward(panel.dates[dev_mask], min_train_years=2, embargo_days=horizon + 3)
    dev_index = np.where(dev_mask)[0]
    for fold in folds:
        train = _sample(dev_index[fold.train][ok[dev_index[fold.train]]], rng)
        val = dev_index[fold.val][ok[dev_index[fold.val]]]
        test = dev_index[fold.test][usable[dev_index[fold.test]]]
        if len(train) < 1000 or not len(val) or not len(test):
            continue
        fitted = _fit(kind, panel.X, y, train, val)
        dev[test] = _score(kind, fitted, panel.X, test, horizon, vol20, 0.0)
        chosen[fold.test_year] = getattr(fitted, "name", "ridge + gradient boosting")
    # holdout: train on development data only, choose/calibrate on its last year
    holdout = np.full(len(panel.dates), np.nan)
    val_start = date(dev_end.year - 1, dev_end.month, min(dev_end.day, 28))
    embargo = timedelta(days=horizon + 3)
    train = _sample(np.where(ok & np.array([d < val_start - embargo for d in panel.dates]))[0], rng)
    val = np.where(ok & np.array([val_start <= d <= dev_end for d in panel.dates]))[0]
    test = np.where(usable & np.array([d >= holdout_start for d in panel.dates]))[0]
    if len(train) >= 1000 and len(val) and len(test):
        fitted = _fit(kind, panel.X, y, train, val)
        holdout[test] = _score(kind, fitted, panel.X, test, horizon, vol20, 0.0)
        chosen["holdout"] = getattr(fitted, "name", "ridge + gradient boosting")
    return Fitted(dev, holdout, chosen)


def _fit(kind, X, y, train, val):
    if kind in ("EXISTING_TARGET10", "MODEL_A_DIRECTION"):
        return _classifier(X, y, train, val)
    return _regressors(X, y, train)

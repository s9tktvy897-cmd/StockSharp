"""Models that turn features into a score. ``predict`` returns a probability-like number; only
the out-of-sample gate in ``evaluation`` decides whether it may be shown as a probability."""

from __future__ import annotations

import numpy as np

try:
    from sklearn.ensemble import HistGradientBoostingClassifier
except ImportError:  # optional dependency
    HistGradientBoostingClassifier = None


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(z, -35, 35)))


class BaseRate:
    name = "base rate"

    def fit(self, X, y):
        self.rate = float(np.mean(y))
        return self

    def predict(self, X):
        return np.full(len(X), self.rate)


class Logistic:
    """L2-regularized logistic regression on standardized features (Newton / IRLS); missing
    values are imputed with the training mean."""

    def __init__(self, l2: float = 1.0):
        self.l2 = l2
        self.name = f"logistic (L2 {l2:g})"

    def _design(self, X):
        Z = (X - self.mean) / self.scale
        return np.column_stack([np.ones(len(Z)), np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0)])

    def fit(self, X, y):
        X = np.asarray(X, dtype=float)
        with np.errstate(all="ignore"):
            self.mean = np.nan_to_num(np.nanmean(np.where(np.isfinite(X), X, np.nan), axis=0))
            self.scale = np.nan_to_num(np.nanstd(np.where(np.isfinite(X), X, np.nan), axis=0), nan=1.0)
        self.scale[self.scale == 0] = 1.0
        A = self._design(X)
        w = np.zeros(A.shape[1])
        penalty = np.full(A.shape[1], self.l2)
        penalty[0] = 0.0
        for _ in range(50):
            p = sigmoid(A @ w)
            gradient = A.T @ (p - y) + penalty * w
            hessian = (A * (p * (1 - p))[:, None]).T @ A + np.diag(penalty) + 1e-9 * np.eye(len(w))
            step = np.linalg.solve(hessian, gradient)
            w -= step
            if np.max(np.abs(step)) < 1e-8:
                break
        self.intercept, self.coef = w[0], w[1:]
        return self

    def predict(self, X):
        return sigmoid(self._design(np.asarray(X, dtype=float)) @ np.r_[self.intercept, self.coef])


class Platt:
    """Calibration map p -> sigmoid(a * logit(p) + b), fitted on validation data."""

    def fit(self, p, y):
        z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
        self.inner = Logistic(l2=0.0).fit(z[:, None], y)
        return self

    def __call__(self, p):
        z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
        return self.inner.predict(z[:, None])


class GradientBoosting:
    name = "gradient boosting (calibrated)"

    def fit(self, X, y, X_val=None, y_val=None):
        self.model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                    l2_regularization=1.0, min_samples_leaf=200, random_state=0)
        self.model.fit(X, y)
        self.calibration = Platt().fit(self._raw(X_val), y_val) if X_val is not None and len(X_val) else None
        return self

    def _raw(self, X):
        return self.model.predict_proba(np.asarray(X, dtype=float))[:, 1]

    def predict(self, X):
        raw = self._raw(X)
        return self.calibration(raw) if self.calibration else raw


def candidates() -> list:
    out = [Logistic(l2=0.1), Logistic(l2=10.0), Logistic(l2=1000.0)]
    if HistGradientBoostingClassifier is not None:
        out.append(GradientBoosting())
    return out


SCANNER_RULE = "log(RVOL) + 2*[close above 20-day high] + [1-day return > 5%] + 2*[8-K after the close] " \
               "+ [earnings 8-K after the close] - 2*[negative-leaning 8-K]"


def scanner_score(X: np.ndarray, names: list[str]) -> np.ndarray:
    """Fixed, unfitted scanner rule (a transparent benchmark for the fitted models)."""
    col = {n: X[:, i] for i, n in enumerate(names)}
    zero = np.zeros(len(X))
    with np.errstate(all="ignore"):
        score = np.log(np.clip(np.nan_to_num(col["rvol"], nan=1.0), 0.1, None))
    score = score + 2 * (np.nan_to_num(col["breakout_20"]) > 0) + (np.nan_to_num(col["ret_1d"]) > 0.05)
    score = score + 2 * col.get("cat_overnight_any", zero) + col.get("cat_overnight_earnings", zero)
    return score - 2 * col.get("cat_overnight_negative", zero)

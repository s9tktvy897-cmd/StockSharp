"""Performance statistics with uncertainty that respects time dependence.

- ``bootstrap_mean``: stationary block bootstrap (Politis & Romano 1994) of a daily return series;
  blocks keep autocorrelation and volatility clusters together.
- ``cluster_bootstrap_mean``: per-trade mean where trades on the same signal day are one cluster
  (they share the market move), with blocks of days.
- ``holm``: Holm-Bonferroni correction over all strategies tested (data snooping).
- ``deflated_sharpe``: probability that the Sharpe ratio is above what the best of ``trials``
  random strategies would show (Bailey & Lopez de Prado 2014, null variance 1/(T-1)).
- ``corwin_schultz``: bid-ask spread estimated from daily highs and lows (Corwin & Schultz 2012)."""

from __future__ import annotations

import math

import numpy as np

SQRT2 = math.sqrt(2.0)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / SQRT2))


def _normal_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, |error| < 1.2e-9)."""
    if not 0 < p < 1:
        return -math.inf if p <= 0 else math.inf
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        return -_normal_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1 + np.asarray(returns, dtype=float))
    if not len(equity):
        return 0.0
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return float(min(0.0, np.min(equity / peak - 1)))


def drawdown_curve(returns: np.ndarray) -> np.ndarray:
    equity = np.cumprod(1 + np.asarray(returns, dtype=float))
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return equity / peak - 1


def performance(returns, periods_per_year: int = 252) -> dict:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return {"days": len(r)}
    total = float(np.prod(1 + r) - 1)
    years = len(r) / periods_per_year
    cagr = float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0
    sd = float(r.std(ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(r, 0) ** 2)))
    mdd = max_drawdown(r)
    return {
        "days": len(r), "total_return": total, "cagr": cagr, "volatility": sd * math.sqrt(periods_per_year),
        "sharpe": float(r.mean() / sd * math.sqrt(periods_per_year)) if sd > 0 else float("nan"),
        "sortino": float(r.mean() / downside * math.sqrt(periods_per_year)) if downside > 0 else float("nan"),
        "max_drawdown": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "mean_daily": float(r.mean()),
    }


def trade_stats(net) -> dict:
    x = np.asarray(net, dtype=float)
    if not len(x):
        return {"trades": 0}
    wins, losses = x[x > 0], x[x <= 0]
    top = int(math.ceil(0.01 * len(x)))
    trimmed = np.sort(x)[:-top] if len(x) > top else x[:0]
    return {
        "trades": len(x), "win_rate": float(len(wins) / len(x)),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("nan"),
        "expected_value": float(x.mean()), "median": float(np.median(x)),
        "mean_without_top_1pct": float(trimmed.mean()) if len(trimmed) else float("nan"),
        "best": float(x.max()), "worst": float(x.min()),
    }


def _stationary_indices(n: int, reps: int, block: float, rng: np.random.Generator) -> np.ndarray:
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, reps)
    if n == 1:
        return idx
    p = 1.0 / max(block, 1.0)
    for j in range(1, n):
        new = rng.random(reps) < p
        idx[:, j] = np.where(new, rng.integers(0, n, reps), (idx[:, j - 1] + 1) % n)
    return idx


def bootstrap_mean(x, block: float = 20, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """95% interval of the mean and the one-sided p-value of mean <= 0 (stationary bootstrap)."""
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = x[_stationary_indices(len(x), n, block, rng)].mean(axis=1)
    observed = x.mean()
    p = float(np.mean(means - observed >= observed))  # null: centred bootstrap distribution
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), p


def cluster_bootstrap_mean(x, clusters, block: float = 5, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Per-trade mean with trades of one cluster (signal day) resampled together, days in blocks."""
    x = np.asarray(x, dtype=float)
    clusters = np.asarray(clusters)
    if len(x) < 2:
        return float("nan"), float("nan"), float("nan")
    keys, inverse = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inverse, weights=x)
    counts = np.bincount(inverse).astype(float)
    rng = np.random.default_rng(seed)
    idx = _stationary_indices(len(keys), n, block, rng)
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    observed = x.mean()
    p = float(np.mean(means - observed >= observed))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), p


def holm(pvalues: dict, alpha: float = 0.05) -> dict:
    """Which hypotheses are rejected (edge significant) after the Holm-Bonferroni step-down."""
    ordered = sorted(pvalues.items(), key=lambda kv: (np.nan_to_num(kv[1], nan=1.0), kv[0]))
    m = len(ordered)
    out = {k: False for k in pvalues}
    for i, (k, p) in enumerate(ordered):
        if not np.isfinite(p) or p * (m - i) > alpha:
            break
        out[k] = True
    return out


def deflated_sharpe(returns, trials: int) -> float:
    r = np.asarray(returns, dtype=float)
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float(np.mean(z ** 3)), float(np.mean(z ** 4))
    if trials <= 1:
        sr0 = 0.0
    else:
        euler = 0.5772156649
        sd = math.sqrt(1.0 / (t - 1))
        sr0 = sd * ((1 - euler) * _normal_ppf(1 - 1 / trials) + euler * _normal_ppf(1 - 1 / (trials * math.e)))
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return _normal_cdf((sr - sr0) * math.sqrt(t - 1) / denom)


def corwin_schultz(high, low, window: int = 20) -> np.ndarray:
    """Rolling mean of the two-day Corwin-Schultz spread estimate (negative estimates set to 0).
    The value on day t uses the highs and lows of t-1 and t only (known after the close of t)."""
    high, low = np.asarray(high, dtype=float), np.asarray(low, dtype=float)
    n = len(high)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(high / low) ** 2
        beta = hl[1:] + hl[:-1]
        gamma = np.log(np.maximum(high[1:], high[:-1]) / np.minimum(low[1:], low[:-1])) ** 2
        k = 3 - 2 * SQRT2
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        spread = np.maximum(2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha)), 0.0)
    two_day = np.concatenate([[np.nan], spread])
    if n >= window:
        from numpy.lib.stride_tricks import sliding_window_view
        out[window - 1:] = np.nanmean(sliding_window_view(two_day, window), axis=1)
    return out

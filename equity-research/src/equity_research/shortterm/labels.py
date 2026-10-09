"""Outcomes of a signal on day t, measured from the open of t+1 (the first tradable price after
a decision taken after the close of t). Overnight gaps before that open are not capturable."""

from __future__ import annotations

import numpy as np

from equity_research.shortterm.bars import Bars
from equity_research.shortterm.config import Config
from equity_research.shortterm.features import rolling


def _future_window(x: np.ndarray, h: int, fn) -> np.ndarray:
    """fn over x[i+1 .. i+h] for each i (NaN where the window runs past the end)."""
    return np.concatenate([rolling(x, h, fn)[h:], np.full(h, np.nan)])


def compute(bars: Bars, config: Config) -> dict[int, dict[str, np.ndarray]]:
    n = len(bars)
    gaps = np.full(n, np.inf)
    if n > 1:
        gaps[:-1] = np.diff(np.array([d.toordinal() for d in bars.dates]))
    entry = np.concatenate([bars.open[1:], [np.nan]])
    out = {}
    for h in config.horizons:
        ok = np.concatenate([rolling(gaps, h, np.max)[h - 1:], np.full(h - 1, np.inf)]) <= config.max_gap_days
        ok &= np.arange(n) + h < n
        high = _future_window(bars.high, h, np.max)
        low = _future_window(bars.low, h, np.min)
        close_h = np.concatenate([bars.close[h:], np.full(h, np.nan)])
        with np.errstate(invalid="ignore"):
            hit = np.where(ok, (high >= entry * (1 + config.target)).astype(float), np.nan)
            drop = np.where(ok, (low <= entry * (1 - config.drop)).astype(float), np.nan)
            ret = np.where(ok, close_h / entry - 1, np.nan)
        out[h] = {"hit": hit, "drop": drop, "ret_close": ret, "max_up": np.where(ok, high / entry - 1, np.nan),
                  "max_down": np.where(ok, low / entry - 1, np.nan)}
    return out

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


def trade_exit(bars: Bars, h: int, target: float) -> np.ndarray:
    """Exit price of the trade rule without a stop (as ``backtest.simulate``): buy at the open of t+1,
    sell at +target with a limit (at the open when a later day gaps above it), else at the close of t+h."""
    n = len(bars)
    exit_price = np.full(n, np.nan)
    if n <= h:
        return exit_price
    entry = bars.open[1:n - h + 1]
    level = entry * (1 + target)
    done = np.zeros(len(entry), dtype=bool)
    out = np.full(len(entry), np.nan)
    for j in range(1, h + 1):
        opens, highs = bars.open[j:n - h + j], bars.high[j:n - h + j]
        if j > 1:
            gap = ~done & (opens >= level)
            out[gap], done = opens[gap], done | gap
        hit = ~done & (highs >= level)
        out[hit], done = level[hit], done | hit
    rest = ~done
    out[rest] = bars.close[h:n][rest]
    exit_price[:n - h] = out
    return exit_price


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
            trade = np.where(ok, trade_exit(bars, h, config.target) / entry - 1, np.nan)
        out[h] = {"hit": hit, "drop": drop, "ret_close": ret, "trade_gross": trade, "max_up": np.where(ok, high / entry - 1, np.nan),
                  "max_down": np.where(ok, low / entry - 1, np.nan)}
    return out

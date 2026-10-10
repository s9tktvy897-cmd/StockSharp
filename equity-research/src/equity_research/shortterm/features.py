"""Point-in-time features per ticker and day t, computed only from bars up to and including t.

The decision is taken after the close of t (before the open of t+1); see ``labels``."""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from equity_research.shortterm.bars import Bars

FEATURES = ("ret_1d", "ret_5d", "ret_20d", "gap", "rvol", "volume_trend", "atr_pct", "vol_ratio", "breakout_20",
            "dist_52w_high", "close_location", "log_price", "log_dollar_volume", "ret_60d", "mom_12_1", "ma50_dist",
            "ma200_dist", "vol_20", "vol_ratio_20_120")


def shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def rolling(x: np.ndarray, n: int, fn) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = fn(sliding_window_view(x, n), axis=1)
    return out


def rolling_max_min_periods(x: np.ndarray, n: int, min_periods: int) -> np.ndarray:
    padded = np.concatenate([np.full(n - 1, np.nan), x])
    with np.errstate(all="ignore"):
        out = np.nanmax(sliding_window_view(padded, n), axis=1)
    out[: min_periods - 1] = np.nan
    return out


def compute(bars: Bars) -> dict[str, np.ndarray]:
    o, h, l, c, v = bars.open, bars.high, bars.low, bars.close, bars.volume
    prev = shift(c, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = c / prev - 1
        true_range = np.fmax(h - l, np.fmax(np.abs(h - prev), np.abs(l - prev)))
        avg20 = rolling(v, 20, np.mean)
        dollar = rolling(c * v, 20, np.mean)
        f = {
            "ret_1d": ret,
            "ret_5d": c / shift(c, 5) - 1,
            "ret_20d": c / shift(c, 20) - 1,
            "gap": o / prev - 1,
            "rvol": v / shift(avg20, 1),
            "volume_trend": rolling(v, 5, np.mean) / shift(avg20, 5),
            "atr_pct": rolling(true_range, 14, np.mean) / c,
            "vol_ratio": rolling(ret, 5, np.std) / rolling(ret, 60, np.std),
            "breakout_20": c / shift(rolling(h, 20, np.max), 1) - 1,
            "dist_52w_high": c / rolling_max_min_periods(h, 252, 60) - 1,
            "close_location": np.where(h > l, (c - l) / (h - l), 0.5),
            "log_price": np.log(c),
            "log_dollar_volume": np.log(dollar),
            "ret_60d": c / shift(c, 60) - 1,
            "mom_12_1": shift(c, 21) / shift(c, 252) - 1,  # 12-month momentum without the last month
            "ma50_dist": c / rolling(c, 50, np.mean) - 1,
            "ma200_dist": c / rolling(c, 200, np.mean) - 1,
            "vol_20": rolling(ret, 20, np.std),
            "vol_ratio_20_120": rolling(ret, 20, np.std) / rolling(ret, 120, np.std),
        }
    f["dollar_volume_20"] = dollar  # liquidity filter (not a model input)
    return f

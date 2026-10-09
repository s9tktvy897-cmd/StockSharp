"""SYNTHETIC price series for the short-term engine tests. Never real market data."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from equity_research.shortterm.bars import Bars


def trading_days(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def make_bars(ticker: str, closes, opens=None, highs=None, lows=None, volumes=None, start=date(2020, 1, 1)) -> Bars:
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    opens = np.asarray(opens if opens is not None else closes, dtype=float)
    highs = np.asarray(highs if highs is not None else np.maximum(opens, closes), dtype=float)
    lows = np.asarray(lows if lows is not None else np.minimum(opens, closes), dtype=float)
    volumes = np.asarray(volumes if volumes is not None else np.full(n, 1e6), dtype=float)
    return Bars(ticker, np.array(trading_days(start, n)), opens, highs, lows, closes, volumes, "SYNTHETIC")


def planted_universe(n_tickers: int = 40, n_days: int = 1300, seed: int = 7, signal: bool = True) -> dict[str, Bars]:
    """Random walks. With ``signal``, a volume spike on day t (RVOL ~ 5) is followed by a +12% high
    on day t+1 in 40% of cases, against ~1% otherwise: a learnable, known pattern."""
    rng = np.random.default_rng(seed)
    universe = {}
    for k in range(n_tickers):
        close = np.empty(n_days)
        opn, high, low = np.empty(n_days), np.empty(n_days), np.empty(n_days)
        volume = rng.uniform(0.8e6, 1.2e6, n_days)
        spike = rng.random(n_days) < 0.03
        volume[spike] *= 5
        price = 20.0
        for i in range(n_days):
            opn[i] = price * (1 + rng.normal(0, 0.005))
            move = rng.normal(0, 0.015)
            jump = False
            if i > 0 and spike[i - 1]:
                jump = signal and rng.random() < 0.40
            elif rng.random() < 0.01:
                jump = True
            high[i] = opn[i] * (1.12 if jump else 1 + abs(rng.normal(0, 0.01)))
            close[i] = opn[i] * (1 + move)
            high[i] = max(high[i], opn[i], close[i])
            low[i] = min(opn[i], close[i]) * (1 - abs(rng.normal(0, 0.01)))
            price = close[i]
        universe[f"T{k:02d}"] = Bars(f"T{k:02d}", np.array(trading_days(date(2019, 1, 1), n_days)), opn, high, low,
                                     close, volume, "SYNTHETIC")
    return universe

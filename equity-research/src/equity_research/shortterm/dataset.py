"""Panel of (ticker, day) rows: point-in-time features, outcomes per horizon and eligibility."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from equity_research.shortterm import catalysts, features, labels
from equity_research.shortterm.bars import Bars
from equity_research.shortterm.catalysts import Filing
from equity_research.shortterm.config import Config

MARKET_FEATURES = ("market_ret_1d", "market_ret_20d", "market_breadth")


@dataclass
class Panel:
    X: np.ndarray
    names: list[str]
    dates: np.ndarray
    tickers: np.ndarray
    rows: np.ndarray  # index into the ticker's Bars
    outcomes: dict[int, dict[str, np.ndarray]]
    eligible: np.ndarray
    price: np.ndarray
    dollar_volume: np.ndarray
    catalysts_used: bool
    excluded: dict[str, str] = field(default_factory=dict)

    def column(self, name: str) -> np.ndarray:
        return self.X[:, self.names.index(name)]


def build_panel(universe: dict[str, Bars], filings: dict[str, list[Filing]] | None, config: Config,
                last_decision: datetime | None = None) -> Panel:
    names = list(features.FEATURES) + (list(catalysts.FEATURES) if filings is not None else [])
    blocks, excluded = [], {}
    for ticker, bars in sorted(universe.items()):
        if len(bars) < config.min_history + 1:
            excluded[ticker] = f"only {len(bars)} bars (< {config.min_history + 1})"
            continue
        f = features.compute(bars)
        if filings is not None:
            f |= catalysts.features(bars, filings.get(ticker, []), last_decision)
        out = labels.compute(bars, config)
        keep = np.arange(len(bars)) >= config.min_history - 1
        keep &= np.isfinite(f["rvol"]) & np.isfinite(f["dollar_volume_20"])
        # Only tradable rows enter the panel (keeps a full-market panel small enough for memory).
        with np.errstate(invalid="ignore"):
            keep &= (bars.close >= config.min_price) & (f["dollar_volume_20"] >= config.min_dollar_volume)
        idx = np.where(keep)[0]
        blocks.append((ticker, bars, f, out, idx))
    if not blocks:
        return Panel(np.empty((0, len(names) + len(MARKET_FEATURES))), names + list(MARKET_FEATURES), np.array([]),
                     np.array([]), np.array([], dtype=int), {h: {} for h in config.horizons}, np.array([], dtype=bool),
                     np.array([]), np.array([]), filings is not None, excluded)

    blocks = [b for b in blocks if len(b[4])]
    if not blocks:
        return build_panel({}, filings, config, last_decision)
    X = np.vstack([np.column_stack([f[name][idx] for name in names]).astype(np.float32) for _, _, f, _, idx in blocks])
    dates = np.concatenate([bars.dates[idx] for _, bars, _, _, idx in blocks])
    tickers = np.concatenate([np.full(len(idx), t, dtype=object) for t, _, _, _, idx in blocks])
    rows = np.concatenate([idx for *_, idx in blocks])
    price = np.concatenate([bars.close[idx] for _, bars, _, _, idx in blocks])
    dollar = np.concatenate([f["dollar_volume_20"][idx] for _, _, f, _, idx in blocks])
    outcomes = {h: {k: np.concatenate([out[h][k][idx] for _, _, _, out, idx in blocks]) for k in blocks[0][3][h]}
                for h in config.horizons}

    # Market context from the same universe on the same day (known after that day's close).
    ordinal = np.array([d.toordinal() for d in dates])
    ret1, ret20 = X[:, names.index("ret_1d")], X[:, names.index("ret_20d")]
    market = np.full((len(dates), 3), np.nan)
    order = np.argsort(ordinal, kind="stable")
    bounds = np.flatnonzero(np.diff(ordinal[order])) + 1
    for group in np.split(order, bounds):
        with np.errstate(all="ignore"):
            market[group] = [np.nanmedian(ret1[group]), np.nanmedian(ret20[group]), np.nanmean(ret1[group] > 0)]
    X = np.column_stack([X, market.astype(np.float32)])
    eligible = (price >= config.min_price) & (dollar >= config.min_dollar_volume)
    return Panel(X, names + list(MARKET_FEATURES), dates, tickers, rows, outcomes, eligible, price, dollar,
                 filings is not None, excluded)

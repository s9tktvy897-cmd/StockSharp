"""Daily OHLCV bars per ticker, loaders and a data-quality check.

Sources: Stooq (secondary, free) or a directory of CSV files (``<TICKER>.csv`` with
Date,Open,High,Low,Close,Volume) exported from any data provider the user is licensed for."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

SPLIT_RATIOS = (2, 3, 4, 5, 7, 8, 10, 20)
TOLERANCE = 0.005  # adjusted prices carry rounding noise; only larger inconsistencies are errors


@dataclass(frozen=True)
class Bars:
    ticker: str
    dates: np.ndarray  # datetime.date objects, strictly increasing
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    source: str
    # Price actually traded that day (not adjusted for later splits); None when the source only has
    # adjusted prices. Filters such as "price >= $2" must use this, or they depend on future splits.
    raw_close: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.dates)

    def until(self, last: date) -> "Bars":
        """Only bars dated on or before ``last`` (what was known after that day's close)."""
        n = int(np.searchsorted(np.array([d.toordinal() for d in self.dates]), last.toordinal(), side="right"))
        return Bars(self.ticker, self.dates[:n], self.open[:n], self.high[:n], self.low[:n], self.close[:n],
                    self.volume[:n], self.source, None if self.raw_close is None else self.raw_close[:n])

    @property
    def traded_close(self) -> np.ndarray:
        """The real (unadjusted) close where known, else the adjusted close."""
        return self.close if self.raw_close is None else self.raw_close


def parse_ohlcv_csv(text: str, ticker: str, source: str) -> Bars:
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        hint = "a JavaScript bot check" if "javascript" in text.lower() else "an HTML page"
        raise ValueError(f"{ticker}: {source} returned {hint} instead of CSV data")
    reader = csv.DictReader(io.StringIO(text.strip()))
    fields = {name.lower(): name for name in reader.fieldnames or []}
    needed = ("date", "open", "high", "low", "close", "volume")
    if not all(k in fields for k in needed):
        raise ValueError(f"{ticker}: CSV needs columns {needed}, got {reader.fieldnames}")
    rows = {}
    for row in reader:
        try:
            values = [float(row[fields[k]]) for k in needed[1:]]
        except (TypeError, ValueError):
            continue
        rows[date.fromisoformat(row[fields["date"]][:10])] = values
    days = sorted(rows)
    data = np.array([rows[d] for d in days], dtype=float).reshape(-1, 5)
    return Bars(ticker.upper(), np.array(days, dtype=object), data[:, 0], data[:, 1], data[:, 2], data[:, 3],
                data[:, 4], source)


def load_csv_dir(directory: Path) -> dict[str, Bars]:
    out = {}
    for path in sorted(Path(directory).glob("*.csv")):
        out[path.stem.upper()] = parse_ohlcv_csv(path.read_text(encoding="utf-8"), path.stem, f"local CSV {path}")
    return out


def validate(bars: Bars) -> list[str]:
    problems = []
    t = bars.ticker
    if len(bars) == 0:
        return [f"{t}: no bars"]
    ordinals = np.array([d.toordinal() for d in bars.dates])
    if np.any(np.diff(ordinals) <= 0):
        problems.append(f"{t}: dates not strictly increasing")
    if np.any(np.minimum.reduce([bars.open, bars.high, bars.low, bars.close]) <= 0):
        problems.append(f"{t}: non-positive prices")
    high_bad = bars.high < np.maximum(bars.open, bars.close) * (1 - TOLERANCE)
    low_bad = bars.low > np.minimum(bars.open, bars.close) * (1 + TOLERANCE)
    if np.any(high_bad):
        problems.append(f"{t}: high below open/close on {int(np.sum(high_bad))} days")
    if np.any(low_bad):
        problems.append(f"{t}: low above open/close on {int(np.sum(low_bad))} days")
    if np.any(bars.volume < 0):
        problems.append(f"{t}: negative volume")
    ratio = bars.close[1:] / bars.close[:-1]
    for i in np.where(np.abs(ratio - 1) > 0.4)[0]:
        for k in SPLIT_RATIOS:
            if abs(ratio[i] * k - 1) < 0.03 or abs(ratio[i] / k - 1) < 0.03:
                problems.append(f"{t}: close jumps x{ratio[i]:.3f} on {bars.dates[i + 1]}: possible unadjusted split ({k}:1)")
                break
    return problems

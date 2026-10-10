"""Daily OHLCV for US stocks from Yahoo Finance via the ``yfinance`` package.

SECONDARY, unofficial source (listed as such in CLAUDE.md, section 3): no API key, covers all
NYSE/Nasdaq listings. Downloaded unadjusted with corporate actions (``auto_adjust=False``,
``actions=True``): Yahoo's Close is split-adjusted, Adj Close also dividend-adjusted. OHLC are
scaled to total-return prices (Adj Close / Close); the price actually traded that day is rebuilt
from the split history (``Bars.raw_close``), so price filters do not depend on later splits. A split
or dividend rewrites the adjusted history: when the overlap between the cache and a fresh download
disagrees, the ticker's full history is downloaded again instead of mixing bases."""

from __future__ import annotations

import gzip
import io
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from equity_research.provenance import MissingDataError, SourcedValue
from equity_research.shortterm.bars import Bars

SOURCE = "Yahoo Finance via yfinance (secondary, unofficial; split- and dividend-adjusted)"
INDEX_SYMBOLS = {"^SPX": "^GSPC"}
FIELDS = ("Open", "High", "Low", "Close", "Volume")
FRESH = timedelta(hours=12)
OVERLAP_DAYS = 10
MISMATCH = 0.005
CACHE_FORMAT = 2  # 2: also stores the real traded close; older caches are downloaded again


def real_close(close: np.ndarray, splits: np.ndarray) -> np.ndarray:
    """Undo the split adjustment: a split of ratio r on day d multiplies every earlier close by r."""
    ratio = np.where(np.isfinite(splits) & (splits > 0), splits, 1.0)
    later = np.concatenate([np.cumprod(ratio[::-1])[::-1][1:], [1.0]])  # product of ratios after each day
    return close * later


def yahoo_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return INDEX_SYMBOLS.get(t, t.replace(".", "-"))


def _yf_download(symbols, **kwargs):
    import yfinance  # imported lazily: optional at import time, required to fetch

    return yfinance.download(symbols, **kwargs)


class YahooPrices:
    def __init__(self, cache_dir: Path, download: Callable | None = None, years: int = 5,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc), chunk: int = 100,
                 pause: float = 1.0, sleep: Callable[[float], None] = time.sleep):
        self.dir = Path(cache_dir) / "yahoo"
        self.download = download or _yf_download
        self.years, self.now, self.chunk, self.pause, self.sleep = years, now, chunk, pause, sleep

    # --- cache --------------------------------------------------------------------------------
    def _path(self, ticker: str) -> Path:
        return self.dir / f"{yahoo_symbol(ticker).replace('^', '_')}.csv.gz"

    def _load(self, ticker: str) -> tuple[Bars | None, datetime | None]:
        path = self._path(ticker)
        meta = path.with_suffix(".json")
        if not path.exists() or not meta.exists():
            return None, None
        info = json.loads(meta.read_text())
        if info.get("years", 0) < self.years or info.get("format", 1) < CACHE_FORMAT:
            return None, None
        from equity_research.shortterm.bars import parse_ohlcv_csv
        text = gzip.decompress(path.read_bytes()).decode()
        bars = parse_ohlcv_csv(text, ticker, SOURCE)
        header = text.split("\n", 1)[0].split(",")
        if "RawClose" in header:
            column = header.index("RawClose")
            raw = {date.fromisoformat(r.split(",")[0]): float(r.split(",")[column])
                   for r in text.strip().split("\n")[1:]}
            bars = Bars(bars.ticker, bars.dates, bars.open, bars.high, bars.low, bars.close, bars.volume, bars.source,
                        np.array([raw[d] for d in bars.dates]))
        return bars, datetime.fromisoformat(info["fetched"])

    def _save(self, bars: Bars) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        out = io.StringIO()
        out.write("Date,Open,High,Low,Close,Volume,RawClose\n")
        raw = bars.traded_close
        for i, d in enumerate(bars.dates):
            out.write(f"{d}," + ",".join(repr(float(x[i])) for x in (bars.open, bars.high, bars.low, bars.close,
                                                                     bars.volume, raw)) + "\n")
        path = self._path(bars.ticker)
        path.write_bytes(gzip.compress(out.getvalue().encode()))
        path.with_suffix(".json").write_text(json.dumps({"fetched": self.now().isoformat(), "years": self.years,
                                                         "format": CACHE_FORMAT}))

    # --- download -----------------------------------------------------------------------------
    def _fetch(self, tickers: list[str], **kwargs) -> dict[str, Bars]:
        symbols = [yahoo_symbol(t) for t in tickers]
        frame = self.download(symbols, interval="1d", auto_adjust=False, actions=True, group_by="ticker",
                              threads=True, progress=False, **kwargs)
        out = {}
        if frame is None or getattr(frame, "empty", True):
            return out
        for ticker, symbol in zip(tickers, symbols):
            try:
                part = frame[symbol] if symbol in frame.columns.get_level_values(0) else None
            except (KeyError, AttributeError):
                part = None
            if part is None or not all(f in part.columns for f in FIELDS):
                continue
            extra = [c for c in ("Adj Close", "Stock Splits") if c in part.columns]
            part = part[list(FIELDS) + extra].dropna(subset=["Open", "High", "Low", "Close"])
            if part.empty:
                continue
            days = np.array([ts.date() for ts in part.index], dtype=object)
            v = part[list(FIELDS)].to_numpy(dtype=float)
            o, h, l, c, vol = v[:, 0], v[:, 1], v[:, 2], v[:, 3], np.nan_to_num(v[:, 4])
            raw = None
            if "Stock Splits" in extra:
                raw = real_close(c, part["Stock Splits"].to_numpy(dtype=float))
            if "Adj Close" in extra:
                adj = part["Adj Close"].to_numpy(dtype=float)
                factor = np.where(np.isfinite(adj) & (c > 0), adj / c, 1.0)
                o, h, l, c = o * factor, h * factor, l * factor, c * factor
            out[ticker] = Bars(ticker.upper(), days, o, h, l, c, vol, SOURCE, raw)
        return out

    def _chunks(self, tickers: list[str]):
        for k in range(0, len(tickers), self.chunk):
            if k:
                self.sleep(self.pause)
            yield tickers[k:k + self.chunk]

    @staticmethod
    def _merge(old: Bars, new: Bars) -> Bars | None:
        """Append new days; None when the overlapping days disagree (history was re-adjusted)."""
        old_close = dict(zip(old.dates, old.close))
        for d, c in zip(new.dates, new.close):
            if d in old_close and abs(c / old_close[d] - 1) > MISMATCH:
                return None
        cut = new.dates[0]
        keep = np.array([d < cut for d in old.dates])
        cat = lambda a, b: np.concatenate([a[keep], b])
        return Bars(old.ticker, cat(old.dates, new.dates), cat(old.open, new.open), cat(old.high, new.high),
                    cat(old.low, new.low), cat(old.close, new.close), cat(old.volume, new.volume), SOURCE,
                    cat(old.traded_close, new.traded_close))

    def bars(self, tickers: list[str]) -> tuple[dict[str, Bars], list[str]]:
        result, missing, full, incremental = {}, [], [], {}
        now = self.now()
        for t in dict.fromkeys(x.upper() for x in tickers):
            cached, fetched = self._load(t)
            if cached is not None and fetched and now - fetched < FRESH:
                result[t] = cached
            elif cached is not None and len(cached):
                incremental[t] = cached
            else:
                full.append(t)

        refetch = []
        if incremental:
            start = min(b.dates[-1] for b in incremental.values()) - timedelta(days=OVERLAP_DAYS)
            for chunk in self._chunks(sorted(incremental)):
                fresh = self._fetch(chunk, start=start.isoformat())
                for t in chunk:
                    merged = self._merge(incremental[t], fresh[t]) if t in fresh else None
                    if t in fresh and merged is None:
                        refetch.append(t)
                    elif merged is not None:
                        result[t] = merged
                        self._save(merged)
                    else:
                        result[t] = incremental[t]
                        missing.append(f"Yahoo {t}: no new bars (kept cached history up to {incremental[t].dates[-1]})")
        for chunk in self._chunks(full + refetch):
            fresh = self._fetch(chunk, period=f"{self.years}y")
            for t in chunk:
                if t in fresh:
                    result[t] = fresh[t]
                    self._save(fresh[t])
                else:
                    missing.append(f"Yahoo {t}: no data")
        return result, missing

    def daily_closes(self, ticker: str) -> list[SourcedValue]:
        bars, _ = self.bars([ticker])
        if ticker.upper() not in bars:
            raise MissingDataError(f"Yahoo Finance returned no prices for {ticker}")
        b = bars[ticker.upper()]
        fetched = self.now().date()
        ref = f"{yahoo_symbol(ticker)} daily close (yfinance)"
        return [SourcedValue(value=float(c), unit="USD/share", source=SOURCE, reference=ref, retrieved=fetched,
                             period_end=d, currency="USD") for d, c in zip(b.dates, b.close)]

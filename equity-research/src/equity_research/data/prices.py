"""Daily closes from Stooq (CSV download). SECONDARY source: unofficial, check splits and gaps.

Format of https://stooq.com/q/d/l/?s=aapl.us&i=d: ``Date,Open,High,Low,Close,Volume``; an
unknown symbol returns the text ``No data``. US tickers carry the suffix ``.us``; indices keep
their caret (``^spx``)."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient
from equity_research.provenance import MissingDataError, SourcedValue

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
MAX_AGE = timedelta(hours=12)
SOURCE = "Stooq (secondary)"


def stooq_symbol(ticker: str) -> str:
    ticker = ticker.strip().lower()
    return ticker if ticker.startswith("^") else ticker.replace(".", "-") + ".us"


def parse_stooq_csv(text: str, symbol: str, retrieved: date, reference: str) -> list[SourcedValue]:
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise MissingDataError(f"Stooq returned {'a JavaScript bot check' if 'javascript' in text.lower() else 'an HTML page'}"
                               f" instead of CSV for {symbol}")
    rows = list(csv.DictReader(io.StringIO(text.strip())))
    if not rows or "Close" not in rows[0] or "Date" not in rows[0]:
        raise MissingDataError(f"Stooq returned no price data for {symbol}: {text[:60]!r}")
    return [SourcedValue(value=float(row["Close"]), unit="USD/share", source=SOURCE, reference=f"{symbol} {reference}",
                         retrieved=retrieved, period_end=date.fromisoformat(row["Date"]), currency="USD")
            for row in rows if row.get("Close") not in (None, "")]


class Stooq:
    def __init__(self, client: HttpClient, cache: DiskCache) -> None:
        self._client = client
        self._cache = cache

    def daily_closes(self, ticker: str) -> list[SourcedValue]:
        symbol = stooq_symbol(ticker)
        url = STOOQ_URL.format(symbol=symbol)
        body, fetched = self._cache.fetch(url, self._client.get, MAX_AGE)
        return parse_stooq_csv(body.decode("utf-8", errors="replace"), symbol, fetched.date(), url)


def close_on_or_before(prices: list[SourcedValue], day: date, max_staleness: timedelta = timedelta(days=7)) -> SourcedValue:
    candidates = [p for p in prices if p.period_end <= day and p.value is not None]
    if not candidates:
        raise MissingDataError(f"no close on or before {day}")
    latest = max(candidates, key=lambda p: p.period_end)
    if day - latest.period_end > max_staleness:
        raise MissingDataError(f"latest close {latest.period_end} is older than {max_staleness} before {day}")
    return latest

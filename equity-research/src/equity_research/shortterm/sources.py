"""Data loading for the short-term engine: universe and 8-K filings from SEC (official), daily
bars from Stooq (secondary) or local CSV files. Failures are returned as messages, never filled."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from equity_research.data.__main__ import CACHE_DIR
from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient, user_agent_from_env
from equity_research.data.prices import STOOQ_URL, stooq_symbol
from equity_research.data.sec_edgar import SUBMISSIONS_URL, format_cik
from equity_research.shortterm.bars import Bars, load_csv_dir, parse_ohlcv_csv
from equity_research.shortterm.catalysts import (CURRENT_FEED_URL, NEW_YORK, Filing, calibrate_times,
                                                 parse_current_feed, parse_submissions)
from equity_research.valuation.run import FETCH_ERRORS

EXCHANGE_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
LISTED = ("Nasdaq", "NYSE")


NON_COMMON_SUFFIXES = {"WT", "WS", "W", "UN", "U", "RT", "R"}


def is_common_stock(ticker: str) -> bool:
    """Leaves out warrants, units and rights (``AAC-WT``, ``AAC-UN``); share classes (``BRK-B``) stay."""
    _, _, suffix = ticker.upper().partition("-")
    return suffix not in NON_COMMON_SUFFIXES


@dataclass
class Listing:
    ticker: str
    cik: str
    name: str
    exchange: str


@dataclass
class LoadResult:
    bars: dict[str, Bars] = field(default_factory=dict)
    filings: dict[str, list[Filing]] | None = None
    names: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    bars_source: str = ""
    timing: dict[str, str] = field(default_factory=dict)  # ticker -> how the 8-K times were checked


class ShortTermSources:
    def __init__(self, client: HttpClient | None = None, cache: DiskCache | None = None):
        self.client = client or HttpClient(user_agent_from_env())
        self.cache = cache or DiskCache(CACHE_DIR)

    def _get(self, url: str, max_age: timedelta) -> bytes:
        return self.cache.fetch(url, self.client.get, max_age)[0]

    def listings(self) -> dict[str, Listing]:
        data = json.loads(self._get(EXCHANGE_TICKERS_URL, timedelta(days=1)))
        cols = data["fields"]
        out = {}
        for row in data["data"]:
            r = dict(zip(cols, row))
            if r["exchange"] in LISTED and is_common_stock(r["ticker"]):
                out[r["ticker"].upper()] = Listing(r["ticker"].upper(), format_cik(r["cik"]), r["name"], r["exchange"])
        return out

    def filings(self, listing: Listing, max_age: timedelta = timedelta(hours=1)) -> tuple[list[Filing], str]:
        """8-K filings with acceptance times checked against the filing pages (see
        ``catalysts.calibrate_times``)."""
        data = json.loads(self._get(SUBMISSIONS_URL.format(cik=listing.cik), max_age))
        return calibrate_times(parse_submissions(data, listing.ticker), self.accepted_on_index)

    def accepted_on_index(self, url: str) -> datetime:
        """The 'Accepted' time (New York) shown on an EDGAR filing index page. Filed documents do
        not change, so the page is cached without expiry."""
        text = html.unescape(re.sub(r"<[^>]+>", " ", self._get(url, None).decode("latin-1")))
        match = re.search(r"Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
        if not match:
            raise ValueError(f"no acceptance time on {url}")
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK).astimezone(timezone.utc)

    def current_8k(self, since: datetime, max_pages: int = 10) -> list[Filing]:
        """New 8-Ks from the EDGAR live feed, newest first, back to ``since`` (UTC)."""
        out = []
        for page in range(max_pages):
            text = self.client.get(CURRENT_FEED_URL.format(start=page * 100)).decode("latin-1")
            batch = parse_current_feed(text)
            out += [f for f in batch if f.accepted >= since]
            if not batch or batch[-1].accepted < since:
                break
        return out

    def stooq_bars(self, ticker: str) -> Bars:
        symbol = stooq_symbol(ticker)
        text = self._get(STOOQ_URL.format(symbol=symbol), timedelta(hours=12)).decode("utf-8", errors="replace")
        return parse_ohlcv_csv(text, ticker, "Stooq (secondary)")


def load(tickers: list[str] | None, bars_dir: Path | None, use_stooq: bool, use_sec: bool,
         sources: ShortTermSources | None = None, max_tickers: int | None = None, use_yahoo: bool = False,
         yahoo=None) -> LoadResult:
    """Bars from (in this order of preference) a CSV directory, Yahoo Finance or Stooq; the default
    universe is every NYSE/Nasdaq listing in the SEC ticker file. ``max_tickers`` 0/None = all."""
    result = LoadResult()
    sources = sources or ShortTermSources()
    listings: dict[str, Listing] = {}
    try:
        listings = sources.listings()
    except FETCH_ERRORS as error:
        result.missing.append(f"SEC ticker list: {error}")

    if bars_dir:
        result.bars = load_csv_dir(bars_dir)
        result.bars_source = f"local CSV files in {bars_dir}"
        if tickers:
            result.bars = {t: b for t, b in result.bars.items() if t in {x.upper() for x in tickers}}
    elif use_yahoo:
        from equity_research.data.yahoo import YahooPrices

        universe = [t.upper() for t in tickers] if tickers else sorted(listings)
        universe = universe[:max_tickers] if max_tickers else universe
        provider = yahoo or YahooPrices(CACHE_DIR)
        result.bars_source = "Yahoo Finance via yfinance (secondary; split- and dividend-adjusted)"
        try:
            result.bars, problems = provider.bars(universe)
        except Exception as error:  # noqa: BLE001 -- report any provider failure, never fill in
            result.missing.append(f"Yahoo Finance: {error}")
            problems = []
        if problems:
            result.missing.append(f"Yahoo Finance: no bars for {len(problems)} of {len(universe)} tickers "
                                  f"(e.g. {'; '.join(problems[:3])})")
    elif use_stooq:
        universe = [t.upper() for t in tickers] if tickers else sorted(listings)
        universe = universe[:max_tickers] if max_tickers else universe
        result.bars_source = "Stooq daily bars (secondary source)"
        failures = 0
        for ticker in universe:
            try:
                result.bars[ticker] = sources.stooq_bars(ticker)
            except FETCH_ERRORS as error:
                failures += 1
                if failures <= 3:
                    result.missing.append(f"Stooq bars {ticker}: {error}")
                if failures == 3 and not result.bars:
                    result.missing.append("Stooq unreachable: stopped after 3 failures")
                    break
        if failures > 3:
            result.missing.append(f"Stooq bars missing for {failures} tickers in total")
    else:
        result.missing.append("no price source given (use --yahoo, --bars-dir or --stooq)")

    result.names = {t: listings[t].name for t in result.bars if t in listings}
    if use_sec:
        result.filings = {}
        for ticker in result.bars:
            if ticker not in listings:
                continue
            try:
                result.filings[ticker], result.timing[ticker] = sources.filings(listings[ticker])
            except FETCH_ERRORS as error:
                result.missing.append(f"SEC filings {ticker}: {error}")
                continue
            if result.timing[ticker].startswith("unreliable"):
                result.missing.append(f"SEC 8-K times {ticker}: {result.timing[ticker]}; its 8-Ks are not used")
    return result

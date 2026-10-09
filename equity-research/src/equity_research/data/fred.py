"""FRED (St. Louis Fed) series via the public fredgraph CSV endpoint."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient
from equity_research.provenance import MissingDataError, SourcedValue

SERIES_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
MAX_AGE = timedelta(days=1)

# Units as documented on the FRED series pages; unknown series are labelled as such, not guessed.
SERIES_UNITS = {
    "DGS10": "percent",
    "DGS30": "percent",
    "DGS5": "percent",
    "DTB3": "percent",
    "T10YIE": "percent",
    "CPIAUCSL": "index 1982-1984=100",
    "GDP": "billions of USD, SAAR",
}


def parse_series_csv(text: str, series: str, retrieved: date, reference: str) -> list[SourcedValue]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) != 2 or rows[0][1].strip() != series:
        raise ValueError(f"unexpected FRED CSV header for {series}: {rows[0] if rows else None}")
    unit = SERIES_UNITS.get(series, "unspecified (see FRED series notes)")
    values = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        raw = row[1].strip() if len(row) > 1 else ""
        values.append(SourcedValue(
            value=None if raw in ("", ".") else float(raw),
            unit=unit,
            source="FRED",
            reference=f"{series} {reference}",
            retrieved=retrieved,
            period_end=date.fromisoformat(row[0].strip()),
        ))
    return values


def latest_on_or_before(series: list[SourcedValue], day: date, max_staleness: timedelta = timedelta(days=10)) -> SourcedValue:
    candidates = [v for v in series if not v.is_missing and v.period_end is not None and v.period_end <= day]
    if not candidates:
        raise MissingDataError(f"no observation on or before {day}")
    latest = max(candidates, key=lambda v: v.period_end)
    if day - latest.period_end > max_staleness:
        raise MissingDataError(f"latest observation {latest.period_end} is older than {max_staleness} before {day}")
    return latest


class Fred:
    def __init__(self, client: HttpClient, cache: DiskCache) -> None:
        self._client = client
        self._cache = cache

    def series(self, series: str) -> list[SourcedValue]:
        url = SERIES_URL.format(series=series)
        body, fetched = self._cache.fetch(url, self._client.get, MAX_AGE)
        return parse_series_csv(body.decode("utf-8"), series, fetched.date(), url)

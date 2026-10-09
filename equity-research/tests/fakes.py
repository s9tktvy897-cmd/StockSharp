"""Test doubles. All fixture data here is SYNTHETIC: it mimics the documented response
formats of SEC EDGAR and FRED but the companies and numbers are invented for tests only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from equity_research.data.cache import DiskCache
from equity_research.data.http import HttpClient

USER_AGENT = "equity-research-tests test@example.com"


class FakeTransport:
    def __init__(self, responses: dict[str, list[tuple[int, bytes]] | tuple[int, bytes]]) -> None:
        self._responses = {url: list(r) if isinstance(r, list) else [r] for url, r in responses.items()}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.calls.append((url, headers))
        queue = self._responses.get(url)
        if not queue:
            return 404, b""
        return queue.pop(0) if len(queue) > 1 else queue[0]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(transport: FakeTransport) -> HttpClient:
    clock = FakeClock()
    return HttpClient(USER_AGENT, transport=transport, clock=clock.clock, sleep=clock.sleep)


def make_cache(tmp_path: Path, now: datetime = datetime(2026, 10, 9, tzinfo=timezone.utc)) -> DiskCache:
    return DiskCache(tmp_path / "cache", now=lambda: now)


def as_json(data) -> tuple[int, bytes]:
    return 200, json.dumps(data).encode()


SYNTHETIC_CIK = "0000000042"

SYNTHETIC_TICKERS = {
    "0": {"cik_str": 42, "ticker": "TSTX", "title": "SYNTHETIC TEST CO"},
    "1": {"cik_str": 43, "ticker": "BRK-B", "title": "SYNTHETIC CLASS B CO"},
}

SYNTHETIC_SUBMISSIONS = {
    "cik": "42", "name": "SYNTHETIC TEST CO", "tickers": ["TSTX"], "exchanges": ["Nasdaq"],
    "sic": "3571", "sicDescription": "Electronic Computers", "fiscalYearEnd": "1231",
}


def _row(start, end, val, accn, fy, fp, form, filed):
    row = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start:
        row["start"] = start
    return row


# FY2023 10-K reports FY2023 and FY2022 (comparative). FY2024 10-K restates FY2023 (1000 -> 990).
# The 10-Q rows are discrete quarters plus a 9-month YTD row that must not be taken as a quarter.
SYNTHETIC_COMPANY_FACTS = {
    "cik": 42,
    "entityName": "SYNTHETIC TEST CO",
    "facts": {
        "us-gaap": {
            "Revenues": {"units": {"USD": [
                _row("2022-01-01", "2022-12-31", 900, "A-23", 2023, "FY", "10-K", "2024-02-15"),
                _row("2023-01-01", "2023-12-31", 1000, "A-23", 2023, "FY", "10-K", "2024-02-15"),
                _row("2023-01-01", "2023-12-31", 990, "A-24", 2024, "FY", "10-K", "2025-02-14"),
                _row("2024-01-01", "2024-12-31", 1100, "A-24", 2024, "FY", "10-K", "2025-02-14"),
                _row("2024-01-01", "2024-03-31", 260, "Q-1", 2024, "Q1", "10-Q", "2024-05-01"),
                _row("2024-04-01", "2024-06-30", 270, "Q-2", 2024, "Q2", "10-Q", "2024-08-01"),
                _row("2024-01-01", "2024-06-30", 530, "Q-2", 2024, "Q2", "10-Q", "2024-08-01"),
                _row("2024-01-01", "2024-09-30", 810, "Q-3", 2024, "Q3", "10-Q", "2024-11-01"),
                _row("2024-07-01", "2024-09-30", 280, "Q-3", 2024, "Q3", "10-Q", "2024-11-01"),
                _row("2024-06-01", "2024-12-31", 700, "8K-1", 2024, "FY", "8-K", "2025-01-30"),
            ]}},
            "Assets": {"units": {"USD": [
                _row(None, "2023-12-31", 5000, "A-23", 2023, "FY", "10-K", "2024-02-15"),
                _row(None, "2024-12-31", 5500, "A-24", 2024, "FY", "10-K", "2025-02-14"),
                _row(None, "2024-06-30", 5200, "Q-2", 2024, "Q2", "10-Q", "2024-08-01"),
            ]}},
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {"units": {"shares": [
                _row(None, "2025-02-01", 100, "A-24", 2024, "FY", "10-K", "2025-02-14"),
            ]}},
        },
    },
}

SYNTHETIC_FRED_DGS10 = "observation_date,DGS10\n2026-10-01,4.00\n2026-10-02,4.10\n2026-10-05,.\n2026-10-06,\n"

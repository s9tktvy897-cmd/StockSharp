from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from equity_research.data import yahoo
from equity_research.provenance import MissingDataError


def frame(prices: dict[str, list[float]], start="2026-10-01", volume=1000.0):
    """SYNTHETIC frame in the layout of yfinance.download(group_by='ticker'): columns (Ticker, Price)."""
    days = pd.bdate_range(start, periods=len(next(iter(prices.values()))))
    cols = {}
    for t, closes in prices.items():
        c = np.asarray(closes, dtype=float)
        for field, values in (("Open", c * 0.99), ("High", c * 1.01), ("Low", c * 0.98), ("Close", c),
                              ("Volume", np.full(len(c), volume))):
            cols[(t, field)] = values
    return pd.DataFrame(cols, index=days)


class FakeDownload:
    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, symbols, **kwargs):
        self.calls.append((list(symbols), kwargs))
        return self.data(symbols, kwargs) if callable(self.data) else self.data


def _prices(tmp_path, download, now=datetime(2026, 10, 9, 23, tzinfo=timezone.utc)):
    return yahoo.YahooPrices(tmp_path, download=download, now=lambda: now, sleep=lambda s: None, chunk=2)


def test_symbols():
    assert yahoo.yahoo_symbol("brk.b") == "BRK-B"
    assert yahoo.yahoo_symbol("^SPX") == "^GSPC"


def test_bars_for_many_tickers_in_chunks_and_missing_ones(tmp_path):
    def data(symbols, kwargs):
        return frame({s: [10, 11, 12] for s in symbols if s != "ZZZZ"} | ({"ZZZZ": [np.nan] * 3} if "ZZZZ" in symbols else {}))
    fake = FakeDownload(data)
    bars, missing = _prices(tmp_path, fake).bars(["AAA", "BBB", "ZZZZ"])
    assert sorted(bars) == ["AAA", "BBB"] and len(fake.calls) == 2  # chunks of 2
    assert bars["AAA"].close.tolist() == [10, 11, 12] and "secondary" in bars["AAA"].source
    assert any("ZZZZ" in m for m in missing)
    assert fake.calls[0][1]["auto_adjust"] is True


def test_cache_is_reused_then_extended_incrementally(tmp_path):
    first = FakeDownload(lambda s, k: frame({t: [10, 11, 12] for t in s}))
    _prices(tmp_path, first).bars(["AAA"])
    again = FakeDownload(lambda s, k: frame({t: [10, 11, 12] for t in s}))
    _prices(tmp_path, again).bars(["AAA"])
    assert again.calls == []  # fresh cache
    later = FakeDownload(lambda s, k: frame({t: [12, 13, 14] for t in s}, start="2026-10-03"))
    bars, _ = _prices(tmp_path, later, now=datetime(2026, 10, 12, 23, tzinfo=timezone.utc)).bars(["AAA"])
    assert "start" in later.calls[0][1]  # only recent days requested
    assert bars["AAA"].close.tolist() == [10, 11, 12, 13, 14]


def test_changed_adjusted_history_triggers_a_full_refetch(tmp_path):
    _prices(tmp_path, FakeDownload(lambda s, k: frame({t: [10, 11, 12] for t in s}))).bars(["AAA"])
    # a 2:1 split: Yahoo now shows the overlapping days halved
    calls = []

    def data(symbols, kwargs):
        calls.append(kwargs)
        if "start" in kwargs:
            return frame({t: [6, 6.5, 7] for t in symbols}, start="2026-10-03")
        return frame({t: [5, 5.5, 6, 6.5, 7] for t in symbols})
    bars, _ = _prices(tmp_path, FakeDownload(data), now=datetime(2026, 10, 12, 23, tzinfo=timezone.utc)).bars(["AAA"])
    assert "period" in calls[-1]
    assert bars["AAA"].close.tolist() == [5, 5.5, 6, 6.5, 7]


def test_daily_closes_and_failure(tmp_path):
    p = _prices(tmp_path, FakeDownload(lambda s, k: frame({t: [10, 11] for t in s})))
    closes = p.daily_closes("AAPL")
    assert closes[-1].value == 11 and closes[-1].currency == "USD" and "Yahoo" in closes[-1].source
    empty = _prices(tmp_path / "x", FakeDownload(lambda s, k: pd.DataFrame()))
    with pytest.raises(MissingDataError):
        empty.daily_closes("NOPE")


def test_longer_history_request_refetches_a_short_cache(tmp_path):
    yahoo.YahooPrices(tmp_path, download=FakeDownload(lambda s, k: frame({t: [10, 11] for t in s})), years=5,
                      sleep=lambda s: None).bars(["AAA"])
    fake = FakeDownload(lambda s, k: frame({t: [9, 10, 11] for t in s}))
    yahoo.YahooPrices(tmp_path, download=fake, years=12, sleep=lambda s: None).bars(["AAA"])
    assert fake.calls and fake.calls[0][1]["period"] == "12y"

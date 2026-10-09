from datetime import date

import pytest

from equity_research.data.fred import SERIES_URL, Fred, latest_on_or_before, parse_series_csv
from equity_research.provenance import MissingDataError

from fakes import SYNTHETIC_FRED_DGS10, FakeTransport, make_cache, make_client


@pytest.fixture
def dgs10(tmp_path):
    transport = FakeTransport({SERIES_URL.format(series="DGS10"): (200, SYNTHETIC_FRED_DGS10.encode())})
    return Fred(make_client(transport), make_cache(tmp_path)).series("DGS10")


def test_parses_values_and_marks_gaps_missing(dgs10):
    assert [(v.period_end, v.value) for v in dgs10] == [
        (date(2026, 10, 1), 4.00),
        (date(2026, 10, 2), 4.10),
        (date(2026, 10, 5), None),
        (date(2026, 10, 6), None),
    ]
    assert dgs10[0].unit == "percent"
    assert dgs10[0].source == "FRED"


def test_latest_on_or_before_skips_missing(dgs10):
    assert latest_on_or_before(dgs10, date(2026, 10, 6)).value == 4.10


def test_latest_refuses_stale_data(dgs10):
    with pytest.raises(MissingDataError):
        latest_on_or_before(dgs10, date(2026, 12, 31))


def test_latest_refuses_when_nothing_before(dgs10):
    with pytest.raises(MissingDataError):
        latest_on_or_before(dgs10, date(2020, 1, 1))


def test_wrong_series_header_is_rejected():
    with pytest.raises(ValueError):
        parse_series_csv("DATE,OTHER\n2026-01-01,1\n", "DGS10", date(2026, 1, 1), "u")

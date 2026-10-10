import argparse
import re
import json
from datetime import date

import pytest

from equity_research.data.damodaran import Damodaran
from equity_research.data.fred import SERIES_URL, Fred
from equity_research.data.prices import Stooq
from equity_research.data.sec_edgar import COMPANY_FACTS_URL, SUBMISSIONS_URL, TICKERS_URL, SecEdgar
from equity_research.fundamentals import checks
from equity_research.report import format as fmt
from equity_research.report.markdown import render, write_report
from equity_research.risk.assess import assess
from equity_research.valuation.run import Sources, add_market_arguments, run

from fakes import (SYNTHETIC_CIK, SYNTHETIC_FUNDAMENTALS, SYNTHETIC_SUBMISSIONS, SYNTHETIC_TICKERS, FakeTransport,
                   as_json, make_cache, make_client)


def test_dutch_number_format():
    assert fmt.nl(1234.5) == "1.234,5"
    assert fmt.nl(-0.25, 2) == "-0,25"
    assert fmt.pct(0.0874) == "8,7%"
    assert fmt.bn(416_161_000_000) == "416,2"
    assert fmt.bn(None) == fmt.MISSING
    assert fmt.multiple(10.83) == "10,8x"


@pytest.fixture
def synthetic_run(tmp_path):
    fred_csv = lambda sid, v: (200, f"observation_date,{sid}\n2026-10-08,{v}\n".encode())
    transport = FakeTransport({
        TICKERS_URL: as_json(SYNTHETIC_TICKERS),
        SUBMISSIONS_URL.format(cik=SYNTHETIC_CIK): as_json(SYNTHETIC_SUBMISSIONS),
        COMPANY_FACTS_URL.format(cik=SYNTHETIC_CIK): (200, json.dumps(
            {"cik": 42, "entityName": "SYNTHETIC TEST CO", "facts": SYNTHETIC_FUNDAMENTALS}).encode()),
        SERIES_URL.format(series="DGS10"): fred_csv("DGS10", "4.50"),
        SERIES_URL.format(series="T10YIE"): fred_csv("T10YIE", "2.30"),
    })  # Stooq and Damodaran are absent: 404
    client, cache = make_client(transport), make_cache(tmp_path)
    sources = Sources(SecEdgar(client, cache), Fred(client, cache), Stooq(client, cache), Damodaran(client, cache))
    parser = argparse.ArgumentParser()
    add_market_arguments(parser)
    r = run(parser.parse_args(["TSTX", "--as-of", "2026-10-09"]), sources)
    return r, assess(r, sources)


def test_report_has_every_section_and_no_placeholders(synthetic_run):
    r, a = synthetic_run
    text = render(r, a, checks.run_all(r.st), generated=date(2026, 10, 9))
    for heading in ("## 1. Afbakening", "## 2. Data", "## 3. Datakwaliteit", "## 4. Fundamentele analyse",
                    "## 5. Kwaliteits- en risicoscores", "## 6. Waardering", "## 7. Classificatie",
                    "## 8. Risico", "## 9. Bronnen"):
        assert heading in text
    assert "geen beleggingsadvies" in text
    assert "SYNTHETIC TEST CO" in text
    for placeholder in (r"\bNone\b", r"\bnan\b", r"\{"):
        assert not re.search(placeholder, text), placeholder
    assert "Stooq" in text and "niet bereikbaar" in text  # missing sources are reported
    assert "Niet te bepalen" in text  # undervalued screen without price


def test_write_report_uses_ticker_and_date(tmp_path, synthetic_run):
    r, a = synthetic_run
    path = write_report("# x\n", "TSTX", date(2026, 10, 9), tmp_path)
    assert path == tmp_path / "TSTX_2026-10-09.md"
    assert path.read_text() == "# x\n"


def test_company_without_annual_statements_is_refused_with_a_reason(tmp_path):
    """A new registrant (e.g. a holding company after a reorganization) has no XBRL history yet."""
    from equity_research.valuation.run import NotApplicable
    transport = FakeTransport({
        TICKERS_URL: as_json(SYNTHETIC_TICKERS),
        SUBMISSIONS_URL.format(cik=SYNTHETIC_CIK): as_json(SYNTHETIC_SUBMISSIONS),
        COMPANY_FACTS_URL.format(cik=SYNTHETIC_CIK): (200, json.dumps(
            {"cik": 42, "entityName": "SYNTHETIC TEST CO", "facts": {}}).encode()),
    })
    client, cache = make_client(transport), make_cache(tmp_path)
    sources = Sources(SecEdgar(client, cache), Fred(client, cache), Stooq(client, cache), Damodaran(client, cache))
    parser = argparse.ArgumentParser()
    add_market_arguments(parser)
    with pytest.raises(NotApplicable, match="no annual XBRL statements"):
        run(parser.parse_args(["TSTX"]), sources)

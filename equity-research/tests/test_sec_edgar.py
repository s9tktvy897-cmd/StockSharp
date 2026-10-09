from datetime import date

import pytest

from equity_research.data.sec_edgar import (
    COMPANY_FACTS_URL, SUBMISSIONS_URL, TICKERS_URL, SecEdgar, UnknownTickerError, format_cik,
)

from fakes import (
    SYNTHETIC_CIK, SYNTHETIC_COMPANY_FACTS, SYNTHETIC_SUBMISSIONS, SYNTHETIC_TICKERS,
    FakeTransport, as_json, make_cache, make_client,
)


@pytest.fixture
def edgar(tmp_path):
    transport = FakeTransport({
        TICKERS_URL: as_json(SYNTHETIC_TICKERS),
        SUBMISSIONS_URL.format(cik=SYNTHETIC_CIK): as_json(SYNTHETIC_SUBMISSIONS),
        COMPANY_FACTS_URL.format(cik=SYNTHETIC_CIK): as_json(SYNTHETIC_COMPANY_FACTS),
    })
    return SecEdgar(make_client(transport), make_cache(tmp_path))


@pytest.fixture
def facts(edgar):
    return edgar.company_facts(SYNTHETIC_CIK)


def _values(series):
    return [(f.period_end, f.value) for f in series]


def test_format_cik_pads_to_ten_digits():
    assert format_cik(42) == "0000000042"
    assert format_cik("CIK320193") == "0000320193"
    with pytest.raises(ValueError):
        format_cik("12a")


def test_ticker_lookup_is_case_insensitive_and_handles_share_classes(edgar):
    assert edgar.cik_for_ticker("tstx") == SYNTHETIC_CIK
    assert edgar.cik_for_ticker("BRK.B") == "0000000043"


def test_unknown_ticker_raises(edgar):
    with pytest.raises(UnknownTickerError):
        edgar.cik_for_ticker("NOPE")


def test_profile(edgar):
    profile = edgar.profile(42)
    assert profile.name == "SYNTHETIC TEST CO"
    assert profile.sic == "3571"
    assert profile.fiscal_year_end == "1231"


def test_annual_uses_latest_filing_per_period(facts):
    assert _values(facts.annual("Revenues")) == [
        (date(2022, 12, 31), 900.0),
        (date(2023, 12, 31), 990.0),  # restated in the FY2024 10-K
        (date(2024, 12, 31), 1100.0),
    ]


def test_annual_as_of_is_point_in_time(facts):
    # Before the FY2024 10-K was filed, FY2023 was 1000 and FY2024 was unknown.
    assert _values(facts.annual("Revenues", as_of=date(2025, 1, 31))) == [
        (date(2022, 12, 31), 900.0),
        (date(2023, 12, 31), 1000.0),
    ]


def test_annual_ignores_quarterly_and_non_periodic_forms(facts):
    assert all(f.form in ("10-K", "10-K/A") for f in facts.annual("Revenues"))


def test_quarterly_excludes_year_to_date_rows(facts):
    assert _values(facts.quarterly("Revenues")) == [
        (date(2024, 3, 31), 260.0),
        (date(2024, 6, 30), 270.0),
        (date(2024, 9, 30), 280.0),
    ]


def test_instant_concepts(facts):
    assert _values(facts.annual("Assets")) == [(date(2023, 12, 31), 5000.0), (date(2024, 12, 31), 5500.0)]


def test_fact_carries_provenance(facts):
    fact = facts.annual("Revenues")[-1]
    assert fact.source == "SEC EDGAR"
    assert fact.accession == "A-24"
    assert "us-gaap:Revenues" in fact.reference
    assert fact.filed == date(2025, 2, 14)
    assert fact.currency == "USD"
    assert fact.retrieved == date(2026, 10, 9)


def test_missing_concept_returns_empty_not_a_guess(facts):
    assert facts.annual("NetIncomeLoss") == []


def test_dei_shares(facts):
    shares = facts.annual("EntityCommonStockSharesOutstanding", unit="shares", taxonomy="dei")
    assert _values(shares) == [(date(2025, 2, 1), 100.0)]
    assert shares[0].currency is None


def test_fiscal_year_describes_the_filing_not_the_period(facts):
    restated_2023 = facts.annual("Revenues")[1]
    assert restated_2023.period_end == date(2023, 12, 31)
    assert restated_2023.filing_fiscal_year == 2024
    assert restated_2023.filing_fiscal_period == "FY"

from datetime import date

import pytest

from equity_research.data.sec_edgar import CompanyFacts
from equity_research.fundamentals.statements import build_annual
from equity_research.fundamentals.ttm import latest_balance, ttm

from fakes import _row

# SYNTHETIC: calendar fiscal year; the Q2 2025 10-Q reports 6-month YTD for 2025 and 2024 plus discrete quarters.
FACTS = {"us-gaap": {
    "Revenues": {"units": {"USD": [
        _row("2024-01-01", "2024-12-31", 1100, "K24", 2024, "FY", "10-K", "2025-02-14"),
        _row("2025-01-01", "2025-06-30", 600, "Q225", 2025, "Q2", "10-Q", "2025-08-01"),
        _row("2024-01-01", "2024-06-30", 530, "Q225", 2025, "Q2", "10-Q", "2025-08-01"),
        _row("2025-04-01", "2025-06-30", 310, "Q225", 2025, "Q2", "10-Q", "2025-08-01"),
    ]}},
    "Assets": {"units": {"USD": [
        _row(None, "2024-12-31", 1700, "K24", 2024, "FY", "10-K", "2025-02-14"),
        _row(None, "2025-06-30", 1800, "Q225", 2025, "Q2", "10-Q", "2025-08-01"),
    ]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _row(None, "2024-12-31", 150, "K24", 2024, "FY", "10-K", "2025-02-14"),
        _row(None, "2025-06-30", 170, "Q225", 2025, "Q2", "10-Q", "2025-08-01"),
    ]}},
    "CommercialPaper": {"units": {"USD": [
        _row(None, "2024-12-31", 20, "K24", 2024, "FY", "10-K", "2025-02-14"),
    ]}},
}}


def _facts():
    return CompanyFacts("0000000042", "SYNTHETIC TEST CO", FACTS, date(2026, 10, 9))


def test_ttm_is_fiscal_year_plus_ytd_minus_prior_ytd():
    value = ttm(_facts(), "revenue")
    assert value.value == pytest.approx(1100 + 600 - 530)
    assert value.period_end == date(2025, 6, 30)
    assert len(value.inputs) == 3


def test_ttm_falls_back_to_fiscal_year_before_first_10q():
    value = ttm(_facts(), "revenue", as_of=date(2025, 5, 1))
    assert value.value == 1100
    assert value.period_end == date(2024, 12, 31)
    assert "no 10-Q" in value.note


def test_ttm_of_unreported_item_is_missing():
    assert ttm(_facts(), "net_income").value is None


def test_latest_balance_uses_newest_filing_date():
    facts = _facts()
    balance = latest_balance(facts, build_annual(facts))
    assert balance.period_end == date(2025, 6, 30)
    assert balance.get("total_assets").value == 1800
    assert balance.get("cash").value == 170
    # commercial paper reported at year end but not in the 10-Q: a gap, not zero
    assert balance.get("commercial_paper").value is None
    # never reported: zero with a note
    assert balance.get("short_term_borrowings").value == 0


def test_ttm_refuses_item_missing_from_latest_10k():
    data = {"us-gaap": dict(FACTS["us-gaap"], InterestExpense={"units": {"USD": [
        _row("2023-01-01", "2023-12-31", 40, "K23", 2023, "FY", "10-K", "2024-02-15")]}})}
    data["us-gaap"]["Assets"] = {"units": {"USD": FACTS["us-gaap"]["Assets"]["units"]["USD"] + [
        _row(None, "2023-12-31", 1600, "K23", 2023, "FY", "10-K", "2024-02-15")]}}
    value = ttm(CompanyFacts("0000000042", "SYNTHETIC", data, date(2026, 10, 9)), "interest_expense")
    assert value.value is None
    assert "2023-12-31" in value.missing_reason


def test_required_item_missing_on_latest_date_is_not_zero():
    facts = _facts()
    balance = latest_balance(facts, build_annual(facts))
    assert balance.get("equity").value is None

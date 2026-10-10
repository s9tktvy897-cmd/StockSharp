import copy
from datetime import date
from fractions import Fraction

import pytest

from equity_research.data.sec_edgar import CompanyFacts
from equity_research.fundamentals import analysis, checks
from equity_research.fundamentals.splits import _split_ratio, detect_splits
from equity_research.fundamentals.statements import build_annual

from fakes import SYNTHETIC_FUNDAMENTALS

FY = {year: date(year, 12, 31) for year in range(2021, 2025)}


def _facts(data=SYNTHETIC_FUNDAMENTALS):
    return CompanyFacts("0000000042", "SYNTHETIC TEST CO", copy.deepcopy(data), date(2026, 10, 9))


@pytest.fixture
def st():
    return build_annual(_facts())


def _values(series):
    return [(f.period_end, f.value) for f in series]


def test_revenue_merges_old_and_new_tag(st):
    revenue = st.series("revenue")
    assert _values(revenue) == [(FY[2021], 800), (FY[2022], 900), (FY[2023], 1000), (FY[2024], 1100)]
    assert "us-gaap:Revenues" in revenue[0].reference
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in revenue[1].reference  # priority tag
    assert any("revenue" in issue and "Revenues" in issue for issue in st.issues)


def test_conflicting_tags_are_reported():
    data = copy.deepcopy(SYNTHETIC_FUNDAMENTALS)
    data["us-gaap"]["Revenues"]["units"]["USD"][1]["val"] = 950
    st = build_annual(_facts(data))
    assert st.get("revenue", FY[2022]).value == 900
    assert any("differ" in issue and "2022-12-31" in issue for issue in st.issues)


def test_fiscal_years(st):
    assert st.fiscal_years == [FY[2021], FY[2022], FY[2023], FY[2024]]


def test_detects_split_from_restated_comparatives():
    history = _facts().history("WeightedAverageNumberOfDilutedSharesOutstanding", unit="shares")
    [split] = detect_splits(history)
    assert split.factor == 2
    assert split.last_filed_before == date(2024, 2, 15)
    assert split.first_filed_after == date(2025, 2, 14)
    assert "K23" in split.evidence and "K24" in split.evidence


def test_restatement_is_not_a_split():
    data = copy.deepcopy(SYNTHETIC_FUNDAMENTALS)
    rows = data["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"]
    for row in rows:
        if row["accn"] == "K24":
            row["val"] = {"2023-12-31": 96, "2024-12-31": 90}[row["end"]]
    assert detect_splits(_facts(data).history("WeightedAverageNumberOfDilutedSharesOutstanding", unit="shares")) == []


def test_shares_and_eps_are_split_adjusted(st):
    assert _values(st.series("diluted_shares")) == [
        (FY[2021], 210), (FY[2022], 200), (FY[2023], 190), (FY[2024], 180)]
    assert st.get("eps_diluted", FY[2022]).value == pytest.approx(0.75)
    assert "split-adjusted" in st.get("diluted_shares", FY[2021]).reference
    assert "split-adjusted" not in st.get("diluted_shares", FY[2024]).reference


def test_point_in_time_before_split_has_no_adjustment():
    st = build_annual(_facts(), as_of=date(2024, 6, 30))
    assert st.splits == []
    assert _values(st.series("diluted_shares")) == [(FY[2021], 105), (FY[2022], 100), (FY[2023], 95)]
    assert st.get("revenue", FY[2024]) is None


def test_fcf_and_margins(st):
    m = analysis.yearly_metrics(st)
    fcf = m["fcf"][FY[2024]]
    assert fcf.value == 200
    assert {f.value for f in fcf.inputs} == {250, 50}
    assert m["operating_margin"][FY[2024]].value == pytest.approx(0.2)
    assert m["fcf_conversion"][FY[2024]].value == pytest.approx(200 / 168)


def test_roic_hand_calculated(st):
    # t = 42/210 = 20%; NOPAT = 220 * 0.8 = 176
    # IC = equity + debt - cash - current and non-current securities: 2023 600, 2024 700, average 650
    roic = analysis.yearly_metrics(st)["roic"][FY[2024]]
    assert roic.value == pytest.approx(176 / 650)


def test_missing_input_gives_reason_not_number(st):
    roic = analysis.yearly_metrics(st)["roic"][FY[2023]]
    assert roic.value is None
    assert roic.missing_reason


def test_revenue_cagr(st):
    growth = analysis.growth(st, periods=(3,))
    assert growth["revenue"][3].value == pytest.approx(1.375 ** (1 / 3) - 1)
    assert growth["fcf"][3].value is None


def test_balance_sheet_check(st):
    results = checks.balance_sheet(st)
    assert [r.passed for r in results] == [True, True]
    data = copy.deepcopy(SYNTHETIC_FUNDAMENTALS)
    data["us-gaap"]["Assets"]["units"]["USD"][1]["val"] = 1800
    assert [r.passed for r in checks.balance_sheet(build_annual(_facts(data)))] == [True, False]


def test_share_jump_check_runs_after_split_adjustment(st):
    assert all(r.passed for r in checks.share_jumps(st))
    unadjusted = build_annual(_facts(), adjust_splits=False)
    assert not all(r.passed for r in checks.share_jumps(unadjusted))


@pytest.mark.parametrize("old,new,factor", [
    (934_818, 6_617_483, 7),       # off by ~1.1% from 7 (comparative restated) -> still 7, not 71/10
    (1000, 1500, Fraction(3, 2)),
    (1000, 100, Fraction(1, 10)),  # reverse split
    (1000, 1150, None),            # restatement
    (1000, 3333, None),            # no simple ratio
])
def test_split_ratio_snaps_to_simple_fractions(old, new, factor):
    assert _split_ratio(old, new, tolerance=0.02) == factor


def test_gap_in_reported_item_is_missing_not_zero():
    data = copy.deepcopy(SYNTHETIC_FUNDAMENTALS)
    data["us-gaap"]["MarketableSecuritiesNoncurrent"]["units"]["USD"].pop()  # FY2024 gone, FY2023 still there
    m = analysis.yearly_metrics(build_annual(_facts(data)))
    assert m["invested_capital"][FY[2024]].value is None
    assert "long_term_investments" in m["invested_capital"][FY[2024]].missing_reason


def test_never_reported_item_counts_as_zero_with_note(st):
    debt = analysis.yearly_metrics(st)["total_debt"][FY[2024]]
    assert debt.value == 400
    assert "commercial_paper" in debt.note and "short_term_borrowings" in debt.note


def test_return_on_capital_including_cash(st):
    # equity + debt: 2023 850, 2024 1000, average 925
    assert analysis.yearly_metrics(st)["return_on_capital_incl_cash"][FY[2024]].value == pytest.approx(176 / 925)


def test_prior_year_must_be_adjacent():
    data = copy.deepcopy(SYNTHETIC_FUNDAMENTALS)
    data["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"] = [
        r for r in data["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
        if r["end"] != "2023-12-31"]
    m = analysis.yearly_metrics(build_annual(_facts(data)))
    assert FY[2023] not in m["roe"]
    assert "no prior fiscal year" in m["diluted_shares_change"][FY[2024]].missing_reason


def test_dropped_debt_component_in_annual_statements():
    from equity_research.data.sec_edgar import EdgarFact
    from equity_research.fundamentals import analysis
    from equity_research.fundamentals.statements import AnnualStatements

    def fact(year, value):
        return EdgarFact(value, "USD", "SEC EDGAR", "x", date(2026, 1, 1), None, date(year, 12, 31))
    st = AnnualStatements("1", "SYN", None, {"commercial_paper": {date(2016, 12, 31): fact(2016, 5.0)}}, [])
    long_ago = analysis._optional(st, "commercial_paper", date(2024, 12, 31))
    assert long_ago.value == 0.0 and "assumption" in long_ago.note
    recent = analysis._optional(st, "commercial_paper", date(2017, 12, 31))
    assert recent.value is None  # reported a year earlier: missing, not zero
    st.items["commercial_paper"][date(2023, 12, 31)] = fact(2023, 0.0)
    nil = analysis._optional(st, "commercial_paper", date(2024, 12, 31))
    assert nil.value == 0.0 and "last reported as 0" in nil.note
    gap = analysis._optional(st, "commercial_paper", date(2020, 12, 31))
    assert gap.value is None  # a gap between two reported years is missing, not zero

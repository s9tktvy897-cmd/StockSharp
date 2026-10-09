import copy
from datetime import date

import pytest

from equity_research.data.sec_edgar import CompanyFacts
from equity_research.fundamentals import analysis
from equity_research.fundamentals.statements import build_annual
from equity_research.provenance import SourcedValue
from equity_research.valuation import assumptions, multiples

from fakes import SYNTHETIC_FUNDAMENTALS


def _st():
    return build_annual(CompanyFacts("0000000042", "SYNTHETIC", copy.deepcopy(SYNTHETIC_FUNDAMENTALS), date(2026, 10, 9)))


def _fact(value):
    return SourcedValue(value=value, unit="ratio", source="FRED", reference="test", retrieved=date(2026, 10, 9))


def test_scenarios_spread_growth_over_reported_cagrs():
    st = _st()
    scenarios = assumptions.default_scenarios(st, analysis.yearly_metrics(st), risk_free=_fact(0.045),
                                              inflation=_fact(0.023))
    cagr3 = 1.375 ** (1 / 3) - 1
    assert scenarios["base"]["revenue_growth"].value == pytest.approx(cagr3)
    assert "3y" in scenarios["base"]["revenue_growth"].rationale
    assert scenarios["base"]["terminal_growth"].value == pytest.approx(0.023)
    assert scenarios["base"]["ebit_margin"].value == pytest.approx(0.20)  # mean of FY2023 200/1000, FY2024 220/1100


def test_terminal_growth_is_capped_at_risk_free():
    st = _st()
    scenarios = assumptions.default_scenarios(st, analysis.yearly_metrics(st), risk_free=_fact(0.02),
                                              inflation=_fact(0.03))
    assert scenarios["base"]["terminal_growth"].value == pytest.approx(0.02)
    assert "capped" in scenarios["base"]["terminal_growth"].rationale


def test_missing_history_raises_instead_of_guessing():
    with pytest.raises(LookupError):
        assumptions.mean_of([], "ebit margin")


def test_market_multiples_hand_calculated():
    m = multiples.market_multiples(price=50, shares=10, debt=300, cash=100, investments=50, minority_interest=0,
                                   revenue=1000, ebit=200, net_income=150, fcf=125)
    assert m["market_cap"] == 500
    assert m["enterprise_value"] == 650
    assert m["ev_ebit"] == pytest.approx(3.25)
    assert m["pe"] == pytest.approx(500 / 150)
    assert m["p_fcf"] == pytest.approx(4)
    assert m["ev_sales"] == pytest.approx(0.65)
    assert m["fcf_yield"] == pytest.approx(0.25)


def test_multiple_with_non_positive_denominator_is_none():
    m = multiples.market_multiples(price=50, shares=10, debt=0, cash=0, investments=0, minority_interest=0,
                                   revenue=1000, ebit=-5, net_income=-5, fcf=10)
    assert m["ev_ebit"] is None and m["pe"] is None

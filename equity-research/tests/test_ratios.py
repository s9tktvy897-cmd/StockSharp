import pytest

from equity_research.fundamentals import ratios
from equity_research.fundamentals.ratios import UndefinedRatioError


def test_cagr_textbook():
    assert ratios.cagr(100, 161.051, 5) == pytest.approx(0.10)


@pytest.mark.parametrize("start,end", [(0, 100), (-50, 100), (100, -10)])
def test_cagr_undefined_for_non_positive(start, end):
    with pytest.raises(UndefinedRatioError):
        ratios.cagr(start, end, 3)


def test_divide_by_zero_is_undefined():
    with pytest.raises(UndefinedRatioError):
        ratios.safe_div(1, 0)


def test_effective_tax_rate_and_nopat():
    assert ratios.effective_tax_rate(21, 100) == pytest.approx(0.21)
    assert ratios.nopat(100, 0.21) == pytest.approx(79)
    with pytest.raises(UndefinedRatioError):
        ratios.effective_tax_rate(5, -10)


def test_invested_capital_and_roic():
    assert ratios.invested_capital(equity=300, debt=200, cash=50, investments=50) == 400
    assert ratios.roic(79, ic_begin=400, ic_end=600) == pytest.approx(0.158)
    with pytest.raises(UndefinedRatioError):
        ratios.roic(79, ic_begin=-100, ic_end=50)


def test_return_on_average_equity():
    assert ratios.return_on_average(30, 100, 200) == pytest.approx(0.2)


def test_accruals_ratio():
    assert ratios.accruals_ratio(100, 130, 900, 1100) == pytest.approx(-0.03)


def test_leverage_and_coverage():
    assert ratios.net_debt(200, 50, 30) == 120
    assert ratios.net_debt_to_ebitda(120, 240) == pytest.approx(0.5)
    with pytest.raises(UndefinedRatioError):
        ratios.net_debt_to_ebitda(120, -5)
    assert ratios.interest_coverage(100, 4) == pytest.approx(25)
    with pytest.raises(UndefinedRatioError):
        ratios.interest_coverage(100, 0)

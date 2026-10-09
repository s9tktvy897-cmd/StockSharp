from datetime import date

from equity_research.screening import screens

D = [date(y, 12, 31) for y in range(2019, 2025)]


def test_undervalued_needs_every_criterion():
    result = screens.undervalued(intrinsic_value=130, price=100, piotroski=6, altman_zone="safe", beneish_flagged=False)
    assert result.passed is True
    result = screens.undervalued(intrinsic_value=120, price=100, piotroski=6, altman_zone="safe", beneish_flagged=False)
    assert result.passed is False
    assert not result.criteria["margin_of_safety"].passed


def test_unknown_criterion_makes_result_unknown_unless_another_fails():
    result = screens.undervalued(intrinsic_value=None, price=None, piotroski=6, altman_zone="safe", beneish_flagged=False)
    assert result.passed is None
    result = screens.undervalued(intrinsic_value=None, price=None, piotroski=2, altman_zone="safe", beneish_flagged=False)
    assert result.passed is False


def test_growth_screen():
    fcf = dict(zip(D, [50, 60, 55, 70, 80, 90]))  # rising and positive in 2021? no; 2022, 2023, 2024 yes; 2020 yes
    result = screens.growth(revenue_cagr_5y=0.12, fcf_by_year=fcf, roic=0.30, wacc=0.09)
    assert result.passed is True
    assert result.criteria["fcf_positive_and_rising"].detail.startswith("4 of 5")
    result = screens.growth(revenue_cagr_5y=0.08, fcf_by_year=fcf, roic=0.30, wacc=0.09)
    assert result.passed is False


def test_growth_screen_without_wacc_is_unknown():
    fcf = dict(zip(D, [50, 60, 55, 70, 80, 90]))
    assert screens.growth(revenue_cagr_5y=0.12, fcf_by_year=fcf, roic=0.30, wacc=None).passed is None

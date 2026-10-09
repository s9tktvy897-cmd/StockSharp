import math

import pytest

from equity_research.risk import market


def test_returns():
    assert market.simple_returns([100, 110, 99]) == pytest.approx([0.10, -0.10])


def test_beta_of_levered_copy_is_two():
    m = [0.01, -0.02, 0.03, 0.005]
    assert market.beta([2 * r for r in m], m) == pytest.approx(2.0)


def test_beta_needs_matching_series():
    with pytest.raises(ValueError):
        market.beta([0.1, 0.2], [0.1])


def test_volatility_annualized():
    returns = [0.01, -0.01] * 10
    sample_sd = math.sqrt(sum(r * r for r in returns) / (len(returns) - 1))
    assert market.annualized_volatility(returns, periods_per_year=12) == pytest.approx(sample_sd * math.sqrt(12))


def test_max_drawdown():
    assert market.max_drawdown([100, 120, 90, 130, 117]) == pytest.approx(-0.25)

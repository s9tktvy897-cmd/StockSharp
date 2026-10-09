from datetime import date

import pytest

from equity_research.fundamentals.ratios import UndefinedRatioError
from equity_research.valuation import dcf, wacc
from equity_research.valuation.dcf import DcfInputs, EquityBridge


def test_capm():
    assert wacc.cost_of_equity(0.04, 1.2, 0.05) == pytest.approx(0.10)


def test_hamada_relever_and_unlever():
    assert wacc.relever_beta(1.0, debt_to_equity=0.5, tax_rate=0.25) == pytest.approx(1.375)
    assert wacc.unlever_beta(1.375, debt_to_equity=0.5, tax_rate=0.25) == pytest.approx(1.0)


def test_wacc_textbook():
    # 0.6 * 10% + 0.4 * 5% * (1 - 25%) = 7.5%
    assert wacc.wacc(equity=600, debt=400, cost_of_equity=0.10, cost_of_debt=0.05, tax_rate=0.25) == pytest.approx(0.075)
    with pytest.raises(UndefinedRatioError):
        wacc.wacc(equity=0, debt=0, cost_of_equity=0.1, cost_of_debt=0.05, tax_rate=0.25)


def test_gordon_requires_wacc_above_growth():
    assert dcf.gordon_terminal_value(100, 0.08, 0.03) == pytest.approx(2000)
    with pytest.raises(UndefinedRatioError):
        dcf.gordon_terminal_value(100, 0.03, 0.03)


def test_growth_path_fades_linearly():
    assert dcf.growth_path(0.10, 0.02, high_growth_years=2, fade_years=4) == pytest.approx(
        [0.10, 0.10, 0.08, 0.06, 0.04, 0.02])


def _inputs(**overrides):
    base = dict(base_revenue=1000, base_period_end=date(2023, 1, 1), valuation_date=date(2023, 1, 1),
                revenue_growth=0.10, high_growth_years=2, fade_years=0, ebit_margin=0.20, tax_rate=0.25,
                da_pct_revenue=0.05, capex_pct_revenue=0.06, nwc_pct_revenue=0.10,
                terminal_growth=0.02, ronic=0.10, wacc=0.08)
    base.update(overrides)
    return DcfInputs(**base)


BRIDGE = EquityBridge(cash=100, investments=0, debt=300, minority_interest=0, diluted_shares=10)


def test_two_year_dcf_hand_calculated():
    # revenue 1100, 1210; NOPAT = 20% * 75% * rev = 165, 181.5
    # FCFF = NOPAT + 5% rev - 6% rev - 10% * d(rev) = 144, 158.4
    # terminal: NOPAT 181.5 * 1.02 = 185.13; reinvestment g/RONIC = 20% -> FCFF 148.104; TV = 148.104 / 6% = 2468.4
    result = dcf.value(_inputs(), BRIDGE)
    assert [p.fcff for p in result.projections] == pytest.approx([144, 158.4])
    assert result.terminal_value == pytest.approx(2468.4)
    ev = 144 / 1.08 + 158.4 / 1.08 ** 2 + 2468.4 / 1.08 ** 2
    assert result.enterprise_value == pytest.approx(ev)
    assert result.equity_value == pytest.approx(ev + 100 - 300)
    assert result.value_per_share == pytest.approx((ev - 200) / 10)
    assert result.terminal_share_of_ev == pytest.approx(2468.4 / 1.08 ** 2 / ev)
    assert result.implied_exit_ev_ebit == pytest.approx(2468.4 / 242)


def test_valuation_date_after_base_period_shortens_discounting():
    later = dcf.value(_inputs(valuation_date=date(2023, 7, 2)), BRIDGE)
    assert later.enterprise_value > dcf.value(_inputs(), BRIDGE).enterprise_value


def test_terminal_growth_at_or_above_ronic_is_refused():
    with pytest.raises(UndefinedRatioError):
        dcf.value(_inputs(terminal_growth=0.10, ronic=0.10, wacc=0.12), BRIDGE)


def test_sensitivity_grid_marks_invalid_cells():
    grid = dcf.sensitivity(_inputs(), BRIDGE, waccs=[0.02, 0.08], growths=[0.01, 0.03])
    assert grid[(0.08, 0.01)] is not None
    assert grid[(0.02, 0.03)] is None  # WACC <= g


def test_reverse_dcf_recovers_growth():
    target = dcf.value(_inputs(revenue_growth=0.07), BRIDGE).value_per_share
    assert dcf.implied_growth(_inputs(), BRIDGE, target) == pytest.approx(0.07, abs=1e-6)


def test_reverse_dcf_without_solution_raises():
    with pytest.raises(UndefinedRatioError):
        dcf.implied_growth(_inputs(), BRIDGE, price=1e9)

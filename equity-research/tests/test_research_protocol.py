from equity_research.research import protocol

PASS = dict(min_trades=True, min_edge=True, beats_spy_sharpe=True, max_drawdown=True, cost_stress_2x=True,
            positive_years=True, both_regimes=True, not_extreme_driven=True, significant_unadjusted=True,
            significant_holm=True)


def test_status_rules():
    assert protocol.status(PASS, holdout_ok=True) == "PAPER TRADING CANDIDATE"
    assert protocol.status(PASS, holdout_ok=False) == "RESEARCH ONLY"
    assert protocol.status(dict(PASS, significant_holm=False), holdout_ok=True) == "RESEARCH ONLY"
    assert protocol.status(dict(PASS, max_drawdown=False), holdout_ok=True) == "REJECTED"
    assert protocol.status(dict(PASS, significant_unadjusted=False, significant_holm=False), True) == "REJECTED"
    assert protocol.status(PASS, holdout_ok=True, paper_ok=True) == "PAPER TRADING VALIDATED"


def test_a_single_backtest_never_validates():
    # Without live paper results nothing reaches the highest status.
    assert protocol.status(PASS, holdout_ok=True) != "PAPER TRADING VALIDATED"


def test_grid_is_fixed_and_unique():
    names = [v.name for v in protocol.GRID]
    assert len(names) == len(set(names)) == 34
    assert protocol.HOLDOUT_START.isoformat() == "2025-10-01"

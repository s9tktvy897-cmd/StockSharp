from datetime import date, timedelta

import numpy as np
import pytest

from equity_research.shortterm import evaluation, models
from equity_research.shortterm.config import Config
from equity_research.shortterm.dataset import build_panel

from shortterm_fakes import planted_universe


def test_brier_and_skill_hand_calculated():
    p, y = np.array([0.1, 0.9, 0.5]), np.array([0, 1, 1])
    assert evaluation.brier(p, y) == pytest.approx((0.01 + 0.01 + 0.25) / 3)
    base = np.full(3, 2 / 3)
    assert evaluation.brier_skill(p, y, 2 / 3) == pytest.approx(1 - evaluation.brier(p, y) / evaluation.brier(base, y))


def test_wilson_interval():
    lo, hi = evaluation.wilson(10, 100)
    assert lo == pytest.approx(0.0552, abs=1e-3) and hi == pytest.approx(0.1744, abs=1e-3)
    assert evaluation.wilson(0, 0) == (0.0, 1.0)


def test_ece_perfect_calibration_is_zero():
    p = np.repeat([0.1, 0.5], 1000)
    y = np.concatenate([np.r_[np.ones(100), np.zeros(900)], np.r_[np.ones(500), np.zeros(500)]])
    assert evaluation.ece(p, y, bins=2) == pytest.approx(0.0, abs=1e-12)


def test_walk_forward_has_embargo_and_no_overlap():
    dates = np.array([date(2018, 1, 1) + timedelta(days=i) for i in range(5 * 365)])
    folds = evaluation.walk_forward(dates, min_train_years=2, embargo_days=5)
    assert [f.test_year for f in folds] == [2021, 2022]
    for f in folds:
        train, val, test = dates[f.train], dates[f.val], dates[f.test]
        assert train.max() < val.min() - timedelta(days=5)
        assert val.max() < test.min() - timedelta(days=5)
        assert {d.year for d in test} == {f.test_year}


def test_logistic_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(20000, 2))
    p = 1 / (1 + np.exp(-(-1.0 + 2.0 * x[:, 0])))
    y = (rng.random(20000) < p).astype(float)
    m = models.Logistic(l2=0.0).fit(x, y)
    assert m.coef[0] / m.scale[0] == pytest.approx(2.0, abs=0.1)
    assert m.coef[1] / m.scale[1] == pytest.approx(0.0, abs=0.1)


def _gate(universe):
    panel = build_panel(universe, None, Config())
    result = evaluation.out_of_sample(panel, horizon=1, config=Config())
    return result.gate


def test_gate_opens_on_a_planted_pattern():
    gate = _gate(planted_universe(signal=True))
    assert gate.passed, gate.reasons


def test_gate_stays_shut_on_noise():
    gate = _gate(planted_universe(signal=False, seed=11))
    assert not gate.passed
    assert gate.reasons


def test_panel_keeps_only_tradable_rows_as_float32():
    from shortterm_fakes import make_bars
    universe = planted_universe(n_tickers=3, n_days=200)
    universe["PENNY"] = make_bars("PENNY", [1.0] * 200)
    panel = build_panel(universe, None, Config())
    assert "PENNY" not in set(panel.tickers)
    assert panel.X.dtype == np.float32 and panel.eligible.all()

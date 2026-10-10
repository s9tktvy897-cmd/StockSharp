from datetime import datetime, timezone

import numpy as np
import pytest

from equity_research.shortterm import backtest, engine, expected, labels
from equity_research.shortterm.config import Config, Costs
from equity_research.shortterm.dataset import build_panel

from shortterm_fakes import make_bars, planted_universe


def test_trade_return_label_matches_the_simulated_trade():
    rng = np.random.default_rng(3)
    n = 300
    opens = 20 * np.cumprod(1 + rng.normal(0, 0.03, n))
    closes = opens * (1 + rng.normal(0, 0.04, n))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.05, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.03, n)))
    bars = make_bars("X", closes, opens=opens, highs=highs, lows=lows)
    cfg = Config()
    out = labels.compute(bars, cfg)
    for h in cfg.horizons:
        for i in range(0, n - h - 1, 7):
            t = backtest.simulate(bars, i, h, cfg, dollar_volume=1e9)
            assert out[h]["trade_gross"][i] == pytest.approx(t.gross), (h, i)


def test_trade_return_hand_calculated():
    # Day 1: entry 10, high 10.5; day 2: opens at 11.5 (gap above the 11 target) -> exit 11.5.
    bars = make_bars("X", [10, 10.3, 11.8, 12], opens=[10, 10, 11.5, 12], highs=[10, 10.5, 12, 12],
                     lows=[10, 9.9, 11.4, 12])
    out = labels.compute(bars, Config())
    assert out[1]["trade_gross"][0] == pytest.approx(0.03)   # time exit at the close of day 1
    assert out[2]["trade_gross"][0] == pytest.approx(0.15)   # gap above target on day 2


def test_panel_net_outcome_includes_costs_per_liquidity_tier():
    universe = planted_universe(n_tickers=3, n_days=200, seed=1)
    cfg = Config(costs=Costs(commission_bps=0, slippage_bps=0, half_spread_tiers=((0.0, 50.0),)))
    panel = build_panel(universe, None, cfg)
    for h in cfg.horizons:
        o = panel.outcomes[h]
        ok = np.isfinite(o["trade_gross"])
        assert np.allclose(o["net"][ok], (1 + o["trade_gross"][ok]) * 0.995 / 1.005 - 1)


def test_regressors_recover_a_linear_signal():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(4000, 3)).astype(np.float32)
    y = 0.02 * X[:, 0] - 0.01 * X[:, 2] + rng.normal(0, 0.005, 4000)
    for model in expected.candidates():
        model.fit(X[:3000], y[:3000])
        assert np.corrcoef(model.predict(X[3000:]), y[3000:])[0, 1] > 0.8, model.name


def _scan(signal: bool, seed: int):
    universe = planted_universe(signal=signal, seed=seed)
    last = max(max(b.dates) for b in universe.values())
    return engine.run(universe, None, Config(), {}, "SYNTHETIC",
                      datetime(last.year, last.month, last.day, 23, 0, tzinfo=timezone.utc))


def test_expected_return_ranking_is_used_when_profitable_and_trades_only_positive_expectations():
    r = _scan(True, 7)
    bt = r.return_backtests[1]
    assert bt.summary["trades"] > 0 and bt.summary["mean_net_ci"][0] > 0
    assert "verwacht netto rendement" in r.ranked_by
    assert r.candidates and all(c.score > 0 for c in r.candidates)


def test_expected_return_ranking_is_not_used_on_noise():
    r = _scan(False, 11)
    assert "verwacht netto rendement" not in r.ranked_by

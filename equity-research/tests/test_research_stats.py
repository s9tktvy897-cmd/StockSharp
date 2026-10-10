import numpy as np
import pytest

from equity_research.research import stats


def test_performance_hand_calculated():
    r = np.array([0.01, -0.02, 0.03, 0.0])
    p = stats.performance(r, periods_per_year=252)
    equity = np.cumprod(1 + r)
    assert p["total_return"] == pytest.approx(equity[-1] - 1)
    assert p["cagr"] == pytest.approx(equity[-1] ** (252 / 4) - 1)
    assert p["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))
    downside = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    assert p["sortino"] == pytest.approx(r.mean() / downside * np.sqrt(252))
    assert p["max_drawdown"] == pytest.approx(1.01 * 0.98 / 1.01 - 1)
    assert p["calmar"] == pytest.approx(p["cagr"] / abs(p["max_drawdown"]))


def test_trade_stats_hand_calculated():
    net = np.array([0.10, -0.05, 0.02, -0.01])
    t = stats.trade_stats(net)
    assert t["trades"] == 4 and t["win_rate"] == 0.5
    assert t["avg_win"] == pytest.approx(0.06) and t["avg_loss"] == pytest.approx(-0.03)
    assert t["profit_factor"] == pytest.approx(0.12 / 0.06)
    assert t["expected_value"] == pytest.approx(0.015)
    assert t["mean_without_top_1pct"] == pytest.approx(np.mean([-0.05, 0.02, -0.01]))


def test_block_bootstrap_detects_a_real_mean_and_not_noise():
    rng = np.random.default_rng(0)
    signal = rng.normal(0.002, 0.01, 2000)
    noise = rng.normal(0.0, 0.01, 2000)
    lo, hi, p = stats.bootstrap_mean(signal, block=20, n=2000, seed=1)
    assert lo > 0 and p < 0.01
    lo, hi, p = stats.bootstrap_mean(noise, block=20, n=2000, seed=1)
    assert lo < 0 < hi and p > 0.05


def test_block_bootstrap_is_wider_for_autocorrelated_returns():
    rng = np.random.default_rng(2)
    e = rng.normal(0, 0.01, 3000)
    ar = np.empty_like(e)
    ar[0] = e[0]
    for i in range(1, len(e)):
        ar[i] = 0.8 * ar[i - 1] + e[i]
    iid_lo, iid_hi, _ = stats.bootstrap_mean(ar, block=1, n=1000, seed=3)
    blk_lo, blk_hi, _ = stats.bootstrap_mean(ar, block=50, n=1000, seed=3)
    assert (blk_hi - blk_lo) > 1.5 * (iid_hi - iid_lo)


def test_cluster_bootstrap_by_signal_date():
    # Ten identical trades per day are one observation per day, not ten.
    days = np.repeat(np.arange(50), 10)
    rng = np.random.default_rng(4)
    day_effect = rng.normal(0.0, 0.02, 50)
    net = day_effect[days]
    lo, hi, _ = stats.cluster_bootstrap_mean(net, days, n=2000, seed=5)
    naive = 1.96 * net.std(ddof=1) / np.sqrt(len(net))
    assert (hi - lo) / 2 > 2 * naive


def test_holm_correction():
    p = {"a": 0.01, "b": 0.04, "c": 0.03}
    # Holm: sorted 0.01*3=0.03 (reject), 0.03*2=0.06 (stop) -> only "a"
    assert stats.holm(p, alpha=0.05) == {"a": True, "b": False, "c": False}


def test_deflated_sharpe_penalizes_many_trials():
    rng = np.random.default_rng(6)
    r = rng.normal(0.0005, 0.01, 1000)
    one = stats.deflated_sharpe(r, trials=1)
    many = stats.deflated_sharpe(r, trials=100)
    assert 0 <= many < one <= 1


def test_corwin_schultz_spread_recovers_a_known_spread():
    # Prices that bounce between bid and ask: with a true 2% spread and no volatility the
    # high/low estimator gives about 2%.
    n = 60
    mid = np.full(n, 100.0)
    high, low = mid * 1.01, mid * 0.99
    s = stats.corwin_schultz(high, low, window=20)
    assert s[-1] == pytest.approx(0.02, rel=0.05)

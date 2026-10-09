import dataclasses

import numpy as np
import pytest

from equity_research.shortterm import backtest
from equity_research.shortterm.config import Config, Costs

from shortterm_fakes import make_bars

NO_COST = Config(costs=Costs(commission_bps=0, slippage_bps=0, half_spread_tiers=((0.0, 0.0),)))


def _bars(opens, highs, lows, closes):
    return make_bars("X", closes, opens=opens, highs=highs, lows=lows)


def test_target_hit_intraday_exits_at_target():
    bars = _bars([10, 10, 10], [10, 11.5, 10], [10, 9.8, 10], [10, 10.2, 10])
    t = backtest.simulate(bars, 0, 1, NO_COST, dollar_volume=1e9)
    assert t.exit_price == pytest.approx(11.0) and t.reason == "target" and t.gross == pytest.approx(0.10)


def test_gap_above_target_fills_at_the_open():
    bars = _bars([10, 10, 11.5], [10, 10.5, 12], [10, 9.9, 11.4], [10, 10.3, 11.8])
    t = backtest.simulate(bars, 0, 2, NO_COST, dollar_volume=1e9)
    assert t.exit_price == pytest.approx(11.5) and t.reason == "gap above target"


def test_target_and_stop_in_one_bar_assumes_the_stop():
    cfg = dataclasses.replace(NO_COST, stop_loss=0.05)
    bars = _bars([10, 10, 10], [10, 11.5, 10], [10, 9.0, 10], [10, 10.0, 10])
    t = backtest.simulate(bars, 0, 1, cfg, dollar_volume=1e9)
    assert t.exit_price == pytest.approx(9.5) and t.reason == "stop (same bar as target)"


def test_time_exit_and_costs():
    cfg = Config(costs=Costs(commission_bps=0, slippage_bps=0, half_spread_tiers=((0.0, 50.0),)))  # 0.5% per side
    bars = _bars([10, 10, 10.2], [10, 10.4, 10.6], [10, 9.9, 10.1], [10, 10.1, 10.5])
    t = backtest.simulate(bars, 0, 2, cfg, dollar_volume=1e6)
    assert t.reason == "time" and t.exit_price == pytest.approx(10.5)
    assert t.net == pytest.approx(10.5 * 0.995 / (10 * 1.005) - 1)


def test_summary_hand_calculated():
    trades = [backtest.Trade("A", None, None, None, 10, 11, 0.10, n, "x", n > 0.05, -0.01)
              for n in (0.10, -0.05, 0.02, -0.01)]
    s = backtest.summarize(trades)
    assert s["trades"] == 4
    assert s["mean_net"] == pytest.approx(0.015)
    assert s["win_rate"] == pytest.approx(0.5)
    assert s["payoff_ratio"] == pytest.approx(0.06 / 0.03)
    assert s["profit_factor"] == pytest.approx(0.12 / 0.06)


def test_equity_curve_drawdown():
    curve = backtest.equity_curve([0.10, -0.20, 0.05])
    assert curve == pytest.approx([1.10, 0.88, 0.924])
    assert backtest.max_drawdown(curve) == pytest.approx(-0.20)
